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
    export_docx = sub.add_parser("export-docx", help="Export a publication-ready textbook version to editable DOCX")
    export_docx.add_argument("database", type=Path)
    export_docx.add_argument("version_id")
    export_docx.add_argument("output", type=Path)
    export_html = sub.add_parser("export-html", help="Export a publication-ready textbook to self-contained HTML")
    export_html.add_argument("database", type=Path)
    export_html.add_argument("version_id")
    export_html.add_argument("output", type=Path)
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
    args = parser.parse_args()
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
        )
        print(json.dumps({
            "run_id":result.run_id,"source_id":result.source_id,
            "duration_ms":result.duration_ms,"segments":len(result.segment_ids),
            "evidence_items":len(result.evidence_ids),
            "evidence_references":len(result.evidence_ref_ids),
            "reused_chunks":result.reused_chunks,
            "processed_chunks":result.processed_chunks,
        },ensure_ascii=False,indent=2))
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
            args.version_id, args.output, font_path=args.font
        )
        print(f"Exported PDF: {output}")
    elif args.command == "export-docx":
        output = TextbookDOCXExporter(args.database).export(args.version_id, args.output)
        print(f"Exported DOCX: {output}")
    elif args.command == "export-html":
        output = TextbookHTMLExporter(args.database).export(args.version_id, args.output)
        print(f"Exported HTML: {output}")
    elif args.command == "export-markdown":
        output = TextbookMarkdownExporter(args.database).export(args.version_id, args.output)
        print(f"Exported Markdown: {output}")
