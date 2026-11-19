"""Explicitly approved, local-only execution of read-only input plans.

This coordinator never launches a shell or subprocess. Concrete adapters are injected
by the application and must expose only the named local stages.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now

_ALLOWED_STAGES = {
    "REGISTER_SOURCE", "EXTRACT_AUDIO", "TRANSCRIBE_LOCAL",
    "EXTRACT_PDF_TEXT", "SAMPLE_VIDEO_FRAMES", "OCR_LOCAL",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class PlanExecutionError(RuntimeError):
    pass


class PlanExecutor:
    """Persist approved plan snapshots and idempotent stage checkpoints."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    @staticmethod
    def _snapshot(plan: dict[str, Any]) -> dict[str, Any]:
        if plan.get("read_only") is not True or plan.get("questions"):
            raise PlanExecutionError("Plan must be read-only and have all user questions resolved")
        inputs = plan.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            raise PlanExecutionError("Plan contains no inputs")
        snapshot_inputs = []
        for item in inputs:
            path = Path(item["path"]).resolve(strict=True)
            if not path.is_file():
                raise PlanExecutionError(f"Input is not a regular file: {path.name}")
            stat = path.stat()
            size = stat.st_size
            planned_mtime = item.get("modified_ns")
            planned_inode = item.get("file_id")
            if (size <= 0 or size != item["byte_size"]
                    or (item.get("modified_ns") and stat.st_mtime_ns != item["modified_ns"])
                    or (item.get("file_id") and stat.st_ino != item["file_id"])):
                raise PlanExecutionError(f"Input changed after planning: {path.name}")
            digest = _sha256_file(path)
            after = path.stat()
            if after.st_size != stat.st_size or after.st_mtime_ns != stat.st_mtime_ns or after.st_ino != stat.st_ino:
                raise PlanExecutionError(f"Input changed while hashing: {path.name}")
            snapshot_inputs.append({
                "path": str(path), "byte_size": size, "sha256": digest,
                "modality": item["modality"], "media_type": item["media_type"],
            })
        return {"schema_version": 1, "inputs": snapshot_inputs}

    def approve_and_run(
        self,
        plan: dict[str, Any],
        stages: list[dict[str, Any]],
        *,
        user_approved: bool,
        handlers: dict[str, Callable[[list[Path], dict[str, Any]], dict[str, Any]]],
    ) -> dict[str, Any]:
        """Run only after an explicit approval flag; handlers are local injected adapters."""
        if user_approved is not True:
            raise PlanExecutionError("Explicit user approval is required before execution")
        snapshot = self._snapshot(plan)
        if not stages:
            raise PlanExecutionError("At least one execution stage must be approved")
        normalized = []
        for stage in stages:
            key = stage.get("stage")
            if key not in _ALLOWED_STAGES or key not in handlers:
                raise PlanExecutionError(f"Stage is not an available local adapter: {key}")
            if stage.get("network", "none") != "none":
                raise PlanExecutionError("Network-enabled stages are not allowed by this executor")
            indices = stage.get("input_indices")
            if not isinstance(indices, list) or not indices or any(
                not isinstance(index, int) or index < 0 or index >= len(snapshot["inputs"])
                for index in indices
            ):
                raise PlanExecutionError("Stage input_indices must reference selected plan inputs")
            normalized.append({"stage": key, "input_indices": indices, "network": "none"})
        payload = {"snapshot": snapshot, "stages": normalized}
        plan_hash = _canonical_hash(payload)
        plan_id = uuid7()
        now = utc_now()
        with connect(self.database_path) as conn:
            migrate(conn)
            existing = conn.execute(
                "SELECT id,status FROM approved_execution_plans WHERE plan_hash=?", (plan_hash,)
            ).fetchone()
            if existing and existing["status"] == "COMPLETED":
                return {"plan_id": existing["id"], "status": "COMPLETED", "reused": True}
            if existing:
                plan_id = existing["id"]
            else:
                conn.execute(
                    """INSERT INTO approved_execution_plans
                       (id,plan_hash,plan_json,approved_at,status)
                       VALUES(?,?,?,?,'APPROVED')""",
                    (plan_id, plan_hash, json.dumps(payload, sort_keys=True), now),
                )
            conn.execute(
                "UPDATE approved_execution_plans SET status='RUNNING' WHERE id=?", (plan_id,)
            )

        results: list[dict[str, Any]] = []
        try:
            for ordinal, stage in enumerate(normalized):
                selected = [snapshot["inputs"][i] for i in stage["input_indices"]]
                input_hash = _canonical_hash(selected)
                stage_key = f"{ordinal}:{stage['stage']}"
                with connect(self.database_path) as conn:
                    prior = conn.execute(
                        """SELECT state,result_json FROM execution_stage_checkpoints
                           WHERE plan_id=? AND stage_key=? AND input_hash=?""",
                        (plan_id, stage_key, input_hash),
                    ).fetchone()
                    if prior and prior["state"] == "COMPLETED":
                        result = json.loads(prior["result_json"] or "{}")
                        results.append({"stage": stage["stage"], "state": "COMPLETED", "result": result, "reused": True})
                        continue
                    checkpoint_id = prior["id"] if prior else uuid7()
                    conn.execute(
                        """INSERT INTO execution_stage_checkpoints
                           (id,plan_id,stage_key,input_hash,state,started_at)
                           VALUES(?,?,?,?,'RUNNING',?)
                           ON CONFLICT(plan_id,stage_key,input_hash) DO UPDATE SET
                             state='RUNNING',error_text=NULL,started_at=excluded.started_at""",
                        (checkpoint_id, plan_id, stage_key, input_hash, utc_now()),
                    )
                # Revalidate immediately before handing a path to an adapter.
                current = self._snapshot(plan)
                if current != snapshot:
                    raise PlanExecutionError("Input changed during execution; refusing stale stage")
                paths = [Path(item["path"]) for item in selected]
                result = handlers[stage["stage"]](paths, {
                    "plan_id": plan_id, "stage": stage["stage"],
                    "expected_sha256": [item["sha256"] for item in selected],
                })
                if not isinstance(result, dict):
                    raise PlanExecutionError("Stage adapters must return a JSON object")
                json.dumps(result, allow_nan=False)
                with connect(self.database_path) as conn:
                    conn.execute(
                        """UPDATE execution_stage_checkpoints
                           SET state='COMPLETED',result_json=?,completed_at=?
                           WHERE plan_id=? AND stage_key=? AND input_hash=?""",
                        (json.dumps(result, sort_keys=True), utc_now(), plan_id, stage_key, input_hash),
                    )
                results.append({"stage": stage["stage"], "state": "COMPLETED", "result": result, "reused": False})
        except Exception as exc:
            with connect(self.database_path) as conn:
                conn.execute(
                    "UPDATE approved_execution_plans SET status='FAILED' WHERE id=?", (plan_id,)
                )
                conn.execute(
                    """UPDATE execution_stage_checkpoints SET state='FAILED',error_text=?
                       WHERE plan_id=? AND state='RUNNING'""",
                    (str(exc)[:2000], plan_id),
                )
            raise
        with connect(self.database_path) as conn:
            conn.execute(
                "UPDATE approved_execution_plans SET status='COMPLETED' WHERE id=?", (plan_id,)
            )
        return {"plan_id": plan_id, "status": "COMPLETED", "reused": False, "stages": results}
