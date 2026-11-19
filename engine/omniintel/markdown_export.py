"""Portable Markdown renderer for audited textbook versions."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .textbook import TextbookStore
from .textbook_audit import TextbookPublicationAuditor


class TextbookMarkdownExporter:
    """Render a publication-ready textbook as portable UTF-8 Markdown."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def export(self, version_id: str, output_path: str | Path) -> Path:
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

        def plain(value: Any) -> str:
            return str(value).replace("\r\n", "\n").replace("\r", "\n")

        def table_cell(value: Any) -> str:
            return plain(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")

        def code_fence(value: Any) -> str:
            source = plain(value)
            longest = max((len(match.group(0)) for match in re.finditer(r"`+", source)), default=0)
            fence = "`" * max(3, longest + 1)
            return f"{fence}\n{source}\n{fence}"

        def slug(value: str) -> str:
            normalized = re.sub(r"[^\w\- ]", "", value.casefold(), flags=re.UNICODE)
            return re.sub(r"[-\s]+", "-", normalized).strip("-") or "chapter"

        def render_table(rows: Any, block_id: str) -> str:
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"Table block {block_id} has no rows")
            if any(not isinstance(row, list) for row in rows):
                raise TypeError(f"Table block {block_id} contains an invalid row")
            width = max((len(row) for row in rows), default=0)
            if width == 0:
                raise ValueError(f"Table block {block_id} has invalid rows")
            normalized = [
                [table_cell(row[index]) if index < len(row) else "" for index in range(width)]
                for row in rows
            ]
            header = "| " + " | ".join(normalized[0]) + " |"
            divider = "| " + " | ".join("---" for _ in range(width)) + " |"
            body = ["| " + " | ".join(row) + " |" for row in normalized[1:]]
            return "\n".join([header, divider, *body])

        def render_block(block: dict[str, Any]) -> str:
            content = block["content"]
            kind = block["block_type"]
            if kind == "HEADING":
                body = f"### {plain(content.get('text', '')).strip()}"
            elif kind in {"PARAGRAPH", "SUMMARY", "SOURCE_REFERENCE"}:
                body = plain(content.get("text", content)).strip()
            elif kind == "DEFINITION":
                body = (
                    f"**{plain(content.get('term', 'Definition')).strip()}**\n\n"
                    f": {plain(content.get('definition', content.get('text', ''))).strip()}"
                )
            elif kind == "EQUATION":
                equation = content.get("latex") or content.get("text") or content.get("expression", "")
                body = f"$$\n{plain(equation)}\n$$"
            elif kind == "TABLE":
                body = render_table(content.get("rows", []), block["id"])
            elif kind == "CODE":
                body = code_fence(content.get("code", content.get("text", "")))
            elif kind in {
                "WARNING", "MISCONCEPTION", "EXAMPLE", "WORKED_SOLUTION", "EXERCISE"
            }:
                label = kind.replace("_", " ").title()
                value = (
                    content.get("text") or content.get("body")
                    or content.get("prompt") or ""
                )
                body = f"> **{label}**\n>\n> " + plain(value).replace("\n", "\n> ")
            elif kind == "FOOTNOTE":
                body = f"*{plain(content.get('text', content)).strip()}*"
            elif kind in {"DIAGRAM", "IMAGE"}:
                description = (
                    content.get("alt") or content.get("description")
                    or content.get("text")
                )
                if not description:
                    raise ValueError(
                        f"{kind} block {block['id']} requires an accessible description"
                    )
                body = f"> **{kind.title()} description:** {plain(description)}"
            else:
                raise ValueError(f"Unsupported Markdown block type: {kind}")

            citations = []
            for evidence in block["evidence"]:
                if evidence["relation"] not in {
                    "SUPPORTS", "ILLUSTRATES", "CONTEXTUALIZES"
                }:
                    continue
                citations.append(
                    f"- Source evidence · {evidence['start_ms'] / 1000:.1f}s · "
                    f"{evidence['provenance']}"
                )
            if citations:
                body += "\n\n" + "\n".join(citations)
            if block["provenance"] in {"DERIVED", "EXTERNAL"}:
                body += f"\n\n*Provenance: {block['provenance']}*"
            return body

        title = plain(version["textbook_title"])
        edition = plain(version["title"])
        lines = [
            f"# {title}",
            "",
            f"*{edition}*",
            "",
            f"Edition {version['version_number']} · {len(chapters)} chapters · "
            f"{report.total_blocks} content blocks",
            "",
            "## Contents",
            "",
        ]
        used_slugs: dict[str, int] = {}
        for index, item in enumerate(chapters, start=1):
            chapter_title = plain(item["chapter"]["title"])
            base = slug(chapter_title)
            used_slugs[base] = used_slugs.get(base, 0) + 1
            anchor = base if used_slugs[base] == 1 else f"{base}-{used_slugs[base]}"
            lines.append(f"{index}. [{chapter_title}](#{anchor})")
        lines.extend(["", "---", ""])

        for index, item in enumerate(chapters, start=1):
            chapter = item["chapter"]
            chapter_title = plain(chapter["title"])
            base = slug(chapter_title)
            occurrence = sum(
                1 for previous in chapters[:index]
                if slug(plain(previous["chapter"]["title"])) == base
            )
            anchor = base if occurrence == 1 else f"{base}-{occurrence}"
            lines.extend([f'<a id="{anchor}"></a>', "", f"## {chapter_title}", ""])
            if chapter.get("summary"):
                lines.extend([plain(chapter["summary"]), ""])
            if chapter.get("source_start_ms") is not None:
                start = chapter["source_start_ms"] / 1000
                end_ms = chapter.get("source_end_ms")
                interval = f"Source time: {start:.1f}s"
                if end_ms is not None:
                    interval += f"–{end_ms / 1000:.1f}s"
                lines.extend([f"*{interval}*", ""])
            for block in item["blocks"]:
                lines.extend([render_block(block), ""])

        lines.extend([
            "---",
            "",
            "*OmniIntel · Evidence-grounded learning.*",
            "",
            "> This edition passed structural publication checks. Those checks do not establish "
            "factual truth, semantic correctness, mathematical correctness or completeness.",
            "",
        ])
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines), encoding="utf-8")
        if not output.is_file() or output.stat().st_size < 100:
            raise RuntimeError("Markdown renderer did not produce a valid output file")
        return output
