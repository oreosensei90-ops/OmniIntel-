from pathlib import Path

import pytest

reportlab = pytest.importorskip("reportlab")

from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.pdf_export import TextbookPDFExporter
from omniintel.store import OmniIntelStore
from omniintel.textbook import BlockInput, TextbookStore


def _ready_book(path: Path) -> tuple[str, str]:
    imported = OmniIntelStore(path).import_transcript(TranscriptImport(
        title="Physics & Motion",
        segments=(TranscriptSegmentInput("Velocity has direction.", 0, 2_000),),
        duration_ms=2_000,
    ))
    store = TextbookStore(path)
    textbook_id = store.create_textbook(imported.source_id, "Physics & Motion")
    version_id = store.create_version(textbook_id, "First edition")
    chapter_id = store.add_chapter(
        version_id, "Motion", ordinal=0, summary="An introduction to motion."
    )
    store.add_block(chapter_id, BlockInput(
        "DEFINITION",
        {"term": "Velocity", "definition": "Rate of change of displacement."},
        "EXPLANATION",
        review_status="ACCEPTED",
    ))
    store.add_block(chapter_id, BlockInput(
        "TABLE",
        {"rows": [["Quantity", "Meaning"], ["Velocity", "Speed with direction"]]},
        "EXPLANATION",
        review_status="ACCEPTED",
        ordinal=1,
    ))
    return version_id, imported.source_id


def test_pdf_exporter_renders_audited_textbook(tmp_path: Path) -> None:
    version_id, _ = _ready_book(tmp_path / "textbook.db")
    output = TextbookPDFExporter(tmp_path / "textbook.db").export(
        version_id, tmp_path / "exports" / "physics.pdf"
    )
    assert output.is_file()
    assert output.read_bytes().startswith(b"%PDF-")
    assert output.stat().st_size > 500


def test_pdf_exporter_refuses_unreviewed_blocks(tmp_path: Path) -> None:
    path = tmp_path / "blocked.db"
    imported = OmniIntelStore(path).import_transcript(TranscriptImport(
        title="Blocked", segments=(TranscriptSegmentInput("Evidence.", 0, 1_000),)
    ))
    store = TextbookStore(path)
    book = store.create_textbook(imported.source_id, "Blocked")
    version = store.create_version(book, "Draft")
    chapter = store.add_chapter(version, "Chapter", ordinal=0)
    store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "Not reviewed."}, "EXPLANATION"
    ))
    with pytest.raises(ValueError, match="not publication-ready"):
        TextbookPDFExporter(path).export(version, tmp_path / "blocked.pdf")
