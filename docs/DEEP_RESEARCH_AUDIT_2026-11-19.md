# Deep research audit — 2026-11-19

## Scope and evidence level

This audit supplements RESEARCH_REGISTER.md and REFERENCE_IMPLEMENTATION_PLAN.md. It separates repository-level discovery from source-level inspection. The supplied list was deduplicated (the Allen0497 URL appeared twice). Distinct repositories received metadata, README and repository-tree review; selected high-value projects received deeper source inspection. This was not a full clone/build/runtime/security audit of every project.

## Selected source-level findings

| Project | Reviewed implementation pattern | Adopted lesson | Boundary / not adopted |
|---|---|---|---|
| drpwchen/lecture-to-notes | Staged route, OCR quality, semantic dedup, temporal re-anchoring, multi-recording offset alignment, synchronized reader | Keep pipeline stages explicit; measure cross-recording offsets; retain source anchors and review state | No code copied; OCR/VLM and timing still require independent evaluation |
| thewh1teagle/vibe | Transcript segments and word timestamps; private temporary staging | Explicit timestamp-unit adapters; secure per-process temporary directories | OmniIntel canonical timestamps remain integer milliseconds; no implicit centisecond conversion |
| HHousen/lecture2notes | Slide extraction, classification, perspective crop, clustering, OCR, ASR, multimodal merge and exports | Preserve a staged visual/audio processing model and deduplicate without destroying source evidence | AGPL-3.0; no code reuse without a deliberate legal compatibility decision |
| amroeser/lecture-notes-app | Course/series grouping, chunked compilation, content+parameter cache | Durable ordered course membership and fingerprint-aware incremental rebuilds | Course membership alone does not prove common timelines or semantic relations |
| Pranav322/youtube-notes | Long-context map/reduce and chapter synthesis | Bounded chunking, per-stage checkpoints, explicit merge/coverage pass | Paid/cloud provider dependency is not our default; map/reduce output remains a draft |
| davertor/take-notes | Genre router and genre-specific output contracts | Source genre and learning objective should influence structure | Generated HTML is not the canonical knowledge store |
| risonsimon/interactive-deep-notes | Interactive learning page and learner interaction | Persist learner responses in canonical study records | Browser-only local state is insufficient |
| Charlo-O/Video2Note / xKarinSan/video-notes | Timestamp-linked note/video interaction | Reader should navigate from evidence to source time | UI interaction is not evidence validation |
| Allen0497/video-to-notes | Captions-first with ASR fallback and frame dedup concepts | Prefer supplied/authorized captions; keep ASR replaceable | Remote acquisition and provider fallback need consent and rights checks |
| satya122id0889/AI-Video-to-Notes-Intelligence-Platform | OCR/embedding-based slide selection | Text/layout signals can reduce expensive vision work | OCR density or similarity alone cannot define importance |

## License and reuse decisions

- MIT / Apache-2.0: potentially reusable only after exact-file notice review, dependency/model license review, security review and attribution.
- GPL-3.0 / AGPL-3.0: no source reuse in this project without an explicit compatibility and distribution decision.
- Missing or ambiguous license: no code reuse until verified.
- Repository license never automatically licenses model weights, datasets, API access, user media or video-platform content.
- This batch copied no third-party source code.

## Implemented consequences in OmniIntel

1. input_plan.py: read-only local modality planner with explicit questions, resource classes and no processing side effects.
2. execution.py: explicit approval gate, immutable plan snapshot hash, local-only allowlisted stage names, no shell execution, per-stage input hashes and resumable checkpoints. The application must inject trusted local handlers; this module does not download, transcribe or OCR by itself.
3. alignment.py: normalized cross-correlation over precomputed feature envelopes. Offset convention is time_in_A = time_in_B + offset_ms. Every proposal is NEEDS_REVIEW; accepted status is a human review decision, not an automatic consequence of a high score.
4. course_textbook.py: separate course-level textbook records, chapter source attribution and evidence links constrained to collection membership and chapter source.
5. Migrations and tests cover approval, stale-input detection, idempotent checkpoints, source clock membership, alignment review, cross-source textbook evidence boundaries and publication blocking.

## Remaining research questions

- Independently benchmark offset estimation on recordings with drift, pauses, edits, different sample rates and non-overlapping excerpts. A single constant offset is insufficient when clocks drift.
- Validate ASR and OCR against a manually transcribed/annotated corpus, not project-reported scores.
- Review model and dataset terms independently from source-code licenses.
- Inspect more of the long tail of repositories only when a concrete unresolved design question justifies the cost.
- Perform a separate security review of actual media adapters before enabling them in a user-facing application.
