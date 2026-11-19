# OmniIntel

**A local-first learning and personal knowledge ecosystem.**

OmniIntel is being engineered to turn authorized learning sources—videos, audio, transcripts, documents and presentations—into detailed, evidence-grounded textbooks and reusable study resources.

The product direction includes native Android and installable web applications, a modular processing engine, offline library/search, structured knowledge, document publishing and personal study tools.

## Current implementation status

The repository is an actively evolving foundation implementation. The feature branch currently includes deterministic transcript ingestion, SQLite persistence, knowledge/evidence records, reviewed topic maps, versioned textbook composition and a deterministic publication-readiness audit. Audited PDF, editable DOCX, self-contained HTML and portable Markdown export are implemented. Initial content-addressed source-asset storage and safe local-file source registration are implemented for supported PDF, text, image, audio and video file signatures. Local-file registration preserves original bytes and records provenance/rights as unverified. Bounded local PDF text extraction stores page-numbered records and indexes them with SQLite FTS5. Optional local OCR handles image-only pages with explicit human review; positioned document structure extraction identifies headings, paragraphs, equation candidates, tables and embedded figures. Registered local audio/video assets can also be inspected with bounded, hash-verified ffprobe metadata probing. Accepted elements can seed draft knowledge units and deterministic textbook chapters with element-level citations. OCR, layout and classification remain heuristic and do not constitute semantic claim extraction or mathematical validation. IMAGE/DIAGRAM textbook blocks can link source-owned image assets with database-enforced source/type/role checks and publication gating. PDF, DOCX, HTML and Markdown exporters now render linked visual assets with source ownership checks and page-aware citations. Initial local PCM WAV transcription with content-addressed chunk checkpoints and source-linked timestamp evidence is implemented through an optional faster-whisper adapter. Registered compressed audio/video can be decoded locally to a normalized PCM WAV derivative with its original stream offset preserved. A read-only plan-first local input planner now classifies mixed source bundles and surfaces language, caption-association and multi-recording clock questions before any work starts. Approved plan execution, native Android ASR, web apps, automated knowledge generation and full general AI orchestration remain pending.

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
python -m pip install -e '.[dev,documents,publishing]'
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

Core persistence uses the Python standard library. Publishing and document parsing dependencies are optional; local faster-whisper transcription is separately installed with `python -m pip install -e '.[asr]'`.

Import a local SRT or WebVTT caption file into the source/evidence store:

```bash
omniintel import-captions ./omniintel.db ./lecture.vtt --title "Lecture 01" --language en
```

The initial caption adapter preserves cue timestamps and optional WebVTT voice labels. It does not download media or fetch caption URLs. See `docs/CAPTION_INGESTION.md` for supported syntax and boundaries.

## Group independent sources into a course

~~~bash
omniintel collection-create ./omniintel.db "Physics 101" --type COURSE
omniintel collection-add-source ./omniintel.db COLLECTION_ID SOURCE_ID --role LEARNING_SOURCE
omniintel collection-show ./omniintel.db COLLECTION_ID
~~~

Collections preserve independent source identity and order. Membership does not assert timeline alignment; caption/slide/media links require separate review. See docs/COLLECTIONS.md.

## Plan a multi-source learning bundle

Before importing a folder of recordings, slides and captions, inspect a read-only plan:

~~~bash
omniintel plan-inputs ./course-folder --recursive
omniintel plan-inputs ./lecture.mp4 ./slides.pdf ./captions.vtt --language en,hi
~~~

The planner classifies supported files, reports next stages and resource/network requirements, and asks for spoken-language or multi-recording alignment decisions rather than guessing. It does not import, decode, transcribe, OCR or write files. See docs/INPUT_PLANNING.md.

## Local media metadata probing

Inspect a registered local audio/video asset's container and stream metadata without decoding it or contacting a remote service:

~~~bash
omniintel import-file ./omniintel.db ./omniintel-assets ./lecture.mp4
omniintel probe-media ./omniintel.db ./omniintel-assets ASSET_ID
~~~

Install FFmpeg tools so ffprobe and ffmpeg are available on PATH. The probe verifies the content-addressed asset and records container/stream metadata. extract-audio creates a content-addressed mono 16 kHz PCM WAV derivative and preserves the source stream start offset. Neither stage downloads media or uses network protocols. Video frame extraction is implemented with timestamped content-addressed JPEGs. See docs/MEDIA_PROBING.md, docs/AUDIO_EXTRACTION.md and docs/VIDEO_FRAME_EXTRACTION.md.

## Local audio transcription

Register a user-selected PCM WAV file, or extract one audio stream from a local video/audio source, then transcribe it with a CTranslate2 model directory already on disk:

~~~bash
omniintel import-file ./omniintel.db ./omniintel-assets ./lecture.mp4 --title "Lecture 01"
omniintel extract-audio ./omniintel.db ./omniintel-assets SOURCE_ASSET_ID
omniintel transcribe-wav ./omniintel.db ./omniintel-assets SOURCE_ID OUTPUT_ASSET_ID --model /path/to/local-ct2-model --device cpu --compute-type int8 --threads 4 --language en
~~~

extract-audio selects the first audio stream by default; use --stream-index when another stream is needed. Its output asset stays linked to the same source, and the stored stream start offset is automatically applied to transcript timestamps. See docs/AUDIO_EXTRACTION.md. Install the optional adapter with python -m pip install -e '.[asr]'. Model downloads are disabled by default; explicitly add --allow-model-download if you authorize faster-whisper to fetch a model by name. Completed chunks are checkpointed by audio content and configuration, so an interrupted run can resume without retranscribing completed chunks. Existing source transcripts are never silently overwritten. The transcription adapter accepts normalized PCM WAV; local FFmpeg extraction now supplies that format for compressed media. VAD filtering is disabled by default to avoid dropping quiet lecture speech; enable it explicitly only when appropriate. Mobile-native ASR, word timestamps and diarization remain future work. See docs/AUDIO_EXTRACTION.md and docs/AUDIO_TRANSCRIPTION.md.

## Video visual intelligence

Extract frames and build the source-bound visual timeline:

~~~bash
omniintel extract-frames ./omniintel.db ./omniintel-assets VIDEO_ASSET_ID
omniintel build-visual-timeline ./omniintel.db FRAME_EXTRACTION_ID
omniintel visual-timeline ./omniintel.db SOURCE_ID
~~~

