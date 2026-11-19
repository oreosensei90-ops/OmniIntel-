"""Background worker for OmniIntel's consent-gated online processing queue."""
from __future__ import annotations

import argparse
import os
import socket
import time
from pathlib import Path

from .jobs import JobQueue, LeaseLost
from .remote_generation import generate_openai_study_json
from .study_generation import generate_study_guide
from .youtube_pipeline import process_youtube_video


def run_once(database_path: str | Path, *, worker_id: str | None = None) -> bool:
    queue = JobQueue(database_path)
    job = queue.claim(worker_id or socket.gethostname(), lease_ms=60 * 60 * 1000)
    if job is None:
        return False
    try:
        if job["job_type"] != "YOUTUBE_TO_NOTES":
            raise ValueError(f"Unsupported job type: {job['job_type']}")
        payload = job["payload"]
        if payload.get("approve_network") is not True:
            raise PermissionError("Job is missing explicit network approval")
        transcript_reader = process_youtube_video(
            database_path,
            payload["url"],
            user_approved_network=True,
            language=payload.get("language"),
            chapter_minutes=int(payload.get("chapter_minutes", 10)),
        )
        result = {
            "video_id": payload["video_id"],
            "title": transcript_reader["source"]["title"],
            "transcript_reader": transcript_reader,
            "reader": transcript_reader,
            "ai_generation": "NOT_REQUESTED",
        }
        if payload.get("approve_ai") is True:
            model = os.environ.get("OMNIINTEL_OPENAI_MODEL", "gpt-4.1-mini")
            study_reader = generate_study_guide(
                database_path,
                transcript_reader["source"]["id"],
                model=model,
                approve_local_model=True,
                generator=generate_openai_study_json,
            )
            study_reader["pipeline"]["provider"] = "openai-api"
            study_reader["pipeline"]["network_access"] = "external-user-approved"
            result["reader"] = study_reader
            result["study_guide_reader"] = study_reader
            result["ai_generation"] = "DRAFT_READY_REVIEW_REQUIRED"
        queue.complete(job["id"], job["lease_token"], result)
    except Exception as error:  # noqa: BLE001 - persist bounded failure for client recovery
        try:
            queue.fail(
                job["id"],
                job["lease_token"],
                f"{type(error).__name__}: {error}",
                retry_delay_ms=0,
            )
        except LeaseLost:
            return True
    return True


def main() -> None:
    parser = argparse.ArgumentParser(prog="omniintel-worker")
    parser.add_argument("--database", type=Path, default=Path(os.environ.get("OMNIINTEL_DATABASE", "omniintel.db")))
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 0.1 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be between 0.1 and 60")
    while True:
        worked = run_once(args.database, worker_id=args.worker_id)
        if args.once:
            break
        if not worked:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
