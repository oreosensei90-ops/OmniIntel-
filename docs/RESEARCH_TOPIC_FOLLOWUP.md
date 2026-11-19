# Video-learning topic follow-up — 2026-11-19

This follow-up records source-level review of the strongest additional candidates surfaced by the user's video-notes, video-learning, video-transcription and audiototext topic indexes. It supplements RESEARCH_REGISTER.md; it does not approve third-party code for copying.

## Executive result

**CoursePilot is the closest inspected end-to-end product reference.** It combines native mobile/desktop clients, local ASR, slide extraction/OCR, transcript-and-slide retrieval, course-level knowledge, quizzes, Feynman checks, and FSRS review. Its MIT repository is actively maintained and its latest inspected GitHub Actions runs were successful. It is still a reference, not a drop-in base: it is a large Tauri/Rust application, its own LLM features normally require a configured provider or self-hosted Ollama, its retrieval evaluation set is small, and its local-ASR benchmark is based on only three manually transcribed Chinese lecture clips.

**Course Navigator is the strongest inspected reference for operational reliability around source and transcript workflows.** Its MIT Python/React desktop app has a bounded per-course scheduler, cancellable network requests, temporary-artifact leases, source identity/invalidation handling, subtitle correction and extensive race/regression tests. It does not implement the visual slide/knowledge pipeline that OmniIntel needs.

**Video Study Pipeline is the strongest output-quality and visual-editorial specification.** It is an MIT agent skill, not a standalone application. Its source manifests, asset manifests, explicit visual intent, renderer-specific briefs, source-return links and semantic quality gates are useful design references.

## Source-level findings

### 1. CoursePilot — highest-priority product reference
Repository: https://github.com/wansui976/CoursePilot

- **License/activity:** GitHub reports MIT; repository activity through 2026-11-17. Latest inspected CI runs on v0.4.1 completed successfully. The code and dependencies still require separate license review before any component reuse.
- **Architecture:** Tauri 2 / Rust application with SQLite (sqlx), native mobile/desktop builds, local media files, background processing stages, and model/provider adapters. The code is substantially more than a prompt wrapper.
- **Pipeline:** persisted stage rows cover crop detection, audio, ASR, slide extraction, slide OCR, chapters, summary, notes, quiz and mind map. Slide extraction runs concurrently with audio/ASR, then AI follow-ups wait for slide work to finish so board text is available. Completed ASR can be reused on retry; interrupted running stages are marked failed at startup and can be retried. This is useful stage-level recovery, not a complete content-addressed checkpoint DAG.
- **Local ASR:** SenseVoice and Qwen3-ASR variants use sherpa-onnx on mobile; desktop can use GGUF/llama.cpp. Model catalogue includes download sizes, checksums during download, VAD assets and platform-aware memory eligibility. Android checks MemAvailable; iOS uses process-available-memory APIs. The model selector falls back to a smaller eligible model rather than assuming installed RAM equals available inference memory.
- **Visual pipeline:** FFmpeg samples reduced luma frames, detects slide changes, stores slide intervals and images, then OCRs pages. A separate visual-signature matcher can map a screenshot back to extracted slides. It explicitly handles crop/letterbox geometry and keeps page image, page number and video time together.
- **Retrieval:** RAG searches transcript segments and OCR slide text with weighted lexical terms, returns clickable timestamp citations and slide-page/image citations, and uses recent user turns only when the current follow-up cannot retrieve evidence. This is a practical baseline before embeddings. The code explicitly labels a no-course-hit fallback as general model knowledge and does not fabricate citations. OmniIntel should keep that answer in a visibly separate provenance channel, never blend it into source-grounded claims.
- **Evaluation:** the checked-in retrieval evaluation contains positive and negative queries, including slide-only terms and questions that must not retrieve anything. It openly records known misses. This is a good pattern, but the corpus is a short synthetic four-minute lecture with a small number of cases; it is not a broad retrieval benchmark. The README's ASR comparison uses three manually transcribed Chinese lecture recordings, so its reported WER values are local evidence, not a universal model ranking.
- **Learning:** quiz styles include recall, transfer/application, error correction and contrast. Feynman checks compare a learner's explanation against course excerpts, distinguish covered/missed/wrong points and attach source times. FSRS-4.5 scheduling is implemented with explicit formulas and tests; weak concepts are derived from review outcomes rather than a decorative single learning score.
- **Data durability:** SQLite uses foreign keys and a five-second busy timeout. The project deliberately uses a rollback journal rather than WAL because it documents a cross-connection visibility problem in its iOS sandbox. Backup uses VACUUM INTO, integrity/schema checks, temp-file validation and staged restore before restart. This is a strong backup/restore reference; journal choice must be platform-tested rather than copied blindly.
- **Risks/limitations:** LLM generation, translation and some OCR/ASR alternatives are provider-dependent; local ASR/OCR do not imply every generated learning artifact is fully offline. RAG is primarily lexical rather than a proven semantic vector system. Source alignment is useful but its small evaluation set cannot prove broad correctness. Bilibili/YouTube download and comments/danmaku features require careful rights/terms boundaries.
- **OmniIntel decision:** adopt the design lessons for stage scheduling, mobile memory gates, source-visible retrieval, slide evidence, course aggregation, FSRS, Feynman review and transactional backups. Do not change OmniIntel's target Android stack or data model merely to match Tauri. No code copied.

