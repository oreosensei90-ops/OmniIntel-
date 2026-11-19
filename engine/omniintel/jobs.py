"""Persistent single-device job queue with leases and bounded retries.

Delivery is at-least-once. Handlers must be idempotent; a lease cannot make
external side effects exactly-once.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now


class JobError(RuntimeError):
    """Base class for job queue errors."""


class IdempotencyConflict(JobError):
    """An idempotency key was reused with different request data."""


class LeaseLost(JobError):
    """The worker no longer owns the active lease."""


class JobQueue:
    def __init__(self, database_path: str | Path, *, clock_ms=None):
        self.database_path = Path(database_path)
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        with connect(self.database_path) as conn:
            migrate(conn)

    def _now(self) -> int:
        return int(self._clock_ms())

    @staticmethod
    def _canonical_payload(payload: dict[str, Any]) -> tuple[str, str]:
        if not isinstance(payload, dict):
            raise ValueError("Job payload must be a JSON object")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        delay_ms: int = 0,
    ) -> str:
        if not job_type or not job_type.strip():
            raise ValueError("job_type must not be empty")
        if idempotency_key is not None and not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        if max_attempts < 1 or delay_ms < 0:
            raise ValueError("max_attempts must be positive and delay_ms non-negative")
        payload_json, payload_hash = self._canonical_payload(payload)
        now = self._now()
        job_id = uuid7()
        with connect(self.database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = conn.execute(
                    "SELECT id,payload_hash,job_type,max_attempts FROM jobs WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    if (
                        existing["payload_hash"] != payload_hash
                        or existing["job_type"] != job_type
                        or existing["max_attempts"] != max_attempts
                    ):
                        raise IdempotencyConflict(
                            "Idempotency key already exists with different job input or options"
                        )
                    return str(existing["id"])
            conn.execute(
                """INSERT INTO jobs
                   (id,job_type,payload_json,state,idempotency_key,payload_hash,
                    attempt_count,max_attempts,available_at_ms,created_at,updated_at)
                   VALUES(?,?,?,'QUEUED',?,?,0,?,?,?,?)""",
                (
                    job_id, job_type, payload_json, idempotency_key, payload_hash,
                    max_attempts, now + delay_ms, utc_now(), utc_now(),
                ),
            )
        return job_id

    def claim(self, worker_id: str, *, lease_ms: int = 60_000) -> dict[str, Any] | None:
        if not worker_id or not worker_id.strip() or lease_ms <= 0:
            raise ValueError("worker_id must be non-empty and lease_ms positive")
        now = self._now()
        token = secrets.token_urlsafe(24)
        with connect(self.database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Expired workers may still be executing. Reclaiming permits at-least-once
            # delivery, so handlers and output commits must be idempotent.
            conn.execute(
                """UPDATE jobs
                   SET state=CASE WHEN attempt_count >= max_attempts THEN 'FAILED' ELSE 'RETRYING' END,
                       lease_owner=NULL, lease_token=NULL, lease_expires_at_ms=NULL,
                       available_at_ms=?, last_error=COALESCE(last_error,'Worker lease expired'),
                       updated_at=?
                   WHERE state='RUNNING' AND lease_expires_at_ms <= ?""",
                (now, utc_now(), now),
            )
            row = conn.execute(
                """SELECT id FROM jobs
                   WHERE state IN ('QUEUED','RETRYING') AND available_at_ms <= ?
                     AND attempt_count < max_attempts
                   ORDER BY available_at_ms, created_at, id LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                return None
            changed = conn.execute(
                """UPDATE jobs
                   SET state='RUNNING', attempt_count=attempt_count+1,
                       lease_owner=?, lease_token=?, lease_expires_at_ms=?, updated_at=?
                   WHERE id=? AND state IN ('QUEUED','RETRYING')""",
                (worker_id, token, now + lease_ms, utc_now(), row["id"]),
            ).rowcount
            if changed != 1:
                return None
            claimed = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            result = dict(claimed)
        result["payload"] = json.loads(result.pop("payload_json"))
        result["result"] = json.loads(result.pop("result_json")) if result["result_json"] else None
        return result

    def heartbeat(self, job_id: str, lease_token: str, *, lease_ms: int = 60_000) -> None:
        if lease_ms <= 0:
            raise ValueError("lease_ms must be positive")
        now = self._now()
        with connect(self.database_path) as conn:
            changed = conn.execute(
                """UPDATE jobs SET lease_expires_at_ms=?,updated_at=?
                   WHERE id=? AND state='RUNNING' AND lease_token=?
                     AND lease_expires_at_ms > ?""",
                (now + lease_ms, utc_now(), job_id, lease_token, now),
            ).rowcount
            if changed != 1:
                raise LeaseLost("Cannot renew an expired or unowned job lease")

    def complete(self, job_id: str, lease_token: str, result: dict[str, Any] | None = None) -> None:
        result_json = json.dumps(result or {}, ensure_ascii=False, sort_keys=True)
        now = self._now()
        with connect(self.database_path) as conn:
            changed = conn.execute(
                """UPDATE jobs SET state='COMPLETED',result_json=?,
                   lease_owner=NULL,lease_token=NULL,lease_expires_at_ms=NULL,
                   completed_at=?,updated_at=?
                   WHERE id=? AND state='RUNNING' AND lease_token=?
                     AND lease_expires_at_ms > ?""",
                (result_json, utc_now(), utc_now(), job_id, lease_token, now),
            ).rowcount
            if changed != 1:
                raise LeaseLost("Cannot complete a job without its active lease")

    def fail(
        self,
        job_id: str,
        lease_token: str,
        error: str,
        *,
        retry_delay_ms: int = 1_000,
    ) -> str:
        if retry_delay_ms < 0:
            raise ValueError("retry_delay_ms must be non-negative")
        now = self._now()
        with connect(self.database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT attempt_count,max_attempts FROM jobs
                   WHERE id=? AND state='RUNNING' AND lease_token=?
                     AND lease_expires_at_ms > ?""",
                (job_id, lease_token, now),
            ).fetchone()
            if row is None:
                raise LeaseLost("Cannot fail a job without its active lease")
            terminal = row["attempt_count"] >= row["max_attempts"]
            state = "FAILED" if terminal else "RETRYING"
            delay = min(retry_delay_ms * (2 ** max(0, row["attempt_count"] - 1)), 3_600_000)
            conn.execute(
                """UPDATE jobs SET state=?,available_at_ms=?,last_error=?,
                   lease_owner=NULL,lease_token=NULL,lease_expires_at_ms=NULL,updated_at=?
                   WHERE id=?""",
                (state, now + (0 if terminal else delay), error[:2_000], utc_now(), job_id),
            )
        return state

    def get(self, job_id: str) -> dict[str, Any] | None:
        with connect(self.database_path) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        result["result"] = json.loads(result.pop("result_json")) if result["result_json"] else None
        result.pop("result_json")
        return result
