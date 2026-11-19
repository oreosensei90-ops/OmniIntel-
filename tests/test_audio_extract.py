from __future__ import annotations

import json
import sqlite3
import sys
import wave
from pathlib import Path

import pytest

from omniintel.assets import AssetStore
from omniintel.audio_extract import extract_audio
from omniintel.cli import main
from omniintel.local_files import import_local_file
from omniintel.models import TranscriptSegmentInput
from omniintel.transcription import ChunkTranscription, run_wav_transcription


def _video(path: Path) -> Path:
    path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"omniintel-video")
    return path


def _ffprobe(path: Path, *, start_time: str = "0.250", audio: bool = True, version: str = "7.1") -> Path:
    streams = [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1280,
            "height": 720,
            "duration": "10.250",
            "start_time": "0.000",
        }
    ]
    if audio:
        streams.append(
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "duration": "10.000",
                "start_time": start_time,
                "sample_rate": "48000",
                "channels": 2,
            }
        )
    payload = {"format": {"format_name": "mp4", "duration": "10.250"}, "streams": streams}
    script = (
        f"#!{sys.executable}\n"
        "import json,sys\n"
        "if '-version' in sys.argv:\n"
        f" print('ffprobe version {version}')\n"
        "else:\n"
        f" print({json.dumps(payload)!r})\n"
    )
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def _ffmpeg(
    path: Path,
    *,
    seconds: int = 10,
    sleep: float = 0,
    invalid_output: bool = False,
    counter: Path | None = None,
) -> Path:
    script = (
        f"#!{sys.executable}\n"
        "import pathlib,sys,time,wave\n"
        "if '-version' in sys.argv:\n"
        " print('ffmpeg version 7.1')\n"
        "else:\n"
        f" time.sleep({sleep!r})\n"
        f" output=pathlib.Path(sys.argv[-1])\n"
        f" invalid={invalid_output!r}\n"
        f" seconds={seconds}\n"
        f" counter={str(counter) if counter else None!r}\n"
        " if counter:\n"
        "  p=pathlib.Path(counter)\n"
        "  p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n"
        " if invalid:\n"
        "  output.write_bytes(b'not a wav' + b' ' * 100)\n"
        " else:\n"
        "  with wave.open(str(output),'wb') as wav:\n"
        "   wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)\n"
        "   wav.writeframes(bytes(2) * 16000 * seconds)\n"
    )
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, ffmpeg_kwargs: dict | None = None):
    video = _video(tmp_path / "lecture.mp4")
    database = tmp_path / "omniintel.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database, assets, video)
    probe = _ffprobe(tmp_path / "ffprobe")
    encoder = _ffmpeg(tmp_path / "ffmpeg", **(ffmpeg_kwargs or {}))
    def which(name: str) -> str | None:
        if name == "ffprobe":
            return str(probe)
        if name == "ffmpeg":
            return str(encoder)
        return None

    monkeypatch.setattr("shutil.which",which)
    return database, assets, imported, probe, encoder


def test_extract_audio_persists_normalized_derivative_and_reuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counter = tmp_path / "ffmpeg-calls.txt"
    database, assets, imported, _, _ = _setup(
        tmp_path, monkeypatch, ffmpeg_kwargs={"counter": counter}
    )
    first = extract_audio(database, assets, imported.asset.id, max_output_bytes=1_000_000)
    second = extract_audio(database, assets, imported.asset.id, max_output_bytes=1_000_000)

    assert first.id == second.id
    assert first.reused is False
    assert second.reused is True
    assert first.source_asset_id == imported.asset.id
    assert first.output_asset_id != imported.asset.id
    assert first.source_stream_start_ms == 250
    assert first.time_offset_ms == 250
    assert first.duration_ms == 10_000
    assert first.sample_rate == 16_000
    assert first.channels == 1
    assert first.sample_width == 2
    assert counter.read_text() == "1"

    output = AssetStore(database, assets).get_asset(first.output_asset_id)
    assert output.role == "AUDIO"
    assert output.media_type == "audio/wav"
    AssetStore(database, assets).resolve_path(output.id)
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM media_derivatives").fetchone()[0] == 1
        assert conn.execute(
            "SELECT duration_ms FROM sources WHERE id=?", (imported.source_id,)
        ).fetchone()[0] == 10_250


