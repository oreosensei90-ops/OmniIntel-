"""Publication-gated exporters for collection-level course textbooks."""
from __future__ import annotations
import html
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape
from .course_textbook import CourseTextbookStore


class CourseTextbookExporter:
    def __init__(self, database_path: str | Path):
        self.store = CourseTextbookStore(database_path)

    @staticmethod
    def _citation(item: dict[str, Any]) -> str:
        source = item.get("source_title") or item.get("source_id") or "Unknown source"
        if item.get("locator_kind") == "DOCUMENT_PAGE":
            locator = f"p. {item.get('page_number')}"
        elif item.get("start_ms") is not None:
            locator = f"{int(item['start_ms']) / 1000:.2f}-{int(item['end_ms']) / 1000:.2f}s"
        else:
            locator = "source"
        return f"{source} · {locator} · {item.get('relation', 'SUPPORTS')}"

    def _tree(self, version_id: str) -> dict[str, Any]:
        audit = self.store.audit(version_id)
        if not audit["publishable"]:
            raise ValueError(f"Course textbook is not publication-ready: {audit['findings']}")
        tree = self.store.get_version(version_id)
        if tree is None:
            raise ValueError("Course textbook version does not exist")
        return tree

    def export_markdown(self, version_id: str, output_path: str | Path) -> Path:
        tree = self._tree(version_id)
        lines = [f"# {tree['version']['title']}", "", f"> Course textbook: {tree['version']['textbook_title']}", ""]
        for index, entry in enumerate(tree["chapters"], 1):
            chapter = entry["chapter"]
            lines.extend([f"## {index}. {chapter['title']}", ""])
            if chapter["summary"]:
                lines.extend([chapter["summary"], ""])
            for block in entry["blocks"]:
                content, kind = block["content"], block["block_type"]
                value = str(content.get("text", content.get("body", content.get("expression", ""))))
                if kind == "HEADING":
                    lines.extend([f"### {value}", ""])
                elif kind == "DEFINITION":
                    lines.extend([f"**{content.get('term', 'Definition')}**: {content.get('definition', value)}", ""])
                elif kind == "EQUATION":
                    lines.extend([f"$$\n{content.get('latex', value)}\n$$", ""])
                elif kind == "CODE":
                    code = str(content.get("code", value))
                    fence = chr(96) * 4 if chr(96) * 3 in code else chr(96) * 3
                    lines.extend([fence + str(content.get("language", "")), code, fence, ""])
                elif kind == "TABLE":
                    rows = content.get("rows", [])
                    if rows:
                        lines.append("| " + " | ".join(map(str, rows[0])) + " |")
                        lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
                        lines.extend("| " + " | ".join(map(str, row)) + " |" for row in rows[1:])
                        lines.append("")
                elif kind in {"WARNING", "MISCONCEPTION", "EXAMPLE", "WORKED_SOLUTION", "EXERCISE"}:
                    lines.extend([f"> **{kind.replace('_', ' ').title()}**: {value}", ""])
                elif kind in {"DIAGRAM", "IMAGE"}:
                    lines.extend([f"> **{kind.title()}**: {content.get('alt') or content.get('description') or value}", ""])
                else:
                    lines.extend([value, ""])
                citations = [self._citation(x) for x in block["evidence"] if x["relation"] in {"SUPPORTS", "ILLUSTRATES", "CONTEXTUALIZES"}]
                if citations:
                    lines.extend(["**Evidence:** " + "; ".join(citations), ""])
                lines.extend([f"*Provenance: {block['provenance']}*", ""])
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def export_html(self, version_id: str, output_path: str | Path) -> Path:
        tree = self._tree(version_id)
        esc = lambda value: html.escape(str(value), quote=True)
        toc, sections = [], []
        for index, entry in enumerate(tree["chapters"], 1):
            chapter = entry["chapter"]
            anchor = f"chapter-{index}"
            toc.append(f'<li><a href="#{anchor}">{esc(chapter["title"])}</a></li>')
            blocks = []
            for block in entry["blocks"]:
                content, kind = block["content"], block["block_type"]
                value = content.get("text", content.get("body", content.get("expression", "")))
                if kind == "HEADING":
                    body = f"<h3>{esc(value)}</h3>"
                elif kind == "DEFINITION":
                    body = f"<dl><dt>{esc(content.get('term', 'Definition'))}</dt><dd>{esc(content.get('definition', value))}</dd></dl>"
                elif kind == "EQUATION":
                    body = f'<pre class="equation">{esc(content.get("latex", value))}</pre>'
                elif kind == "CODE":
                    body = f"<pre><code>{esc(content.get('code', value))}</code></pre>"
                elif kind == "TABLE":
                    rows = content.get("rows", [])
                    body = "<table>" + "".join("<tr>" + "".join(f"<{'th' if ri == 0 else 'td'}>{esc(cell)}</{'th' if ri == 0 else 'td'}>" for cell in row) + "</tr>" for ri, row in enumerate(rows)) + "</table>"
                elif kind in {"WARNING", "MISCONCEPTION", "EXAMPLE", "WORKED_SOLUTION", "EXERCISE"}:
                    body = f'<aside class="{kind.lower()}"><strong>{esc(kind.replace("_", " ").title())}</strong><p>{esc(value)}</p></aside>'
                elif kind in {"DIAGRAM", "IMAGE"}:
                    body = f"<figure><figcaption>{esc(content.get('alt') or content.get('description') or value)}</figcaption></figure>"
                else:
                    body = f"<p>{esc(value).replace(chr(10), '<br>')}</p>"
                citations = [self._citation(x) for x in block["evidence"] if x["relation"] in {"SUPPORTS", "ILLUSTRATES", "CONTEXTUALIZES"}]
                if citations:
                    body += f'<p class="evidence">Evidence: {esc("; ".join(citations))}</p>'
                body += f'<p class="provenance">Provenance: {esc(block["provenance"])}</p>'
                blocks.append(body)
            summary = f'<p class="summary">{esc(chapter["summary"])}</p>' if chapter["summary"] else ""
            sections.append(f'<section id="{anchor}"><h2>{esc(chapter["title"])}</h2>{summary}{"".join(blocks)}</section>')
        title = esc(tree["version"]["title"])
        course = esc(tree["version"]["textbook_title"])
        document = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            f"<title>{title}</title><style>body{{font:17px/1.65 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}}"
            "pre{overflow:auto;padding:1rem;background:#f2f4f7}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.45rem}"
            "aside{padding:.8rem;border-left:4px solid #777;background:#f5f5f5}.evidence,.provenance{font-size:.85rem;color:#555}"
            "@media print{nav{display:none}}</style></head><body>"
            f"<header><h1>{title}</h1><p>Course textbook: {course}</p></header>"
            f"<nav aria-label=\"Contents\"><h2>Contents</h2><ol>{''.join(toc)}</ol></nav>"
            f"<main>{''.join(sections)}</main></body></html>")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document, encoding="utf-8")
        return path

    def export_pdf(self, version_id: str, output_path: str | Path, *, font_path: str | Path | None = None) -> Path:
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle
        except ImportError as exc:
            raise RuntimeError("PDF export requires the documents extra") from exc
        tree = self._tree(version_id)
        font = "Helvetica"
        if font_path:
            pdfmetrics.registerFont(TTFont("OmniIntelCourse", str(font_path)))
            font = "OmniIntelCourse"
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="CourseTitle", parent=styles["Title"], fontName=font))
        styles.add(ParagraphStyle(name="CourseBody", parent=styles["BodyText"], fontName=font, leading=16, spaceAfter=8))
        styles.add(ParagraphStyle(name="CourseHeading", parent=styles["Heading2"], fontName=font, spaceBefore=16))
        story = [Paragraph(xml_escape(tree["version"]["title"]), styles["CourseTitle"]),
                 Paragraph("Course textbook: " + xml_escape(tree["version"]["textbook_title"]), styles["CourseBody"]), Spacer(1, 16)]
        for index, entry in enumerate(tree["chapters"], 1):
            chapter = entry["chapter"]
            story.append(Paragraph(f"{index}. {xml_escape(chapter['title'])}", styles["CourseHeading"]))
            if chapter["summary"]:
                story.append(Paragraph(xml_escape(chapter["summary"]), styles["CourseBody"]))
            for block in entry["blocks"]:
                content, kind = block["content"], block["block_type"]
                value = str(content.get("text", content.get("body", content.get("expression", ""))))
                if kind == "TABLE":
                    rows = content.get("rows", [])
                    if rows:
                        table = Table([[Paragraph(xml_escape(str(cell)), styles["CourseBody"]) for cell in row] for row in rows], repeatRows=1)
                        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                        story.append(table)
                elif kind == "CODE":
                    story.append(Preformatted(str(content.get("code", value)), styles["Code"]))
                elif kind == "EQUATION":
                    story.append(Preformatted(str(content.get("latex", value)), styles["Code"]))
                elif kind == "DEFINITION":
                    story.append(Paragraph("<b>" + xml_escape(content.get("term", "Definition")) + "</b>: " + xml_escape(content.get("definition", value)), styles["CourseBody"]))
                else:
                    if kind in {"DIAGRAM", "IMAGE"}:
                        value = content.get("alt") or content.get("description") or value
                    story.append(Paragraph(xml_escape(str(value)).replace("\n", "<br/>"), styles["CourseBody"]))
                citations = [self._citation(x) for x in block["evidence"] if x["relation"] in {"SUPPORTS", "ILLUSTRATES", "CONTEXTUALIZES"}]
                if citations:
                    story.append(Paragraph("Evidence: " + xml_escape("; ".join(citations)), styles["CourseBody"]))
                story.append(Paragraph("Provenance: " + xml_escape(block["provenance"]), styles["CourseBody"]))
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        SimpleDocTemplate(str(path), pagesize=A4, title=tree["version"]["title"]).build(story)
        return path

    def export_docx(self, version_id: str, output_path: str | Path) -> Path:
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("DOCX export requires the documents extra") from exc
        tree = self._tree(version_id)
        document = Document()
        document.add_heading(tree["version"]["title"], 0)
        document.add_paragraph("Course textbook: " + tree["version"]["textbook_title"])
        for index, entry in enumerate(tree["chapters"], 1):
            chapter = entry["chapter"]
            document.add_heading(f"{index}. {chapter['title']}", level=1)
            if chapter["summary"]:
                document.add_paragraph(chapter["summary"])
            for block in entry["blocks"]:
                content, kind = block["content"], block["block_type"]
                value = str(content.get("text", content.get("body", content.get("expression", ""))))
                if kind == "HEADING":
                    document.add_heading(value, level=2)
                elif kind == "TABLE":
                    rows = content.get("rows", [])
                    if rows:
                        table = document.add_table(rows=0, cols=len(rows[0]))
                        table.style = "Table Grid"
                        for row in rows:
                            cells = table.add_row().cells
                            for cell, text_value in zip(cells, row):
                                cell.text = str(text_value)
                elif kind == "CODE":
                    document.add_paragraph(str(content.get("code", value)), style="No Spacing")
                elif kind == "DEFINITION":
                    paragraph = document.add_paragraph()
                    paragraph.add_run(str(content.get("term", "Definition")) + ": ").bold = True
                    paragraph.add_run(str(content.get("definition", value)))
                elif kind == "EQUATION":
                    document.add_paragraph(str(content.get("latex", value)), style="No Spacing")
                else:
                    if kind in {"DIAGRAM", "IMAGE"}:
                        value = str(content.get("alt") or content.get("description") or value)
                    paragraph = document.add_paragraph()
                    if kind in {"WARNING", "MISCONCEPTION", "EXAMPLE", "WORKED_SOLUTION", "EXERCISE"}:
                        paragraph.add_run(kind.replace("_", " ").title() + ": ").bold = True
                    paragraph.add_run(value)
                citations = [self._citation(x) for x in block["evidence"] if x["relation"] in {"SUPPORTS", "ILLUSTRATES", "CONTEXTUALIZES"}]
                if citations:
                    paragraph = document.add_paragraph("Evidence: " + "; ".join(citations))
                    paragraph.style = "Caption"
                paragraph = document.add_paragraph("Provenance: " + block["provenance"])
                paragraph.style = "Caption"
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        document.save(path)
        return path
