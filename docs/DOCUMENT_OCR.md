# Local PDF OCR

OmniIntel can render image-only PDF pages and pass the page PNG to a local OCR adapter. The
default adapter is Tesseract's TSV command-line interface; no remote OCR provider is contacted.

## Install

Install the Python document dependencies and the Tesseract executable separately:

\`\`\`bash
python -m pip install -e '.[documents]'
tesseract --version
\`\`\`

Tesseract is an optional system program, not bundled into the Python package. A different local
engine can implement the \`OCRAdapter\` protocol and be injected into \`ocr_pdf\`.

## Run

\`\`\`bash
omniintel import-file ./omniintel.db ./omniintel-assets ./scan.pdf
omniintel extract-pdf ./omniintel.db ./omniintel-assets ASSET_ID
omniintel ocr-pdf ./omniintel.db ./omniintel-assets ASSET_ID
omniintel review-ocr-page ./omniintel.db PAGE_ID ACCEPTED
omniintel search-evidence ./omniintel.db "quantum tunnelling"
\`\`\`

Only pages without native extracted text are OCRed by default. OCR results store the rendered page
as a content-addressed image asset, engine/version, recognized text, word boxes, mean confidence
and review status. OCR starts as \`NEEDS_REVIEW\`; it is not source-authored text. Accepted claim,
topic, knowledge-unit or textbook evidence links cannot rely on OCR text until the page is accepted.
Downgrading OCR review automatically demotes dependent accepted links and recomputes affected
claim status.

## Resource and trust boundaries

- Default render resolution is 144 DPI, configurable only from 72–300 DPI.
- Each page is limited to 20 million estimated pixels and 25 MiB encoded PNG.
- A run is limited to 200 pages and 200 million estimated rendered pixels.
- Each page has a bounded OCR timeout.
- PDF bytes are resolved from local content-addressed storage and hash-verified first.
- No URL fetching, remote fallback, shell interpolation or arbitrary OCR configuration is used.
- OCR confidence is a signal, not proof of correctness; handwriting, rotation, tables and math
  can still be misread.
- Mixed pages containing both native text and scanned image regions are currently skipped by the
  default OCR pass; region-level hybrid OCR is future work.

This is an initial local adapter, not a malware sandbox. Production processing of hostile PDFs
should run in a restricted worker with OS-level CPU, memory, filesystem and process limits.