def test_extract_audio_rejects_missing_audio_and_non_audio_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, assets, imported, _, _ = _setup(tmp_path, monkeypatch)
    no_audio_probe = _ffprobe(tmp_path / "ffprobe-no-audio", audio=False)
    monkeypatch.setattr(
        "shutil.which",
        lambda name: str(no_audio_probe) if name == "ffprobe" else None,
    )
    with pytest.raises(ValueError, match="no audio stream"):
        extract_audio(database, assets, imported.asset.id)

    database2 = tmp_path / "other.db"
    assets2 = tmp_path / "other-assets"
    imported2 = import_local_file(database2, assets2, _video(tmp_path / "other.mp4"))
    probe2 = _ffprobe(tmp_path / "ffprobe-other")
    encoder = _ffmpeg(tmp_path / "ffmpeg-other")
    monkeypatch.setattr(
        "shutil.which",
        lambda name: str(probe2) if name == "ffprobe" else str(encoder) if name == "ffmpeg" else None,
    )
    with pytest.raises(ValueError, match="not an audio stream"):
        extract_audio(database2, assets2, imported2.asset.id, stream_index=0)


def test_extract_audio_enforces_output_size_and_rejects_invalid_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, assets, imported, _, encoder = _setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="size limit"):
        extract_audio(database, assets, imported.asset.id, max_output_bytes=64 * 1024)

    _ffmpeg(encoder, invalid_output=True)
    with pytest.raises(ValueError, match="not a readable WAV"):
        extract_audio(database, assets, imported.asset.id, max_output_bytes=1_000_000)


def test_extract_audio_enforces_timeout_and_negative_stream_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, assets, imported, _, encoder = _setup(
        tmp_path, monkeypatch, ffmpeg_kwargs={"sleep": 2}
    )
    with pytest.raises(TimeoutError, match="time limit"):
        extract_audio(
            database, assets, imported.asset.id,
            timeout_seconds=1.0,max_output_bytes=1_000_000,
        )

    negative_probe = _ffprobe(tmp_path / "ffprobe-negative", start_time="-0.250", version="7.2")
    monkeypatch.setattr(
        "shutil.which",
        lambda name: str(negative_probe) if name == "ffprobe" else str(encoder) if name == "ffmpeg" else None,
    )
    with pytest.raises(ValueError, match="Negative audio stream start"):
        extract_audio(database, assets, imported.asset.id, max_output_bytes=1_000_000)


def test_extract_audio_cli_emits_source_timeline_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    database, assets, imported, _, _ = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sys.argv",
        ["omniintel","extract-audio",str(database),str(assets),imported.asset.id,
         "--max-output-bytes","1000000"],
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["output_asset_id"]
    assert result["time_offset_ms"] == 250

def test_extracted_audio_flows_into_source_aligned_resumable_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, assets, imported, _, _ = _setup(tmp_path, monkeypatch)
    extracted = extract_audio(
        database,assets,imported.asset.id,max_output_bytes=1_000_000,
    )

    class Adapter:
        name = "audio-extract-integration"
        version = "1"
        model_id = "fixture"

        def transcribe_chunk(self, wav_path: Path, *, language: str | None) -> ChunkTranscription:
            return ChunkTranscription(
                language="en",
                segments=(TranscriptSegmentInput(
                    "The lecture begins.",100,800,language="en",
                ),),
            )

    result = run_wav_transcription(
        database,assets,imported.source_id,extracted.output_asset_id,Adapter(),
        language="en",chunk_seconds=120,
    )
    assert result.time_offset_ms == 250
    from omniintel.store import OmniIntelStore
    segments = OmniIntelStore(database).get_transcript(imported.source_id)
    assert segments[0]["start_ms"] == 350
    assert segments[0]["end_ms"] == 1050

