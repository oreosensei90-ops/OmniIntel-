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

def test_uploaded_media_worker_allows_explicit_hosted_model_download(tmp_path, monkeypatch):
    database = tmp_path / "worker.db"
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    upload = upload_root / "lecture.mp4"
    upload.write_bytes(b"test media fixture")
    monkeypatch.setenv("OMNIINTEL_UPLOAD_DIR", str(upload_root))
    monkeypatch.setenv("OMNIINTEL_ASSET_DIR", str(tmp_path / "assets"))
    monkeypatch.delenv("OMNIINTEL_ASR_MODEL_PATH", raising=False)
    monkeypatch.setenv("OMNIINTEL_ASR_MODEL_ID", "tiny")
    monkeypatch.setenv("OMNIINTEL_ASR_ALLOW_MODEL_DOWNLOAD", "1")

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
    imported = SimpleNamespace(source_id="source-upload", asset=SimpleNamespace(id="video-asset"))
    extracted = SimpleNamespace(output_asset_id="audio-asset")
    adapter_options = {}
    monkeypatch.setattr("omniintel.worker.import_local_file", lambda *args, **kwargs: imported)
    monkeypatch.setattr("omniintel.worker.extract_audio", lambda *args, **kwargs: extracted)

    class FakeAdapter:
        def __init__(self, **kwargs):
            adapter_options.update(kwargs)

    monkeypatch.setattr("omniintel.worker.FasterWhisperAdapter", FakeAdapter)
    monkeypatch.setattr("omniintel.worker.run_wav_transcription", lambda *args, **kwargs: None)
    monkeypatch.setattr("omniintel.worker.compose_registered_source", lambda *args, **kwargs: reader)

    assert run_once(database, worker_id="hosted-asr-test") is True
    assert adapter_options["model_id"] == "tiny"
    assert adapter_options["allow_model_download"] is True
    assert queue.get(job_id)["state"] == "COMPLETED"
    assert not upload.exists()



def test_uploaded_media_worker_preserves_input_until_retry_finishes(tmp_path, monkeypatch):
    database = tmp_path / "worker.db"
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    upload = upload_root / "retry-lecture.mp4"
    upload.write_bytes(b"test media fixture")
    model_root = tmp_path / "asr-model"
    model_root.mkdir()
    monkeypatch.setenv("OMNIINTEL_UPLOAD_DIR", str(upload_root))
    monkeypatch.setenv("OMNIINTEL_ASSET_DIR", str(tmp_path / "assets"))
    monkeypatch.setenv("OMNIINTEL_ASR_MODEL_PATH", str(model_root))

    reader = {
        "source": {"id": "source-retry", "title": "Retry lecture"},
        "version": {"id": "version-retry"},
        "chapters": [],
    }
    queue = JobQueue(database)
    job_id = queue.enqueue(
        "UPLOADED_MEDIA_TO_NOTES",
        {
            "upload_path": str(upload.resolve()),
            "original_name": "retry-lecture.mp4",
            "title": "Retry lecture",
            "language": "en",
            "chapter_minutes": 10,
            "approve_ai": False,
        },
        max_attempts=2,
    )
    imported = SimpleNamespace(
        source_id="source-retry",
        asset=SimpleNamespace(id="video-asset"),
    )
    extracted = SimpleNamespace(output_asset_id="audio-asset")
    attempts = {"extract": 0}

    monkeypatch.setattr("omniintel.worker.import_local_file", lambda *args, **kwargs: imported)

    def extract_once_then_succeed(*args, **kwargs):
        attempts["extract"] += 1
        if attempts["extract"] == 1:
            raise RuntimeError("temporary extraction failure")
        return extracted

    monkeypatch.setattr("omniintel.worker.extract_audio", extract_once_then_succeed)

    class FakeAdapter:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr("omniintel.worker.FasterWhisperAdapter", FakeAdapter)
    monkeypatch.setattr("omniintel.worker.run_wav_transcription", lambda *args, **kwargs: None)
    monkeypatch.setattr("omniintel.worker.compose_registered_source", lambda *args, **kwargs: reader)

    assert run_once(database, worker_id="retry-worker") is True
    assert queue.get(job_id)["state"] == "RETRYING"
    assert upload.exists(), "retryable jobs must retain their staged input"

    assert run_once(database, worker_id="retry-worker") is True
    assert queue.get(job_id)["state"] == "COMPLETED"
    assert not upload.exists(), "completed jobs should clean up their staged input"


