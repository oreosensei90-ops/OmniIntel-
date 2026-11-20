"""Lease-aware local execution bridge for Cloudflare D1 + Backblaze B2 jobs.

The bridge never embeds provider credentials. It reuses the existing local JobQueue and
worker handlers, so transcript, evidence, textbook and ASR behavior stay in one engine.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .jobs import JobQueue
from .worker import run_once as run_local_once

_MAX_UPLOAD = 250 * 1024 * 1024
_MAX_READER = 20 * 1024 * 1024
_MEDIA_SUFFIX = re.compile(r"\.(mp3|m4a|wav|aac|flac|ogg|opus|mp4|m4v|mov|mkv|webm)$", re.I)


class BridgeError(RuntimeError):
    """A bounded remote/local bridge failure."""


def _api_origin(raw: str) -> str:
    parsed = urlparse(raw.strip())
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    ):
        raise ValueError("Use HTTPS for a remote OmniIntel Worker API.")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API address must be an origin without credentials, query or fragment.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_json(origin: str, token: str, path: str, *, method: str = "GET",
                  body: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        origin + path, data=data, method=method,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                 **({"Content-Type": "application/json"} if data is not None else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(2 * 1024 * 1024 + 1))
    except urllib.error.HTTPError as error:
        detail = error.read(16 * 1024).decode("utf-8", "replace")
        raise BridgeError(f"Worker API returned HTTP {error.code}: {detail[:1000]}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise BridgeError(f"Worker API request failed: {error}") from error
    if not isinstance(payload, dict):
        raise BridgeError("Worker API returned an invalid JSON object.")
    return payload


def _download_input(url: str, destination: Path, *, max_bytes: int = _MAX_UPLOAD) -> int:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise BridgeError("Worker supplied an invalid B2 download URL.")
    request = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("xb") as output:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > max_bytes:
                raise BridgeError("Uploaded media exceeds the 250 MiB processing limit.")
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise BridgeError("Uploaded media exceeds the 250 MiB processing limit.")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if total <= 0:
        destination.unlink(missing_ok=True)
        raise BridgeError("Uploaded media object is empty.")
    return total


def _validate_reader(reader: Any) -> None:
    if not isinstance(reader, dict) or not isinstance(reader.get("version"), dict):
        raise BridgeError("Engine returned an invalid reader document.")
    if not isinstance(reader.get("sources"), list) or not reader["sources"]:
        raise BridgeError("Reader document has no source catalog.")
    chapters = reader.get("chapters")
    if not isinstance(chapters, list) or not chapters or len(chapters) > 500:
        raise BridgeError("Reader document has an invalid chapter list.")
    blocks = 0
    for chapter in chapters:
        if not isinstance(chapter, dict) or not isinstance(chapter.get("chapter"), dict):
            raise BridgeError("Reader document contains invalid chapter metadata.")
        items = chapter.get("blocks")
        if not isinstance(items, list):
            raise BridgeError("Reader document contains invalid chapter blocks.")
        blocks += len(items)
        if blocks > 25_000:
            raise BridgeError("Reader document exceeds the 25,000 block safety limit.")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("content"), dict):
                raise BridgeError("Reader document contains an invalid block.")
            if not isinstance(item.get("evidence"), list) or len(item["evidence"]) > 100:
                raise BridgeError("Reader document contains invalid evidence references.")
    if len(json.dumps(reader, ensure_ascii=False).encode("utf-8")) > _MAX_READER:
        raise BridgeError("Reader document exceeds the 20 MiB artifact limit.")


def _local_payload(job: dict[str, Any], media_path: Path | None) -> dict[str, Any]:
    payload = dict(job.get("payload") or {})
    if job.get("job_type") == "YOUTUBE_TO_NOTES":
        if payload.get("approve_network") is not True:
            raise BridgeError("YouTube job is missing explicit network approval.")
        return payload
    if job.get("job_type") != "UPLOADED_MEDIA_TO_NOTES" or media_path is None:
        raise BridgeError("Unsupported job type or missing uploaded media.")
    if payload.get("approve_media_upload") is not True:
        raise BridgeError("Media job is missing explicit upload approval.")
    return {
        "upload_path": str(media_path.resolve()),
        "original_name": Path(str(payload.get("filename") or "uploaded-media")).name[:255],
        "title": str(payload.get("title") or Path(str(payload.get("filename") or "Uploaded media")).stem)[:300],
        "language": payload.get("language"),
        "chapter_minutes": int(payload.get("chapter_minutes", 10)),
        "approve_ai": payload.get("approve_ai") is True,
    }


def _heartbeat_loop(origin: str, token: str, job_id: str, lease_token: str,
                    stop: threading.Event, errors: list[BaseException],
                    interval: int = 240) -> None:
    while not stop.wait(interval):
        try:
            _request_json(origin, token, f"/v1/worker/jobs/{job_id}/heartbeat",
                          method="POST", body={"lease_token": lease_token}, timeout=30)
        except BaseException as error:  # heartbeat failure means remote ownership may be lost
            errors.append(error)
            stop.set()
            return


def process_claimed_job(job: dict[str, Any], *, database: Path, origin: str, token: str,
                        upload_dir: Path, asset_dir: Path) -> dict[str, Any]:
    job_id = str(job["job_id"])
    lease_token = str(job["lease_token"])
    media_path: Path | None = None
    old_upload = os.environ.get("OMNIINTEL_UPLOAD_DIR")
    old_asset = os.environ.get("OMNIINTEL_ASSET_DIR")
    upload_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    try:
        if job.get("job_type") == "UPLOADED_MEDIA_TO_NOTES":
            filename = Path(str((job.get("payload") or {}).get("filename") or "upload.bin")).name
            suffix = Path(filename).suffix.lower()
            if not _MEDIA_SUFFIX.search(filename):
                raise BridgeError("Unsupported uploaded media file extension.")
            media_path = upload_dir / (job_id + suffix)
            media_path.unlink(missing_ok=True)
            _download_input(str(job.get("download_url") or ""), media_path)
        local_payload = _local_payload(job, media_path)
        os.environ["OMNIINTEL_UPLOAD_DIR"] = str(upload_dir.resolve())
        os.environ["OMNIINTEL_ASSET_DIR"] = str(asset_dir.resolve())
        local_queue = JobQueue(database)
        local_id = local_queue.enqueue(
            str(job["job_type"]), local_payload,
            idempotency_key="cloudflare:" + job_id, max_attempts=1,
        )
        run_local_once(database, worker_id="cloudflare-" + job_id)
        completed = local_queue.get(local_id)
        if not completed or completed["state"] != "COMPLETED":
            detail = (completed or {}).get("last_error") or "Local engine did not complete the job."
            raise BridgeError(str(detail)[:1000])
        result = completed.get("result") or {}
        reader = result.get("reader")
        _validate_reader(reader)
        response = _request_json(
            origin, token, f"/v1/worker/jobs/{job_id}/complete", method="POST",
            body={"lease_token": lease_token, "reader": reader}, timeout=120,
        )
        return response
    finally:
        if media_path is not None:
            media_path.unlink(missing_ok=True)
        if old_upload is None:
            os.environ.pop("OMNIINTEL_UPLOAD_DIR", None)
        else:
            os.environ["OMNIINTEL_UPLOAD_DIR"] = old_upload
        if old_asset is None:
            os.environ.pop("OMNIINTEL_ASSET_DIR", None)
        else:
            os.environ["OMNIINTEL_ASSET_DIR"] = old_asset


def run_bridge_once(*, api_base: str, api_token: str, database: Path,
                    upload_dir: Path, asset_dir: Path) -> bool:
    origin = _api_origin(api_base)
    if not api_token:
        raise ValueError("Set OMNIINTEL_API_TOKEN before starting the bridge.")
    claimed = _request_json(origin, api_token, "/v1/worker/claim", method="POST", body={})
    job = claimed.get("job")
    if job is None:
        return False
    stop = threading.Event()
    heartbeat_errors: list[BaseException] = []
    thread = threading.Thread(
        target=_heartbeat_loop,
        args=(origin, api_token, str(job["job_id"]), str(job["lease_token"]),
              stop, heartbeat_errors),
        daemon=True,
    )
    thread.start()
    try:
        process_claimed_job(job, database=database, origin=origin, token=api_token,
                            upload_dir=upload_dir, asset_dir=asset_dir)
        if heartbeat_errors:
            raise BridgeError(f"Remote job lease heartbeat failed: {heartbeat_errors[0]}")
    except Exception as error:
        try:
            _request_json(
                origin, api_token, f"/v1/worker/jobs/{job['job_id']}/fail",
                method="POST", body={"lease_token": job["lease_token"],
                                     "error": f"{type(error).__name__}: {error}"[:1900]},
            )
        except Exception:
            pass
    finally:
        stop.set()
        thread.join(timeout=2)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(prog="omniintel-cloud-worker")
    parser.add_argument("--api", default=os.environ.get("OMNIINTEL_WORKER_API", ""))
    parser.add_argument("--database", type=Path, default=Path(os.environ.get("OMNIINTEL_DATABASE", "omniintel.db")))
    parser.add_argument("--upload-dir", type=Path, default=Path(os.environ.get("OMNIINTEL_UPLOAD_DIR", "omniintel-uploads")))
    parser.add_argument("--asset-dir", type=Path, default=Path(os.environ.get("OMNIINTEL_ASSET_DIR", "omniintel-assets")))
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.api:
        parser.error("Provide --api or set OMNIINTEL_WORKER_API.")
    if not 0.5 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be between 0.5 and 60.")
    token = os.environ.get("OMNIINTEL_API_TOKEN", "")
    if not token:
        parser.error("Set OMNIINTEL_API_TOKEN in the environment.")
    while True:
        worked = run_bridge_once(api_base=args.api, api_token=token, database=args.database,
                                 upload_dir=args.upload_dir, asset_dir=args.asset_dir)
        if args.once:
            break
        if not worked:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
