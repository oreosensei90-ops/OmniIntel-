# OmniIntel — Master Architecture & Engineering Handoff
**Prepared:** 2026-11-21  
**Repository:** https://github.com/oreosensei90-ops/OmniIntel-  
**Primary application source branch:** `milestone/end-to-end-reliability-2026-11-21`  
**Source commit at handoff preparation:** `c81623bb8e53ae8c6dd406b5141d60fc82d5d339`  
**Default branch:** `main` (contains the hosted-worker scheduler entry; it is not the full application source snapshot).

> This is an engineering handoff, not a claim that production is working. The latest hosted-worker run failed before processing a job. Its log proves that the image was pulled successfully and Docker then exited with `invalid reference format`. The workflow's shell command contains doubled backslashes at line endings; this is the first concrete P0 defect to fix and verify.

---

## 1. Product goal and boundaries

OmniIntel converts an authorized YouTube video or user-uploaded audio/video into a structured, timestamped, evidence-linked reader / study document. The web reader can open exported reader JSON locally and keep annotations, bookmarks, study progress, and imported books in browser-local storage.

The product has two deliberately different operating modes:

1. **Local/offline reader:** open a reader JSON export, read chapters, inspect evidence, attach a local copy of the original media for timestamp seeking, and keep private study notes locally.
2. **Online media-to-notes pipeline:** submit a YouTube URL or upload a media file, obtain consent, send a job to the API, store upload objects in B2, process through a Python worker, persist job/artifact metadata, and retrieve a reader JSON artifact.

Do not confuse the local reader UI with the remote processing service. A working Pages homepage does not prove that API submission, B2 transfer, worker execution, or artifact retrieval works.

Non-goals / safety boundaries currently expressed by the code:
- YouTube support is restricted to supported public video URLs; playlist URLs are not accepted.
- Public captions are preferred. Audio-stream download for transcription is a fallback only when the user has separately approved it.
- No cookies, private YouTube endpoints, DRM circumvention, or video-file download in the YouTube caption path.
- User-uploaded media processing requires explicit authorization/consent.
- AI transcript submission is a separate opt-in.
- Visual frame sampling is a separate opt-in and candidate alignments remain unreviewed until accepted.
- Reader composition is intended to preserve transcript/source evidence rather than inventing source facts.

## 2. System context / components

### A. Browser frontend — Cloudflare Pages
- Public site: `https://omniintel.pages.dev`
- Preview domain previously used: `https://b9588ac7.omniintel.pages.dev`
- Main source files: `apps/web/index.html`, `apps/web/app.js`, `apps/web/styles.css`, manifest and service-worker assets.
- The homepage exposes:
  - YouTube URL submission and preferred caption language.
  - Explicit network/media processing approval.
  - Separate AI-provider approval.
  - Audio/video upload (250 MiB UI limit), language, upload approval, optional AI approval, optional visual-sampling approval.
  - Reader JSON import.
- Reader mode renders chapters and blocks, evidence references, optional source seek controls, study cards, local annotations/bookmarks/progress, and local backup/restore.
- The browser should never hold a provider API key. It may hold a user-scoped OmniIntel bearer token in tab memory for the current session. Do not persist it in localStorage, IndexedDB, URLs, analytics, or logs.
- CSP is declared in the HTML. Review every new external dependency against it.

### B. Cloudflare Worker API
- Public API origin: `https://omniintel-api.scrbaba502.workers.dev`
- Source: `infra/cloudflare/worker/src/index.ts` plus D1 migrations/configuration under `infra/cloudflare/`.
- Responsibilities:
  - Validate authenticated client requests and consent payloads.
  - Create and persist jobs in D1.
  - Create upload intents and issue short-lived, object-scoped B2 presigned URLs.
  - Finalize/validate uploaded objects.
  - Expose worker-bridge claim, heartbeat, completion/failure, and artifact retrieval endpoints.
  - Enforce job ownership, lease state, request limits, and allowed transitions.
- The API is a control plane, not the CPU-intensive transcription engine.
- Keep API authentication, worker bridge authentication, and B2 credentials separate. Never ship the worker token or B2 application key to the browser.

### C. D1 — durable job/control-plane database
- Cloudflare D1 stores durable job state and metadata, not large media bytes.
- Review migrations, uniqueness constraints, indexes, foreign keys, lease expiry, attempt counters, idempotency, and status transition rules.
- Job lifecycle expected at a high level:
  `CREATED/UPLOAD_PENDING → QUEUED → RUNNING (leased) → SUCCEEDED | FAILED`.
  Exact enum names and allowed transitions must be confirmed against the current schema/API code.
