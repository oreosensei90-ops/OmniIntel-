from __future__ import annotations

import json
from pathlib import Path

import pytest

from omniintel.input_plan import plan_local_inputs


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_plan_classifies_mixed_sources_without_writing(tmp_path: Path) -> None:
    pdf = _write(tmp_path / "slides.pdf", b"%PDF-1.7\ncontent")
    video = _write(tmp_path / "lecture.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 40)
    captions = _write(tmp_path / "lecture.vtt", b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello")
    before = {p.name: p.read_bytes() for p in (pdf, video, captions)}

    plan = plan_local_inputs([pdf, video, captions])
    data = plan.to_dict()

    assert data["read_only"] is True
    assert [item["modality"] for item in data["inputs"]] == ["DOCUMENT", "VIDEO", "CAPTIONS"]
    assert data["ready_for_execution"] is False
    assert any("spoken language" in q for q in data["questions"])
    assert any("which media source" in q for q in data["questions"])
    assert any("alignment" in warning for warning in data["warnings"])
    assert {p.name: p.read_bytes() for p in (pdf, video, captions)} == before
    assert set(p.name for p in tmp_path.iterdir()) == set(before)


def test_plan_requires_confirmed_language_for_speech_and_accepts_it(tmp_path: Path) -> None:
    audio = _write(tmp_path / "lecture.wav", b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 24)
    pending = plan_local_inputs([audio])
    ready = plan_local_inputs([audio], language="en,hi")
    assert pending.questions
    assert ready.questions == ()
    assert ready.to_dict()["ready_for_execution"] is True


def test_plan_flags_multiple_recording_clocks(tmp_path: Path) -> None:
    first = _write(tmp_path / "camera-a.mp4", b"\x00\x00\x00\x18ftypisom" + b"a" * 40)
    second = _write(tmp_path / "camera-b.mp4", b"\x00\x00\x00\x18ftypisom" + b"b" * 40)
    plan = plan_local_inputs([first, second], language="en")
    assert any("share one recording timeline" in q for q in plan.questions)


def test_plan_rejects_unknown_archives_and_oversized_bundles(tmp_path: Path) -> None:
    archive = _write(tmp_path / "bundle.zip", b"PK\x03\x04payload")
    with pytest.raises(ValueError, match="Unsupported"):
        plan_local_inputs([archive])
    pdf = _write(tmp_path / "large.pdf", b"%PDF-1.7\n" + b"x" * 100)
    with pytest.raises(ValueError, match="per-file"):
        plan_local_inputs([pdf], max_file_bytes=20)


def test_plan_rejects_empty_and_excessive_input_sets(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        plan_local_inputs([])
    file = _write(tmp_path / "notes.txt", b"Some notes")
    with pytest.raises(ValueError, match="input count"):
        plan_local_inputs([file, file], max_files=1)


def test_plan_output_is_stable_json_data(tmp_path: Path) -> None:
    note = _write(tmp_path / "notes.txt", "Learning notes".encode())
    plan = plan_local_inputs([note])
    encoded = json.dumps(plan.to_dict(), sort_keys=True)
    assert '"schema_version": 1' in encoded
    assert '"network": "none"' in encoded