### 2. Course Navigator — queue, cancellation and source-race reference
Repository: https://github.com/Liu-Bot24/course-navigator

- **License/activity:** MIT; recent 2026 activity. The repository contains a sizeable backend test suite. No GitHub Actions runs were returned by the inspected Actions endpoint, so do not infer CI health from test files alone.
- **Architecture:** local desktop workspace with Python backend and React frontend; supports URL/local video, subtitle acquisition, manual subtitle upload/editing, local/online ASR, translation and configurable LLM profiles.
- **Reliability patterns inspected:** KeyedExecutor bounds total pending work and worker count, serializes work per course while allowing different courses to proceed, and rotates queues for fairness. SourceOperations invalidates in-flight metadata work when a source is deleted/replaced, preventing stale responses from resurrecting old course entries. Temporary extraction directories use leases so cleanup does not delete files still used by an active operation.
- **Network/cancellation:** LLM, ASR and search calls use cancellable HTTP request helpers; tests exercise cancellation while waiting for headers and response bodies and verify another request remains usable. URL/profile endpoint rules are tested to avoid silently changing the actual service endpoint or misrouting saved API keys.
- **Subtitle handling:** normalizes rolling YouTube captions without deleting genuinely repeated speech; source identity is kept stable across URL aliases; manual corrections and translations are distinct artifacts.
- **Limitations:** no comparable frame/slide extraction or source-image evidence pipeline was found in the inspected architecture. It is a transcript-first course workspace, not OmniIntel's full multimodal knowledge engine. Configurable cloud services mean local-first storage is not equivalent to local-only inference.
- **OmniIntel decision:** adapt bounded fair scheduling, per-source identity, cancellation, temporary-artifact leases and race-condition test scenarios. Keep visual evidence and knowledge/textbook publication in OmniIntel's separate pipeline. No code copied.

### 3. Video Study Pipeline — quality and renderer specification
Repository: https://github.com/cdy1206/video-study-pipeline

- **License/type:** MIT agent skill, not a packaged mobile/web product. Its workflow depends on a local-capable coding agent and external tools such as yt-dlp, FFmpeg, OCR/VLM/ASR and renderer dependencies.
- **Strongest ideas:** source acquisition creates a unified source package and source manifest; evidence assets live in a separate asset manifest; knowledge reconstruction is separate from visual-expression planning; every visual has an intent (evidence, structure or comparison); HTML/PDF/presentation receive distinct renderer briefs rather than blind format conversions.
- **Quality controls:** checks transcript coverage before final writing, preserves timestamp/page anchors, demands human semantic review, rejects generic prose padding, verifies asset placement and skip reasons, and calls for rendered-page/contact-sheet inspection. It explicitly says structural checkers do not prove teaching quality.
- **Reader interaction:** original video clips, chapter/transcript timeline, search, bookmarks, reading progress and local personal notes are integrated into the reading experience.
- **Limitations:** its detailed Chinese-first editorial conventions are one workflow's house style, not a universal textbook standard. Many checks are procedural or human/agent-driven rather than an independently measured automated semantic evaluator. It is not a durable cross-device database or job engine.
- **OmniIntel decision:** adapt the source/asset manifest relationship, visual-intent labels, renderer-specific enrichment, asset-consumption audit and explicit visual inspection gates. Keep OmniIntel's canonical structured textbook blocks and language-neutral contracts. No code copied.