- A job must not be marked successful until the reader artifact has been durably stored and can be retrieved by the authorized client.

### D. Backblaze B2 — object storage
- Bucket: `omniintel-vault-2026`
- S3 endpoint: `https://s3.us-east-005.backblazeb2.com`
- Region: `us-east-005`
- B2 stores uploaded media and generated artifacts; D1 stores object keys/metadata.
- Browser uploads are direct-to-B2 using a presigned PUT URL. Browser CORS must allow the exact Pages origins, PUT, required signed headers, and any response headers the frontend reads.
- Intended origins currently configured by the deployment workflow:
  - `https://omniintel.pages.dev`
  - `https://b9588ac7.omniintel.pages.dev`
- CORS configuration has had two workflow defects: the no-CORS error-name casing check, and read-back validation relying on an optional ID. Both were patched on the milestone branch; the latest deployment outcome still needs confirmation.
- Do not make the bucket public merely to bypass CORS. Keep object access private and presigned URLs short-lived.

### E. Python processing engine
- Package root: `engine/omniintel/`
- Project configuration: `pyproject.toml`
- Entrypoint: `omniintel-cloud-worker = omniintel.cloud_worker_bridge:main`
- Docker image: `Dockerfile.cloud-worker`
- Container entrypoint: `deploy/start-cloud-worker.sh`
- Core modules include the cloud bridge, job queue/worker, YouTube pipeline, captions parsing, FFmpeg/audio extraction, Faster-Whisper transcription, source store/textbook composition, reader export, and optional AI/study generation.
- The bridge downloads media only from an allowlisted B2 host, validates job consent, runs the existing local pipeline, validates the reader JSON structure/size, and reports the result back to the Worker API.
- Public captions should be attempted first. If captions are unavailable, only the consented audio fallback is permitted. For uploaded media, FFmpeg/ffprobe and the configured ASR model are required.
- The image is expected to run as an unprivileged user and the hosted runner applies read-only root filesystem, bounded CPU/memory/PIDs, dropped capabilities, and a writable mounted work directory.

### F. Hosted worker orchestration — GitHub Actions + GHCR
- Workflow on default branch: `.github/workflows/hosted-worker.yml`
- Image publisher on the processing branch: `.github/workflows/publish-worker-image.yml`
- Image registry: `ghcr.io/oreosensei90-ops/omniintel-cloud-worker`
- The worker workflow should run from the default branch (GitHub scheduled workflows are evaluated from the default branch), check out the processing branch, resolve its immutable SHA image tag, authenticate to GHCR, pull the image, then run a bounded polling worker.
- Required GitHub Actions secrets (names only; never put values in this document):
  - `OMNIINTEL_WORKER_TOKEN`
  - `GEMINI_API_KEY` (only if the selected provider needs it)
  - `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`
  - `OMNIINTEL_API_TOKEN`, `OMNIINTEL_WORKER_TOKEN`
  - `B2_KEY_ID`, `B2_APPLICATION_KEY`
- The deployed Worker also needs correctly configured environment bindings/secrets for D1, B2 signing, API auth and worker-bridge auth. Verify the exact variable names against Worker source and deployment workflow; do not assume GitHub secrets automatically exist in Cloudflare.
- GitHub Actions scheduled cadence currently intended: every 15 minutes, plus push/manual trigger. A scheduled worker is not a continuously running always-on server; design job leases and retry behavior accordingly.

### G. Android client (secondary surface)
- Source under `apps/android/`.
- It uses the remote API client and local reader/study features. Treat Android API authentication, upload retries, background job recovery, and reader import/export as a separate client integration. Do not use Android build success as proof the web-to-worker pipeline works.

## 3. End-to-end data flows

### Flow A — YouTube URL to reader notes
1. User pastes a supported YouTube URL.
2. Browser validates required fields and obtains explicit approval for public metadata/captions and, if needed, audio fallback. AI use is a separate approval.
3. Browser sends authenticated job-creation request to the Worker API.
4. Worker validates token, request, URL/consent, quotas and creates a D1 job in queued state.
5. Worker runner calls the claim endpoint and obtains a job lease/token with bounded lease expiry.
6. Python bridge validates the job ID and payload. It checks network consent.
7. Python pipeline canonicalizes the YouTube URL and attempts public caption sidecars first.
8. If captions exist, parse caption text into timestamped transcript segments. If none exist, do not silently fetch audio: only the separately consented audio fallback can proceed.
9. Existing engine stores transcript/source metadata and composes chapter groups and evidence-linked reader blocks.
10. Optional AI stage runs only with explicit approval and the configured provider. Provider errors must not erase a valid extractive reader result unless product requirements explicitly say otherwise.
11. Bridge validates reader JSON schema/limits, writes artifact to B2, and reports success plus artifact metadata to API.
12. API commits terminal job state and authorized artifact pointer.
13. Browser polls job state with bounded backoff, shows meaningful progress/error, then fetches artifact using an authorized short-lived URL.
14. Reader opens JSON, persists it locally, and renders chapters/evidence.

