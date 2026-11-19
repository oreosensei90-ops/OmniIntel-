# HTML publishing

The initial HTML exporter emits a single UTF-8 document with embedded CSS and no external
runtime, fonts, scripts, image hosts or network dependencies. It consumes the canonical textbook
tree and runs the deterministic publication audit before writing output.

## Included

- Responsive semantic document structure and an in-page chapter contents list.
- Escaped text, headings, definitions, tables, code, equations and learning callouts.
- Evidence timestamps and provenance labels.
- Accessible descriptions for visual blocks when rendered assets are not yet available.
- Print stylesheet for browser print-to-PDF workflows.

All source text is treated as untrusted text and escaped; imported content cannot inject HTML or
script markup through textbook blocks.

## Current limitations

- Diagram and image blocks currently render accessible descriptions, not embedded image files.
- Equations are text/LaTeX, not rendered mathematics.
- No JavaScript, external stylesheet, external fonts or network resources are included.
- The publication audit is structural/review-oriented and does not establish factual truth,
  semantic evidence relevance, mathematical correctness, source completeness or pedagogy.

## CLI

```bash
omniintel export-html ./omniintel.db VERSION_ID ./exports/textbook.html
```
