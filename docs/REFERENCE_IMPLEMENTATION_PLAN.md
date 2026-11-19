# Reference-Informed Implementation Plan

Updated: 2026-11-19

This document converts the 2026-11-19 video-to-notes research batch into implementation decisions. It is deliberately not a dependency list. Research code is not imported into OmniIntel merely because a repository is MIT-licensed or technically interesting.

## Architecture decisions

| Area | Accepted design | Research signal | OmniIntel implementation boundary |
|---|---|---|---|
| Multi-input intake | Plan first; classify selected local files, identify modality combinations, show required user decisions, estimate work and list side effects before execution. | drpwchen/lecture-to-notes route_inputs.py; davertor/take-notes source router. | New typed InputPlan and source-bundle contract. Plan generation must be read-only; execution uses explicit approved steps, argv arrays, network/GPU declarations and durable jobs. |
| Multi-source course | A course is a durable collection of independently sourced lectures, decks, audio, notes and references. Each source retains its own identity; shared timeline relationships are explicit, reviewed records. | amroeser/lecture-notes-app course batches; drpwchen multi-recording/media-offset alignment; take-notes multi-source synthesis. | Add course entities and source membership without merging source identity or evidence IDs. |
| Acquisition | Prefer user-selected files and supplied captions. For remote sources, use only authorized/terms-compliant adapters and never imply public availability grants download/reproduction rights. | drpwchen/ytscribe subtitle-first flow; Allen0497 captions-first flow. | Provider adapters return source metadata/caption provenance. No hidden downloads or remote fallback. |
| ASR | Keep model/engine adapters replaceable; distinguish creator captions, manual captions, auto captions and ASR; preserve language and confidence; VAD is an explicit recall/speed trade-off. | Vibe, StudyMitra, ytscribe and lecture-to-notes. | Adapter contract and chunk cache in transcription.py; VAD-off default for lecture content; evaluate word/segment timing and WER on a reference corpus. |
| Slide/frame intelligence | Cheap first-pass sampling and image-quality/entropy signals; combine perceptual, text-subset and layout similarity; preserve progressive reveals when meaningful; run expensive VLM only on canonical candidates. | lecture-to-notes stages A-D; Allen0497 PSNR dedup; satya122id0889 OCR embeddings; HHousen research pipeline. | Keep every raw frame and metrics immutable; dedup creates candidate groups, not destructive deletion. Thresholds are versioned/configurable and human-reviewable. |
| Cross-modal alignment | Transcript-to-slide alignment must use temporal overlap plus semantic signals; multi-recording clock offsets require measured cross-correlation or explicit human confirmation. | lecture-to-notes ground_slides.py, xcorr_media_offsets.py, ts_anchor.py. | Typed alignment records with score, rationale, algorithm/version, input hashes, uncertainty and review state. Never promote nearest timestamp to accepted semantic evidence. |
| Provenance/recovery | Every derived artifact records exact input hashes, parameters, tool/model versions, provider/network, and a reproducible job/stage identity. Detect stale artifacts rather than silently reuse them. | lecture-to-notes provenance.py; CoursePilot content+parameter cache; LearnNote revision-bound citations. | Extend existing jobs, job_stages, job_checkpoints, model_runs and content-addressed assets; no parallel ad-hoc JSON manifest as source of truth. |
| Synthesis | Generate from structured, accepted evidence. Long context uses bounded map/reduce with durable per-chunk checkpoints and a merge/coverage pass. | Pranav322 map/reduce; amroeser chapter merge/guardrails; take-notes genre router. | Keep model outputs as drafts; coverage and claim-evidence gates are independent of stylistic generation. |
| Learning artifacts | Choose structure from source genre and learning objective. Each important concept should be explained, tested and applied; persist user responses outside generated HTML. | take-notes and interactive-deep-notes pedagogy. | Canonical textbook blocks plus separate study_items, study_sessions, responses and FSRS scheduling. HTML is an export/view, not the database of record. |
| Reader | Offer synchronized video/transcript/notes navigation, seekable evidence timestamps, progress and source references. | lecture-to-notes synced HTML viewer; Charlo-O editor; VNotes timestamp links. | Build as a web reader over canonical records. Preserve offline export and accessible controls. |
| Evaluation | Evaluate ASR, alignment, semantic support, coverage, export and study outcomes separately. Never collapse unlike metrics into one invented score. | StudyMitra WER/ROUGE/QA metrics; lecture-to-notes OCR bench and audit; CoursePilot reported benchmarks. | Golden corpus with human references; report WER/CER, timing error, OCR quality, evidence precision/recall, coverage, export validity and resource costs separately. |