### Flow B — Uploaded media to reader notes
1. Browser validates file type/size and explicit ownership/authorization consent.
2. Browser requests an upload intent from API.
3. API creates a D1 job/upload record and signs a private B2 PUT URL scoped to one object key and short expiry.
4. Browser performs PUT to B2 with the exact signed headers. CORS preflight must succeed for both production and supported preview origin.
5. Browser calls finalize endpoint. API verifies object existence, expected key, size/type and upload state before queueing.
6. Hosted worker claims job and obtains a lease.
7. Bridge downloads from allowlisted B2 host with size bound (current bridge constant is 250 MiB).
8. FFmpeg/ffprobe extracts normalized audio; Faster-Whisper transcribes on CPU (tiny/int8 currently configured in hosted workflow).
9. Optional visual sampling only occurs with separate approval. Candidate frame/time alignments remain unreviewed.
10. Optional AI generation only occurs with separate approval.
11. Engine builds evidence-linked reader JSON; bridge validates output (current reader cap 20 MiB; chapter/block/evidence limits in bridge).
12. Artifact is uploaded to B2 and job marked succeeded; browser fetches it.

### Flow C — Offline reader
1. User imports reader JSON locally.
2. Frontend validates enough shape to render; malformed/oversized data must fail safely.
3. Reader displays chapter navigation, content blocks, evidence, study cards.
4. User may attach the original local media file to enable source-specific seek buttons.
5. Personal annotations/bookmarks/study progress are stored in IndexedDB for this browser/device.
6. Backup/restore exports/imports local state; it does not imply cloud sync.

## 4. API contract map to verify

The following route families are visible in the Worker/bridge architecture; verify exact HTTP methods, schemas, status codes and response fields in `infra/cloudflare/worker/src/index.ts` before changing clients:
- Health/readiness and authenticated identity.
- YouTube job creation and job status.
- Media upload intent creation, upload finalization, upload status.
- Worker claim/lease acquisition.
- Worker heartbeat/lease extension.
- Worker completion/success with artifact metadata.
- Worker failure/retry reporting.
- Authorized reader artifact metadata/download.
- Any Android-specific job list/recovery routes.

Contract rules:
- Every mutating endpoint must authenticate and validate body size/type.
- Every job-scoped client route must enforce tenant/user ownership.
- Worker routes must require a distinct worker bridge credential and validate lease token.
- State changes must be idempotent or protected by idempotency keys.
- Reject stale leases and duplicate completions.
- Do not return raw B2 credentials or long-lived object URLs.
- Use structured error envelopes with stable machine-readable codes and safe user-facing messages.

## 5. Reliability and security invariants

1. A job is never silently dropped between API queue and processor.
2. Every queued job has a visible age, attempt count, next retry, and last safe error.
3. Every running job has an owner/lease and heartbeat; expired leases become retryable.
4. Worker claims are atomic and cannot lease the same job to two processors.
5. Completion is idempotent; a retry cannot corrupt or overwrite a completed artifact.
6. Upload finalization checks actual B2 object existence and size.
7. Upload/download hosts are allowlisted; no arbitrary URL fetch/SSRF.
8. B2 bucket remains private; all URLs are scoped and short-lived.
9. Browser never receives Cloudflare, B2, AI provider, or worker bridge secrets.
10. Consent flags are persisted with the job and rechecked by the processor.
11. AI is optional and separately consented; provider outage should produce an explicit, recoverable state.
12. Reader JSON is schema-validated, bounded, and safe to render (use textContent, avoid unsafe HTML injection).
13. API/worker logs redact tokens, presigned URLs, user media URLs, and transcript content.
14. Retention/deletion semantics for uploaded media and generated artifacts must be documented and implemented.
15. CORS is not authentication; auth must remain enforced independently.

## 6. Current known blockers / evidence at handoff

