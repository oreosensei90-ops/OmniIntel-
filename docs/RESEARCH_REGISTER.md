# Product and Repository Research Register

These are user-supplied research leads, not approved dependencies or endorsements. Before adapting code, inspect the exact source, current maintenance state, license, transitive dependencies, security posture and model/data terms. Product websites are feature references, not implementation licenses.

## Product references
- https://mylens.ai/
- https://notebook.google/
- https://www.studyfetch.com/
- https://notegpt.io/

## Repository and technical references
- https://github.com/topics/notebooklm
- https://github.com/jxnl/noteGPT
- https://github.com/Nutlope/notesGPT
- https://github.com/rypkwj31/notegpt
- https://github.com/jxnl/noteGPT/blob/main/.example.env
- https://github.com/Nialled69/Note-gpt
- https://github.com/xxz2211/ai-meeting-note-taker-tools
- https://github.com/notegpt-official/notegpt-skills/blob/main/skills/ai-paper-writer/SKILL.md
- https://github.com/Milkshiift/YouTubeTLDR
- https://github.com/amicalhq/prismical
- https://github.com/molly554/Multi_sources_summarizition_lynote.ai

## Evaluation checklist
- Product capability and workflow.
- Source ingestion and evidence traceability.
- Transcript/visual alignment.
- Textbook and study artifact quality.
- Offline/local-first behaviour.
- AI provider abstraction and privacy.
- Accessibility and user experience.
- License and attribution obligations.
- Security and dependency health.
- Maintenance activity and reproducibility.

No source code is approved for copying merely because it appears in this register.


## Additional GitHub discovery topics
- https://github.com/topics/ai-learning-assistant
- https://github.com/topics/ai-note-taking-app

These topic pages are broad discovery indexes. Select repositories for deeper review based on relevance to OmniIntel, source availability, maintenance, security, architecture and verified licensing. Topic membership alone is not evidence of quality or permission to reuse code.

## Video-to-notes / lecture-transcription research batch (2026-11-19)

The user-supplied repositories below were checked at repository-metadata, README, file-tree and selected-source level. High-value implementations were inspected directly. This is source review, not a claim that every project was cloned, installed, executed or security-certified. Metadata and activity are a time-sensitive snapshot.

### Repository inventory and disposition

