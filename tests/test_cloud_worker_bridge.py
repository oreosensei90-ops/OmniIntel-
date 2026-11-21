from __future__ import annotations

from pathlib import Path

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

def test_process_claimed_youtube_job_reuses_local_engine_and_posts_reader(tmp_path, monkeypatch):
    import omniintel.cloud_worker_bridge as bridge

    calls = {}
    reader = {
        "version": {"id": "version-1"},
        "sources": [{"source_id": "source-1"}],
        "chapters": [{"chapter": {"id": "chapter-1"}, "blocks": [{
            "content": {"text": "grounded"}, "evidence": []
        }]}],
    }

    class FakeQueue:
        def __init__(self, _database):
            pass

        def enqueue(self, job_type, payload, **kwargs):
            calls["job_type"] = job_type
            calls["payload"] = payload
            calls["idempotency_key"] = kwargs["idempotency_key"]
            return "local-job"

        def get(self, _job_id):
            return {"state": "COMPLETED", "result": {"reader": reader}}

    def fake_complete(origin, token, path, **kwargs):
        calls["complete_path"] = path
        calls["complete_body"] = kwargs["body"]
        return {"status": "COMPLETED"}

    monkeypatch.setattr(bridge, "JobQueue", FakeQueue)
    def fake_run_once(database, **_kwargs):
        calls["worker_database"] = database
        calls["asset_dir"] = Path(__import__("os").environ["OMNIINTEL_ASSET_DIR"])
        assert calls["asset_dir"].is_dir()
        return True
    monkeypatch.setattr(bridge, "run_local_once", fake_run_once)
    monkeypatch.setattr(bridge, "_request_json", fake_complete)
    job = {
        "job_id": "11111111-1111-4111-8111-111111111111",
        "job_type": "YOUTUBE_TO_NOTES",
        "lease_token": "lease-1",
        "payload": {"url": "https://www.youtube.com/watch?v=abcdef12345",
                    "approve_network": True, "approve_ai": False},
    }
    response = bridge.process_claimed_job(
        job, database=tmp_path / "bridge.db", origin="https://worker.example",
        token="secret", upload_dir=tmp_path / "uploads", asset_dir=tmp_path / "assets",
    )
    assert response["status"] == "COMPLETED"
    assert calls["job_type"] == "YOUTUBE_TO_NOTES"
    assert calls["payload"]["approve_network"] is True
    assert calls["idempotency_key"] == "cloudflare:11111111-1111-4111-8111-111111111111:1"
    assert str(calls["worker_database"]).endswith(
        "cloud-worker-jobs/11111111-1111-4111-8111-111111111111-attempt-1/worker.sqlite3"
    )
    assert calls["worker_database"] != tmp_path / "bridge.db"
    assert not calls["worker_database"].parent.exists(), "completed attempt workspace must be removed"
    assert calls["complete_path"].endswith("/complete")
    assert calls["complete_body"]["reader"] == reader


