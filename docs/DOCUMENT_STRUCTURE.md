# PDF document structure extraction

The local PDF structure adapter uses pdfplumber/pdfminer layout information to create ordered,
page-native elements. It never converts page numbers into timestamps.

## Element types

- \`HEADING\`: likely heading based on relative font size and boldness.
- \`PARAGRAPH\`: positioned text grouped into reading-order lines.
- \`LIST_ITEM\`: text line with a recognized bullet prefix.
- \`EQUATION\`: short text region containing common mathematical operators/symbols.
- \`TABLE\`: grid/table candidates returned by pdfplumber with extracted cell rows.
- \`FIGURE\`: embedded raster image regions; a bounded page crop is stored as a DIAGRAM asset
  when rasterization succeeds.
- OCR-only pages can produce paragraph elements from word boxes and retain OCR confidence.

## Run and review

\`\`\`bash
omniintel extract-pdf ./omniintel.db ./omniintel-assets ASSET_ID
omniintel ocr-pdf ./omniintel.db ./omniintel-assets ASSET_ID
omniintel structure-pdf ./omniintel.db ./omniintel-assets ASSET_ID
omniintel search-document-elements ./omniintel.db "conservation momentum"
omniintel list-document-elements ./omniintel.db
omniintel review-document-element ./omniintel.db ELEMENT_ID ACCEPTED
\`\`\`

Each element stores its page citation ID, ordinal, normalized bounding box, parser/version,
content JSON, confidence, provenance, review state and optional source-owned figure asset. The
preflight defaults cap extraction at 20,000 elements, 100,000 characters per element and
5,000,000 total element characters. Figure crops are capped at 20 million pixels and 25 MiB.
Database triggers enforce that the page citation and any figure asset belong to the same source.
Elements begin in \`NEEDS_REVIEW\`. If an accepted element is later downgraded, dependent accepted
claim, topic, knowledge-unit and textbook links are automatically demoted.

## Heuristic limitations

Heading, equation and reading-order classification is deterministic but heuristic. Table
recognition depends on visible table geometry and may miss borderless tables. Figure detection
currently covers embedded image objects, not every vector illustration or chart. OCR-derived
elements retain \`UNCERTAIN\` provenance even after layout review. Mathematical notation is stored
as extracted text; it is not parsed into symbolic math or validated. No semantic claim is made
about the content or completeness of the document.