| Repository | Observed architecture / useful ideas | License signal | OmniIntel disposition |
|---|---|---|---|
| https://github.com/Akarshkushwaha/studymitra | Gradio lecture tool; faster-whisper, VAD/word timestamps, BART map/reduce, KeyBERT/MMR, TF-IDF extractive Q&A, MarianMT and WER/ROUGE/QA evaluation; lazy model registry. | No license identified. | Model/evaluation research only; heavy Python/PyTorch/HF stack and English-specific subsystems. |
| https://github.com/kiaashkan/LectureFlow | Cloudflare Worker/browser transcription; browser WAV conversion and chunking; Groq Whisper large-v3/Turbo; TXT/PDF export; separate Android client. | No license identified. | UX/chunking reference only. Hosted transcription sends audio off-device; transcription is English although UI supports 11 languages. |
| https://github.com/Enyu-Liu/video-to-notes-skill | Agent skill; captions-first option, local Whisper fallback, OpenRouter text generation, Markdown output, multi-platform/language support. | MIT and LICENSE. | Acquisition and agent-workflow reference; generation still uses hosted API. |
| https://github.com/HHousen/lecture2notes | Research pipeline with learned slide classifier, frame sampling, slide crop/dedup/clustering, OCR/SSA, figure detection, ASR and extractive+abstractive summarization. | AGPL-3.0. | Important historical multimodal research reference; code reuse requires an explicit AGPL compatibility decision. Legacy frame extraction builds a shell command and invokes os.system; do not reuse that pattern. |
| https://github.com/SujalJaveri/ai-video-note-extractor | FastAPI + frontend; yt-dlp/FFmpeg, Whisper and Groq LLM; model fallback and progress UI. | No license identified. | Basic workflow reference only; hosted inference, no demonstrated evidence model. |
| https://github.com/Vicky-Vrishni/video-note-extractor | Streamlit; URL/local upload, Groq Whisper timestamps, Llama notes/key points/action items. | No license identified. | Simple UI/output reference; hosted audio processing, no claim-level citations. |
| https://github.com/Allen0497/video-to-notes | Skill/script: subtitles first, local faster-whisper fallback, FFmpeg frames, PSNR dedup, batched frame analysis, translation, Markdown/Jupyter outputs. Duplicate URL in user list consolidated. | MIT. | Strong feature/workflow reference; inspect downloader, prompt provenance and platform terms before adaptation. |
| https://github.com/xKarinSan/video-notes | Electron desktop product plus Python/agent experiments; metadata/transcript, note modes, JSON/TXT/PDF, local cache and timestamp links. | MIT. | Desktop information architecture reference; README labels some note modes as coming soon. |
| https://github.com/thewh1teagle/vibe | Large Rust/Tauri desktop transcription product; offline ASR, multiple model families, diarization, batch, stable timestamps, CLI/API and exports. | MIT. | High-value ASR benchmark/reference, not an Android app. Review telemetry/privacy and native model packaging before considering components. |
| https://github.com/AdritPal08/YouTube-Video-to-Notes-Transcription-Application- | Streamlit/Gemini prompt-driven notes; subject presets, custom prompt, output language and text download. | GPL-3.0. | Low architectural depth; GPL obligations make reuse a separate decision. |
| https://github.com/satya122id0889/AI-Video-to-Notes-Intelligence-Platform | OCR + BERT semantic frame embeddings, cosine change detection, representative keyframes, human selection and PDF export. | No license identified. | Useful frame/slide selection concept; not a complete transcript-grounded note generator. |
| https://github.com/di37/youtube-notes-generator | Streamlit/Gemini audio-understanding notes with tutorial vs lecture prompts and custom prompt. | MIT metadata. | Task-specific prompt-routing reference; no separate transcript/evidence layer. |
| https://github.com/Pranav322/youtube-notes | FastAPI + Next.js; transcript retrieval, chunked map/reduce technical notes, chapter storage, PostgreSQL/SQLite and PDF/Markdown export. | README says MIT; LICENSE file/metadata not verified. | Useful long-context/course concepts. Inspected map stage uses asyncio.gather over all chunks; OmniIntel should use bounded concurrency and per-chunk checkpoints. |
| https://github.com/amroeser/lecture-notes-app | MIT desktop Electron/Next app; course/semester batches, one chapter per lecture, series ordering/merge, Markdown/PDF, file-hash cache, retry and guardrails. OpenAI/Mistral transcription plus OpenAI-compatible or local Claude/Codex CLI text generation. | MIT. | Strong batch/course workflow reference; hosted transcription/API and desktop-first. Series marker checks do not prove semantic coverage. |
| https://github.com/AnishBashyal/NotesAI | Older Flask hackathon project using Google Cloud speech, OpenAI/LangChain, Auth0 and Firebase history. | No license identified. | Historical product-flow reference only; stale/cloud-coupled. |
| https://github.com/davertor/take-notes | MIT agent skill; video/article/paper/slides/repository input, multi-source synthesis, genre-specific didactic notes, self-contained HTML, Markdown/Anki, local archive and active recall/application guidance. | MIT. | Strong pedagogy and multi-source composition reference; not a durable source/evidence/job engine. |
| https://github.com/drpwchen/lecture-to-notes | MIT staged local-first pipeline: route/plan inputs, ASR, slide/PDF/image extraction, OCR, dedup, local VLM, transcript-slide grounding, provenance hashes, note audit, Markdown/PDF/Obsidian and synchronized offline HTML viewer. | MIT. | Top architecture reference. Explicit language questions, human-confirmed multi-source alignment, stage manifests and viewer safety map well to OmniIntel. Desktop NVIDIA hardware tested; not mobile-ready. |
| https://github.com/drpwchen/ytscribe | Channel-level incremental transcript fetch; subtitles first, local Whisper fallback, source labels, skip existing outputs, no video retained. | MIT. | Excellent low-cost ingestion pattern; distinguishes captions from ASR and avoids needless video download. |
| https://github.com/risonsimon/youtube-notes | yt-dlp + Gemini/LiteLLM transcript-to-notes script with Markdown/PDF output. | MIT. | Basic exporter reference only. |
| https://github.com/risonsimon/interactive-deep-notes | Agent skill producing self-contained interactive HTML; pedagogy sequence cover → explain → test → apply; video/article input and localStorage-backed interaction. | MIT. | Strong study interaction ideas; localStorage is not a durable cross-artifact study database or spaced-repetition engine. |
| https://github.com/theashishmaurya/videoNotes | Older SaaS Next/React/Firebase app using YouTube captions, GPT-3.5, translation and blog output. | MIT metadata and LICENCE file. | Product-history reference; older cloud/SaaS design. |
| https://github.com/EKarton/Lecture-Video-to-PDF | Computer-vision slide-change/animation segmentation aligned with supplied subtitles; PDF pages pair screenshots and transcript. | GPL-3.0. | Slide-change/pairing research; older dependency-heavy implementation and GPL obligations. |
| https://github.com/ajaypokharel/ai-powered-notes | Flask + React, Whisper and fine-tuned BART for live/recorded lecture notes. | No license identified. | Concept reference; stale and insufficiently documented for reuse. |
| https://github.com/Charlo-O/Video2Note | Electron/React/FastAPI; subtitle-driven LLM timestamp selection, OpenCV frame capture, blur retry, editable two-pane video/notes editor, Markdown/PDF and OpenAI-compatible providers. | README claims MIT; license file/metadata signal not verified. | Useful editor/keyframe UX reference. Validate model timestamps against media; blur heuristics are not semantic correctness. |
| https://github.com/Sairaj-25/YT_AI_NOTES | FastAPI, SQLite, auth, faster-whisper and Gemini; web app and note history. | GitHub reports NOASSERTION; treat as unclear/unlicensed until verified. | Basic architecture reference. Inspected ASR code uses CPU base model, VAD and batch size 16; not a mobile default without benchmarks. |
| https://github.com/RJohnPaul/YouNotes | Next/React + Express, Supabase auth, RapidAPI transcript retrieval, Gemini and responsive web UI. | README claims MIT; LICENSE file/metadata signal not verified. | UX reference only; README exposes API keys as NEXT_PUBLIC variables, an unsafe pattern never to copy. |
| https://github.com/saketk511/Youtube-Video-Notes | Streamlit, YouTube Transcript API, Gemini, subject-specific prompts, Hindi translation and ReportLab PDF. | No license identified. | Simple subject-routing/export reference; no evidence model. |
| https://github.com/ayushdubey570/VidNotes | Streamlit + YouTube Transcript API + Gemini Pro, concise summaries. | No license identified. | Minimal baseline; README lists export/mobile/auth as future work. |
| https://github.com/vilsijain/AI-Note | Older Lecture Noted prototype: YouTube/upload, transcript API, cross-referenced graphics and Word export. | No license identified; repository appears old. | Historical UX concept only. |
| https://github.com/manthan410/audio-lecture-notes-generator | Older notebook/Tkinter prototype for section-wise topics, transcription and timestamp-based playback. | No license identified. | Historical topic/timestamp navigation idea only. |

