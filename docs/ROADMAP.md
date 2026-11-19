# OmniIntel Roadmap

This roadmap is a plan, not a claim that every item exists.

## Foundation
- [x] Repository engineering rules and initial Python package metadata.
- [x] Stable ID and transcript domain foundation.
- [x] SQLite migration ledger with checksum verification.
- [x] Initial source/transcript/evidence persistence and knowledge schema migrations.\n- [ ] Asset repository, source adapters and richer evidence types.
- [x] Persistent leased job queue with idempotency and bounded retries (initial slice; stage DAG/checkpoints remain pending).
- [x] Initial cross-platform JSON Schema contracts and validation tests.

## Source and evidence intelligence
- [ ] Authorized source adapters and metadata inspection.
- [ ] Caption/transcript ingestion and timestamp alignment.
- [ ] Local audio transcription adapter.
- [ ] Video scene/slide extraction and OCR.
- [x] Deterministic claim/evidence audit and uncertainty counters (initial slice).\n- [ ] Source-level topic coverage, semantic entailment and uncertainty analysis.

## Knowledge and publishing
- [x] Initial provider-neutral knowledge-unit, claim and relationship persistence.\n- [ ] Automated topic/concept discovery and claim extraction.
- [x] Reviewed claim/evidence links with conservative publication gating.\n- [ ] Semantic relevance verifier and contradiction-scope analysis.
- [ ] Knowledge graph and contradiction handling.
- [ ] Structured textbook composition.
- [ ] PDF, DOCX, HTML and Markdown exporters.

## Applications
- [ ] Web PWA and offline library.
- [ ] Native Android app and Room persistence.
- [ ] Reader, annotations, bookmarks and search.
- [ ] Flashcards, practice and study planning.

## Intelligence and operations
- [ ] Local/self-hosted AI adapters.
- [ ] Optional approved provider registry and privacy controls.
- [ ] Model benchmark and routing system.
- [ ] Backup/restore and optional synchronization.
- [ ] CI, security checks, SBOM and release certification.
