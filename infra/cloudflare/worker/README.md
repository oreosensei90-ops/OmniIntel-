# OmniIntel Cloudflare + Backblaze bridge

This is the first remote coordination slice. It does not replace the Python engine or the
existing local SQLite queue. Cloudflare Worker owns authenticated job coordination and D1
metadata; Backblaze B2 stores input objects and completed reader JSON. A separately running
local agent will claim jobs and invoke the existing Python processing engine.

## Resources and secrets

Create the D1 database named `omniintel-db` and bind it as `DB`. Replace the placeholder
`database_id` in `wrangler.toml` with its actual ID.

Set Worker secrets (never commit their values):

```sh
npx wrangler secret put OMNIINTEL_API_TOKEN
npx wrangler secret put B2_KEY_ID
npx wrangler secret put B2_APPLICATION_KEY
```

The B2 application key must be restricted to the `omniintel-assets` bucket and allow
list/read/write object operations. Set `B2_S3_ENDPOINT` as a Worker secret or environment
variable to the exact S3 endpoint shown by Backblaze, for example
`https://s3.us-west-004.backblazeb2.com`. `B2_BUCKET_NAME` is configured in wrangler.toml.

## Deploy

```sh
cd infra/cloudflare/worker
npm install
npx wrangler d1 migrations apply omniintel-db --remote
npx wrangler deploy
```

The Wrangler account must already have the D1 database. Deploying does not create or upgrade
paid services; check the current Cloudflare and Backblaze account limits before production use.

## API contract

All endpoints except `GET /health` require `Authorization: Bearer <OMNIINTEL_API_TOKEN>`.

- `POST /v1/jobs`: JSON `{ "job_type": "YOUTUBE_TO_NOTES", "payload": { "url": "...", "approve_network": true, "approve_ai": false } }`.
- `POST /v1/jobs`: uploaded media uses `job_type: "UPLOADED_MEDIA_TO_NOTES"` and payload
  `{ "filename": "lecture.mp4", "approve_media_upload": true, "approve_ai": false }`.
  Response includes a short-lived B2 `upload_url`; PUT the selected media bytes to it.
- `POST /v1/worker/claim`: local agent claims one queued job and receives a lease token.
  Uploaded-media jobs include a short-lived B2 `download_url`.
- `POST /v1/worker/jobs/{id}/complete`: send `{ "lease_token": "...", "reader": { ...reader JSON... } }`.
  The Worker stores the reader JSON in B2 and changes the D1 job to COMPLETED.
- `POST /v1/worker/jobs/{id}/fail`: send `{ "lease_token": "...", "error": "..." }`; jobs are requeued
  up to the configured attempt limit.
- `GET /v1/jobs/{id}`: authenticated job status; completed jobs include a temporary result URL.

YouTube jobs require explicit network approval. Media jobs require explicit upload approval.
AI generation remains separately opt-in through `approve_ai`. Do not put API keys or other
secrets inside job payloads.

## Current boundary / next integration

This commit implements the D1 schema, authenticated Worker routes, B2 presigned input uploads,
B2 input downloads for claimed jobs, and B2 storage of completed reader artifacts. It does not
yet include the local Python polling agent, client-side media upload wiring, per-user identity,
or production observability. The next change must add a lease-aware Python bridge that downloads
authorized input into a private temporary directory, invokes the existing engine, uploads only
validated reader JSON, and reports bounded failures. Until then, the Worker is an API foundation,
not an end-to-end processing service.