### Deeper source inspections: lessons that affect OmniIntel

1. Keep acquisition, evidence construction and writing separate. drpwchen/lecture-to-notes prepares OCR, slide semantics and transcript-to-slide grounding before final prose. Its plan-only router emits argv, network/GPU requirements, reads/writes and unresolved human questions.
2. Alignment must be measured, not guessed. That project treats capture times from filenames/metadata as hypotheses and asks for cross-correlation or human confirmation. Its slide grounding uses transcript windows and guarded keyword matching rather than timestamp proximity alone.
3. Provenance must be independently verifiable. Its manifest records input/output digests, stage, provider, engine, model, network and parameters, then detects missing/modified/stale artifacts. OmniIntel should adapt this to durable DB-backed job records.
4. Treat every generated page as an untrusted-content boundary. Its viewer sanitizer allowlists/re-serializes HTML, restricts media URLs to relative paths, safely embeds JSON and applies restrictive CSP. Apply equivalent defenses to transcripts, OCR, notes and model output.
5. Separate study output from evidence. take-notes and interactive-deep-notes offer strong pedagogy: explain rather than compress, organize by prerequisites, test recall, then apply. Their agent-generated pages do not replace OmniIntel's versioned evidence and study database.
6. Bound concurrency and preserve checkpoints. Pranav322 uses character chunks and concurrent map calls; useful pattern, but unconstrained fan-out is unsuitable for mobile and rate-limited providers. OmniIntel keeps bounded concurrency and durable checkpoints.
7. Treat transcription engines as replaceable subsystems. Vibe and StudyMitra show model/backend choice, local ASR, diarization, multilingual support and quality metrics. They are desktop/server or Python-heavy projects, not Android integration candidates by default.
8. Frame selection is not visual understanding. satya122id0889 demonstrates OCR embedding and semantic slide-change selection; Charlo-O uses LLM-chosen timestamps plus blur heuristics. These are candidate signals only. Validate frame/time, preserve original assets and selection rationale, and do not treat generated descriptions as source-authored facts.
9. Do not confuse an API demo with offline-first. LectureFlow, Vicky-Vrishni, SujalJaveri, Sairaj, AdritPal08, RJohnPaul, Saket and VidNotes depend on hosted transcription or generation. They can inspire UI/prompts but do not meet OmniIntel's local-first core requirement.
10. License is a hard gate. MIT sources are potentially reusable subject to attribution/dependency review. GPL/AGPL sources need explicit compatibility decisions. Missing, claimed-only or NOASSERTION licenses are not approved for code reuse.

