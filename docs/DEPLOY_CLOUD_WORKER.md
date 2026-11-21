# Deploy the OmniIntel Cloud Processing Worker

The Cloudflare Worker is the public API/control plane. This container is the separate
long-running processor that claims jobs, runs the existing Python engine, and returns
reader documents to the Cloudflare API.

## Deployment bundle

- Docker image: `Dockerfile.cloud-worker`.
- Compose definition: `deploy/cloud-worker.compose.yml`.
- Safe configuration template: `deploy/cloud-worker.env.example`.
- Runtime: one Docker background worker; it exposes no inbound HTTP port and polls
  the Cloudflare API outbound over HTTPS.
- Persistent volume: `omniintel-worker-data`, used for the SQLite queue, working files,
  assets and downloaded ASR model cache.

The image installs FFmpeg, yt-dlp and Faster-Whisper, runs as an unprivileged user, and
uses a read-only root filesystem with a bounded temporary filesystem. The Docker build
copies only the Python package and its project metadata; it does not copy repository
secrets, local databases, test fixtures, Android builds or local model files.

## Configure and start

From the repository root on a Docker host with Docker Compose v2:

```sh
cp deploy/cloud-worker.env.example deploy/cloud-worker.env
# Edit deploy/cloud-worker.env and replace OMNIINTEL_WORKER_TOKEN.
docker compose -f deploy/cloud-worker.compose.yml up -d --build
docker compose -f deploy/cloud-worker.compose.yml logs -f cloud-worker
```

Set `OMNIINTEL_WORKER_API` to the deployed API origin and set
`OMNIINTEL_WORKER_TOKEN` to the exact same secret configured on the Cloudflare Worker.
Never commit `deploy/cloud-worker.env`, paste the token into chat, or print it in logs.

## Processing settings

The example selects a CPU `small` Faster-Whisper model with int8 compute and permits its
first-run download. Model downloads can be large and CPU transcription can be slow.
Use a host with sufficient RAM, CPU time and persistent disk (4 GB RAM and 10 GB disk
are sensible starting points for the small model; more resources improve throughput).
You can change `OMNIINTEL_ASR_MODEL_ID`, `OMNIINTEL_ASR_DEVICE`,
`OMNIINTEL_ASR_COMPUTE_TYPE`, and `OMNIINTEL_ASR_THREADS` in the environment file.
For an offline/preloaded model, set `OMNIINTEL_ASR_MODEL_PATH` to a mounted local model
directory and disable model downloads.

## Optional AI generation

AI study-guide generation is used only for jobs carrying explicit AI consent. The
example selects the OpenAI provider; set `OMNIINTEL_OPENAI_API_KEY` on the processing
host only if that provider is selected and AI generation is desired. The key is
`OMNIINTEL_OPENAI_API_KEY`, not a generic client-side key. The default model is
`gpt-4.1-mini`; it can be changed with `OMNIINTEL_OPENAI_MODEL` or
`OMNIINTEL_AI_MODEL`. Never embed provider credentials in the Web or Android apps.

## Storage and lifecycle

The Cloudflare API stores job state in D1 and uploaded input in the private Backblaze B2
bucket. The processor downloads inputs through short-lived signed URLs, processes them
locally, sends the bounded reader result to the API, and removes temporary upload files.
The persistent Docker volume is for the processor's local queue/model cache; it is not
a replacement for D1 or B2.

## Production acceptance checks

1. Confirm the worker starts and authenticates to the Cloudflare API.
2. Submit a small, user-authorized public-caption YouTube job.
3. Confirm it moves from QUEUED to RUNNING to COMPLETED and imports into Web/Android.
4. Submit a small authorized media upload and confirm B2 download plus FFmpeg/ASR.
5. Verify AI generation only when explicitly selected and configured.
6. Restart the container and verify the persistent volume preserves its model cache and
   local recovery state.

## Zero-cost GitHub Actions processing

For a public repository, the `.github/workflows/hosted-worker.yml` workflow can run the
same bridge on GitHub-hosted Linux runners instead of a permanent VM. This is a
best-effort, burst-style option, not an always-on server:

- It checks the queue every 15 minutes and claims at most one job per run.
- Each run has a 45-minute processing-step limit and a 50-minute job limit.
- It uses the smaller `tiny` Faster-Whisper model to reduce cold-start time and caches
  the model between eligible runs.
- Runner files are ephemeral. D1 remains the job-state source of truth and B2 remains
  the durable media/artifact store; never rely on the runner filesystem surviving.
- A job interrupted by runner shutdown is recovered through the API's lease expiry and
  retry policy. The concurrency group prevents two hosted runs from claiming jobs at
  the same time.

The hosted workflow needs the existing `OMNIINTEL_WORKER_TOKEN` repository secret.
It can be run manually from the Actions tab on the milestone branch. GitHub scheduled
events run only from the repository's default branch, so automatic 15-minute polling
starts after this workflow reaches that branch. Do not merge the milestone PR merely
to enable scheduling without reviewing the full PR first.

AI generation is separately consent-gated. If a job requests AI generation, configure
a provider key such as `GEMINI_API_KEY` as a GitHub Actions repository secret. A free
Google AI Studio key can be used; no paid hosting is needed. Without a provider key,
AI-approved jobs fail closed rather than silently switching to an unapproved provider.
Do not put provider keys in source files, app bundles, or job payloads.

This hosted option is intended for development and low-volume testing. GitHub queue
delays, scheduled-run delays, free-tier policies, model download time and job limits
mean it does not provide continuous processing or production uptime guarantees.
