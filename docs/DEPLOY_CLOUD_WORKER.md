# Deploy the OmniIntel Cloud Processing Worker

The Cloudflare Worker is the public API/control plane. This container is the separate
long-running processor that claims jobs, runs the existing Python engine, and returns
reader documents to the Cloudflare API.

## Container configuration

- Runtime: Docker background worker (not a web service).
- Build context: repository root.
- Dockerfile: `Dockerfile.cloud-worker`.
- Start command: use the Dockerfile ENTRYPOINT; do not override it.
- Exposed HTTP port: none. The processor polls the Cloudflare API outbound over HTTPS.

## Required environment

| Variable | Value |
| --- | --- |
| `OMNIINTEL_WORKER_API` | `https://omniintel-api.scrbaba502.workers.dev` |
| `OMNIINTEL_WORKER_TOKEN` | The same secret configured on the Cloudflare Worker as `OMNIINTEL_WORKER_TOKEN`; set it as a secret in the processor host. |

Never commit or paste the token into source control, logs, or chat.

## Recommended processing settings

- `OMNIINTEL_POLL_SECONDS=5`
- `OMNIINTEL_ASR_MODEL_ID=small` (choose a model appropriate to the host's RAM/CPU)
- `OMNIINTEL_ASR_ALLOW_MODEL_DOWNLOAD=1` only when the host is allowed to download the selected model.
- `OMNIINTEL_ASR_DEVICE=cpu`
- `OMNIINTEL_ASR_COMPUTE_TYPE=int8`
- `OMNIINTEL_ASR_THREADS=4` (adjust to the host's CPU allocation)
- `HF_HOME=/var/lib/omniintel/huggingface` when a persistent disk is mounted at `/var/lib/omniintel`.

The image includes FFmpeg, yt-dlp and Faster-Whisper support. Model downloads can be large
and CPU transcription can be slow; select a host with enough memory, CPU time and disk.
Without ASR model configuration, caption-backed YouTube jobs may work, but jobs requiring
local transcription will fail clearly rather than silently using a cloud ASR provider.

## Optional AI generation

AI study-guide generation is separately consented. If users request it, configure exactly
one supported provider and its credentials in the processor host, for example
`OMNIINTEL_AI_PROVIDER=openai` plus `OMNIINTEL_OPENAI_API_KEY`. Do not enable or send
transcripts to an external provider unless the user has approved AI processing.

## Storage and lifecycle

The Cloudflare API stores job state in D1 and uploaded input in the private Backblaze B2
bucket. The processor downloads inputs through short-lived signed URLs, processes them
locally, sends the bounded reader result to the API, and removes temporary upload files.
A persistent disk is recommended for the local model cache; it is not a replacement for
the D1 job database or B2 source storage.

## Validation still required after host deployment

1. Confirm the processor starts and authenticates to the Cloudflare API.
2. Submit one small, user-authorized public-caption YouTube job.
3. Confirm it moves from QUEUED to RUNNING to COMPLETED and imports into Web/Android.
4. Submit one small authorized media upload and confirm the B2 download + FFmpeg/ASR path.
5. Verify AI generation only when explicitly selected and configured.