def test_uploaded_video_worker_runs_opt_in_visual_sampling_and_keeps_review_gate(
    tmp_path, monkeypatch
):
    database = tmp_path / "worker.db"
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    upload = upload_root / "visual-lecture.mp4"
    upload.write_bytes(b"video fixture")
    monkeypatch.setenv("OMNIINTEL_UPLOAD_DIR", str(upload_root))
    monkeypatch.setenv("OMNIINTEL_ASSET_DIR", str(tmp_path / "assets"))
    model_root = tmp_path / "asr-model"
    model_root.mkdir()
    monkeypatch.setenv("OMNIINTEL_ASR_MODEL_PATH", str(model_root))

    reader = {
        "source": {"id": "source-visual", "title": "Visual lecture"},
        "version": {"id": "version-visual"},
        "chapters": [],
    }
    queue = JobQueue(database)
    job_id = queue.enqueue(
        "UPLOADED_MEDIA_TO_NOTES",
        {
            "upload_path": str(upload.resolve()),
            "original_name": upload.name,
            "title": "Visual lecture",
            "language": "en",
            "chapter_minutes": 10,
            "approve_ai": False,
            "approve_visual": True,
        },
        max_attempts=1,
    )
    imported = SimpleNamespace(
        source_id="source-visual",
        asset=SimpleNamespace(id="video-asset", media_type="video/mp4"),
    )
    extracted = SimpleNamespace(output_asset_id="audio-asset")
    frame_extraction = SimpleNamespace(id="frame-extraction", frame_count=2, sample_interval_ms=15_000)
    timeline = SimpleNamespace(events_created=2, alignments_created=1)
    timeline_rows = [
        {
            "visual_event_id": "event-1", "timestamp_ms": 1000, "frame_index": 0,
            "review_state": "NEEDS_REVIEW", "alignment_id": "alignment-1",
            "transcript_segment_id": "segment-1", "transcript_start_ms": 500,
            "transcript_end_ms": 2000, "relation": "OVERLAPS", "delta_ms": 0,
            "alignment_review_state": "NEEDS_REVIEW",
        },
        {
            "visual_event_id": "event-2", "timestamp_ms": 16000, "frame_index": 1,
            "review_state": "NEEDS_REVIEW", "alignment_id": None,
            "transcript_segment_id": None, "transcript_start_ms": None,
            "transcript_end_ms": None, "relation": None, "delta_ms": None,
            "alignment_review_state": None,
        },
    ]
    monkeypatch.setattr("omniintel.worker.import_local_file", lambda *args, **kwargs: imported)
    monkeypatch.setattr("omniintel.worker.extract_audio", lambda *args, **kwargs: extracted)
    monkeypatch.setattr("omniintel.worker.FasterWhisperAdapter", lambda **kwargs: object())
    monkeypatch.setattr("omniintel.worker.run_wav_transcription", lambda *args, **kwargs: None)
    monkeypatch.setattr("omniintel.worker.compose_registered_source", lambda *args, **kwargs: reader)
    monkeypatch.setattr("omniintel.worker.extract_video_frames", lambda *args, **kwargs: frame_extraction)
    monkeypatch.setattr("omniintel.worker.build_visual_timeline", lambda *args, **kwargs: timeline)
    monkeypatch.setattr("omniintel.worker.list_visual_timeline", lambda *args, **kwargs: timeline_rows)

    assert run_once(database, worker_id="visual-worker") is True
    completed = queue.get(job_id)
    assert completed["state"] == "COMPLETED"
    visual = completed["result"]["visual_analysis"]
    assert visual["status"] == "SAMPLED_NEEDS_REVIEW"
    assert visual["frame_count"] == 2
    assert visual["automatic_acceptance"] is False
    assert visual["events"][0]["transcript_alignments"][0]["review_state"] == "NEEDS_REVIEW"
    assert completed["result"]["reader"]["visual_timeline"] == visual
    assert not upload.exists()
