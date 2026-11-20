# OmniIntel Cloudflare + Backblaze bridge

This service is the lightweight remote coordination layer. Cloudflare Workers exposes the
authenticated API, D1 stores durable job metadata and leases, and a private Backblaze B2 bucket
stores user-uploaded media and completed reader JSON. A local computer/Termux agent runs the
existing Python engine. No paid compute service is required for processing; the machine running
the agent must stay online and have the required local dependencies and ASR model.

## Resource bindings and secrets

Create the D1 database `omniintel-db`, bind it as `DB`, and replace the placeholder
`database_id` in `wrangler.toml` with the ID from `npx wrangler d1 list`.

Set secrets interactively; never commit their values:

```sh
cd infra/cloudflare/worker
npx wrangler secret put OMNIINTEL_API_TOKEN
npx wrangler secret put B2_KEY_ID
npx wrangler secret put B2_APPLICATION_KEY
npx wrangler secret put B2_S3_ENDPOINT
```

Use the Backblaze S3 endpoint shown for the `omniintel-assets` bucket. The B2 application key
must be restricted to that bucket and allow object read, write, delete and list operations.
The endpoint is typically shaped like
`https://s3.<region>.backblazeb2.com`; do not guess the region.

Set `CORS_ORIGIN` in `wrangler.toml` to a comma-separated allowlist of exact Web origins
(no wildcard). For local development, use a separate local Wrangler environment and add the
exact localhost origin. Android native requests do not use browser CORS.

## B2 bucket CORS

The Web app uploads media to a short-lived presigned B2 URL and downloads completed reader
artifacts from another short-lived URL. Configure the bucket's S3 CORS policy to allow the
exact Web origin(s), methods `PUT, GET, HEAD`, request headers `Content-Type` and
`x-amz-*`, and expose `ETag, Content-Length`. Do not make the bucket public. Keep B2
application keys private.

## Deploy

First inspect the account and confirm that the existing D1 database and bucket are the intended
resources. The commands below deploy only the Worker and D1 schema; they do not create a paid
compute service.

```sh
cd infra/cloudflare/worker
npm install
npx wrangler d1 migrations apply omniintel-db --remote
npm run typecheck
npm test
npx wrangler deploy
```

Check current Cloudflare and Backblaze account limits before production use. The project is
zero-cost-first; do not enable billing, upgrade plans or create paid resources to make this
architecture work.

## API contract

All routes except `GET /health` require `Authorization: Bearer <OMNIINTEL_API_TOKEN>`.

- `POST /v1/youtube/jobs`: JSON containing `url`, `approve_network: true`,
  `approve_ai`, optional `language` and `chapter_minutes`.
- `POST /v1/media/jobs`: JSON containing `filename`, `title`,
  `approve_media_upload: true`, `approve_ai`, optional `language` and
  `chapter_minutes`. The response has a short-lived `upload_url` and an
  `upload_complete_url`.
- Upload media bytes with an unauthenticated HTTP `PUT` to `upload_url`, then call
  `POST upload_complete_url` with the API bearer token. The Worker verifies the object exists
  and is within the configured 250 MiB limit before making the job claimable.
- `POST /v1/worker/claim`: the local agent claims one job and receives a 15-minute lease.
  Uploaded-media jobs include a short-lived B2 `download_url`.
- `POST /v1/worker/jobs/{id}/heartbeat`: renew the active lease while the local engine runs.
- `POST /v1/worker/jobs/{id}/complete`: send `{ "lease_token": "...", "reader": { ... } }`.
  The Worker stores validated reader JSON in B2 and marks the D1 job complete.
- `POST /v1/worker/jobs/{id}/fail`: send a bounded error; the job is requeued within its
  attempt limit, otherwise it becomes terminally failed.
- `GET /v1/jobs/{id}`: returns job status and, when complete, a short-lived `result_url`.

The D1 migration includes an upload-completion gate, attempt limits and lease expiry. Jobs
whose final lease expires are moved to FAILED rather than remaining stuck. Worker lease tokens
are required for heartbeat, completion and failure. Artifacts use lease-specific object keys so
a stale worker cannot overwrite the current worker's output.

## Run the local processing agent

Install the project and the optional dependencies for the source types you intend to process.
For YouTube public captions:

```sh
python -m pip install -e ".[youtube,service]"
```

For uploaded audio/video, also install FFmpeg and the optional ASR dependency, then configure a
local faster-whisper/CTranslate2 model directory. The model files are not downloaded
automatically by the bridge.

Set the same API bearer token that was configured as the Worker secret. Set the AI provider key
locally only if users explicitly approve AI generation and the existing engine is configured to
use it. The key stays on the processing machine; it is never sent to D1 or B2.

```sh
export OMNIINTEL_WORKER_API="https://<your-worker-subdomain>.workers.dev"
export OMNIINTEL_API_TOKEN="<same-token-as-worker-secret>"
export OMNIINTEL_DATABASE="$HOME/omniintel/omniintel.db"
export OMNIINTEL_ASR_MODEL_PATH="$HOME/models/faster-whisper-small"
# Optional, only when approved AI generation is enabled:
export OMNIINTEL_OPENAI_API_KEY="<your-provider-key>"
omniintel-cloud-worker --poll-seconds 5
```

The local agent claims jobs, downloads media to a private local upload directory, runs the
existing Python `JobQueue` worker and processing adapters, renews the D1 lease while work is
running, validates the reader export, and posts the artifact back to the Worker for B2 storage.
Temporary uploaded media is removed after processing. Keep the local database and asset
directories on persistent storage. The agent does not expose an inbound port.

Use `--once` for a one-job smoke test. Keep the agent running to process queued jobs.

## Client integration

The Web and Android clients now use the same Worker endpoints. They submit YouTube consent and
media-upload consent explicitly. Media uploads go directly to the private B2 presigned URL;
completed reader JSON is downloaded from its short-lived B2 result URL and imported into the
existing offline reader library. Set the exact Web origin in Worker CORS and B2 bucket CORS.

## Security and operational boundary

- This initial deployment is single-tenant: the bearer token is a shared API credential, not
  per-user identity or authorization. Do not expose it in a public multi-user product.
- Keep API tokens, B2 keys and provider keys out of source control, logs, job payloads and reader
  documents. Rotate them if exposed.
- Uploads are limited to 250 MiB and reader artifacts to 20 MiB. B2 is private; only temporary
  presigned URLs grant object access.
- YouTube processing requires explicit public-network approval. It retrieves public metadata
  and captions only; it does not download video/audio, use cookies, retrieve private captions,
  or bypass DRM/access controls.
- Media processing requires explicit upload approval. External AI generation is a separate
  opt-in. Generated content remains a draft requiring human review.
- Local processing depends on the user's machine being online. Android/Termux faster-whisper
  compatibility is not assumed; a supported PC/Linux host may be needed for ASR.
- There is no public live endpoint or deployment implied by this source change. Before deploying,
  replace the D1 ID and CORS placeholder, configure B2 bucket CORS, and verify account quotas.
