from pathlib import Path

import pytest

docx = pytest.importorskip("docx")

from omniintel.docx_export import TextbookDOCXExporter
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
    return version_id


def test_docx_exporter_creates_editable_word_document(tmp_path: Path) -> None:
    path = tmp_path / "textbook.db"
    version_id = _ready_book(path)
    output = TextbookDOCXExporter(path).export(
        version_id, tmp_path / "exports" / "physics.docx"
    )
    assert output.is_file()
    assert output.read_bytes().startswith(b"PK")
    document = docx.Document(output)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Physics & Motion" in text
    assert "Velocity" in text
    assert "OmniIntel" in document.sections[0].header.paragraphs[0].text
    assert len(document.tables) == 1


def test_docx_exporter_refuses_unreviewed_blocks(tmp_path: Path) -> None:
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
        TextbookDOCXExporter(path).export(version, tmp_path / "blocked.docx")
