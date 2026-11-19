# OmniIntel Roadmap

This roadmap is a plan, not a claim that every item exists.

## Foundation
- [x] Repository engineering rules and initial Python package metadata.
- [x] Stable ID and transcript domain foundation.
- [x] SQLite migration ledger with checksum verification.
- [x] Initial source/transcript/evidence persistence and knowledge schema migrations.
- [x] Initial content-addressed asset blob store, source-asset registry and source-safe IMAGE/DIAGRAM block links (local ingestion only; visual rendering implemented).
- [x] Initial local-file source registration with content-addressed byte preservation and explicit unverified-rights metadata (content extraction pending).
- [x] Read-only plan-first local input classification with resource/network declarations and explicit language/caption/clock questions.\n- [ ] Approved plan execution coordinator with TOCTOU revalidation and durable stage-job creation.\n- [ ] Authorized source adapters and richer evidence types.
- [x] Persistent leased job queue with idempotency and bounded retries (initial slice; stage DAG/checkpoints remain pending).
- [x] Initial cross-platform JSON Schema contracts and validation tests.

## Source and evidence intelligence
- [x] Initial local-file signature classification and source metadata registration (deep content extraction pending).
- [x] Bounded local ffprobe inspection for registered audio/video assets with immutable stream metadata and idempotent tool-version fingerprints.
- [x] Bounded local FFmpeg audio extraction to content-addressed mono 16 kHz PCM WAV derivatives, including source stream start-offset provenance.
- [x] Bounded timestamped local video-frame extraction with content-addressed frame assets.
- [x] Source-bound visual frame events and reviewable transcript-time alignment candidates.
- [x] Heuristic scene-change candidates using bounded grayscale frame-difference analysis (human review required).
- [x] Optional local Tesseract OCR on accepted video frames with normalized word boxes and confidence.
- [x] Opt-in loopback-only Ollama vision descriptions and semantic frame/transcript scoring adapters (all results review-gated).
- [x] Cross-modal claim verification proposals; accepted visual contradictions block textbook publication.
- [x] Initial bounded local PDF text extraction with stable page-number records, content hashes and SQLite FTS5 page search.
- [x] Optional local OCR adapter for image-only pages with pixel/time limits, word boxes, source-owned render assets and mandatory review before evidence acceptance.
- [x] Initial deterministic PDF layout extraction for positioned paragraphs/headings, equation candidates, table candidates and embedded figure assets (classification remains heuristic).
- [x] Unified source-bound evidence locator IDs for transcript intervals and PDF pages.
- [x] Claim and textbook block evidence links support unified references, with review and publication gates spanning both locator types.
- [ ] Authorized source adapters and platform-specific media acquisition.
- [x] Initial local SRT/WebVTT caption ingestion with timestamp preservation (additional formats and semantic alignment pending).
- [x] Initial local PCM WAV transcription adapter with sequential, content-addressed chunk checkpoints and source-linked timestamp evidence (native Android ASR and transcript versioning pending).
- [ ] Slide classification, visual topic discovery and semantic scene segmentation.
- [x] Document structure elements carry page/element citations, review state and same-source guards.
- [x] Deterministic claim/evidence audit and uncertainty counters (initial slice).
- [ ] Source-level topic coverage, semantic entailment and uncertainty analysis.

## Knowledge and publishing
- [x] Initial provider-neutral knowledge-unit, claim and relationship persistence.
- [x] Source-linked draft knowledge candidates with explicit review/validation and element lineage (semantic claim extraction remains pending).
- [ ] Automated topic/concept discovery and claim extraction.
- [x] Reviewed claim/evidence links with conservative publication gating.
- [ ] Semantic relevance verifier and contradiction-scope analysis.
- [ ] Knowledge graph and contradiction handling.
- [x] Source-scoped video topic hierarchy and reviewed timestamp/evidence alignment (initial slice).
- [x] Page-native document topic hierarchy with reviewed unified evidence references and same-source guards.
- [x] Versioned textbook/chapter/block persistence with per-block provenance and evidence links (initial deterministic storage slice).
- [x] Deterministic video topic-to-chapter outline composition with accepted evidence-gated claim placement (initial slice).
- [x] Deterministic document topic-to-chapter composition using shared accepted page/element citations, including reviewed paragraphs, equations, tables and figure assets with retained provenance.
- [x] Initial deterministic textbook publication readiness gate (structural/review rules only).
- [ ] Semantic block validation, source coverage and pedagogical quality scoring.
- [x] Audited PDF exporter with source-owned image embedding and page-aware citations (native math typesetting pending).
- [x] Editable DOCX exporter with source-owned image embedding and page-aware citations (native equation objects pending).
- [x] Self-contained HTML exporter with bounded embedded image data and page-aware citations.
- [x] Portable Markdown exporter with adjacent content-addressed image assets and page-aware citations.
- [x] Render linked visual assets in PDF/DOCX/HTML/Markdown with source checks, bounded sizes and accessibility descriptions.
- [ ] Native math rendering across formats.

## Applications
- [ ] Web PWA and offline library.
- [ ] Native Android app and Room persistence.
- [ ] Reader, annotations, bookmarks and search.
- [ ] Flashcards, practice and study planning.

## Intelligence and operations
- [x] Initial loopback-only local Ollama vision adapter (general provider registry and task routing pending).
- [ ] Optional approved provider registry and privacy controls.
- [ ] Model benchmark and routing system.
- [ ] Backup/restore and optional synchronization.
- [ ] CI, security checks, SBOM and release certification.