def test_process_claimed_job_rejects_bad_reader_before_remote_completion(tmp_path, monkeypatch):
    import omniintel.cloud_worker_bridge as bridge

    class FakeQueue:
        def __init__(self, _database):
            pass

        def enqueue(self, *_args, **_kwargs):
            return "local-job"

        def get(self, _job_id):
            return {"state": "COMPLETED", "result": {"reader": {"version": {}}}}

    monkeypatch.setattr(bridge, "JobQueue", FakeQueue)
    monkeypatch.setattr(bridge, "run_local_once", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(bridge, "_request_json", lambda *_args, **_kwargs: pytest.fail("must not post invalid reader"))
    job = {
        "job_id": "11111111-1111-4111-8111-111111111111",
        "job_type": "YOUTUBE_TO_NOTES",
        "lease_token": "lease-1",
        "payload": {"url": "https://www.youtube.com/watch?v=abcdef12345",
                    "approve_network": True},
    }
    with pytest.raises(BridgeError, match="source catalog"):
        bridge.process_claimed_job(
            job, database=tmp_path / "bridge.db", origin="https://worker.example",
            token="secret", upload_dir=tmp_path / "uploads", asset_dir=tmp_path / "assets",
        )


def test_download_input_rejects_untrusted_host_before_network(tmp_path):
    import omniintel.cloud_worker_bridge as bridge
    with pytest.raises(BridgeError, match="untrusted B2"):
        bridge._download_input("https://attacker.example/object?signature=x", tmp_path / "x.bin")


def test_download_input_rejects_nonstandard_port(tmp_path):
    import omniintel.cloud_worker_bridge as bridge
    with pytest.raises(BridgeError, match="untrusted B2"):
        bridge._download_input("https://s3.us-east-005.backblazeb2.com:8443/object", tmp_path / "x.bin")


def test_late_heartbeat_failure_does_not_override_successful_job_completion(tmp_path, monkeypatch):
    import threading
    import omniintel.cloud_worker_bridge as bridge

    job = {
        "job_id": "11111111-1111-4111-8111-111111111111",
        "lease_token": "lease-1",
    }
    calls = []
    heartbeat_seen = threading.Event()

    def fake_request(_origin, _token, path, **_kwargs):
        calls.append(path)
        if path == "/v1/worker/claim":
            return {"job": job}
        pytest.fail("a completed job must not be reported as failed")

    def fake_heartbeat(_origin, _token, _job_id, _lease, _stop, errors):
        errors.append(RuntimeError("late heartbeat returned 409 after completion"))
        heartbeat_seen.set()

    def fake_process(*_args, **_kwargs):
        assert heartbeat_seen.wait(timeout=2)
        return {"status": "COMPLETED"}

    monkeypatch.setattr(bridge, "_request_json", fake_request)
    monkeypatch.setattr(bridge, "_heartbeat_loop", fake_heartbeat)
    monkeypatch.setattr(bridge, "process_claimed_job", fake_process)

    assert bridge.run_bridge_once(
        api_base="https://worker.example",
        worker_token="worker-secret",
        database=tmp_path / "bridge.db",
        upload_dir=tmp_path / "uploads",
        asset_dir=tmp_path / "assets",
    ) is True
    assert calls == ["/v1/worker/claim"]



def test_local_payload_preserves_explicit_visual_analysis_consent(tmp_path):
    job = {
        "job_type": "UPLOADED_MEDIA_TO_NOTES",
        "payload": {
            "filename": "lecture.mp4",
            "approve_media_upload": True,
            "approve_ai": False,
            "approve_visual": True,
        },
    }
    local = _local_payload(job, tmp_path / "lecture.mp4")
    assert local["approve_visual"] is True
    assert local["approve_ai"] is False



def test_worker_workspace_pruning_is_age_and_name_bounded(tmp_path):
    import os
    import time
    from omniintel.cloud_worker_bridge import _prune_stale_workspaces

    root = tmp_path / "cloud-worker-jobs"
    stale = root / "11111111-1111-4111-8111-111111111111-attempt-1"
    recent = root / "22222222-2222-4222-8222-222222222222-attempt-2"
    unrelated = root / "keep-this-directory"
    for directory in (stale, recent, unrelated):
        directory.mkdir(parents=True)
        (directory / "marker").write_text("keep")
    old_time = time.time() - (8 * 24 * 60 * 60)
    os.utime(stale, (old_time, old_time))

    assert _prune_stale_workspaces(root) == 1
    assert not stale.exists()
    assert recent.exists()
    assert unrelated.exists()


def test_process_claimed_job_rejects_invalid_job_identifier_before_workspace_creation(tmp_path):
    import omniintel.cloud_worker_bridge as bridge

    with pytest.raises(BridgeError, match="invalid job identifier"):
        bridge.process_claimed_job(
            {"job_id": "../outside", "lease_token": "lease-1", "job_type": "YOUTUBE_TO_NOTES",
             "payload": {"approve_network": True}},
            database=tmp_path / "bridge.db", origin="https://worker.example",
            token="secret", upload_dir=tmp_path / "uploads", asset_dir=tmp_path / "assets",
        )
    assert not (tmp_path / "cloud-worker-jobs").exists()
