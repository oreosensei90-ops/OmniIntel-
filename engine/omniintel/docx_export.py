"""Editable DOCX renderer for audited textbook versions.

The renderer consumes the canonical textbook tree and never generates content.
python-docx is an optional publishing dependency.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class TextbookDOCXExporter:
    """Render a publication-ready textbook as an editable Word document."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def export(self, version_id: str, output_path: str | Path) -> Path:
        try:
            from docx import Document
            from docx.enum.section import WD_SECTION
            from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.oxml import OxmlElement
            from docx.oxml.ns import qn
            from docx.shared import Inches, Pt, RGBColor
        except ImportError as exc:
            raise RuntimeError(
                "DOCX export requires the optional publishing dependencies: "
                "pip install -e '.[publishing]'"
            ) from exc

        from .textbook import TextbookStore
        from .textbook_audit import TextbookPublicationAuditor

        report = TextbookPublicationAuditor(self.database_path).audit(version_id)
        if not report.ready:
            codes = ", ".join(sorted({
                item.code for item in report.findings if item.severity == "ERROR"
            }))
            raise ValueError(f"Textbook version is not publication-ready: {codes}")

        tree = TextbookStore(self.database_path).get_version_tree(version_id)
        if tree is None:
            raise ValueError("Textbook version does not exist")
        version = tree["version"]
        chapters = tree["chapters"]

        document = Document()
        section = document.sections[0]
        section.top_margin = Inches(0.72)
        section.bottom_margin = Inches(0.72)
        section.left_margin = Inches(0.82)
        section.right_margin = Inches(0.82)

        styles = document.styles
        styles["Normal"].font.name = "Aptos"
        styles["Normal"].font.size = Pt(10.5)
        styles["Normal"].paragraph_format.space_after = Pt(7)
        for name, size, color in (
            ("Title", 28, "202A44"),
            ("Subtitle", 14, "526078"),
            ("Heading 1", 19, "202A44"),
            ("Heading 2", 14, "35435E"),
            ("Heading 3", 12, "35435E"),
        ):
            style = styles[name]
            style.font.name = "Aptos Display" if name != "Subtitle" else "Aptos"
            style.font.size = Pt(size)
            style.font.color.rgb = RGBColor.from_string(color)
            if name.startswith("Heading"):
                style.paragraph_format.keep_with_next = True

        header = section.header.paragraphs[0]
        header.text = "OMNIINTEL  |  EVIDENCE-GROUNDED LEARNING"
        header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for run in header.runs:
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(100, 110, 125)

        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer.add_run("OmniIntel  ·  Page ")
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        footer._p.append(field)

        def add_shading(cell: Any, fill: str) -> None:
            properties = cell._tc.get_or_add_tcPr()
            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), fill)
            properties.append(shading)

        def add_callout(label: str, body: Any) -> None:
            table = document.add_table(rows=1, cols=1)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            cell = table.cell(0, 0)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            add_shading(cell, "F1F4F8")
            p = cell.paragraphs[0]
            lead = p.add_run(label + "\n")
            lead.bold = True
            lead.font.color.rgb = RGBColor(53, 67, 94)
            p.add_run(str(body))
            document.add_paragraph()

        def add_table(rows: Any, block_id: str) -> None:
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"Table block {block_id} has no rows")
            width = max((len(row) for row in rows if isinstance(row, list)), default=0)
            if width == 0:
                raise ValueError(f"Table block {block_id} has invalid rows")
            table = document.add_table(rows=0, cols=width)
            table.style = "Light Shading Accent 1"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for row_index, source_row in enumerate(rows):
                if not isinstance(source_row, list):
                    raise ValueError(f"Table block {block_id} contains an invalid row")
                cells = table.add_row().cells
                for col_index in range(width):
                    value = source_row[col_index] if col_index < len(source_row) else ""
                    cells[col_index].text = str(value)
                    cells[col_index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
                    if row_index == 0:
                        for run in cells[col_index].paragraphs[0].runs:
                            run.bold = True
            document.add_paragraph()

        title = document.add_paragraph(style="Title")
        title.add_run(str(version["textbook_title"]))
        subtitle = document.add_paragraph(style="Subtitle")
        subtitle.add_run(str(version["title"]))
        meta = document.add_paragraph()
        meta_run = meta.add_run(
            f"Edition {version['version_number']}  ·  {len(chapters)} chapters  ·  "
            f"{report.total_blocks} content blocks"
        )
        meta_run.font.size = Pt(9)
        meta_run.font.color.rgb = RGBColor(100, 110, 125)
        document.add_page_break()

        for chapter_index, item in enumerate(chapters):
            if chapter_index:
                document.add_page_break()
            chapter = item["chapter"]
            document.add_heading(str(chapter["title"]), level=1)
            if chapter.get("summary"):
                p = document.add_paragraph(str(chapter["summary"]))
                p.paragraph_format.keep_together = True
            if chapter.get("source_start_ms") is not None:
                start = chapter["source_start_ms"] / 1000
                end_ms = chapter.get("source_end_ms")
                interval = f"Source time: {start:.1f}s"
                if end_ms is not None:
                    interval += f"–{end_ms / 1000:.1f}s"
                p = document.add_paragraph(interval)
                for run in p.runs:
                    run.italic = True
                    run.font.size = Pt(8)
                    run.font.color.rgb = RGBColor(100, 110, 125)

            for block in item["blocks"]:
                content = block["content"]
                kind = block["block_type"]
                if kind == "HEADING":
                    document.add_heading(str(content.get("text", "")), level=2)
                elif kind in {"PARAGRAPH", "SUMMARY", "SOURCE_REFERENCE"}:
                    document.add_paragraph(str(content.get("text", content)))
                elif kind == "DEFINITION":
                    p = document.add_paragraph()
                    term = p.add_run(str(content.get("term", "Definition")) + ": ")
                    term.bold = True
                    p.add_run(str(content.get("definition", content.get("text", ""))))
                    p.paragraph_format.keep_together = True
                elif kind == "EQUATION":
                    p = document.add_paragraph()
                    p.paragraph_format.left_indent = Inches(0.25)
                    run = p.add_run(str(
                        content.get("latex") or content.get("text")
                        or content.get("expression", "")
                    ))
                    run.font.name = "Cambria Math"
                    run.font.size = Pt(11)
                elif kind == "TABLE":
                    add_table(content.get("rows", []), block["id"])
                elif kind == "CODE":
                    p = document.add_paragraph()
                    p.paragraph_format.left_indent = Inches(0.2)
                    run = p.add_run(str(content.get("code", content.get("text", ""))))
                    run.font.name = "Consolas"
                    run.font.size = Pt(9)
                elif kind in {
                    "WARNING", "MISCONCEPTION", "EXAMPLE", "WORKED_SOLUTION", "EXERCISE"
                }:
                    label = kind.replace("_", " ").title()
                    body = (
                        content.get("text") or content.get("body")
                        or content.get("prompt") or ""
                    )
                    add_callout(label, body)
                elif kind == "FOOTNOTE":
                    p = document.add_paragraph(str(content.get("text", content)))
                    for run in p.runs:
                        run.font.size = Pt(8)
                        run.italic = True
                elif kind in {"DIAGRAM", "IMAGE"}:
                    description = (
                        content.get("alt") or content.get("description")
                        or content.get("text")
                    )
                    if not description:
                        raise ValueError(
                            f"{kind} block {block['id']} requires an accessible description"
                        )
                    add_callout(f"{kind.title()} description", description)
                else:
                    raise ValueError(f"Unsupported DOCX block type: {kind}")

                for evidence in block["evidence"]:
                    if evidence["relation"] not in {
                        "SUPPORTS", "ILLUSTRATES", "CONTEXTUALIZES"
                    }:
                        continue
                    timestamp = f"{evidence['start_ms'] / 1000:.1f}s"
                    citation = document.add_paragraph()
                    citation.paragraph_format.left_indent = Inches(0.18)
                    citation.paragraph_format.space_after = Pt(3)
                    run = citation.add_run(
                        f"Source evidence · {timestamp} · {evidence['provenance']}"
                    )
                    run.font.size = Pt(8)
                    run.font.color.rgb = RGBColor(95, 105, 120)

                if block["provenance"] in {"DERIVED", "EXTERNAL"}:
                    p = document.add_paragraph()
                    run = p.add_run(f"Provenance: {block['provenance']}")
                    run.italic = True
                    run.font.size = Pt(8)

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        document.core_properties.title = (
            f"{version['textbook_title']} — {version['title']}"
        )
        document.core_properties.author = "OmniIntel"
        document.core_properties.subject = "Evidence-grounded learning textbook"
        document.save(output)
        if not output.is_file() or output.stat().st_size < 500:
            raise RuntimeError("DOCX renderer did not produce a valid output file")
        with output.open("rb") as handle:
            if handle.read(2) != b"PK":
                raise RuntimeError("Rendered output is not a valid DOCX ZIP package")
        return output
