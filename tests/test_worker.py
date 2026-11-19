from types import SimpleNamespace

from omniintel.jobs import JobQueue
from omniintel.worker import run_once


def test_youtube_job_worker_completes_with_reader_export_without_network_in_test(tmp_path, monkeypatch):
    database = tmp_path / "worker.db"
    reader = {
        "source": {"id": "source-youtube", "title": "Lecture"},
        "version": {"id": "version-youtube"},
        "chapters": [],
    }
    queue = JobQueue(database)
    job_id = queue.enqueue(
        "YOUTUBE_TO_NOTES",
        {
            "url": "https://www.youtube.com/watch?v=abcdefghijk",
            "video_id": "abcdefghijk",
            "approve_network": True,
            "approve_ai": False,
            "chapter_minutes": 10,
        },
        max_attempts=1,
    )
    monkeypatch.setattr(
        "omniintel.worker.process_youtube_video",
        lambda *args, **kwargs: reader,
    )

    assert run_once(database, worker_id="test-worker") is True
    job = queue.get(job_id)
    assert job["state"] == "COMPLETED"
    assert job["result"]["reader"] == reader
    assert job["result"]["ai_generation"] == "NOT_REQUESTED"


def test_uploaded_media_worker_runs_local_asr_then_composes_reader(tmp_path, monkeypatch):
    database = tmp_path / "worker.db"
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    upload = upload_root / "lecture.mp4"
    upload.write_bytes(b"test media fixture")
    asset_root = tmp_path / "assets"
    model_root = tmp_path / "asr-model"
    model_root.mkdir()
    monkeypatch.setenv("OMNIINTEL_UPLOAD_DIR", str(upload_root))
    monkeypatch.setenv("OMNIINTEL_ASSET_DIR", str(asset_root))
    monkeypatch.setenv("OMNIINTEL_ASR_MODEL_PATH", str(model_root))

    reader = {
        "source": {"id": "source-upload", "title": "Uploaded lecture"},
        "version": {"id": "version-upload"},
        "chapters": [],
    }
    queue = JobQueue(database)
    job_id = queue.enqueue(
        "UPLOADED_MEDIA_TO_NOTES",
        {
            "upload_path": str(upload.resolve()),
            "original_name": "lecture.mp4",
            "title": "Uploaded lecture",
            "language": "en",
            "chapter_minutes": 10,
            "approve_ai": False,
        },
        max_attempts=1,
    )
    imported = SimpleNamespace(
        source_id="source-upload",
        asset=SimpleNamespace(id="video-asset"),
    )
    extracted = SimpleNamespace(output_asset_id="audio-asset")
    monkeypatch.setattr("omniintel.worker.import_local_file", lambda *args, **kwargs: imported)
    monkeypatch.setattr("omniintel.worker.extract_audio", lambda *args, **kwargs: extracted)
    monkeypatch.setattr("omniintel.worker.run_wav_transcription", lambda *args, **kwargs: None)
    monkeypatch.setattr("omniintel.worker.compose_registered_source", lambda *args, **kwargs: reader)

    assert run_once(database, worker_id="test-worker") is True
    job = queue.get(job_id)
    assert job["state"] == "COMPLETED"
    assert job["result"]["reader"] == reader
    assert job["result"]["video_id"] == "lecture.mp4"
    assert not upload.exists()
