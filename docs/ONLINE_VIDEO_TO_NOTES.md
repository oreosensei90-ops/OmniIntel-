# Online video → AI study notes

## Current online flow

1. The Web or Android client submits a single supported YouTube URL to the authenticated OmniIntel API.
2. The client must explicitly approve public metadata/caption retrieval and external AI processing.
3. The API validates the YouTube host/video ID and enqueues a durable `YOUTUBE_TO_NOTES` job.
4. A separate worker retrieves bounded public metadata and caption sidecars only, imports timestamped transcript evidence, and composes an extractive reader draft.
5. When the user approved AI processing, the worker sends bounded transcript evidence to the server-configured OpenAI model using a strict JSON schema. Generated study-guide blocks and evidence links remain `NEEDS_REVIEW` / `PENDING`.
6. The client polls job status and imports the returned reader JSON into the Web reader or Android Room library.

The worker and API share the same persistent SQLite database. The API token is server-configured; the OpenAI API key is never sent to clients. The Web client keeps its bearer token in tab-scoped session storage. Android keeps the token in the current Compose session and persists only the API origin.

## Run

Install the service, YouTube and local ASR extras:

```bash
python -m pip install -e '.[service,youtube,asr]'
export OMNIINTEL_DATABASE=/srv/omniintel/omniintel.db
export OMNIINTEL_API_TOKEN='use-a-long-random-secret'
export OMNIINTEL_CORS_ORIGINS='https://your-web-app.example'
export OMNIINTEL_OPENAI_API_KEY='server-side-secret'
export OMNIINTEL_OPENAI_MODEL='gpt-4.1-mini'
export OMNIINTEL_UPLOAD_DIR=/srv/omniintel/uploads
export OMNIINTEL_ASSET_DIR=/srv/omniintel/assets
export OMNIINTEL_ASR_MODEL_PATH=/models/faster-whisper-small
omniintel-api
```

In a separate process/container using the same database:

```bash
omniintel-worker --database /srv/omniintel/omniintel.db
```

The API defaults to loopback binding. Put it behind a TLS reverse proxy for remote access. Configure exact CORS origins and protect the bearer token. Keep the database on persistent storage and do not expose SQLite over a network filesystem with unsafe locking semantics.

## API

- `GET /health` — public process health.
- `POST /v1/youtube/jobs` — bearer-authenticated job submission; requires `approve_network: true`. AI generation additionally requires `approve_ai: true` and a server-configured API key.
- `POST /v1/media/jobs` — bearer-authenticated multipart audio/video upload (250 MiB maximum), optional language/title, and explicit `approve_ai` form value.
- `GET /v1/jobs/{job_id}` — bearer-authenticated status and completed reader result.

The job request accepts `url`, `approve_network`, `approve_ai`, optional `language`, and `chapter_minutes` (1–30). The optional `Idempotency-Key` header prevents duplicate submissions when the same key and payload are retried.

## Explicit current limitations

- The hosted YouTube adapter retrieves metadata and public caption sidecars only. It does not download video/audio, bypass DRM, use cookies, or access private captions.
- The Web client also supports direct user-authorized audio/video upload (maximum 250 MiB). The worker registers the original asset, uses FFmpeg/ffprobe to extract audio, and transcribes it with a preinstalled local faster-whisper/CTranslate2 model. Configure `OMNIINTEL_UPLOAD_DIR`, `OMNIINTEL_ASSET_DIR`, `OMNIINTEL_ASR_MODEL_PATH`, and install FFmpeg/ffprobe on the worker host.
- When YouTube captions are unavailable, the user can provide an authorized media file through the upload route. The Android client currently submits YouTube URLs; direct media upload is available in the Web client.
- AI generation is an evidence-cited draft, not a verified answer key. Citation IDs are structurally constrained to supplied source evidence, but semantic entailment, factual correctness, completeness and contradiction resolution still require review.
- This is a single-token service foundation, not a multi-tenant account/billing system. Production deployment still needs rate limiting, abuse controls, observability, backup/restore, security review and operational monitoring.
- A server and worker must actually be deployed and configured. The repository does not include a production API hostname or secrets.

Never process content without appropriate rights and authorization. Public availability does not automatically grant download, reproduction or redistribution rights.
