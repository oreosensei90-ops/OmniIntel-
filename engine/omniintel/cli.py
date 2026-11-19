"""Minimal CLI for database initialization and health inspection."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .store import OmniIntelStore
from .textbook_audit import TextbookPublicationAuditor
from .pdf_export import TextbookPDFExporter
from .docx_export import TextbookDOCXExporter
from .html_export import TextbookHTMLExporter
from .markdown_export import TextbookMarkdownExporter
from .captions import import_caption_file
from .local_files import import_local_file


def main() -> None:
    parser = argparse.ArgumentParser(prog="omniintel")
    sub = parser.add_subparsers(dest="command", required=True)
    collection_create = sub.add_parser("collection-create", help="Create a course or multi-source collection")
    collection_create.add_argument("database", type=Path)
    collection_create.add_argument("title")
    collection_create.add_argument("--type", default="COURSE", choices=["COURSE","PLAYLIST","PROJECT","RESEARCH_SET"])
    collection_create.add_argument("--description", default="")
    collection_add = sub.add_parser("collection-add-source", help="Add an existing source to a course/collection")
    collection_add.add_argument("database", type=Path)
    collection_add.add_argument("collection_id")
    collection_add.add_argument("source_id")
    collection_add.add_argument("--role", default="LEARNING_SOURCE", choices=["LEARNING_SOURCE","SLIDE_DECK","CAPTIONS","REFERENCE","NOTES"])
    collection_add.add_argument("--ordinal", type=int, default=None)
    collection_show = sub.add_parser("collection-show", help="Show a collection and its ordered source members")
    collection_show.add_argument("database", type=Path)
    collection_show.add_argument("collection_id")
    course_book_create = sub.add_parser("course-book-create", help="Create a collection-level textbook")
    course_book_create.add_argument("database", type=Path)
    course_book_create.add_argument("collection_id")
    course_book_create.add_argument("title")
    course_book_version = sub.add_parser("course-book-version", help="Create a course textbook version")
    course_book_version.add_argument("database", type=Path)
    course_book_version.add_argument("textbook_id")
    course_book_version.add_argument("title")
    course_book_version.add_argument("--mode", default="HYBRID", choices=["SOURCE_ORDER","CONCEPTUAL","HYBRID"])
    course_book_chapter = sub.add_parser("course-book-chapter", help="Add a source-attributed course chapter")
    course_book_chapter.add_argument("database", type=Path)
    course_book_chapter.add_argument("version_id")
    course_book_chapter.add_argument("title")
    course_book_chapter.add_argument("ordinal", type=int)
    course_book_chapter.add_argument("--source-id", default=None)
    course_book_chapter.add_argument("--summary", default="")
    course_book_block = sub.add_parser("course-book-block", help="Add a structured course textbook block")
    course_book_block.add_argument("database", type=Path)
    course_book_block.add_argument("chapter_id")
    course_book_block.add_argument("block_type")
    course_book_block.add_argument("content_json")
    course_book_block.add_argument("--provenance", default="EXPLANATION", choices=["SOURCE","EXPLANATION","DERIVED","EXTERNAL","UNCERTAIN"])
    course_book_block.add_argument("--review", default="DRAFT", choices=["DRAFT","NEEDS_REVIEW","ACCEPTED","REJECTED"])
    course_book_block.add_argument("--ordinal", type=int, default=0)
    course_book_link = sub.add_parser("course-book-link-evidence", help="Link a block to a source evidence reference")
    course_book_link.add_argument("database", type=Path)
    course_book_link.add_argument("block_id")
    course_book_link.add_argument("evidence_ref_id")
    course_book_link.add_argument("--relation", default="SUPPORTS", choices=["SUPPORTS","ILLUSTRATES","CONTEXTUALIZES","CONTRADICTS"])
    course_book_review = sub.add_parser("course-book-review-evidence", help="Review a course textbook evidence link")
    course_book_review.add_argument("database", type=Path)
    course_book_review.add_argument("link_id")
    course_book_review.add_argument("state", choices=["ACCEPTED","REJECTED","NEEDS_REVIEW"])
    course_book_audit = sub.add_parser("course-book-audit", help="Audit a course textbook version for publication")
    course_book_audit.add_argument("database", type=Path)
    course_book_audit.add_argument("version_id")
    plan_inputs = sub.add_parser("plan-inputs", help="Create a read-only plan for selected local learning sources")
    plan_inputs.add_argument("paths", nargs="+", type=Path, help="Files or directories selected by the user")
    plan_inputs.add_argument("--recursive", action="store_true", help="Include files in selected directories recursively")
    plan_inputs.add_argument("--language", default=None, help="Confirmed spoken language(s), e.g. en or en,hi")
    init = sub.add_parser("init", help="Initialize or migrate a local OmniIntel database")
    init.add_argument("database", type=Path)
    check = sub.add_parser("check", help="Run SQLite integrity checks")
    check.add_argument("database", type=Path)
    audit = sub.add_parser("audit-textbook", help="Check whether a textbook version passes publication gates")
    audit.add_argument("database", type=Path)
    audit.add_argument("version_id")
    export_pdf = sub.add_parser("export-pdf", help="Export a publication-ready textbook version to PDF")
    export_pdf.add_argument("database", type=Path)
    export_pdf.add_argument("version_id")
    export_pdf.add_argument("output", type=Path)
    export_pdf.add_argument("--font", type=Path, default=None, help="Unicode TTF font, required for scripts not covered by built-in fonts")
    export_pdf.add_argument("--asset-dir", type=Path, default=None, help="Asset store directory required when textbook blocks contain linked images")
    export_docx = sub.add_parser("export-docx", help="Export a publication-ready textbook version to editable DOCX")
    export_docx.add_argument("database", type=Path)
    export_docx.add_argument("version_id")
    export_docx.add_argument("output", type=Path)
    export_docx.add_argument("--asset-dir", type=Path, default=None)
    export_html = sub.add_parser("export-html", help="Export a publication-ready textbook to self-contained HTML")
    export_html.add_argument("database", type=Path)
    export_html.add_argument("version_id")
    export_html.add_argument("output", type=Path)
    export_html.add_argument("--asset-dir", type=Path, default=None)
    import_captions = sub.add_parser("import-captions", help="Import a local SRT or WebVTT caption file")
    import_captions.add_argument("database", type=Path)
    import_captions.add_argument("caption_file", type=Path)
    import_captions.add_argument("--title", default=None)
    import_captions.add_argument("--source-uri", default=None)
    import_captions.add_argument("--language", default=None)
    import_captions.add_argument("--duration-ms", type=int, default=None)
    import_file = sub.add_parser("import-file", help="Register a user-selected local source file and preserve its original bytes")
    import_file.add_argument("database", type=Path)
    import_file.add_argument("asset_dir", type=Path)
    import_file.add_argument("file", type=Path)
    import_file.add_argument("--title", default=None)
    import_file.add_argument("--max-bytes", type=int, default=250 * 1024 * 1024)
    transcribe_wav = sub.add_parser("transcribe-wav", help="Transcribe a registered local PCM WAV with resumable local ASR")
    transcribe_wav.add_argument("database", type=Path)
    transcribe_wav.add_argument("asset_dir", type=Path)
    transcribe_wav.add_argument("source_id")
    transcribe_wav.add_argument("asset_id")
    transcribe_wav.add_argument("--model", required=True, help="Local CTranslate2 model directory, or model name with --allow-model-download")
    transcribe_wav.add_argument("--allow-model-download", action="store_true", help="Explicitly permit faster-whisper to download the selected model")
    transcribe_wav.add_argument("--device", default="cpu")
    transcribe_wav.add_argument("--compute-type", default="int8")
    transcribe_wav.add_argument("--threads", type=int, default=4)
    transcribe_wav.add_argument("--beam-size", type=int, default=5)
    transcribe_wav.add_argument("--vad", action="store_true", help="Enable VAD filtering; may omit quiet lecture speech")
    transcribe_wav.add_argument("--language", default=None)
    transcribe_wav.add_argument("--chunk-seconds", type=int, default=120)
    transcribe_wav.add_argument("--time-offset-ms", type=int, default=None)
    extract_frames = sub.add_parser("extract-frames", help="Extract bounded timestamped JPEG frames from a local video asset")
    extract_frames.add_argument("database", type=Path)
    extract_frames.add_argument("asset_dir", type=Path)
    extract_frames.add_argument("asset_id")
    extract_frames.add_argument("--video-stream-index", type=int, default=None)
    extract_frames.add_argument("--min-interval-ms", type=int, default=5000)
    extract_frames.add_argument("--max-frames", type=int, default=500)
    extract_frames.add_argument("--max-frame-bytes", type=int, default=2 * 1024 * 1024)
    extract_frames.add_argument("--max-total-bytes", type=int, default=256 * 1024 * 1024)
    extract_frames.add_argument("--max-frame-pixels", type=int, default=20000000)
    extract_frames.add_argument("--max-total-pixels", type=int, default=100000000)
    extract_frames.add_argument("--max-width", type=int, default=1280)
    extract_frames.add_argument("--max-height", type=int, default=720)
    extract_frames.add_argument("--timeout", type=float, default=600.0)
    describe_video = sub.add_parser("describe-video-frames", help="Describe frames with an explicitly selected local Ollama vision model")
    describe_video.add_argument("database", type=Path)
    describe_video.add_argument("asset_dir", type=Path)
    describe_video.add_argument("source_id")
    describe_video.add_argument("--model", required=True)
    describe_video.add_argument("--max-frames", type=int, default=100)
    semantic_video = sub.add_parser("align-video-semantics", help="Score visual-frame and transcript relevance with local Ollama")
    semantic_video.add_argument("database", type=Path)
    semantic_video.add_argument("asset_dir", type=Path)
    semantic_video.add_argument("source_id")
    semantic_video.add_argument("--model", required=True)
    semantic_video.add_argument("--max-pairs", type=int, default=500)
    verify_visual_claim_cmd = sub.add_parser("verify-visual-claim", help="Run a local visual/transcript claim check")
    verify_visual_claim_cmd.add_argument("database", type=Path)
    verify_visual_claim_cmd.add_argument("source_id")
    verify_visual_claim_cmd.add_argument("claim_id")
    verify_visual_claim_cmd.add_argument("visual_event_id")
    verify_visual_claim_cmd.add_argument("description_id")
    verify_visual_claim_cmd.add_argument("--transcript-segment-id", default=None)
    verify_visual_claim_cmd.add_argument("--model", required=True)
    detect_scenes = sub.add_parser("detect-scenes", help="Detect reviewable scene-change candidates from sampled frames")
    detect_scenes.add_argument("database", type=Path)
    detect_scenes.add_argument("asset_dir", type=Path)
    detect_scenes.add_argument("source_id")
    detect_scenes.add_argument("--threshold", type=float, default=0.28)
    detect_scenes.add_argument("--max-comparisons", type=int, default=2000)
    ocr_video = sub.add_parser("ocr-video-frames", help="OCR sampled video frames using local Tesseract")
    ocr_video.add_argument("database", type=Path)
    ocr_video.add_argument("asset_dir", type=Path)
    ocr_video.add_argument("source_id")
    ocr_video.add_argument("--max-frames", type=int, default=200)
    ocr_video.add_argument("--timeout", type=int, default=30)
    review_visual_record_cmd = sub.add_parser("review-visual-record", help="Review a scene, OCR, description, semantic or verification record")
    review_visual_record_cmd.add_argument("database", type=Path)
    review_visual_record_cmd.add_argument("table", choices=["visual_transcript_alignments","visual_scene_candidates","visual_ocr_results","visual_descriptions","visual_semantic_alignments","visual_claim_verifications"])
    review_visual_record_cmd.add_argument("record_id")
    review_visual_record_cmd.add_argument("state", choices=["ACCEPTED","REJECTED","NEEDS_REVIEW"])
    build_visual_timeline = sub.add_parser("build-visual-timeline", help="Create reviewable visual-frame and transcript alignment candidates")
    build_visual_timeline.add_argument("database", type=Path)
    build_visual_timeline.add_argument("extraction_id")
    build_visual_timeline.add_argument("--tolerance-ms", type=int, default=10000)
    visual_timeline = sub.add_parser("visual-timeline", help="List visual frame events and transcript alignment candidates")
    visual_timeline.add_argument("database", type=Path)
    visual_timeline.add_argument("source_id")
    review_visual_event = sub.add_parser("review-visual-event", help="Review a sampled visual event")
    review_visual_event.add_argument("database", type=Path)
    review_visual_event.add_argument("event_id")
    review_visual_event.add_argument("state", choices=["ACCEPTED","REJECTED","NEEDS_REVIEW"])
    extract_audio = sub.add_parser("extract-audio", help="Extract a selected local audio stream to resumable-transcription WAV")
    extract_audio.add_argument("database", type=Path)
    extract_audio.add_argument("asset_dir", type=Path)
    extract_audio.add_argument("asset_id")
    extract_audio.add_argument("--stream-index", type=int, default=None)
    extract_audio.add_argument("--timeout", type=float, default=600.0)
    extract_audio.add_argument("--max-output-bytes", type=int, default=512 * 1024 * 1024)
    probe_media = sub.add_parser("probe-media", help="Inspect a registered local audio/video asset with ffprobe")
    probe_media.add_argument("database", type=Path)
    probe_media.add_argument("asset_dir", type=Path)
    probe_media.add_argument("asset_id")
    probe_media.add_argument("--timeout", type=float, default=30.0)
    probe_media.add_argument("--max-streams", type=int, default=32)
    probe_media.add_argument("--max-output-bytes", type=int, default=1000000)
    extract_pdf_cmd = sub.add_parser("extract-pdf", help="Extract bounded page text from an ingested local PDF asset")
    extract_pdf_cmd.add_argument("database", type=Path)
    extract_pdf_cmd.add_argument("asset_dir", type=Path)
    extract_pdf_cmd.add_argument("asset_id")
    extract_pdf_cmd.add_argument("--max-pages", type=int, default=500)
    extract_pdf_cmd.add_argument("--max-chars-per-page", type=int, default=100_000)
    extract_pdf_cmd.add_argument("--max-total-chars", type=int, default=5_000_000)
    review_knowledge_unit = sub.add_parser("review-knowledge-unit", help="Review a source-linked knowledge candidate")
    review_knowledge_unit.add_argument("database", type=Path)
    review_knowledge_unit.add_argument("unit_id")
    review_knowledge_unit.add_argument("status", choices=["DRAFT","VALIDATED","NEEDS_REVIEW","REJECTED"])
    review_knowledge_unit.add_argument("--provenance", choices=["EXPLANATION","DERIVED","UNCERTAIN"], required=True)
    build_document_knowledge = sub.add_parser("build-document-knowledge", help="Create draft knowledge units from accepted document elements")
    build_document_knowledge.add_argument("database", type=Path)
    build_document_knowledge.add_argument("source_id")
    build_document_knowledge.add_argument("--include-unreviewed", action="store_true")
    build_document_knowledge.add_argument("--max-total-chars", type=int, default=5000000)
    ocr_pdf_cmd = sub.add_parser("ocr-pdf", help="OCR image-only pages in a registered local PDF")
    ocr_pdf_cmd.add_argument("database", type=Path)
    ocr_pdf_cmd.add_argument("asset_dir", type=Path)
    ocr_pdf_cmd.add_argument("asset_id")
    ocr_pdf_cmd.add_argument("--dpi", type=int, default=144)
    ocr_pdf_cmd.add_argument("--max-pages", type=int, default=200)
    ocr_pdf_cmd.add_argument("--force", action="store_true")
    review_ocr = sub.add_parser("review-ocr-page", help="Review one OCR page before its text can support claims")
    review_ocr.add_argument("database", type=Path)
    review_ocr.add_argument("page_id")
    review_ocr.add_argument("state", choices=["ACCEPTED","REJECTED","NEEDS_REVIEW"])
    structure_pdf = sub.add_parser("structure-pdf", help="Extract positioned text, tables, equations and figure regions")
    structure_pdf.add_argument("database", type=Path)
    structure_pdf.add_argument("asset_dir", type=Path)
    structure_pdf.add_argument("asset_id")
    structure_pdf.add_argument("--max-pages", type=int, default=500)
    structure_pdf.add_argument("--max-elements", type=int, default=20000)
    structure_pdf.add_argument("--max-total-chars", type=int, default=5000000)
    structure_pdf.add_argument("--max-figure-pixels", type=int, default=20000000)
    structure_pdf.add_argument("--max-total-figure-pixels", type=int, default=100000000)
    structure_pdf.add_argument("--no-figure-assets", action="store_true")
    review_element = sub.add_parser("review-document-element", help="Review one extracted document element")
    review_element.add_argument("database", type=Path)
    review_element.add_argument("element_id")
    review_element.add_argument("state", choices=["ACCEPTED","REJECTED","NEEDS_REVIEW"])
    review_element.add_argument("--rationale", default=None)
    review_element.add_argument("--provenance", choices=["SOURCE","DERIVED","UNCERTAIN"], default=None)
    list_elements = sub.add_parser("list-document-elements", help="List extracted page-level document elements")
    list_elements.add_argument("database", type=Path)
    list_elements.add_argument("--page-id", default=None)
    search_elements = sub.add_parser("search-document-elements", help="Search extracted document structure")
    search_elements.add_argument("database", type=Path)
    search_elements.add_argument("query")
    search_elements.add_argument("--limit", type=int, default=50)
    search_evidence = sub.add_parser("search-evidence", help="Search unified transcript and document-page evidence")
    search_evidence.add_argument("database", type=Path)
    search_evidence.add_argument("query")
    search_evidence.add_argument("--limit", type=int, default=50)
    resolve_evidence = sub.add_parser("resolve-evidence", help="Resolve a unified evidence citation ID")
    resolve_evidence.add_argument("database", type=Path)
    resolve_evidence.add_argument("reference_id")
    search_pages = sub.add_parser("search-pages", help="Search extracted local PDF page text")
    search_pages.add_argument("database", type=Path)
    search_pages.add_argument("query")
    search_pages.add_argument("--limit", type=int, default=20)
    compose_document = sub.add_parser("compose-document-textbook", help="Compose a draft textbook from accepted document topics and claims")
    compose_document.add_argument("database", type=Path)
    compose_document.add_argument("source_id")
    compose_document.add_argument("title")
    compose_document.add_argument("--version-title", default="Draft 1")
    document_outline = sub.add_parser("document-outline", help="Show the reviewed page-native topic outline for a document source")
    document_outline.add_argument("database", type=Path)
    document_outline.add_argument("source_id")
    export_markdown = sub.add_parser("export-markdown", help="Export a publication-ready textbook to portable Markdown")
    export_markdown.add_argument("database", type=Path)
    export_markdown.add_argument("version_id")
    export_markdown.add_argument("output", type=Path)
    export_markdown.add_argument("--asset-dir", type=Path, default=None)
    args = parser.parse_args()
    if args.command == "collection-create":
        from .collections import CollectionStore

        collection_id = CollectionStore(args.database).create(
            args.title,collection_type=args.type,description=args.description,
        )
        print(json.dumps({"collection_id":collection_id},indent=2))
    elif args.command == "collection-add-source":
        from .collections import CollectionStore

        ordinal = CollectionStore(args.database).add_source(
            args.collection_id,args.source_id,role=args.role,ordinal=args.ordinal,
        )
        print(json.dumps({"collection_id":args.collection_id,"source_id":args.source_id,"ordinal":ordinal},indent=2))
    elif args.command == "collection-show":
        from .collections import CollectionStore

        result = CollectionStore(args.database).get(args.collection_id)
        if result is None:
            raise SystemExit("Collection not found")
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command == "course-book-create":
        from .course_textbook import CourseTextbookStore

        book_id=CourseTextbookStore(args.database).create(args.collection_id,args.title)
        print(json.dumps({"textbook_id":book_id},indent=2))
    elif args.command == "course-book-version":
        from .course_textbook import CourseTextbookStore

        version_id=CourseTextbookStore(args.database).create_version(
            args.textbook_id,args.title,composition_mode=args.mode,
        )
        print(json.dumps({"version_id":version_id},indent=2))
    elif args.command == "course-book-chapter":
        from .course_textbook import CourseTextbookStore

        chapter_id=CourseTextbookStore(args.database).add_chapter(
            args.version_id,args.title,ordinal=args.ordinal,
            source_id=args.source_id,summary=args.summary,
        )
        print(json.dumps({"chapter_id":chapter_id},indent=2))
    elif args.command == "course-book-block":
        from .course_textbook import CourseTextbookStore

        content=json.loads(args.content_json)
        block_id=CourseTextbookStore(args.database).add_block(
            args.chapter_id,args.block_type,content,provenance=args.provenance,
            review_status=args.review,ordinal=args.ordinal,
        )
        print(json.dumps({"block_id":block_id},indent=2))
    elif args.command == "course-book-link-evidence":
        from .course_textbook import CourseTextbookStore

        link_id=CourseTextbookStore(args.database).link_evidence(
            args.block_id,args.evidence_ref_id,relation=args.relation,
        )
        print(json.dumps({"link_id":link_id,"review_state":"PENDING"},indent=2))
    elif args.command == "course-book-review-evidence":
        from .course_textbook import CourseTextbookStore

        state=CourseTextbookStore(args.database).review_evidence(args.link_id,args.state)
        print(json.dumps({"link_id":args.link_id,"review_state":state},indent=2))
    elif args.command == "course-book-audit":
        from .course_textbook import CourseTextbookStore

        report=CourseTextbookStore(args.database).audit(args.version_id)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        if not report["publishable"]:
            raise SystemExit(1)
    if args.command == "plan-inputs":
        from .input_plan import plan_local_inputs

        selected = []
        for item in args.paths:
            if item.is_symlink() and item.is_dir():
                raise SystemExit(f"Refusing to recursively scan a symbolic-link directory: {item}")
            if item.is_dir():
                iterator = item.rglob("*") if args.recursive else item.iterdir()
                selected.extend(path for path in iterator if path.is_file())
            else:
                selected.append(item)
        plan = plan_local_inputs(selected, language=args.language)
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        if not plan.to_dict()["ready_for_execution"]:
            raise SystemExit(2)
    if args.command == "init":
        OmniIntelStore(args.database)
        print(f"Initialized database: {args.database}")
    elif args.command == "check":
        with sqlite3.connect(args.database) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        print(f"integrity_check: {result}")
        print(f"foreign_key_violations: {len(fk)}")
        if result != "ok" or fk:
            raise SystemExit(1)
    elif args.command == "audit-textbook":
        report = TextbookPublicationAuditor(args.database).audit(args.version_id)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        if not report.ready:
            raise SystemExit(1)
    elif args.command == "import-captions":
        transcript = import_caption_file(
            args.caption_file, title=args.title, source_uri=args.source_uri,
            language=args.language, duration_ms=args.duration_ms,
        )
        result = OmniIntelStore(args.database).import_transcript(transcript)
        print(json.dumps({
            "source_id": result.source_id,
            "segments": len(result.segment_ids),
            "evidence_items": len(result.evidence_ids),
            "evidence_references": len(result.evidence_ref_ids),
            "duration_ms": transcript.duration_ms,
            "caption_format": transcript.metadata["caption_format"],
        }, ensure_ascii=False, indent=2))
    elif args.command == "import-file":
        result = import_local_file(
            args.database, args.asset_dir, args.file,
            title=args.title, max_bytes=args.max_bytes,
        )
        print(json.dumps({
            "source_id": result.source_id,
            "title": result.title,
            "modality": result.modality,
            "asset_id": result.asset.id,
            "sha256": result.asset.sha256,
            "media_type": result.asset.media_type,
            "byte_size": result.asset.byte_size,
            "rights_status": "UNVERIFIED",
        }, ensure_ascii=False, indent=2))
    elif args.command == "transcribe-wav":
        from .transcription import FasterWhisperAdapter, run_wav_transcription

        adapter = FasterWhisperAdapter(
            model_id=args.model,device=args.device,
            compute_type=args.compute_type,cpu_threads=args.threads,
            beam_size=args.beam_size,vad_filter=args.vad,
            allow_model_download=args.allow_model_download,
        )
        result = run_wav_transcription(
            args.database,args.asset_dir,args.source_id,args.asset_id,adapter,
            language=args.language,chunk_seconds=args.chunk_seconds,
            time_offset_ms=args.time_offset_ms,
        )
        print(json.dumps({
            "run_id":result.run_id,"source_id":result.source_id,
            "duration_ms":result.duration_ms,"segments":len(result.segment_ids),
            "evidence_items":len(result.evidence_ids),
            "evidence_references":len(result.evidence_ref_ids),
            "reused_chunks":result.reused_chunks,
            "processed_chunks":result.processed_chunks,
            "time_offset_ms":result.time_offset_ms,
        },ensure_ascii=False,indent=2))
    elif args.command == "extract-frames":
        from .video_frames import extract_video_frames, frame_extraction_dict

        result = extract_video_frames(
            args.database,args.asset_dir,args.asset_id,
            video_stream_index=args.video_stream_index,
            min_interval_ms=args.min_interval_ms,max_frames=args.max_frames,
            max_frame_bytes=args.max_frame_bytes,max_total_bytes=args.max_total_bytes,
            max_frame_pixels=args.max_frame_pixels,max_total_pixels=args.max_total_pixels,
            max_width=args.max_width,max_height=args.max_height,
            timeout_seconds=args.timeout,
        )
        print(json.dumps(frame_extraction_dict(result),ensure_ascii=False,indent=2))
    elif args.command == "describe-video-frames":
        from .video_intelligence import OllamaLocalVisionAdapter, describe_visual_events

        adapter=OllamaLocalVisionAdapter(args.model)
        print(json.dumps(describe_visual_events(
            args.database,args.asset_dir,args.source_id,adapter,max_frames=args.max_frames,
        ),ensure_ascii=False,indent=2))
    elif args.command == "align-video-semantics":
        from .video_intelligence import OllamaLocalVisionAdapter, align_visual_semantics

        adapter=OllamaLocalVisionAdapter(args.model)
        print(json.dumps(align_visual_semantics(
            args.database,args.asset_dir,args.source_id,adapter,max_pairs=args.max_pairs,
        ),ensure_ascii=False,indent=2))
    elif args.command == "verify-visual-claim":
        from .video_intelligence import OllamaLocalVisionAdapter, verify_visual_claim

        adapter=OllamaLocalVisionAdapter(args.model)
        record_id=verify_visual_claim(
            args.database,args.source_id,args.claim_id,args.visual_event_id,adapter,
            description_id=args.description_id,
            transcript_segment_id=args.transcript_segment_id,
        )
        print(json.dumps({"verification_id":record_id,"review_state":"NEEDS_REVIEW"},indent=2))
    elif args.command == "detect-scenes":
        from .video_intelligence import detect_scene_changes

        print(json.dumps(detect_scene_changes(
            args.database,args.asset_dir,args.source_id,
            threshold=args.threshold,max_comparisons=args.max_comparisons,
        ),ensure_ascii=False,indent=2))
    elif args.command == "ocr-video-frames":
        from .video_intelligence import ocr_video_frames

        print(json.dumps(ocr_video_frames(
            args.database,args.asset_dir,args.source_id,
            max_frames=args.max_frames,timeout_seconds=args.timeout,
        ),ensure_ascii=False,indent=2))
    elif args.command == "review-visual-record":
        from .video_intelligence import review_visual_record

        print(json.dumps({
            "record_id":args.record_id,
            "review_state":review_visual_record(
                args.database,args.table,args.record_id,args.state,
            ),
        },indent=2))
    elif args.command == "build-visual-timeline":
        from .visual_timeline import build_visual_timeline

        result = build_visual_timeline(
            args.database,args.extraction_id,tolerance_ms=args.tolerance_ms,
        )
        print(json.dumps({
            "source_id": result.source_id,
            "events_created": result.events_created,
            "alignments_created": result.alignments_created,
            "reused_events": result.reused_events,
        },ensure_ascii=False,indent=2))
    elif args.command == "visual-timeline":
        from .visual_timeline import list_visual_timeline

        print(json.dumps(
            list_visual_timeline(args.database,args.source_id),
            ensure_ascii=False,indent=2,
        ))
    elif args.command == "review-visual-event":
        from .visual_timeline import review_visual_event

        print(json.dumps({
            "event_id": args.event_id,
            "review_state": review_visual_event(args.database,args.event_id,args.state),
        },indent=2))
    elif args.command == "extract-audio":
        from .audio_extract import audio_extraction_dict, extract_audio

        result = extract_audio(
            args.database,args.asset_dir,args.asset_id,
            stream_index=args.stream_index,timeout_seconds=args.timeout,
            max_output_bytes=args.max_output_bytes,
        )
        print(json.dumps(audio_extraction_dict(result),ensure_ascii=False,indent=2))
    elif args.command == "probe-media":
        from .media_probe import media_probe_dict, probe_local_media

        result = probe_local_media(
            args.database,args.asset_dir,args.asset_id,
            timeout_seconds=args.timeout,max_streams=args.max_streams,
            max_output_bytes=args.max_output_bytes,
        )
        print(json.dumps(media_probe_dict(result),ensure_ascii=False,indent=2))
    elif args.command == "extract-pdf":
        from .document_pdf import extract_pdf

        result = extract_pdf(
            args.database, args.asset_dir, args.asset_id,
            max_pages=args.max_pages,
            max_chars_per_page=args.max_chars_per_page,
            max_total_chars=args.max_total_chars,
        )
        print(json.dumps({
            "extraction_id": result.extraction_id,
            "source_id": result.source_id,
            "asset_id": result.asset_id,
            "page_count": result.page_count,
            "extracted_pages": result.extracted_pages,
            "empty_pages": result.empty_pages,
            "evidence_references": list(result.evidence_ref_ids),
            "pages": [
                {"page_id": page.id, "page_number": page.page_number,
                 "char_count": page.char_count, "sha256": page.content_sha256,
                 "status": page.status}
                for page in result.pages
            ],
        }, ensure_ascii=False, indent=2))
    elif args.command == "review-knowledge-unit":
        from .knowledge_store import KnowledgeStore

        status = KnowledgeStore(args.database).review_unit(
            args.unit_id,status=args.status,provenance=args.provenance,
        )
        print(json.dumps({"unit_id": args.unit_id,"status": status},indent=2))
    elif args.command == "build-document-knowledge":
        from .document_knowledge import create_knowledge_candidates_from_document_elements

        result = create_knowledge_candidates_from_document_elements(
            args.database,args.source_id,
            accepted_elements_only=not args.include_unreviewed,
            max_total_chars=args.max_total_chars,
        )
        print(json.dumps({
            "source_id": result.source_id,
            "candidate_units": list(result.candidate_unit_ids),
            "created_or_reused": len(result.candidate_unit_ids),
            "skipped_unreviewed_elements": result.skipped_unreviewed_elements,
        },ensure_ascii=False,indent=2))
    elif args.command == "ocr-pdf":
        from .document_ocr import ocr_pdf

        result = ocr_pdf(
            args.database,args.asset_dir,args.asset_id,dpi=args.dpi,
            max_pages=args.max_pages,force=args.force,
        )
        print(json.dumps({
            "source_id": result.source_id,"asset_id": result.asset_id,
            "processed_pages": len(result.pages),"skipped_pages": list(result.skipped_pages),
            "pages": [{
                "page_id": page.page_id,"page_number": page.page_number,
                "rendered_asset_id": page.rendered_asset_id,
                "characters": len(page.text),"mean_confidence": page.mean_confidence,
                "status": page.status,
            } for page in result.pages],
        },ensure_ascii=False,indent=2))
    elif args.command == "review-ocr-page":
        from .document_ocr import review_ocr_page

        print(json.dumps({
            "page_id": args.page_id,
            "status": review_ocr_page(args.database,args.page_id,args.state),
        },indent=2))
    elif args.command == "structure-pdf":
        from .document_structure import extract_document_structure

        result = extract_document_structure(
            args.database,args.asset_dir,args.asset_id,
            max_pages=args.max_pages,max_elements=args.max_elements,
            max_total_chars=args.max_total_chars,
            max_figure_pixels=args.max_figure_pixels,
            max_total_figure_pixels=args.max_total_figure_pixels,
            extract_figure_assets=not args.no_figure_assets,
        )
        print(json.dumps({
            "source_id": result.source_id,"asset_id": result.asset_id,
            "pages": result.page_count,"elements": result.element_count,
            "counts_by_type": result.counts_by_type,
            "element_ids": [element.id for element in result.elements],
        },ensure_ascii=False,indent=2))
    elif args.command == "review-document-element":
        from .document_structure import review_document_element

        print(json.dumps({
            "element_id": args.element_id,
            "review_state": review_document_element(
                args.database,args.element_id,args.state,rationale=args.rationale,
                provenance=args.provenance,
            ),
        },ensure_ascii=False,indent=2))
    elif args.command == "list-document-elements":
        from .document_structure import list_document_elements

        print(json.dumps(
            list_document_elements(args.database,args.page_id),
            ensure_ascii=False,indent=2,
        ))
    elif args.command == "search-document-elements":
        from .document_structure import search_document_elements

        print(json.dumps(
            search_document_elements(args.database,args.query,limit=args.limit),
            ensure_ascii=False,indent=2,
        ))
    elif args.command == "search-evidence":
        from .evidence_refs import search_evidence_references

        results = search_evidence_references(args.database, args.query, limit=args.limit)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.command == "resolve-evidence":
        from .evidence_refs import get_evidence_reference

        result = get_evidence_reference(args.database, args.reference_id)
        if result is None:
            raise SystemExit("Evidence reference not found")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "search-pages":
        from .document_pdf import search_document_pages

        results = search_document_pages(args.database, args.query, limit=args.limit)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.command == "compose-document-textbook":
        from .textbook import TextbookStore

        version_id = TextbookStore(args.database).compose_from_accepted_document_topics(
            args.source_id,args.title,version_title=args.version_title,
        )
        print(json.dumps({"version_id": version_id}, indent=2))
    elif args.command == "document-outline":
        from .topics import TopicStore

        outline = TopicStore(args.database).get_document_outline(args.source_id)
        print(json.dumps(outline, ensure_ascii=False, indent=2))
    elif args.command == "export-pdf":
        output = TextbookPDFExporter(args.database).export(
            args.version_id, args.output, font_path=args.font, asset_dir=args.asset_dir
        )
        print(f"Exported PDF: {output}")
    elif args.command == "export-docx":
        output = TextbookDOCXExporter(args.database).export(args.version_id, args.output, asset_dir=args.asset_dir)
        print(f"Exported DOCX: {output}")
    elif args.command == "export-html":
        output = TextbookHTMLExporter(args.database).export(args.version_id, args.output, asset_dir=args.asset_dir)
        print(f"Exported HTML: {output}")
    elif args.command == "export-markdown":
        output = TextbookMarkdownExporter(args.database).export(args.version_id, args.output, asset_dir=args.asset_dir)
        print(f"Exported Markdown: {output}")
