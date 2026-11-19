from pathlib import Path

import pytest

from omniintel.markdown_export import TextbookMarkdownExporter
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore
from omniintel.textbook import BlockInput, TextbookStore


def _ready_book(path: Path) -> str:
    imported = OmniIntelStore(path).import_transcript(TranscriptImport(
        title="Physics & Motion",
        segments=(TranscriptSegmentInput("Velocity has direction.", 0, 2_000),),
        duration_ms=2_000,
    ))
    store = TextbookStore(path)
    textbook_id = store.create_textbook(imported.source_id, "Physics & Motion")
    version_id = store.create_version(textbook_id, "First edition")
    chapter_id = store.add_chapter(version_id, "Motion", ordinal=0)
    store.add_block(chapter_id, BlockInput(
        "PARAGRAPH", {"text": "A pipe | and a newline\nremain readable."},
        "EXPLANATION", review_status="ACCEPTED",
    ))
    store.add_block(chapter_id, BlockInput(
        "TABLE", {"rows": [["Quantity", "Meaning"], ["Velocity", "Direction | change"]]},
        "EXPLANATION", review_status="ACCEPTED", ordinal=1,
    ))
    store.add_block(chapter_id, BlockInput(
        "CODE", {"code": "print('hello')\n```"},
        "EXPLANATION", review_status="ACCEPTED", ordinal=2,
    ))
    store.add_block(chapter_id, BlockInput(
        "EQUATION", {"latex": "v = \\frac{\\Delta x}{\\Delta t}"},
        "EXPLANATION", review_status="ACCEPTED", ordinal=3,
    ))
    return version_id


def test_markdown_exporter_renders_portable_content(tmp_path: Path) -> None:
    path = tmp_path / "textbook.db"
    version_id = _ready_book(path)
    output = TextbookMarkdownExporter(path).export(version_id, tmp_path / "book.md")
    content = output.read_text(encoding="utf-8")
    assert content.startswith("# Physics & Motion")
    assert "[Motion](#motion)" in content
    assert r"Direction \\| change" in content
    assert "print('hello')" in content
    assert "v = \\frac" in content


def test_markdown_exporter_refuses_unreviewed_blocks(tmp_path: Path) -> None:
    path = tmp_path / "blocked.db"
    imported = OmniIntelStore(path).import_transcript(TranscriptImport(
        title="Blocked", segments=(TranscriptSegmentInput("Evidence.", 0, 1_000),)
    ))
    store = TextbookStore(path)
    book = store.create_textbook(imported.source_id, "Blocked")
    version = store.create_version(book, "Draft")
    chapter = store.add_chapter(version, "Chapter", ordinal=0)
    store.add_block(chapter, BlockInput("PARAGRAPH", {"text": "Draft"}, "EXPLANATION"))
    with pytest.raises(ValueError, match="not publication-ready"):
        TextbookMarkdownExporter(path).export(version, tmp_path / "blocked.md")
