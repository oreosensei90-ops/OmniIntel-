from __future__ import annotations

import pytest

from omniintel.cloud_worker_bridge import (
    BridgeError, _api_origin, _local_payload, _validate_reader,
)


def test_api_origin_requires_https_and_rejects_credentials():
    assert _api_origin("https://worker.example/") == "https://worker.example"
    assert _api_origin("http://localhost:8787") == "http://localhost:8787"
    with pytest.raises(ValueError):
        _api_origin("http://worker.example")
    with pytest.raises(ValueError):
        _api_origin("https://user:pass@worker.example")


def test_local_payload_preserves_youtube_consent():
    job = {
        "job_type": "YOUTUBE_TO_NOTES",
        "payload": {"url": "https://www.youtube.com/watch?v=abcdef12345",
                    "approve_network": True, "approve_ai": False},
    }
    assert _local_payload(job, None) == job["payload"]


def test_local_payload_requires_media_upload_approval(tmp_path):
    job = {"job_type": "UPLOADED_MEDIA_TO_NOTES",
           "payload": {"filename": "lecture.mp4", "approve_media_upload": False}}
    with pytest.raises(BridgeError, match="upload approval"):
        _local_payload(job, tmp_path / "lecture.mp4")


def test_reader_validator_accepts_engine_reader_shape():
    _validate_reader({
        "version": {"id": "v1"},
        "sources": [{"source_id": "s1"}],
        "chapters": [{"chapter": {"id": "c1"}, "blocks": [{
            "content": {"text": "grounded"}, "evidence": []
        }]}],
    })


@pytest.mark.parametrize("reader", [None, {}, {"version": {}, "sources": [], "chapters": []}])
def test_reader_validator_rejects_invalid_reader(reader):
    with pytest.raises(BridgeError):
        _validate_reader(reader)
