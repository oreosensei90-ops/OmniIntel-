"""Self-contained semantic HTML renderer for audited textbook versions."""
from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Any

from .export_visuals import evidence_locator_label, resolve_block_assets
from .textbook import TextbookStore
from .textbook_audit import TextbookPublicationAuditor


class TextbookHTMLExporter:
    """Render a publication-ready textbook as a self-contained HTML document."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def export(self, version_id: str, output_path: str | Path, *, asset_dir: str | Path | None = None) -> Path:
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

        def esc(value: Any) -> str:
            return html.escape(str(value), quote=True)

        def text_block(value: Any) -> str:
            return esc(value).replace("\n", "<br>")

        def render_table(rows: Any, block_id: str) -> str:
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"Table block {block_id} has no rows")
            rendered = []
            for index, row in enumerate(rows):
                if not isinstance(row, list):
                    raise TypeError(f"Table block {block_id} contains an invalid row")
                tag = "th" if index == 0 else "td"
                cells = "".join(f"<{tag}>{text_block(cell)}</{tag}>" for cell in row)
                rendered.append(f"<tr>{cells}</tr>")
            return "<div class=\"table-wrap\"><table>" + "".join(rendered) + "</table></div>"

        def render_block(block: dict[str, Any]) -> str:
            content = block["content"]
            kind = block["block_type"]
            if kind == "HEADING":
                body = f"<h3>{text_block(content.get('text', ''))}</h3>"
            elif kind in {"PARAGRAPH", "SUMMARY", "SOURCE_REFERENCE"}:
                body = f"<p>{text_block(content.get('text', content))}</p>"
            elif kind == "DEFINITION":
                body = (
                    '<dl class="definition"><dt>'
                    + text_block(content.get("term", "Definition"))
                    + "</dt><dd>"
                    + text_block(content.get("definition", content.get("text", "")))
                    + "</dd></dl>"
                )
            elif kind == "EQUATION":
                value = (
                    content.get("latex") or content.get("text")
                    or content.get("expression", "")
                )
                body = f'<pre class="equation">{esc(value)}</pre>'
            elif kind == "TABLE":
                body = render_table(content.get("rows", []), block["id"])
            elif kind == "CODE":
                body = (
                    "<pre><code>"
                    + esc(content.get("code", content.get("text", "")))
                    + "</code></pre>"
                )
            elif kind in {
                "WARNING", "MISCONCEPTION", "EXAMPLE", "WORKED_SOLUTION", "EXERCISE"
            }:
                label = kind.replace("_", " ").title()
                value = (
                    content.get("text") or content.get("body")
                    or content.get("prompt") or ""
                )
                body = (
                    f'<aside class="callout {kind.lower()}"><strong>{esc(label)}</strong>'
                    f"<p>{text_block(value)}</p></aside>"
                )
            elif kind == "FOOTNOTE":
                body = f'<p class="footnote">{text_block(content.get("text", content))}</p>'
            elif kind in {"DIAGRAM", "IMAGE"}:
                description = (
                    content.get("alt") or content.get("description")
                    or content.get("text")
                )
                if not description:
                    raise ValueError(
                        f"{kind} block {block['id']} requires an accessible description"
                    )
                rendered_images=[]
                for image_path,caption,media_type,digest in resolve_block_assets(
                    self.database_path,asset_dir,version["source_id"],block
                ):
                    if image_path.stat().st_size > 10*1024*1024:
                        raise ValueError("Self-contained HTML image exceeds the 10 MiB per-image limit")
                    encoded=base64.b64encode(image_path.read_bytes()).decode("ascii")
                    rendered_images.append(
                        f'<img src="data:{esc(media_type)};base64,{encoded}" '
                        f'alt="{esc(caption or description)}" loading="lazy">'
                    )
                body = (
                    f'<figure class="visual-placeholder">{"".join(rendered_images)}'
                    f'<figcaption>{text_block(description)}</figcaption></figure>'
                )
            else:
                raise ValueError(f"Unsupported HTML block type: {kind}")

            citations = []
            for evidence in [*block["evidence"], *block.get("evidence_references", [])]:
                if evidence["relation"] not in {
                    "SUPPORTS", "ILLUSTRATES", "CONTEXTUALIZES"
                }:
                    continue
                locator=evidence_locator_label(evidence)
                provenance=evidence.get("provenance") or evidence.get("evidence_provenance") or "SOURCE"
                citations.append(
                    '<li>Source evidence · '
                    f"{esc(locator)} · {esc(provenance)}</li>"
                )
            if citations:
                body += '<ul class="citations">' + "".join(citations) + "</ul>"
            if block["provenance"] in {"DERIVED", "EXTERNAL"}:
                body += (
                    f'<p class="provenance">Provenance: '
                    f"{esc(block['provenance'])}</p>"
                )
            return body

        nav = "".join(
            f'<li><a href="#chapter-{index + 1}">{esc(item["chapter"]["title"])}</a></li>'
            for index, item in enumerate(chapters)
        )
        chapter_html = []
        for index, item in enumerate(chapters):
            chapter = item["chapter"]
            pieces = [
                f'<section class="chapter" id="chapter-{index + 1}">',
                f"<h2>{text_block(chapter['title'])}</h2>",
            ]
            if chapter.get("summary"):
                pieces.append(f'<p class="chapter-summary">{text_block(chapter["summary"])}</p>')
            if chapter.get("source_start_ms") is not None:
                start = chapter["source_start_ms"] / 1000
                end_ms = chapter.get("source_end_ms")
                interval = f"Source time: {start:.1f}s"
                if end_ms is not None:
                    interval += f"–{end_ms / 1000:.1f}s"
                pieces.append(f'<p class="source-time">{esc(interval)}</p>')
            pieces.extend(render_block(block) for block in item["blocks"])
            pieces.append("</section>")
            chapter_html.append("\n".join(pieces))

        title = f"{version['textbook_title']} — {version['title']}"
        page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="OmniIntel">
<title>{esc(title)}</title>
<style>
:root {{ color-scheme: light; --ink:#202a44; --muted:#5d687a; --line:#dce2eb; --paper:#fff; --wash:#f3f5f8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#eef1f5; color:#273247; font:16px/1.68 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:900px; margin:32px auto; padding:48px clamp(20px,6vw,72px); background:var(--paper); box-shadow:0 8px 32px #17243a12; }}
h1,h2,h3 {{ color:var(--ink); line-height:1.25; }}
h1 {{ font-size:2.2rem; margin-bottom:.25rem; }}
h2 {{ font-size:1.65rem; border-bottom:1px solid var(--line); padding-bottom:.5rem; }}
h3 {{ font-size:1.2rem; }}
.subtitle {{ color:var(--muted); font-size:1.15rem; }}
.meta,.source-time,.provenance,.footnote,.citations {{ color:var(--muted); font-size:.86rem; }}
nav {{ background:var(--wash); padding:16px 24px; border-radius:12px; margin:28px 0; }}
nav a {{ color:#284a7b; text-decoration:none; }}
.chapter {{ margin-top:48px; }}
.chapter-summary {{ color:var(--muted); }}
.definition {{ border-left:4px solid #8396b3; padding:10px 18px; background:var(--wash); }}
.definition dt {{ font-weight:700; color:var(--ink); }}
.definition dd {{ margin-left:0; }}
.callout {{ margin:20px 0; padding:16px 20px; border:1px solid var(--line); border-radius:10px; background:var(--wash); }}
.callout p {{ margin-bottom:0; }}
pre {{ overflow-x:auto; padding:14px 16px; background:#f3f5f8; border-radius:8px; white-space:pre-wrap; overflow-wrap:anywhere; }}
.equation {{ text-align:center; font-family:ui-monospace,monospace; }}
.table-wrap {{ overflow-x:auto; margin:18px 0; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ text-align:left; vertical-align:top; padding:9px 12px; border:1px solid var(--line); }}
th {{ background:var(--wash); }}
.citations {{ padding-left:22px; margin-top:4px; }}
.visual-placeholder {{ padding:14px; background:var(--wash); border:1px dashed #9aa8bc; border-radius:8px; }}
footer {{ border-top:1px solid var(--line); margin-top:56px; padding-top:16px; color:var(--muted); font-size:.82rem; }}
@media print {{ body {{ background:white; }} main {{ margin:0; max-width:none; box-shadow:none; }} nav {{ break-inside:avoid; }} .chapter {{ break-before:page; }} }}
</style>
</head>
<body><main>
<header><p class="meta">OMNIINTEL · EVIDENCE-GROUNDED LEARNING</p>
<h1>{esc(version['textbook_title'])}</h1><p class="subtitle">{esc(version['title'])}</p>
<p class="meta">Edition {version['version_number']} · {len(chapters)} chapters · {report.total_blocks} content blocks</p></header>
<nav aria-label="Table of contents"><strong>Contents</strong><ol>{nav}</ol></nav>
{''.join(chapter_html)}
<footer>OmniIntel · Evidence-grounded learning. This edition passed structural publication checks; those checks do not establish factual truth or semantic correctness.</footer>
</main></body></html>"""

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(page, encoding="utf-8")
        if not output.is_file() or output.stat().st_size < 500:
            raise RuntimeError("HTML renderer did not produce a valid output file")
        if not page.startswith("<!doctype html>"):
            raise RuntimeError("Rendered output is not an HTML document")
        return output
