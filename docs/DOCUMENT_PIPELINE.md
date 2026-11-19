# Local PDF-to-textbook workflow

This is the current deterministic local workflow for an already-authorized PDF. Install the
optional Python document dependencies and local Tesseract only if scanned pages need OCR.

\`\`\`bash
# 1. Register the user's selected local PDF; preserve original bytes.
omniintel import-file ./omniintel.db ./omniintel-assets ./course.pdf

# 2. Extract page text and stable page citations.
omniintel extract-pdf ./omniintel.db ./omniintel-assets ASSET_ID

# 3. OCR image-only pages when needed; review each OCR page before use.
omniintel ocr-pdf ./omniintel.db ./omniintel-assets ASSET_ID
omniintel review-ocr-page ./omniintel.db PAGE_ID ACCEPTED

# 4. Extract structure; inspect and review headings, paragraphs, equations, tables and figures.
omniintel structure-pdf ./omniintel.db ./omniintel-assets ASSET_ID
omniintel list-document-elements ./omniintel.db
omniintel review-document-element ./omniintel.db ELEMENT_ID ACCEPTED --provenance DERIVED

# 5. Create draft knowledge units from accepted elements.
omniintel build-document-knowledge ./omniintel.db SOURCE_ID
omniintel review-knowledge-unit ./omniintel.db UNIT_ID VALIDATED --provenance DERIVED

# 6. After topics and claims have been separately reviewed and linked to the same exact
#    element/page citations, compose and audit a textbook.
omniintel document-outline ./omniintel.db SOURCE_ID
omniintel compose-document-textbook ./omniintel.db SOURCE_ID "Course textbook"
omniintel audit-textbook ./omniintel.db VERSION_ID
\`\`\`

This pipeline is not yet a one-click AI textbook generator. Topic discovery, semantic claim
extraction, relevance verification, mathematical validation, cross-page concept synthesis and
pedagogical rewriting remain separate future stages. The current composer places accepted
source elements and accepted claims into deterministic chapters; it does not invent explanatory
prose. Exported figure assets are linked and audited, but embedding/rendering those assets in all
export formats is still pending.
