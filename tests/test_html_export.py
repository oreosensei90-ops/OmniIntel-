from pathlib import Path

import pytest

from omniintel.html_export import TextbookHTMLExporter
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
        "PARAGRAPH", {"text": "<script>alert('x')</script> & safe text"},
        "EXPLANATION", review_status="ACCEPTED",
    ))
    store.add_block(chapter_id, BlockInput(
        "TABLE", {"rows": [["Quantity", "Meaning"], ["Velocity", "Direction"]]},
        "EXPLANATION", review_status="ACCEPTED", ordinal=1,
    ))
    return version_id


def test_html_exporter_escapes_content_and_renders_structure(tmp_path: Path) -> None:
    path = tmp_path / "textbook.db"
    version_id = _ready_book(path)
    output = TextbookHTMLExporter(path).export(version_id, tmp_path / "out" / "book.html")
    page = output.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>")
    assert "&lt;script&gt;" in page
    assert "<script>alert" not in page
    assert "<table>" in page
    assert 'href="#chapter-1"' in page
    assert "Physics &amp; Motion" in page


def test_html_exporter_refuses_unreviewed_blocks(tmp_path: Path) -> None:
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
        TextbookHTMLExporter(path).export(version, tmp_path / "blocked.html")
