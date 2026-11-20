from __future__ import annotations

import json
import wave
from pathlib import Path

from omniintel.database import connect
from omniintel.jobs import JobQueue
from omniintel.models import TranscriptSegmentInput
from omniintel.transcription import ChunkTranscription
from omniintel.worker import run_once


def _write_executable(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_uploaded_video_reaches_evidence_grounded_reader_through_real_worker(tmp_path, monkeypatch):
    database = tmp_path / "omniintel.db"
    upload_root = tmp_path / "uploads"
    asset_root = tmp_path / "assets"
    upload_root.mkdir()
    upload = upload_root / "physics-lecture.mp4"
    upload.write_bytes(bytes([0, 0, 0, 24]) + b"ftypisom" + b"synthetic-video-fixture")

    probe_payload = {
        "format": {"format_name": "mp4", "duration": "8.000", "size": str(upload.stat().st_size)},
        "streams": [
            {
                "index": 0, "codec_type": "video", "codec_name": "h264",
                "width": 640, "height": 360, "duration": "8.000", "start_time": "0.000",
            },
            {
                "index": 1, "codec_type": "audio", "codec_name": "aac",
                "duration": "8.000", "start_time": "0.000",
                "sample_rate": "48000", "channels": 2,
            },
        ],
    }
    ffprobe = _write_executable(
        tmp_path / "ffprobe",
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "if '-version' in sys.argv: print('ffprobe version 7.1')\n"
        f"else: print({json.dumps(probe_payload)!r})\n",
    )
    ffmpeg = _write_executable(
        tmp_path / "ffmpeg",
        "#!/usr/bin/env python3\n"
        "import pathlib, sys, wave\n"
        "if '-version' in sys.argv: print('ffmpeg version 7.1')\n"
        "else:\n"
        " output = pathlib.Path(sys.argv[-1])\n"
        " with wave.open(str(output), 'wb') as audio:\n"
        "  audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)\n"
        "  audio.writeframes(bytes(2) * 16000 * 8)\n",
    )
    monkeypatch.setattr(
        "omniintel.media_probe.shutil.which",
        lambda name: str(ffprobe) if name == "ffprobe" else None,
    )
    monkeypatch.setattr(
        "omniintel.audio_extract.find_executable",
        lambda name: str(ffmpeg) if name == "ffmpeg" else None,
    )

    class DeterministicAsr:
        name = "e2e-fixture-asr"
        version = "1"
        model_id = "deterministic-test-model"
        @property
        def configuration(self) -> dict[str, bool]:
            return {"deterministic": True, "network": False}

        def transcribe_chunk(self, wav_path: Path, *, language: str | None):
            with wave.open(str(wav_path), "rb") as audio:
                duration_ms = audio.getnframes() * 1000 // audio.getframerate()
            end_ms = min(4_000, duration_ms)
            return ChunkTranscription(
                language=language or "en",
                segments=(
                    TranscriptSegmentInput(
                        text="Acceleration is the rate of change of velocity.",
                        start_ms=500,
                        end_ms=end_ms,
                        language=language or "en",
                    ),
                ),
            )

    monkeypatch.setattr(
        "omniintel.worker.FasterWhisperAdapter",
        lambda **_kwargs: DeterministicAsr(),
    )
    monkeypatch.setenv("OMNIINTEL_UPLOAD_DIR", str(upload_root))
    monkeypatch.setenv("OMNIINTEL_ASSET_DIR", str(asset_root))
    model_path = tmp_path / "asr-model"
    model_path.mkdir()
    monkeypatch.setenv("OMNIINTEL_ASR_MODEL_PATH", str(model_path))

    queue = JobQueue(database)
    job_id = queue.enqueue(
        "UPLOADED_MEDIA_TO_NOTES",
        {
            "upload_path": str(upload.resolve()),
            "original_name": upload.name,
            "title": "Physics lecture",
            "language": "en",
            "chapter_minutes": 10,
            "approve_ai": False,
        },
        max_attempts=1,
    )

    assert run_once(database, worker_id="media-e2e-worker") is True

    completed = queue.get(job_id)
    assert completed["state"] == "COMPLETED", completed.get("last_error")
    reader = completed["result"]["reader"]
    assert reader["source"]["title"] == "Physics lecture"
    assert reader["pipeline"]["status"] == "TRANSCRIPT_DRAFT_READY"
    blocks = [
        block
        for chapter in reader["chapters"]
        for block in chapter["blocks"]
    ]
    assert any(
        "Acceleration is the rate of change of velocity." in str(block.get("content"))
        and block.get("evidence")
        for block in blocks
    )
    assert reader["sources"]
    assert not upload.exists()

    with connect(database) as conn:
        evidence_count = conn.execute(
            "SELECT count(*) FROM evidence_items WHERE source_id=?",
            (reader["source"]["id"],),
        ).fetchone()[0]
        reference_count = conn.execute(
            "SELECT count(*) FROM evidence_refs WHERE source_id=?",
            (reader["source"]["id"],),
        ).fetchone()[0]
        derivative_count = conn.execute(
            "SELECT count(*) FROM media_derivatives",
        ).fetchone()[0]
    assert evidence_count >= 1
    assert reference_count >= 1
    assert derivative_count == 1
