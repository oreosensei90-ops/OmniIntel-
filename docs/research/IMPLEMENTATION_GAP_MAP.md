# OmniIntel Implementation Gap Map

Updated: 2026-11-20

## Architecture to preserve

Keep Source, Evidence, Knowledge and Learning as separate canonical layers. Original assets remain immutable. Textbooks are versioned compositions over accepted evidence, not the evidence database. Deterministic local operations remain available without an AI provider. External AI, media acquisition and publishing require explicit approval.

## Implemented foundations — do not rebuild

Based on the current `ROADMAP.md`, `ARCHITECTURE.md` and `DEEP_RESEARCH_AUDIT_2026-11-19.md`:
- Read-only input planning and explicit execution approval.
- Plan hash, local allowlisted stages, input revalidation and idempotent checkpoints.
- Persistent leased job queue with bounded retries (initial slice).
- Collections/courses with typed membership and source identity preservation.
- Cross-correlation alignment proposals marked NEEDS_REVIEW.
- Course-level textbook/version/chapter/block records with evidence boundary checks.
- Local ffprobe/FFmpeg probing/audio extraction, timestamped frame assets and reviewable frame events.
- Local SRT/VTT and PCM transcription paths with checkpoints.
- PDF text, optional local OCR, positioned layout elements and evidence-gated composition.
- Provider-neutral knowledge persistence and initial claim/evidence audit.

## P0 — Remote pipeline correctness and security

**Files to inspect:** `.github/workflows/python.yml`, `engine/omniintel/api.py`, `worker.py`, `remote_generation.py`, `study_generation.py`, `cloud_worker_bridge.py`, `jobs.py`, `infra/cloudflare/worker/src/index.ts`, `pyproject.toml`.

Known issues from the active-branch review:
- Hosted worker previously failed because remote generation expected `OMNIINTEL_OPENAI_API_KEY`; readiness remains OpenAI-specific.
- Local FreeLLM changes are not reflected in remote branch; do not assume end-to-end wiring.
- Python CI push trigger omits `fix/sync-worker-token`.
- YouTube jobs hit anti-bot responses; do not bypass. Prove pipeline with user-uploaded media or supplied captions/transcript.
- Cloud-worker input download requires redirect/host/IP revalidation and strict host allowlist.
- Job retry/max-attempts and hourly scheduling need inspection.
- No successful full upload/acquire → ASR → reader → B2 proof yet.

**Acceptance:** explicit provider readiness without secret leakage; deterministic no-key path works; remote AI opt-in and consent-bound; upload-based E2E fixture completes; SSRF/redirect tests pass; lease/heartbeat/cancel/retry/idempotency tests pass; active branch CI passes.

## P1 — Provider-neutral AI boundary

**Files:** `remote_generation.py`, `worker.py`, `api.py`, `study_generation.py`, `pyproject.toml`, provider contract tests.

Add stable provider/model identity, explicit route selection and consent, local Ollama and user-key adapters, bounded timeouts/concurrency/output/retries, Retry-After/cooldown, stream-aware fallback, cancellation, redacted errors and strict evidence-ID validation.

**Acceptance:** fake-provider contract tests, retry/cancel/stream tests, secret-redaction tests and deterministic no-provider test.

## P2 — Queue and stage reliability

**Files:** `jobs.py`, `cloud_worker_bridge.py`, Cloudflare Worker `index.ts`, `execution.py`, migrations/tests.

Add stage DAG/checkpoints, source identity locks, cancellation propagation, stale-source invalidation, fair bounded scheduling, temp-artifact leases, exponential backoff/jitter and exactly-once completion under lease races.

**Acceptance:** claim/heartbeat/expiry/cancel race tests, restart recovery, no duplicate outputs, fairness and cleanup lease tests.

## P3 — Evidence and multimodal quality

**Files:** `alignment.py`, `scene_detector.py`, `visual_*.py`, `evidence*.py`, `knowledge_store.py`, `QUALITY_BENCHMARKS.md`.

Add typed frame/slide locators, transcript-slide grounding with temporal and semantic signals, drift/warp alignment, OCR-failed vs no-text states, positive/negative retrieval tests and claim-level evidence precision/recall/coverage.

**Acceptance:** annotated golden corpus, reproducible metrics, no false acceptance of uncertain alignment, source-boundary tests and review workflow.

## P4 — Reader and learning loop

**Files:** `course_textbook.py`, `textbook_*.py`, `TEXTBOOK_COMPOSITION.md`, `SYNCHRONIZED_READER.md`, Web/Android client modules.

Build synchronized video/transcript/visual/textbook reader, timestamped annotations/bookmarks tied to canonical IDs, persisted recall/transfer/error-correction responses, FSRS after durable study records, course search over transcript/OCR.

**Acceptance:** source-to-textbook-to-study navigation, offline persistence, regeneration without annotation loss, accessible controls and sync-conflict tests.

## P5 — Optional multimodal generation and agents

Keep isolated from core processing. Add only after core reliability: image/diagram/voice/video generation adapters; synthetic assets separately labelled; agent workspaces/routines with capability-specific approvals and sandboxing.

**Acceptance:** asset provenance, rights/terms review, cost/consent visibility, stop control and red-team tests.

## Priority order

1. P0 remote pipeline truth/security and upload-based E2E proof.
2. P1 provider-neutral gateway.
3. P2 durable job-stage reliability.
4. P3 evidence/visual quality.
5. P4 reader and persistent learning.
6. P5 optional generation/agent automation.

Do not let attractive provider demos displace P0 correctness, privacy and evidence integrity.
