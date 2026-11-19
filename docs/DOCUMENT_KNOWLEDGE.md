# Document elements into knowledge reconstruction

The document-to-knowledge adapter creates draft knowledge units from accepted structured PDF
elements. It is deliberately not an automatic claim extractor.

## Run

\`\`\`bash
omniintel structure-pdf ./omniintel.db ./omniintel-assets ASSET_ID
omniintel review-document-element ./omniintel.db ELEMENT_ID ACCEPTED
omniintel build-document-knowledge ./omniintel.db SOURCE_ID
\`\`\`

The adapter maps headings to concept candidates, equations to formula candidates, tables to
comparison candidates, list items to procedure candidates and paragraphs/figures/captions to
reference candidates. Each knowledge unit stores its source element ID and a reviewed-evidence
relationship to the exact page citation and element.

All created units remain \`NEEDS_REVIEW\`. Native source elements use DERIVED provenance for the
knowledge-unit representation; OCR-derived elements retain UNCERTAIN provenance. Their evidence
links begin PENDING. Re-running the import is idempotent per source element.

A later knowledge agent can use these source-linked units to propose definitions, concepts,
claims and relationships. It must still create claims separately and establish reviewed SUPPORTS
or CONTRADICTS relationships. Copying a paragraph into a knowledge unit does not make it a
validated claim, and no automatic entailment or contradiction verification is implied here.
