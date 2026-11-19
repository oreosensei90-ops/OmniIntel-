# PDF page extraction

OmniIntel's first document-text adapter reads an already-ingested local PDF asset and stores
one immutable page-text record per page for a specific parser version.

## CLI

First register the local PDF with \`import-file\`, then pass the returned asset ID:

\`\`\`bash
omniintel extract-pdf ./omniintel.db ./omniintel-assets ASSET_ID
\`\`\`

Install the optional parser dependency using \`pip install -e ".[documents]"\`.

## Stored provenance

- Extraction record: source asset, parser name/version, page count and extraction timestamp.
- Page record: stable page number, extracted text, character count, SHA-256 of normalized text and status.
- Re-running the same parser version replaces its page set atomically while retaining the extraction identity.
- Original PDF bytes remain unchanged in content-addressed storage.

Page numbers are one-based and are not represented as fake video timestamps. Page text is stored
separately from transcript segments. Unified evidence references now connect document pages and
transcript intervals to shared claim, topic and textbook evidence workflows. See DOCUMENT_OCR.md,
DOCUMENT_STRUCTURE.md and DOCUMENT_PIPELINE.md for scanned-page OCR and structured extraction.

## Limits and security boundaries

Defaults: 500 pages, 100,000 characters per page and 5,000,000 total extracted characters.
Encrypted PDFs are rejected. The text parser does not execute JavaScript, follow links, download
resources or unpack attachments. OCR and raster rendering are separate optional local stages;
see DOCUMENT_OCR.md. Empty pages are explicitly marked and can be sent to OCR.

Extraction errors abort before page records are written. Extraction is local-only and uses the
content-addressed asset hash check before parsing. File size is already bounded at ingestion.
These limits reduce resource abuse but are not a substitute for sandboxing hostile documents
in a production service.


## Page search

Extracted page text is indexed with SQLite FTS5. Search is local and returns the source ID,
original asset ID, page ID, one-based page number and a short excerpt. Search terms are parsed
and quoted before being passed to FTS, so raw user text is never treated as an FTS query program.

\`\`\`bash
omniintel search-pages ./omniintel.db "quantum entanglement"
\`\`\`

The index is maintained by database triggers and rebuilt from stored page text when the search
migration is first applied. This is lexical retrieval, not semantic search and not proof that a
page supports a particular claim.