### P0 — Hosted worker cannot start its container
- Run: https://github.com/oreosensei90-ops/OmniIntel-/actions/runs/44885127121
- Branch/event: `main` / push.
- Worker token guard passed.
- Processing branch checkout passed and resolved `c81623bb8e53ae8c6dd406b5141d60fc82d5d339`.
- GHCR login passed.
- Immutable image `ghcr.io/oreosensei90-ops/omniintel-cloud-worker:sha-c81623bb8e53ae8c6dd406b5141d60fc82d5d339` pulled successfully.
- Docker then exited code 125 with `docker: invalid reference format`.
- The workflow's shell script contains doubled backslashes (`\\`) at the end of each continued `docker run` line. Replace them with one shell continuation backslash (`\`) or use a YAML folded scalar/array-safe command, run shellcheck, and prove the container starts. This failure occurred before any job was claimed; it does not explain later pipeline behavior yet.

### P0 — Worker image publication race
- The next runner attempt after the shell-continuation fix checked out source commit `07aa2f7c7cb9b9d147d4362548d30b067edcdd8f`, derived its immutable image tag, and failed because that GHCR tag did not yet exist (`manifest ... not found`).
- This happened while a newer branch push was concurrently building/publishing the worker image. The hosted-worker workflow can start before the image-publisher workflow finishes.
- Fix the dependency deterministically: either make the worker workflow wait for and verify the exact matching image digest/tag, trigger it only after successful image publication, or build/publish and run the same immutable image in one coordinated workflow. Never fall back silently to `latest`.
- Acceptance: for a given source SHA, GHCR contains the exact `sha-<full-SHA>` image before the runner attempts `docker pull`; then the container starts and reports a successful API connection/claim. Add a regression check for missing tags and clear retry behavior.

### P1 — B2 browser CORS deployment still requires live confirmation
- The previous workflow failed because B2 returned `NoSuchCorsConfiguration` (case-sensitive spelling differed from the workflow matcher).
- Follow-up failed because verification assumed a CORS rule ID was returned.
- Both checks were patched on the processing branch. Run deployment, inspect actual B2 CORS read-back and browser preflight/PUT/finalize. Do not declare upload fixed until a real browser upload and finalize succeeds.

### P1 — Frontend Pages deployment / live bundle alignment
- Worker API deployment workflow contains Pages inspection/validation logic, but Pages deployment is a distinct release step.
- Previous inspection reported Cloudflare API permission error 10000 because the token lacked Pages Edit access. Verify token scope without exposing it.
- Verify live `index.html` and `app.js` are the same commit as the intended source and contain the current API endpoints, upload workflow, job polling and recovery. A stale Pages bundle can render the homepage but fail submission.
- Do not conflate stale frontend code, B2 CORS, API auth and worker runtime; isolate each layer with a direct test.

### P2 — Job lifecycle and artifact retrieval need a full real-media test
- Previous UI displayed a queued job with attempt 0. This was consistent with no active scheduled processor on the default branch.
- The default branch previously had only a manual placeholder; the main-branch workflow was replaced with a real scheduler/runner.
- The first actual runner invocation failed before claim due to the Docker command formatting above. Therefore no end-to-end processing has been proven yet.
- After fixing runner startup, verify claim, heartbeat, caption fetch, transcript, reader composition, B2 artifact upload, completion, API status and browser retrieval in one test.
- Test a caption-available short public video first, then a no-caption/consented audio fallback, then a small uploaded audio file. Do not begin with a long video.

### Branch hygiene issue
- `main` is currently not the same source tree as the application branch. The actual app is on `milestone/end-to-end-reliability-2026-11-21`; main has the hosted-worker workflow commit. This split is a release hazard.
- Before production hardening, establish a single canonical integration branch and merge reviewed app source + workflow files. Do not blindly force-push or overwrite either branch. Preserve both histories and make the chosen default branch build/test the full product.

## 7. Step-by-step independent audit plan

### Phase 0 — Freeze and inventory
1. Record repository URL, default branch, all active branches, latest commit SHAs and deployment URLs.
2. Confirm which branch is canonical for source, API deployment, Pages deployment and worker image publishing.
3. Do not rotate or request secrets unless a leak is proven. Audit secret names/consumers only.
4. Export current Cloudflare Worker config, D1 schema/migrations, B2 CORS/policy, Pages project config and GH Actions workflows (redact all secret values).
5. Create a branch from the exact source commit; no destructive edits to main.

### Phase 1 — Reproduce the known P0
1. Inspect `.github/workflows/hosted-worker.yml` from main.
2. Fix Docker command quoting/line continuation (one backslash per line, or a folded command with no fragile continuations).
3. Run `bash -n` on extracted shell; run ShellCheck if available.
4. Trigger workflow manually and confirm the Docker container starts and prints worker startup/health logs.
5. Confirm worker reaches the API and successfully claims a synthetic test job.
6. Only then submit a short public-caption YouTube test.

