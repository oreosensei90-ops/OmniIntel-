# OmniIntel Architecture — Initial Foundation

## Target architecture

OmniIntel is a modular monorepo with native Android and web clients, shared versioned contracts, and a replaceable processing engine. Each platform owns its local database and files; contracts and import/export formats are shared rather than sharing a live SQLite database.

```text
Android (Compose / Room)                 Web (vanilla JS / IndexedDB / Service Worker)
                    \                         /
                     Shared domain + event contracts
                                  |
              Source -> Evidence -> Knowledge -> Learning artifacts
                                  |
          Processing engine / persistent jobs / asset manager
                                  |
        SQLite + FTS / local files / optional approved AI adapters
```

## Three canonical layers

- **Source:** source identity, immutable original assets, transcript segments, visual events and evidence.
- **Knowledge:** topics, concepts, claims, relationships, evidence mappings, provenance and uncertainty.
- **Learning:** textbooks, chapter blocks, annotations, flashcards, assessments and study history.

Do not collapse these layers into one summary field.

## Initial Python slice

The implemented engine includes local-file registration, FFmpeg audio extraction, optional Faster-Whisper transcription, public-caption YouTube intake, bounded PDF text/OCR/layout extraction, source-linked knowledge candidates, review-gated textbook composition, optional local vision adapters and audited PDF/DOCX/HTML/Markdown publishing. Uploaded-media processing and visual timeline sampling are connected through the leased worker path. Model-generated study content remains a review-required draft; semantic correctness and completeness are not inferred from structurally valid citations.

## Planned processing flow

1. Inspect and validate an authorized source.
2. Acquire permitted captions/transcript or process user-provided media.
3. Preserve original evidence and timestamps.
4. Extract visual evidence where applicable.
5. Reconstruct topics, concepts and claims.
6. Validate references, coverage, provenance and uncertainty.
7. Compose versioned textbook blocks.
8. Render and validate exports.
9. Publish into the offline library and derive study materials.

## Persistence rules

- SQLite is the initial metadata and relational store; binary assets live outside the database.
- Enable foreign keys on every connection.
- Use short transactions; never hold a transaction open during inference or media processing.
- Configure WAL during database initialization where supported.
- Migrations are numbered, immutable and checksum-verified.
- Full-text indexes are derived and rebuildable from canonical records.

## AI boundary

AI providers are optional adapters. Deterministic core operations must remain available without a model. External processing is disabled unless the user explicitly authorizes it.


## Current local media metadata slice

A registered local audio/video asset is inspected by the optional ffprobe executable. The adapter verifies the content-addressed original asset, invokes ffprobe without a shell and with local-only protocol restrictions, enforces time/stream/output limits, stores immutable container and stream metadata (including each stream's source start time), and records duration on the source only when no duration was already present. The optional FFmpeg stage can extract one selected audio stream to a normalized mono 16 kHz PCM WAV derivative. It stores both asset hashes, tool/configuration identity and the source stream offset; the transcription stage applies that offset to every segment and evidence locator. Original media remains immutable. Opt-in video frame sampling and conservative transcript-to-visual temporal alignment are now connected to the uploaded-media worker path; candidates remain NEEDS_REVIEW and sampled frame assets stay in the local asset store. OCR, slide classification, visual descriptions, semantic frame/transcript scoring and cross-modal claim verification remain separate review-gated stages. See MEDIA_PROBING.md, AUDIO_EXTRACTION.md, AUDIO_TRANSCRIPTION.md and VISUAL_TIMELINE.md.

## Current local PDF processing slice

The implemented document path is deliberately staged:

1. A user-selected PDF is registered as an immutable, content-addressed source asset.
2. pypdf extracts page-numbered native text with per-page hashes and bounded limits.
3. An optional local OCR adapter renders image-only pages, stores word boxes/confidence and requires explicit page review. Tesseract is the initial adapter; it is not bundled and no remote OCR fallback exists.
4. pdfplumber extracts positioned headings/paragraphs, equation candidates, table candidates and embedded/vector figure regions. Every element retains a page citation, normalized bounds, provenance and review state.
5. Accepted elements can create idempotent draft knowledge units with exact source-element lineage. This does not automatically create or validate claims.
6. Reviewed document topics can map multiple elements on one page. Deterministic textbook composition carries reviewed source blocks and accepted claims into chapters only when their exact page/element citations align.
7. The publication auditor blocks uncertain provenance, unreviewed evidence, unsupported claims and unaccepted OCR/element references.

Page numbers remain page numbers; they are never encoded as fake media timestamps. OCR and layout extraction are heuristic and bounded, not a hostile-file sandbox. See DOCUMENT_PIPELINE.md for the current CLI sequence and limitations.

The current document composer preserves source paragraphs, equations, tables and figure assets as structured blocks. Actual image embedding across PDF/DOCX/HTML/Markdown, native math rendering, semantic concept/claim discovery, formula verification and generated pedagogical explanations remain future work.