### GitHub topic indexes supplied with this batch

- https://github.com/topics/video-transcription — 225 public repositories at review time; broad transcription, diarization and media-processing index.
- https://github.com/topics/video-notes — 43 repositories at review time; notable additional leads: wansui976/CoursePilot, like-attract/video-to-note, cdy1206/video-study-pipeline, lucky-Luor/bilibili-douyin-notes and m1429155411-bot/framenote.
- https://github.com/topics/audiototext — 20 repositories at review time; local Whisper, lecture and podcast transcription leads.
- https://github.com/topics/video-learning — 55 repositories at review time; notable additional leads: wansui976/CoursePilot, hurry060215-tech/learnnote-assistant, Elviszhuoyu/VidSage-Releases and rohansachinpatil/learnquest.

Topic pages were scanned for relevant candidates; hundreds of unrelated tagged projects were not individually audited. The additional leads are queued for a separate focused source/license review, not treated as vetted.

### Implementation decisions (no dependency adoption yet)

- Keep canonical typed evidence locators and add page/element/frame references with source-boundary and review gates.
- Adapt the staged plan-first workflow and provenance audit to durable DB-backed checkpoints.
- Keep local ASR, hosted ASR and hosted LLM providers explicit, consent-gated and separately benchmarked.
- Build a synchronized viewer as a consumer of canonical evidence and learning artifacts, not as the database of record.
- Add evidence-coverage and output-quality audits; a quotation, chapter marker or page link alone does not prove semantic support.
- Keep all research leads separate from approved third-party dependencies. No third-party code was copied into OmniIntel during this research pass.

## Highest-priority topic discoveries: deeper review

### CoursePilot — https://github.com/wansui976/CoursePilot

**License signal:** MIT. **Platform:** Tauri/Rust + TypeScript; Android and iOS build configurations and workflows are present.

This was the strongest newly discovered competitor/reference in the video-notes topic scan. Its current source tree includes an Android Gradle project, 44 SQLite migrations, native mobile service, ASR/OCR pipelines, RAG, concepts, FSRS study scheduling, sync, backup, export and tests.

Directly inspected: Android build workflow and manifest; Tauri Android config and Kotlin foreground KeepAliveService; SQLite migration/DB setup and processing job lifecycle; mobile model catalog and sherpa-onnx ASR; local PaddleOCR model management/inference; transcript chunking, backups and atomic replacement; transcript/OCR RAG citations; content+parameter-hash ASR chunk cache; AI artifact source fingerprints; Anki export and sync outbox; FSRS scheduling implementation.