### Phase 2 — Contract and state-machine audit
1. Read all D1 migrations and derive exact job/upload schema.
2. Map each browser/Android API request to the Worker route and response contract.
3. Validate authentication separation: user token vs worker token vs B2 credentials.
4. Test each legal and illegal state transition, lease expiry, heartbeat, retry, duplicate completion and cancellation.
5. Confirm API polling returns progress and stable terminal errors; no infinite queued state.

### Phase 3 — Storage audit
1. Confirm B2 bucket private, region/endpoint correct, and key is least-privilege.
2. Inspect CORS by reading it back from B2; confirm exact origins, PUT, headers and ETag exposure.
3. Browser test preflight OPTIONS, signed PUT, finalize and worker GET.
4. Verify signed URL expiry and object-key isolation.
5. Test zero-byte, wrong content type, oversized, expired URL and finalize-before-upload rejection.
6. Test cleanup/retention for abandoned uploads and failed jobs.

### Phase 4 — Engine audit
1. Install Python 3.11 and project extras: `pip install -e '.[dev,youtube,asr,ai,service]'`.
2. Run `pytest -q` and `ruff check .`; record exact results.
3. Test URL normalization, unsupported hosts, playlist rejection and malformed IDs.
4. Test public captions parse to monotonic timestamped segments.
5. Test no-caption behavior without audio approval (must fail safely without downloading audio).
6. Test consented audio fallback with a short authorized video.
7. Test uploaded WAV/MP3/MP4 via FFmpeg/ffprobe and Faster-Whisper.
8. Test AI-off path and AI-on path separately; provider failure must be observable and recoverable.
9. Validate reader JSON schema, evidence references, chapter ordering, timestamp bounds, output-size limits and deterministic export.
10. Test container with read-only root and least privileges.

### Phase 5 — Frontend audit
1. Build/deploy Pages from the chosen canonical branch.
2. Inspect the actual served `index.html`, JS/CSS hashes and CSP.
3. Test API URL configuration, auth errors, consent gating, submit button state and duplicate-submit prevention.
4. Test upload progress, abort/retry, B2 CORS, finalize, queued/running/succeeded/failed UI.
5. Test page reload/reopen recovery and stale job polling.
6. Test reader JSON import, invalid JSON, large files, local media attach/seek, study cards, IndexedDB notes, backup/restore.
7. Run browser console/network checks on mobile Chrome and desktop Chromium.

### Phase 6 — Android integration audit
1. Build debug/release from the canonical commit.
2. Verify API token lifecycle, URL validation, upload retries and job recovery after process death.
3. Verify local reader import/export and offline operation.
4. Ensure Android and web use the same versioned API schema.
5. Do not gate web launch on Android-only enhancements unless they block shared API contracts.

### Phase 7 — Production acceptance
A release is accepted only when one short test job completes end-to-end:
- create job → D1 queued → worker claim → lease heartbeat → transcript → reader JSON → B2 artifact → D1 succeeded → browser downloads and opens artifact.
Then repeat with a small uploaded audio file.
Capture sanitized logs, commit SHA, workflow run URL, artifact checksum, API state transitions and browser network evidence. Only then mark the site operational.

## 8. Suggested command checklist

From repository root:
```bash
python -V
python -m pip install -e '.[dev,youtube,asr,ai,service]'
pytest -q
ruff check .
python -m compileall -q engine
```

Worker image:
```bash
docker build -f Dockerfile.cloud-worker -t omniintel-cloud-worker:local .
docker run --rm --entrypoint /bin/sh omniintel-cloud-worker:local -lc 'omniintel-cloud-worker --help'
```

Shell workflow:
```bash
bash -n /tmp/hosted-worker-step.sh
shellcheck /tmp/hosted-worker-step.sh
```

Never place actual tokens in command history, issue comments, screenshots, or this handoff. Use environment variables or CI secret stores.

## 9. What the reviewer should return

Please return:
1. Architecture diagram and trust boundaries.
2. P0/P1/P2 findings with exact file, line, reproduction and root cause.
3. A minimal patch set, each patch tied to a failing test.
4. A reproducible local test script and CI workflow.
5. Proof of one completed YouTube job and one completed upload job.
6. Deployment checklist and rollback procedure.
7. Explicit list of assumptions that remain unverified.

**Review principle:** do not redesign everything at once. Reproduce the current failure, fix the smallest root cause, add a regression test, and verify the complete path before moving to the next layer.
