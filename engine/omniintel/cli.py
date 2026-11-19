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
