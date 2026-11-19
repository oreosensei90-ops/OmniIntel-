"""Authenticated HTTP API for online OmniIntel video-to-notes jobs.

The API only accepts explicit user approval for remote source access and external AI.
Long-running work is performed by the separate omniintel-worker process.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .jobs import JobQueue
from .youtube_pipeline import normalize_youtube_url


class YouTubeJobRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    approve_network: bool = False
    approve_ai: bool = False
    language: str | None = Field(default=None, min_length=2, max_length=16)
    chapter_minutes: int = Field(default=10, ge=1, le=30)


def create_app(
    database_path: str | Path | None = None,
    *,
    api_token: str | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    db_path = Path(database_path or os.environ.get("OMNIINTEL_DATABASE", "omniintel.db"))
    expected_token = api_token if api_token is not None else os.environ.get("OMNIINTEL_API_TOKEN", "")
    origins = cors_origins if cors_origins is not None else [
        item.strip() for item in os.environ.get("OMNIINTEL_CORS_ORIGINS", "").split(",")
        if item.strip()
    ]
    app = FastAPI(
        title="OmniIntel API",
        version="0.1.0",
        description="Consent-gated online video-to-notes processing API.",
    )
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )
    queue = JobQueue(db_path)
    app.state.database_path = db_path
    app.state.job_queue = queue

    def require_token(authorization: str | None = Header(default=None)) -> None:
        if not expected_token:
            raise HTTPException(status_code=503, detail="API authentication is not configured")
        supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
        if not hmac.compare_digest(supplied, expected_token):
            raise HTTPException(status_code=401, detail="A valid bearer token is required")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "omniintel-api"}

    @app.post("/v1/youtube/jobs", status_code=202)
    def submit_youtube_job(
        body: YouTubeJobRequest,
        _: None = Depends(require_token),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict:
        if body.approve_network is not True:
            raise HTTPException(
                status_code=400,
                detail="Explicit approval is required before contacting YouTube.",
            )
        try:
            canonical_url, video_id = normalize_youtube_url(body.url)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if body.approve_ai and not os.environ.get("OMNIINTEL_OPENAI_API_KEY"):
            raise HTTPException(
                status_code=503,
                detail="External AI generation is not configured on this server.",
            )
        payload = {
            "url": canonical_url,
            "video_id": video_id,
            "language": body.language,
            "chapter_minutes": body.chapter_minutes,
            "approve_network": True,
            "approve_ai": body.approve_ai,
        }
        try:
            job_id = queue.enqueue(
                "YOUTUBE_TO_NOTES",
                payload,
                idempotency_key=idempotency_key,
                max_attempts=1,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "job_id": job_id,
            "video_id": video_id,
            "status": "QUEUED",
            "status_url": f"/v1/jobs/{job_id}",
        }

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, _: None = Depends(require_token)) -> dict:
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "job_id": job["id"],
            "job_type": job["job_type"],
            "status": job["state"],
            "attempt": job["attempt_count"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "error": job["last_error"],
            "result": job["result"] if job["state"] == "COMPLETED" else None,
        }

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(
        "omniintel.api:app",
        host=os.environ.get("OMNIINTEL_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("OMNIINTEL_API_PORT", "8000")),
        reload=False,
    )


app = create_app()
