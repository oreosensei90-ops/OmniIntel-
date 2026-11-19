# Unified evidence references

OmniIntel now exposes a common citation handle for evidence that lives in different native source
locations. The handle is not a fabricated universal timestamp: it retains the source-specific
locator type and fields.

## Locator types

- \`TRANSCRIPT_INTERVAL\`: references an existing transcript evidence item and its exact
  \`start_ms\` / \`end_ms\` interval.
- \`DOCUMENT_PAGE\`: references an extracted PDF page, its source asset and one-based
  \`page_number\`. Time fields remain null.

The database enforces that the cited evidence belongs to the stated source. For page citations,
the document page must belong to the stated PDF asset, which must in turn belong to that source.
A citation ID is stable for the lifetime of the underlying page record.

## CLI

Search transcript and PDF page evidence through one result shape:

\`\`\`bash
omniintel search-evidence ./omniintel.db "velocity direction"
omniintel resolve-evidence ./omniintel.db EVIDENCE_REFERENCE_ID
\`\`\`

The existing \`search-pages\` command remains useful for PDF-only retrieval. Search uses a shared SQLite FTS5 index over transcript and document-page evidence. It is lexical;
it does not establish semantic support for a claim.

## Lifecycle

Transcript imports automatically create unified references alongside their existing evidence items.
PDF extraction creates page references automatically. Re-running the same PDF parser version
preserves page and reference IDs when page count is unchanged. If page count changes, extraction
fails and requires a parser-version bump rather than silently invalidating existing citations.

## Scope

This is the shared citation-location layer. Claim and textbook relationship tables still use their
original transcript evidence links; integrating all relationships with the new reference IDs is
the next migration. Claims and textbook blocks can now link directly to unified evidence references, and their review/publication gates aggregate old transcript links with new native-location links. The reference layer itself does not assert that a cited passage supports a claim.

## Cross-platform relationship contracts

The JSON Schema contracts are split by responsibility:

- \`evidence-reference.schema.json\`: native source locator.
- \`claim-evidence-reference.schema.json\`: reviewed relationship between a claim and a citation.
- \`block-evidence-reference.schema.json\`: reviewed relationship between a textbook block and a citation.

This keeps the location itself independent from how a claim or published block uses it. The same
page citation can support multiple claims or appear in multiple learning artifacts without copying
or rewriting its source locator.

