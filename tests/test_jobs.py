from pathlib import Path

import pytest

from omniintel.jobs import IdempotencyConflict, JobQueue, LeaseLost


class Clock:
    def __init__(self, value=1_000_000):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, milliseconds):
        self.value += milliseconds


def test_enqueue_is_persistent_and_idempotent(tmp_path: Path):
    path = tmp_path / "jobs.db"
    queue = JobQueue(path)
    first = queue.enqueue("transcript.import", {"source": "abc"}, idempotency_key="import:abc")
    second = JobQueue(path).enqueue(
        "transcript.import", {"source": "abc"}, idempotency_key="import:abc"
    )
    assert first == second
    assert queue.get(first)["state"] == "QUEUED"


def test_idempotency_key_rejects_different_payload(tmp_path: Path):
    queue = JobQueue(tmp_path / "jobs.db")
    queue.enqueue("process", {"source": "a"}, idempotency_key="same")
    with pytest.raises(IdempotencyConflict):
        queue.enqueue("process", {"source": "b"}, idempotency_key="same")


def test_claim_complete_and_stale_lease_rejected(tmp_path: Path):
    clock = Clock()
    queue = JobQueue(tmp_path / "jobs.db", clock_ms=clock)
    job_id = queue.enqueue("render.pdf", {"book": "book-1"})
    claimed = queue.claim("worker-1", lease_ms=100)
    assert claimed["id"] == job_id
    clock.advance(101)
    with pytest.raises(LeaseLost):
        queue.complete(job_id, claimed["lease_token"])
    reclaimed = queue.claim("worker-2", lease_ms=100)
    assert reclaimed["id"] == job_id
    queue.complete(job_id, reclaimed["lease_token"], {"pages": 12})
    assert queue.get(job_id)["state"] == "COMPLETED"


def test_failure_uses_bounded_retry_then_dead_ends(tmp_path: Path):
    clock = Clock()
    queue = JobQueue(tmp_path / "jobs.db", clock_ms=clock)
    job_id = queue.enqueue("transcribe", {}, max_attempts=2)
    first = queue.claim("w1", lease_ms=100)
    assert queue.fail(job_id, first["lease_token"], "temporary") == "RETRYING"
    clock.advance(1_000)
    second = queue.claim("w2", lease_ms=100)
    assert second["attempt_count"] == 2
    assert queue.fail(job_id, second["lease_token"], "permanent") == "FAILED"
    assert queue.get(job_id)["state"] == "FAILED"


def test_heartbeat_extends_lease(tmp_path: Path):
    clock = Clock()
    queue = JobQueue(tmp_path / "jobs.db", clock_ms=clock)
    job_id = queue.enqueue("analyze", {})
    claim = queue.claim("worker", lease_ms=50)
    clock.advance(30)
    queue.heartbeat(job_id, claim["lease_token"], lease_ms=100)
    clock.advance(60)
    queue.complete(job_id, claim["lease_token"])
    assert queue.get(job_id)["state"] == "COMPLETED"


def test_delayed_job_is_not_claimed_early(tmp_path: Path):
    clock = Clock()
    queue = JobQueue(tmp_path / "jobs.db", clock_ms=clock)
    queue.enqueue("delayed", {}, delay_ms=500)
    assert queue.claim("worker") is None
    clock.advance(500)
    assert queue.claim("worker") is not None
