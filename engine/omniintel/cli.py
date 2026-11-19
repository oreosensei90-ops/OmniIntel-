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
    elif args.command == "export-pdf":
        output = TextbookPDFExporter(args.database).export(
            args.version_id, args.output, font_path=args.font
        )
        print(f"Exported PDF: {output}")
    elif args.command == "export-docx":
        output = TextbookDOCXExporter(args.database).export(args.version_id, args.output)
        print(f"Exported DOCX: {output}")
