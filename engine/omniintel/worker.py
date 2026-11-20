"""Background worker for OmniIntel's consent-gated online processing queue."""
from __future__ import annotations

import argparse
import os
import socket
import time
from pathlib import Path

from .jobs import JobQueue, LeaseLost
from .audio_extract import extract_audio
from .local_files import import_local_file
from .transcription import FasterWhisperAdapter, run_wav_transcription
from .generation_providers import resolve_study_generator
from .study_generation import generate_study_guide
from .youtube_pipeline import compose_registered_source, process_youtube_video
from .video_frames import extract_video_frames
from .visual_timeline import build_visual_timeline, list_visual_timeline


def run_once(database_path: str | Path, *, worker_id: str | None = None) -> bool:
    queue = JobQueue(database_path)
    job = queue.claim(worker_id or socket.gethostname(), lease_ms=60 * 60 * 1000)
    if job is None:
        return False
    upload_path: Path | None = None
    cleanup_upload = False
    result_visual: dict[str, object] | None = None
    try:
        payload = job["payload"]
        if job["job_type"] == "YOUTUBE_TO_NOTES":
            if payload.get("approve_network") is not True:
                raise PermissionError("Job is missing explicit network approval")
            transcript_reader = process_youtube_video(
                database_path, payload["url"], user_approved_network=True,
                language=payload.get("language"),
                chapter_minutes=int(payload.get("chapter_minutes", 10)),
            )
        elif job["job_type"] == "UPLOADED_MEDIA_TO_NOTES":
            upload_root = Path(os.environ.get("OMNIINTEL_UPLOAD_DIR", str(Path(database_path).parent / "uploads"))).resolve()
            upload_path = Path(payload["upload_path"]).resolve()
            if upload_root not in upload_path.parents or not upload_path.is_file():
                raise ValueError("Uploaded media path is outside the configured upload directory")
            asset_dir = Path(os.environ.get("OMNIINTEL_ASSET_DIR", "omniintel-assets"))
            imported = import_local_file(database_path, asset_dir, upload_path,
                title=payload.get("title") or payload.get("original_name"),
                max_bytes=250 * 1024 * 1024)
            extracted = extract_audio(database_path, asset_dir, imported.asset.id, timeout_seconds=1800)
            model_path = os.environ.get("OMNIINTEL_ASR_MODEL_PATH", "")
            model_id = model_path if model_path and Path(model_path).is_dir() else os.environ.get(
                "OMNIINTEL_ASR_MODEL_ID", ""
            )
            allow_model_download = os.environ.get("OMNIINTEL_ASR_ALLOW_MODEL_DOWNLOAD") == "1"
            if not model_id:
                raise RuntimeError(
                    "ASR is not configured; set OMNIINTEL_ASR_MODEL_PATH to a local model "
                    "or explicitly set OMNIINTEL_ASR_MODEL_ID and OMNIINTEL_ASR_ALLOW_MODEL_DOWNLOAD=1."
                )
            adapter = FasterWhisperAdapter(
                model_id=model_id,
                device=os.environ.get("OMNIINTEL_ASR_DEVICE", "cpu"),
                compute_type=os.environ.get("OMNIINTEL_ASR_COMPUTE_TYPE", "int8"),
                cpu_threads=int(os.environ.get("OMNIINTEL_ASR_THREADS", "4")),
                allow_model_download=allow_model_download,
            )
            run_wav_transcription(database_path, asset_dir, imported.source_id, extracted.output_asset_id,
                adapter,
                language=payload.get("language"),
                progress=lambda _done, _total: queue.heartbeat(
                    job["id"], job["lease_token"], lease_ms=60 * 60 * 1000
                ))
            transcript_reader = compose_registered_source(database_path, imported.source_id,
                chapter_minutes=int(payload.get("chapter_minutes", 10)))
            if payload.get("approve_visual") is True:
                if not str(getattr(imported.asset, "media_type", "")).startswith("video/"):
                    result_visual = {"status": "NOT_APPLICABLE", "reason": "NO_VIDEO_STREAM"}
                else:
                    extraction = extract_video_frames(
                        database_path, asset_dir, imported.asset.id,
                        min_interval_ms=15_000, max_frames=120,
                        max_total_bytes=128 * 1024 * 1024,
                        max_total_pixels=60_000_000,
                    )
                    timeline = build_visual_timeline(database_path, extraction.id)
                    timeline_rows = list_visual_timeline(database_path, imported.source_id)
                    events = {}
                    for row in timeline_rows:
                        event = events.setdefault(row["visual_event_id"], {
                            "event_id": row["visual_event_id"],
                            "timestamp_ms": row["timestamp_ms"],
                            "frame_index": row["frame_index"],
                            "review_state": row["review_state"],
                            "transcript_alignments": [],
                        })
                        if row["alignment_id"] is not None:
                            event["transcript_alignments"].append({
                                "transcript_segment_id": row["transcript_segment_id"],
                                "transcript_start_ms": row["transcript_start_ms"],
                                "transcript_end_ms": row["transcript_end_ms"],
                                "relation": row["relation"],
                                "delta_ms": row["delta_ms"],
                                "review_state": row["alignment_review_state"],
                            })
                    result_visual = {
                        "status": "SAMPLED_NEEDS_REVIEW",
                        "frame_count": extraction.frame_count,
                        "sample_interval_ms": extraction.sample_interval_ms,
                        "events_created": timeline.events_created,
                        "alignments_created": timeline.alignments_created,
                        "events": list(events.values()),
                        "automatic_acceptance": False,
                    }
                    transcript_reader["visual_timeline"] = result_visual
        else:
            raise ValueError("Unsupported job type: " + str(job["job_type"]))
        result = {
            "video_id": payload.get("video_id") or payload.get("original_name"),
            "title": transcript_reader["source"]["title"],
            "reader": transcript_reader,
            "ai_generation": "NOT_REQUESTED",
        }
        if payload.get("approve_visual") is True:
            result["visual_analysis"] = result_visual or {
                "status": "NOT_AVAILABLE",
                "reason": "VISUAL_SAMPLING_REQUIRES_UPLOADED_VIDEO",
            }
        if payload.get("approve_ai") is True:
            provider = os.environ.get("OMNIINTEL_AI_PROVIDER", "openai").strip().lower()
            default_model = (
                os.environ.get("OMNIINTEL_OLLAMA_MODEL", "llama3.1")
                if provider == "ollama"
                else os.environ.get("OMNIINTEL_FREE_LLM_MODEL", "chat:fast")
                if provider == "freelm"
                else os.environ.get("OMNIINTEL_OPENAI_MODEL", "gpt-4.1-mini")
            )
            model = os.environ.get("OMNIINTEL_AI_MODEL", default_model)
            generator = resolve_study_generator(provider)
            study_reader = generate_study_guide(
                database_path,
                transcript_reader["source"]["id"],
                model=model,
                approve_local_model=True,
                generator=generator,
            )
            study_reader["pipeline"]["provider"] = provider
            study_reader["pipeline"]["network_access"] = (
                "loopback-only" if provider == "ollama" else "external-user-approved"
            )
            result["reader"] = study_reader
            result["ai_generation"] = "DRAFT_READY_REVIEW_REQUIRED"
        queue.complete(job["id"], job["lease_token"], result)
        cleanup_upload = True
    except Exception as error:  # noqa: BLE001 - persist bounded failure for client recovery
        try:
            failure_state = queue.fail(
                job["id"],
                job["lease_token"],
                f"{type(error).__name__}: {error}",
                retry_delay_ms=0,
            )
            cleanup_upload = failure_state == "FAILED"
        except LeaseLost:
            return True
    finally:
        if cleanup_upload and upload_path is not None:
            upload_root = Path(os.environ.get(
                "OMNIINTEL_UPLOAD_DIR", str(Path(database_path).parent / "uploads")
            )).resolve()
            if upload_root in upload_path.resolve().parents:
                upload_path.unlink(missing_ok=True)
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