Why it matters:
1. Demonstrates an offline-capable video-learning app targeting Android/iOS with native media processing and on-device ASR/OCR. This is a closer mobile architecture reference than desktop-only transcription tools.
2. Separates caption/ASR source records, slide OCR, generated AI artifacts and user study records. Migration 0026 fingerprints the exact transcript/OCR input used for each AI artifact and marks artifacts stale rather than silently regenerating or presenting outdated notes as current.
3. Protects expensive ASR work with a content+parameters hash cache, including submitted-but-pending cloud jobs, so interruption does not force duplicate paid requests.
4. Stores transcript backups and replaces transcript segments transactionally, refusing to replace a transcript with zero segments.
5. RAG searches both transcript and slide OCR; citations preserve time ranges or slide page/image references.
6. Includes a mobile foreground service, wake lock, notification progress and Android-specific model choice. Source comments document a real process-memory kill on a 4GB iPad and explain why mobile models differ from desktop models.
7. Its local ASR benchmark is project-reported on a small set of manually transcribed Mandarin lecture samples, not an independent benchmark. Do not generalize those numbers to OmniIntel's corpus or the user's device.
8. Not purely offline in every mode: Android manifest includes INTERNET; the product supports user-configured remote LLM/ASR and optional sync/download workflows. Local transcription/OCR can run offline after model setup.
9. Job rows model stage lifecycle/progress, but should not be assumed equivalent to OmniIntel's richer checkpoint/version/recovery model without further auditing.
10. Current Tauri/Rust/TypeScript stack is a valuable architecture study, not a reason to replace OmniIntel's chosen Kotlin/Compose Android and Python reference-engine approach.

Disposition: highest-priority competitive benchmark and design reference. Do not copy wholesale. Compare native mobile pipeline, study system, migration history, model package licensing, third-party notices, sync protocol and actual release behavior. MIT is only the top-level repository license; model and dependency licenses remain separate.

### LearnNote — https://github.com/hurry060215-tech/learnnote-assistant

**License signal:** Apache-2.0. **Platform:** local-first desktop/web service with browser extension; not a native Android app.

Directly inspected: current README and security policy; localhost-only service boundary; optional browser extension data capture and user-confirmed send flow; per-task model-data consent and page-context fingerprinting; claim/evidence projection; revision-bound document citations; QA retrieval; five-minute ASR chunk checkpoints; durable SQLite queue journal; cancellation state transitions; resource monitor; and the note completion pipeline.

Why it matters:
1. Treats local service boundaries, external model transfer and browser-captured page data as explicit trust decisions.
2. Binds claim spans to a specific note revision and evidence revision; stale or foreign-task citations are rejected.
3. Distinguishes direct text matches from located candidate sources, inference and unsupported claims, with visible review markers in the note.
4. Checkpoints long ASR in five-minute windows using audio-byte and model-identity signatures; malformed or stale chunks are not reused.
5. Applies an evidence reliability gate before summary generation and quarantines failed/low-quality drafts rather than publishing them.
6. Queue journal reads SQLite in read-only mode, supports cancellation without a live worker callback, and uses a transactional state transition to race safely with worker claims.
7. Measures local CPU/RSS/disk resources without inspecting task contents.
8. Its security policy candidly notes that localhost is not an authentication boundary against same-user software, short-lived browser cookies may remain after forced termination, and remote model providers receive content required for the selected operation.
9. Browser extension access to page cookies/subtitles is opt-in and must not be confused with permission to download or reproduce platform media.

Disposition: high-priority architecture reference for claim verification, consent, revision-bound citations, local queue recovery and resource-aware execution. Apache-2.0 is compatible in principle subject to notices, dependency review and attribution; no code was copied.

### Additional topic discoveries queued for a separate source/license review

- https://github.com/cdy1206/video-study-pipeline
- https://github.com/like-attract/video-to-note
- https://github.com/lucky-Luor/bilibili-douyin-notes
- https://github.com/m1429155411-bot/framenote
- https://github.com/Elviszhuoyu/VidSage-Releases
- https://github.com/rohansachinpatil/learnquest

These appeared relevant in the supplied GitHub topic scans. They are leads only until source, license, platform support, maintenance and security are separately verified.