### 4. Scribly — in-player annotation reference
Repository: https://github.com/onkar69483/Scribly

- **License:** MIT.
- **Inspected scope:** Chrome Manifest V3 extension, timestamped notes, drawing/highlighting/shapes, screenshot capture, dashboard, tags and import/export. README identifies localStorage as its persistence mechanism.
- **Limitations:** no source acquisition, ASR, OCR, evidence graph, or AI textbook pipeline. Browser-local storage is not sufficient as OmniIntel's durable annotation/sync database.
- **OmniIntel decision:** useful interaction reference for timestamped annotations and screenshot notes only. Store annotations against canonical source/evidence IDs and preserve them across textbook regeneration.

### 5. LearnQuest — playlist study UX reference
Repository: https://github.com/rohansachinpatil/learnquest

- **License:** MIT; Manifest V3 extension with only the storage permission in its manifest.
- **Inspected scope:** YouTube chapters, user-imported SRT/VTT/timestamp lines, topic timeline, course map, playlist progress, daily goals and local study streaks. The README explicitly says it does not download transcripts.
- **Limitations:** not a transcription or knowledge extraction engine; progress is browser-local and its XP/goal mechanics are motivational UX, not mastery evidence.
- **OmniIntel decision:** use course navigation and timeline UX as references; keep real learning progress based on study attempts, recall, application and review history.

## Topic-index scope and interpretation

The four supplied indexes are broad discovery pages, not four bounded codebases. The review used their visible candidate sets and searched for projects with actual lecture/video-learning relevance. It did not individually audit every repository tagged by GitHub (the video-transcription index alone showed hundreds of projects). Topic membership and stars are discovery signals only.

Highest-priority candidates from this batch are CoursePilot, lecture-to-notes, Vibe, Course Navigator, ytscribe and Video Study Pipeline. Scribly and LearnQuest are narrower UX references. Other repositories in the original user list are catalogued in RESEARCH_REGISTER.md with their specific limitations and licensing signals.

## Engineering consequences for OmniIntel

1. Build a media-source adapter boundary: authorized captions first; local audio extraction and replaceable local ASR second; keep caption-vs-ASR provenance explicit.
2. Add video frame/slide evidence as a first-class typed locator, never fake timestamps or page numbers. Store frame time, source asset, image hash, extraction method and review state.
3. Implement transcript-to-slide grounding as a measured relationship, not nearest-timestamp attachment. Keep uncertain matches pending review.
4. Use bounded job scheduling, per-source identity locks, cancellation and leased temporary artifacts. Persist stage input hashes and checkpoint state; do not adopt only an in-memory queue.
5. Evaluate retrieval with both positive and negative cases, including slide-only facts and explicit not-covered questions. Report recall and false-positive rates; a citation list alone is not proof of relevance.
6. Keep model/provider provenance visible. Local ASR/OCR, self-hosted LLM, and hosted API are separate routes with explicit data-transfer consent.
7. Add course-level knowledge and learning tools only after source coverage and evidence links are reliable. FSRS, Feynman and application questions should reference the source-backed knowledge layer.
8. Benchmark Android models against free RAM, peak native memory, thermal throttling, battery and transcription quality. Never infer model suitability from installed RAM or model-file size alone.
9. Add transactional backup/restore and verify restore in tests; include external asset files and manifests, not just the SQLite database.
10. Preserve the MIT root project license; do not import code from GPL/AGPL or repositories with missing/ambiguous licenses without a deliberate legal decision.