## Implementation sequence

### P0 — Complete current source intelligence foundation
- Finish integration tests for cross-modal visual review and publication blocking.
- Verify every exporter includes all accepted unified evidence references, including document page/element locators.
- Ensure frame extraction, OCR, VLM and alignment artifacts are tied to exact input hashes and tool/model configuration.
- Ensure source-boundary checks reject cross-course/cross-source evidence leakage.
- Keep all VLM/ASR output unaccepted until review or a separately validated policy explicitly allows acceptance.

### P1 — Plan-first multi-source intake
- Introduce a read-only directory/file planner with modality classification for video, audio, PDF, images, captions and supported text documents.
- Return a machine-readable plan: steps, dependencies, argv, network policy, resource class, estimated input/output bounds, reads/writes, user questions and unresolved placeholders.
- Require explicit language confirmation when speech language cannot be reliably determined; preserve code-switching and uncertain language labels.
- Ask for human confirmation when multiple independent capture clocks or slide-photo sources need alignment.
- Execution must create durable jobs only after plan approval; retries must be idempotent and cancellation must not corrupt completed stages.

### P2 — Course and multi-source knowledge
- Add course/collection membership and ordered lecture/source records.
- Add reviewed relationships between independent source clocks and a course timeline.
- Support a course textbook assembled from multiple lecture versions while every claim retains source-specific evidence.
- Implement incremental append/rebuild with source fingerprint invalidation and preserved annotations.

### P3 — Reader and learning loop
- Build a synchronized reader with transcript, visual timeline, chapter blocks and seek-to-source controls.
- Add persisted recall, application prompts, learner notes and export of learner-created responses.
- Add spaced repetition only after durable study records and scheduling tests exist.

### P4 — Benchmark and optimize
- Compare subtitle retrieval, Whisper variants, VAD modes and local inference on the same manually reviewed corpus.
- Benchmark CPU/GPU/RAM, throughput, battery/thermal behavior and failure recovery on representative Android devices before selecting mobile defaults.
- Benchmark slide sampling and dedup thresholds against progressive reveals, animation, low-contrast slides and camera motion.
- Keep local, self-hosted and external providers separately selectable; external transfer requires explicit user consent.

## Explicitly rejected patterns

- Unbounded asyncio.gather over every transcript chunk; use bounded concurrency and persistent checkpoints.
- Automatic hosted-model fallback when a local model fails; that silently changes privacy and cost.
- Treating OCR/VLM/LLM text as ground truth or instructor-authored material.
- Using frame count, OCR text length or similarity alone as proof that a frame is important.
- Guessing source language, clip offsets, slide alignment or missing timestamps without uncertainty labels.
- Storing reader answers only in browser localStorage; user learning history belongs in the canonical study store.
- Exposing API keys in browser-visible variables or shipping provider secrets in the Android APK.
- Copying code from GPL/AGPL or unlicensed repositories without a separate legal decision.
- Treating a README claim, star count, project-reported benchmark or passing demo as independent quality/security evidence.

## License and reuse gate

- MIT / Apache-2.0: potentially reusable after checking the exact file, copyright notices, dependency/model licenses, security and attribution.
- GPL-3.0 / AGPL-3.0: no code reuse without an explicit compatibility and distribution decision.
- Missing / NOASSERTION / README-only claims: treat as not approved for code reuse until the actual license is verified.
- Model weights, datasets, APIs and media sources have their own terms; repository license does not automatically cover them.

## Research status

The research register records all distinct repositories and topic indexes supplied in this batch, duplicate consolidation, metadata/license snapshots, README/tree review and selected source inspections. Selected high-value repositories received deeper source review. This does not claim that every repository was cloned, installed, executed, penetration-tested or independently benchmarked. No third-party source code was copied into OmniIntel in this research pass.
