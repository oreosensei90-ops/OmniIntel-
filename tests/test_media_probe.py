from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from omniintel.cli import main
from omniintel.local_files import import_local_file
from omniintel.media_probe import probe_local_media


def _media_file(path: Path) -> Path:
    path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"omniintel-test-media")
    return path


def _fake_ffprobe(path: Path, *, version: str = "7.1", payload: dict | None = None, sleep: float = 0) -> Path:
    payload = payload or {
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "125.125",
            "size": "31",
            "bit_rate": "64000",
        },
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "profile": "High",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30/1",
                "duration": "125.125",
                "start_time": "0.000",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "channel_layout": "stereo",
                "duration": "125.000",
                "start_time": "0.250",
            },
        ],
    }
    source = (
        f"#!{sys.executable}\n"
        "import json,sys,time\n"
        f"VERSION={version!r}\n"
        f"PAYLOAD={json.dumps(payload)!r}\n"
        f"SLEEP={sleep!r}\n"
        "if '-version' in sys.argv:\n"
        " print('ffprobe version ' + VERSION)\n"
        "else:\n"
        " time.sleep(SLEEP)\n"
        " print(json.dumps(json.loads(PAYLOAD)))\n"
    )
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


def _import_media(tmp_path: Path) -> tuple[Path, Path, str, str]:
    media = _media_file(tmp_path / "lecture.mp4")
    database = tmp_path / "omniintel.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database, assets, media)
    return database, assets, imported.asset.id, imported.source_id


def test_probe_persists_container_and_stream_metadata_and_reuses_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, assets, asset_id, source_id = _import_media(tmp_path)
    executable = _fake_ffprobe(tmp_path / "ffprobe")
    monkeypatch.setattr("omniintel.media_probe.shutil.which", lambda _: str(executable))

    first = probe_local_media(database, assets, asset_id)
    second = probe_local_media(database, assets, asset_id)

    assert first.id == second.id
    assert first.reused is False
    assert second.reused is True
    assert first.format_name == "mov,mp4,m4a,3gp,3g2,mj2"
    assert first.duration_ms == 125125
    assert [stream.codec_type for stream in first.streams] == ["video", "audio"]
    assert first.streams[0].width == 1920
    assert first.streams[0].height == 1080
    assert first.streams[1].sample_rate == 48000
    assert first.streams[1].channels == 2
    assert first.streams[1].start_ms == 250
    with sqlite3.connect(database) as conn:
        duration = conn.execute(
            "SELECT duration_ms FROM sources WHERE id=?", (source_id,)
        ).fetchone()[0]
        probe_count = conn.execute("SELECT count(*) FROM media_probes").fetchone()[0]
        stream_count = conn.execute("SELECT count(*) FROM media_streams").fetchone()[0]
    assert duration == 125125
    assert probe_count == 1
    assert stream_count == 2


def test_probe_version_and_limits_participate_in_idempotency_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, assets, asset_id, _ = _import_media(tmp_path)
    executable = _fake_ffprobe(tmp_path / "ffprobe", version="7.1")
    monkeypatch.setattr("omniintel.media_probe.shutil.which", lambda _: str(executable))
    first = probe_local_media(database, assets, asset_id)
    _fake_ffprobe(executable, version="7.2")
    second = probe_local_media(database, assets, asset_id)
    third = probe_local_media(database, assets, asset_id, max_streams=16)
    assert len({first.id, second.id, third.id}) == 3


def test_probe_rejects_non_media_asset_and_missing_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "notes.pdf"
    pdf.write_bytes(b"%PDF-1.7\nminimal test")
    database = tmp_path / "omniintel.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database, assets, pdf)
    with pytest.raises(ValueError, match="Only registered audio and video"):
        probe_local_media(database, assets, imported.asset.id)

    media = _media_file(tmp_path / "lecture.mp4")
    imported_media = import_local_file(database, assets, media)
    monkeypatch.setattr("omniintel.media_probe.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="ffprobe was not found"):
        probe_local_media(database, assets, imported_media.asset.id)


def test_probe_rejects_malformed_stream_list_and_stream_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, assets, asset_id, _ = _import_media(tmp_path)
    executable = _fake_ffprobe(
        tmp_path / "ffprobe",
        payload={"format": {"format_name": "mp4", "duration": "10"}, "streams": "bad"},
    )
    monkeypatch.setattr("omniintel.media_probe.shutil.which", lambda _: str(executable))
    with pytest.raises(ValueError, match="no inspectable streams"):
        probe_local_media(database, assets, asset_id)

    too_many = {
        "format": {"format_name": "mp4", "duration": "10"},
        "streams": [
            {"index": index, "codec_type": "audio", "codec_name": "aac"}
            for index in range(3)
        ],
    }
    _fake_ffprobe(executable, payload=too_many)
    with pytest.raises(ValueError, match="stream-count limit"):
        probe_local_media(database, assets, asset_id, max_streams=2)


def test_probe_enforces_timeout_and_output_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, assets, asset_id, _ = _import_media(tmp_path)
    executable = _fake_ffprobe(tmp_path / "ffprobe", sleep=2)
    monkeypatch.setattr("omniintel.media_probe.shutil.which", lambda _: str(executable))
    with pytest.raises(TimeoutError, match="time limit"):
        probe_local_media(database, assets, asset_id, timeout_seconds=1.0)

    huge_payload = {
        "format": {"format_name": "mp4", "duration": "10"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "x" * 5000}
        ],
    }
    _fake_ffprobe(executable, payload=huge_payload)
    with pytest.raises(ValueError, match="output limit"):
        probe_local_media(database, assets, asset_id, max_output_bytes=1024)


def test_probe_refuses_corrupted_asset_before_invoking_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, assets, asset_id, _ = _import_media(tmp_path)
    store_path = next((assets / "assets").glob("*/*/*"), None)
    if store_path is None:
        store_path = next(path for path in assets.rglob("*") if path.is_file() and path.name != ".")
    store_path.write_bytes(b"corrupted")
    monkeypatch.setattr(
        "omniintel.media_probe.shutil.which",
        lambda _: pytest.fail("ffprobe must not run for a corrupted asset"),
    )
    with pytest.raises(RuntimeError, match="size does not match"):
        probe_local_media(database, assets, asset_id)

def test_probe_media_cli_emits_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    database, assets, asset_id, _ = _import_media(tmp_path)
    executable = _fake_ffprobe(tmp_path / "ffprobe")
    monkeypatch.setattr("omniintel.media_probe.shutil.which", lambda _: str(executable))
    monkeypatch.setattr(
        "sys.argv",
        ["omniintel","probe-media",str(database),str(assets),asset_id],
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["source_asset_id"] == asset_id
    assert result["duration_ms"] == 125125
    assert len(result["streams"]) == 2

