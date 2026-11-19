# Markdown publishing

The initial Markdown exporter serializes the canonical textbook block tree after running the
deterministic publication audit. Output is UTF-8 and intended to remain portable across common
Markdown readers and static-site tools.

## Included

- Title, edition metadata, chapter contents and anchors.
- Paragraphs, definitions, tables, equations, fenced code and pedagogical callouts.
- Evidence timestamps, provenance labels and accessible descriptions for visual blocks.
- Dynamic code fences that avoid colliding with backtick sequences in source code.
- Escaped table-cell pipes and normalized line endings.

## Current limitations

- Image and diagram blocks render accessible descriptions, not embedded assets.
- Equations remain source text/LaTeX; no math renderer is bundled.
- Chapter anchors use a simple Unicode-aware slug algorithm; individual Markdown renderers
  may normalize heading anchors differently.
- The publication audit is not semantic or factual verification.

## CLI

```bash
omniintel export-markdown ./omniintel.db VERSION_ID ./exports/textbook.md
```