Review each visual event with \`review-visual-event\`, then review its temporal link with
\`review-visual-record\` and the table \`visual_transcript_alignments\`. Scene-change detection and
frame OCR are optional local stages:

~~~bash
omniintel detect-scenes ./omniintel.db ./omniintel-assets SOURCE_ID
omniintel ocr-video-frames ./omniintel.db ./omniintel-assets SOURCE_ID
~~~

Install the optional vision dependency with \`pip install -e '.[vision]'\`; install Tesseract
separately for OCR. OCR output always starts in NEEDS_REVIEW.

Visual descriptions, semantic matching and cross-modal claim checks use an explicitly selected
local Ollama vision model. Start Ollama locally and install a compatible vision model first:

~~~bash
omniintel describe-video-frames ./omniintel.db ./omniintel-assets SOURCE_ID --model MODEL
omniintel align-video-semantics ./omniintel.db ./omniintel-assets SOURCE_ID --model MODEL
omniintel verify-visual-claim ./omniintel.db SOURCE_ID CLAIM_ID VISUAL_EVENT_ID DESCRIPTION_ID --model MODEL
~~~

The adapter connects only to \`127.0.0.1:11434\`, refuses redirects, and does not use hosted model
endpoints. All model outputs remain NEEDS_REVIEW. Cross-modal contradictions accepted by a reviewer
block textbook publication. See \`docs/VIDEO_VISUAL_INTELLIGENCE.md\`.

When exporting a textbook containing linked images, provide the asset store:

~~~bash
omniintel export-pdf ./omniintel.db VERSION_ID ./exports/book.pdf --asset-dir ./omniintel-assets
omniintel export-docx ./omniintel.db VERSION_ID ./exports/book.docx --asset-dir ./omniintel-assets
omniintel export-html ./omniintel.db VERSION_ID ./exports/book.html --asset-dir ./omniintel-assets
omniintel export-markdown ./omniintel.db VERSION_ID ./exports/book.md --asset-dir ./omniintel-assets
~~~

PDF/DOCX embed supported image files; HTML embeds them as bounded data URIs; Markdown copies them
to a sibling \`.assets\` folder. Exported page citations display page numbers rather than fabricated
video timestamps.

## Rights and source access

Only process media and documents the user is authorized to access and use. Public availability does not automatically grant download, reproduction or redistribution rights. Respect platform terms, copyright and access controls. OmniIntel will not implement DRM or access-control circumvention.

## License

The repository's existing MIT license is retained. Third-party code, model weights, fonts, datasets and native dependencies require separate license review before distribution.


Register an explicitly selected local file while preserving its original bytes:

```bash
omniintel import-file ./omniintel.db ./omniintel-assets ./lecture.pdf --title "Lecture 01"
```

This records the source, detected media type, content hash and an asset reference. It does not
extract PDF text, OCR, transcribe or decode media. Those are separate local stages; the source rights status remains UNVERIFIED.
See `docs/LOCAL_FILE_INGESTION.md` for supported types and limitations.


Extract bounded text from an already-ingested local PDF, preserving page numbers and page hashes:

```bash
omniintel extract-pdf ./omniintel.db ./omniintel-assets ASSET_ID
```

Install the optional PDF parser with `pip install -e ".[documents]"`. Extraction is local-only,
rejects encrypted PDFs, enforces page and character limits, and stores per-page text separately
from video transcript segments. Scanned pages are marked empty until the optional OCR stage is run. See `docs/PDF_PAGE_EXTRACTION.md` and `docs/DOCUMENT_OCR.md`.


Search extracted PDF pages locally:

```bash
omniintel search-pages ./omniintel.db "quantum entanglement"
```


Search and resolve evidence using one citation model across transcript intervals and PDF pages:

```bash
omniintel search-evidence ./omniintel.db "velocity direction"
omniintel resolve-evidence ./omniintel.db EVIDENCE_REFERENCE_ID
```

Transcript imports and PDF extraction now create stable evidence-reference IDs. Transcript citations
retain millisecond intervals; PDF citations retain one-based page numbers and the original asset ID.
The unified locator does not fabricate timestamps for documents. Claims, topic maps and textbook blocks can now use these shared references, including optional exact document element IDs. See
`docs/UNIFIED_EVIDENCE_REFERENCES.md`.


PDF pages can also be organized into a page-native topic hierarchy without inventing timestamps. Accepted source elements can be carried into deterministic textbook chapters; accepted claims must use the same exact page/element citation as the topic alignment. Source-linked draft knowledge units can be reviewed and validated separately. See `docs/DOCUMENT_TOPIC_MAPS.md` and `docs/DOCUMENT_KNOWLEDGE.md`.


## Video visual timeline

After extracting bounded timestamped frames from a registered local video, build a reviewable
visual timeline and propose nearby transcript alignment candidates:

~~~bash
omniintel extract-frames ./omniintel.db ./omniintel-assets VIDEO_ASSET_ID
omniintel build-visual-timeline ./omniintel.db FRAME_EXTRACTION_ID --tolerance-ms 10000
omniintel visual-timeline ./omniintel.db SOURCE_ID
~~~

Frame events and transcript links remain NEEDS_REVIEW. Alignment is based only on temporal overlap
or nearest-segment distance; it does not establish that speech describes the image. See
`docs/VISUAL_TIMELINE.md`.

## Local PDF intelligence

See `docs/DOCUMENT_PIPELINE.md` for the end-to-end workflow, `docs/DOCUMENT_OCR.md` for
local OCR, `docs/DOCUMENT_STRUCTURE.md` for positioned document elements, and
`docs/DOCUMENT_KNOWLEDGE.md` for the reviewed handoff into knowledge reconstruction.

## Research and architecture decisions

The video-to-notes and lecture-learning research batch is recorded in
[docs/RESEARCH_REGISTER.md](docs/RESEARCH_REGISTER.md). The accepted design decisions,
rejected patterns and implementation sequence are summarized in
[docs/REFERENCE_IMPLEMENTATION_PLAN.md](docs/REFERENCE_IMPLEMENTATION_PLAN.md).
These references inform our own implementation; they are not automatically approved
dependencies or permission to copy third-party code.


## Multi-source intake and course textbooks

Create a read-only plan for local files, then review it before any work is approved:

```bash
omniintel plan-inputs ./course-folder --recursive --language en,hi
```

The execution coordinator is an application API: it requires an explicit approval decision and injected local stage adapters; it never runs shell commands or performs network acquisition. See [docs/EXECUTION_ALIGNMENT_COURSE_TEXTBOOKS.md](docs/EXECUTION_ALIGNMENT_COURSE_TEXTBOOKS.md).

Create a course and a source-attributed course textbook:

```bash
omniintel collection-create ./omniintel.db "Physics 101" --type COURSE
omniintel course-book-create ./omniintel.db COLLECTION_ID "Physics 101 — Complete Textbook"
omniintel course-book-version ./omniintel.db TEXTBOOK_ID "Draft 1" --mode HYBRID
omniintel course-book-chapter ./omniintel.db VERSION_ID "Kinematics" 0 --source-id SOURCE_ID
omniintel course-book-block ./omniintel.db CHAPTER_ID PARAGRAPH '{"text":"Reviewed content"}' --provenance SOURCE --review ACCEPTED
omniintel course-book-link-evidence ./omniintel.db BLOCK_ID EVIDENCE_REFERENCE_ID
omniintel course-book-review-evidence ./omniintel.db LINK_ID ACCEPTED
omniintel course-book-audit ./omniintel.db VERSION_ID
```

Course textbook evidence remains source-specific. Clock alignment proposals use measured feature envelopes and remain NEEDS_REVIEW until reviewed. Existing single-source exporters are not yet connected to course textbook versions. See [docs/DEEP_RESEARCH_AUDIT_2026-11-19.md](docs/DEEP_RESEARCH_AUDIT_2026-11-19.md).
