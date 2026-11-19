"""Accessible PDF renderer for audited textbook versions.

The renderer consumes the canonical textbook tree and never generates content.
ReportLab is an optional publishing dependency.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from .export_visuals import evidence_locator_label, resolve_block_assets
from .textbook import TextbookStore
from .textbook_audit import TextbookPublicationAuditor

_DEVANAGARI = re.compile(r"[\u0900-\u097f]")
_LATIN_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
)


class TextbookPDFExporter:
    """Render an audited textbook version to a tagged-by-style, searchable PDF."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.store = TextbookStore(database_path)
        self.auditor = TextbookPublicationAuditor(database_path)

    def export(
        self, version_id: str, output_path: str | Path, *, font_path: str | Path | None = None, asset_dir: str | Path | None = None
    ) -> Path:
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_LEFT
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import (
                KeepTogether, PageBreak, Paragraph, Preformatted,
                SimpleDocTemplate, Spacer, Table, TableStyle,
            )
        except ImportError as exc:
            raise RuntimeError(
                "PDF export requires the optional publishing dependencies: "
                "pip install -e '.[publishing]'"
            ) from exc

        report = self.auditor.audit(version_id)
        if not report.ready:
            codes = ", ".join(sorted({item.code for item in report.findings if item.severity == "ERROR"}))
            raise ValueError(f"Textbook version is not publication-ready: {codes}")

        tree = self.store.get_version_tree(version_id)
        if tree is None:
            raise ValueError("Textbook version does not exist")
        version = tree["version"]
        chapters = tree["chapters"]
        all_text = " ".join(
            str(value)
            for chapter in chapters
            for block in chapter["blocks"]
            for value in block["content"].values()
        )
        chosen_font = Path(font_path) if font_path else next(
            (candidate for candidate in _LATIN_FONT_CANDIDATES if candidate.is_file()), None
        )
        if _DEVANAGARI.search(all_text) and chosen_font is None:
            raise ValueError(
                "This textbook contains Devanagari text. Supply a Unicode TTF font "
                "with Devanagari glyph coverage using font_path."
            )
        if chosen_font is not None:
            if not chosen_font.is_file():
                raise FileNotFoundError(f"Font file does not exist: {chosen_font}")
            pdfmetrics.registerFont(TTFont("OmniIntelBody", str(chosen_font)))
            body_font = "OmniIntelBody"
        else:
            body_font = "Helvetica"

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name="OI_Title", parent=styles["Title"], fontName=body_font,
            fontSize=25, leading=31, alignment=TA_LEFT, spaceAfter=12,
        ))
        styles.add(ParagraphStyle(
            name="OI_Subtitle", parent=styles["BodyText"], fontName=body_font,
            fontSize=14, leading=19, spaceAfter=8,
        ))
        styles.add(ParagraphStyle(
            name="OI_Chapter", parent=styles["Heading1"], fontName=body_font,
            fontSize=19, leading=24, spaceBefore=10, spaceAfter=9,
            textColor=colors.HexColor("#202A44"),
        ))
        styles.add(ParagraphStyle(
            name="OI_Section", parent=styles["Heading2"], fontName=body_font,
            fontSize=14, leading=18, spaceBefore=8, spaceAfter=6,
        ))
        styles.add(ParagraphStyle(
            name="OI_Body", parent=styles["BodyText"], fontName=body_font,
            fontSize=10, leading=15, alignment=TA_LEFT, spaceAfter=7,
        ))
        styles.add(ParagraphStyle(
            name="OI_Small", parent=styles["BodyText"], fontName=body_font,
            fontSize=8, leading=11, textColor=colors.HexColor("#555555"),
        ))
        styles.add(ParagraphStyle(
            name="OI_Callout", parent=styles["BodyText"], fontName=body_font,
            fontSize=9.5, leading=14, leftIndent=8, rightIndent=8,
            borderColor=colors.HexColor("#AAB4C5"), borderWidth=0.6,
            borderPadding=7, spaceBefore=4, spaceAfter=9,
        ))

        story: list[Any] = [
            Spacer(1, 28 * mm),
            Paragraph(html.escape(version["textbook_title"]), styles["OI_Title"]),
            Paragraph(html.escape(version["title"]), styles["OI_Subtitle"]),
            Spacer(1, 4 * mm),
            Paragraph(
                f"Edition {version['version_number']} · {len(chapters)} chapters · "
                f"{report.total_blocks} content blocks",
                styles["OI_Small"],
            ),
            PageBreak(),
        ]

        def safe(value: Any) -> str:
            return html.escape(str(value)).replace("\n", "<br/>")

        def paragraph(value: Any, style: str = "OI_Body") -> Paragraph:
            return Paragraph(safe(value), styles[style])

        for chapter_index, item in enumerate(chapters):
            chapter = item["chapter"]
            if chapter_index:
                story.append(PageBreak())
            story.append(Paragraph(safe(chapter["title"]), styles["OI_Chapter"]))
            if chapter.get("summary"):
                story.append(paragraph(chapter["summary"]))
            if chapter.get("source_start_ms") is not None:
                start = chapter["source_start_ms"] / 1000
                end = chapter["source_end_ms"] / 1000 if chapter.get("source_end_ms") else None
                interval = f"Source time: {start:.1f}s"
                if end is not None:
                    interval += f"–{end:.1f}s"
                story.append(Paragraph(safe(interval), styles["OI_Small"]))
                story.append(Spacer(1, 3 * mm))

            for block in item["blocks"]:
                content = block["content"]
                kind = block["block_type"]
                if kind == "HEADING":
                    story.append(paragraph(content.get("text", ""), "OI_Section"))
                elif kind in {"PARAGRAPH", "SUMMARY"}:
                    story.append(paragraph(content.get("text", content)))
                elif kind == "DEFINITION":
                    term = content.get("term", "Definition")
                    definition = content.get("definition", content.get("text", ""))
                    story.append(KeepTogether([
                        Paragraph(f"<b>{safe(term)}</b>", styles["OI_Section"]),
                        paragraph(definition),
                    ]))
                elif kind == "EQUATION":
                    equation = content.get("latex") or content.get("text") or content.get("expression", "")
                    story.append(Preformatted(str(equation), styles["Code"]))
                elif kind == "TABLE":
                    rows = content.get("rows", [])
                    if not isinstance(rows, list) or not rows:
                        raise ValueError(f"Table block {block['id']} has no rows")
                    table_data = [[paragraph(cell, "OI_Small") for cell in row] for row in rows]
                    table = Table(table_data, repeatRows=1, hAlign="LEFT")
                    table.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8ECF3")),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AAB4C5")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]))
                    story.append(table)
                    story.append(Spacer(1, 3 * mm))
                elif kind == "CODE":
                    story.append(Preformatted(str(content.get("code", content.get("text", ""))), styles["Code"]))
                elif kind in {"WARNING", "MISCONCEPTION", "EXAMPLE", "WORKED_SOLUTION", "EXERCISE"}:
                    heading = kind.replace("_", " ").title()
                    body = content.get("text") or content.get("body") or content.get("prompt") or ""
                    story.append(KeepTogether([
                        Paragraph(f"<b>{safe(heading)}</b>", styles["OI_Callout"]),
                        paragraph(body, "OI_Callout"),
                    ]))
                elif kind == "SOURCE_REFERENCE":
                    story.append(paragraph(content.get("text", content)))
                elif kind == "FOOTNOTE":
                    story.append(paragraph(content.get("text", content), "OI_Small"))
                elif kind in {"DIAGRAM", "IMAGE"}:
                    description = content.get("alt") or content.get("description") or content.get("text")
                    if not description:
                        raise ValueError(
                            f"{kind} block {block['id']} requires an accessible description"
                        )
                    story.append(paragraph(f"[{kind.title()}] {description}", "OI_Callout"))
                    for image_path, caption, media_type, digest in resolve_block_assets(
                        self.database_path,asset_dir,version["source_id"],block
                    ):
                        from reportlab.platypus import Image as ReportLabImage
                        from reportlab.lib.utils import ImageReader

                        reader=ImageReader(str(image_path))
                        image_width,image_height=reader.getSize()
                        max_width,max_height=174*mm,210*mm
                        scale=min(max_width/image_width,max_height/image_height,1.0)
                        story.append(ReportLabImage(
                            str(image_path),width=image_width*scale,height=image_height*scale
                        ))
                        if caption:
                            story.append(paragraph(caption,"OI_Small"))
                else:
                    raise ValueError(f"Unsupported PDF block type: {kind}")

                citations = [
                    evidence for evidence in block["evidence"]
                    if evidence["relation"] in {"SUPPORTS", "ILLUSTRATES", "CONTEXTUALIZES"}
                ]
                for evidence in citations:
                    locator = evidence_locator_label(evidence)
                    provenance = evidence.get("provenance") or evidence.get("evidence_provenance") or "SOURCE"
                    story.append(Paragraph(
                        f"Source evidence · {safe(locator)} · {safe(provenance)}",
                        styles["OI_Small"],
                    ))
                if block["provenance"] in {"DERIVED", "EXTERNAL"}:
                    story.append(Paragraph(
                        f"Provenance: {safe(block['provenance'])}",
                        styles["OI_Small"],
                    ))
                story.append(Spacer(1, 2 * mm))

        def decorate(canvas: Any, doc: Any) -> None:
            canvas.saveState()
            canvas.setFont(body_font, 8)
            canvas.setFillColor(colors.HexColor("#666666"))
            canvas.drawString(18 * mm, 12 * mm, "OmniIntel · Evidence-grounded learning")
            canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Page {doc.page}")
            canvas.restoreState()

        document = SimpleDocTemplate(
            str(output), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
            topMargin=18 * mm, bottomMargin=20 * mm,
            title=f"{version['textbook_title']} — {version['title']}",
            author="OmniIntel",
            subject="Evidence-grounded learning textbook",
        )
        document.build(story, onFirstPage=decorate, onLaterPages=decorate)
        if not output.is_file() or output.stat().st_size < 500:
            raise RuntimeError("PDF renderer did not produce a valid output file")
        with output.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise RuntimeError("Rendered output does not have a PDF signature")
        return output
