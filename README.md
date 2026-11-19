# OmniIntel

**A local-first learning and personal knowledge ecosystem.**

OmniIntel is being engineered to turn authorized learning sources—videos, audio, transcripts, documents and presentations—into detailed, evidence-grounded textbooks and reusable study resources.

The product direction includes native Android and installable web applications, a modular processing engine, offline library/search, structured knowledge, document publishing and personal study tools.

## Current implementation status

This repository is at the beginning of its implementation. The foundation branch currently includes deterministic transcript ingestion, SQLite persistence, knowledge/evidence records, reviewed topic maps, versioned textbook composition and a deterministic publication-readiness audit. Audited PDF, editable DOCX, self-contained HTML and portable Markdown export are implemented. Initial content-addressed source-asset storage and safe local-file source registration are implemented for supported PDF, text, image, audio and video file signatures. Local-file registration preserves original bytes and records provenance/rights as unverified. Bounded local PDF text extraction now stores page-numbered records and indexes them with SQLite FTS5; scanned-page OCR and audio/video decoding remain pending. IMAGE/DIAGRAM textbook blocks can link source-owned image assets with database-enforced source/type/role checks and publication gating. Visual asset rendering in export formats remains pending. Android, web, media extraction adapters and AI inference are not yet implemented.

## Engineering principles

- Local-first data ownership; reading and saved-library access should work offline.
- Preserve original source material and provenance.
- Separate source evidence, interpreted knowledge and learning artifacts.
- Treat model output and imported content as untrusted until validated.
- Make long-running jobs resumable and idempotent.
- Never claim a source citation proves a claim without checking relevance.
- External processing requires explicit user approval.
- Keep provider, model and platform integrations replaceable.
- Preserve user-authored notes and history across regeneration.

## Repository map

- `engine/omniintel/` — Python domain and persistence foundation.
- `schemas/` — versioned cross-platform data contracts.
- `tests/` — automated tests.
- `docs/` — architecture, decisions, research and roadmap.
- `apps/` — future Android and web applications.

## Python development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

Audit a saved textbook version before export:

```bash
omniintel audit-textbook ./omniintel.db VERSION_ID

# Export a publication-ready PDF
omniintel export-pdf ./omniintel.db VERSION_ID ./exports/textbook.pdf

# Export an editable Word document
omniintel export-docx ./omniintel.db VERSION_ID ./exports/textbook.docx

# Export a self-contained HTML textbook
omniintel export-html ./omniintel.db VERSION_ID ./exports/textbook.html

# Export portable Markdown
omniintel export-markdown ./omniintel.db VERSION_ID ./exports/textbook.md
```

The audit command prints a JSON report and exits non-zero when publication gates fail. PDF export runs the same gate before rendering and refuses blocked editions. Passing deterministic checks is not a substitute for semantic or human review. Install `.[publishing]` for ReportLab and python-docx publishing dependencies.

Core persistence initially uses the Python standard library. Optional publishing dependencies are installed with `python -m pip install -e '.[publishing]'`.

Import a local SRT or WebVTT caption file into the source/evidence store:

```bash
omniintel import-captions ./omniintel.db ./lecture.vtt --title "Lecture 01" --language en
```

The initial caption adapter preserves cue timestamps and optional WebVTT voice labels. It does not download media or fetch caption URLs. See `docs/CAPTION_INGESTION.md` for supported syntax and boundaries.

## Rights and source access

Only process media and documents the user is authorized to access and use. Public availability does not automatically grant download, reproduction or redistribution rights. Respect platform terms, copyright and access controls. OmniIntel will not implement DRM or access-control circumvention.

## License

The repository's existing MIT license is retained. Third-party code, model weights, fonts, datasets and native dependencies require separate license review before distribution.


Register an explicitly selected local file while preserving its original bytes:

\`\`\`bash
omniintel import-file ./omniintel.db ./omniintel-assets ./lecture.pdf --title "Lecture 01"
\`\`\`

This records the source, detected media type, content hash and an asset reference. It does not
extract PDF text, OCR, transcribe or decode media. The source rights status remains UNVERIFIED.
See `docs/LOCAL_FILE_INGESTION.md` for supported types and limitations.


Extract bounded text from an already-ingested local PDF, preserving page numbers and page hashes:

\`\`\`bash
omniintel extract-pdf ./omniintel.db ./omniintel-assets ASSET_ID
\`\`\`

Install the optional PDF parser with \`pip install -e ".[documents]"\`. Extraction is local-only,
rejects encrypted PDFs, enforces page and character limits, and stores per-page text separately
from video transcript segments. Scanned pages may be empty until an OCR adapter is implemented.
See \`docs/PDF_PAGE_EXTRACTION.md\`.


Search extracted PDF pages locally:

\`\`\`bash
omniintel search-pages ./omniintel.db "quantum entanglement"
\`\`\`


Search and resolve evidence using one citation model across transcript intervals and PDF pages:

\`\`\`bash
omniintel search-evidence ./omniintel.db "velocity direction"
omniintel resolve-evidence ./omniintel.db EVIDENCE_REFERENCE_ID
\`\`\`

Transcript imports and PDF extraction now create stable evidence-reference IDs. Transcript citations
retain millisecond intervals; PDF citations retain one-based page numbers and the original asset ID.
The unified locator does not fabricate timestamps for documents. See
\`docs/UNIFIED_EVIDENCE_REFERENCES.md\`. Claim and textbook link migration to these unified IDs is
still pending.


PDF pages can also be organized into a page-native topic hierarchy without inventing timestamps.
See \`docs/DOCUMENT_TOPIC_MAPS.md\` for the API, review rules and source-boundary protections.
