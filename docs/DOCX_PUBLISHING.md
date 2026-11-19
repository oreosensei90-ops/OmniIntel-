# DOCX publishing

The initial DOCX exporter writes the canonical textbook block tree to an editable Microsoft Word
package using `python-docx`. It runs the deterministic textbook publication audit before writing
anything and refuses editions that fail the current review/provenance gates.

## Included

- Title and edition metadata, consistent document styles, chapter headings and page breaks.
- Editable paragraphs, definitions, tables, code and equation text.
- Styled callouts for examples, worked solutions, warnings, misconceptions and exercises.
- Source-time intervals, evidence timestamps and provenance labels.
- Header/footer branding and a dynamic page-number field.
- Accessible text descriptions for diagram/image blocks when no rendered asset is available.

## Current limitations

- Equations are editable text (LaTeX or the stored expression), not native Word equation objects.
- Diagram and image blocks currently publish their accessible descriptions, not embedded visual
  assets. The canonical model must gain safe asset resolution before image embedding.
- This is a structural publication gate, not semantic verification. Passing it does not prove
  factual truth, evidence relevance, mathematical correctness, completeness or pedagogical quality.
- Font availability and layout can vary between Word-compatible applications. Visual regression
  checks across office suites remain future work.

## CLI

```bash
omniintel audit-textbook ./omniintel.db VERSION_ID
omniintel export-docx ./omniintel.db VERSION_ID ./exports/textbook.docx
```

Install the optional publishing dependencies with `python -m pip install -e '.[publishing]'`.
