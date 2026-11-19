import sqlite3
from pathlib import Path

import pytest

from omniintel.database import connect
from omniintel.store import OmniIntelStore
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.textbook import BlockInput, TextbookStore


def sample() -> TranscriptImport:
    return TranscriptImport(
        title="Intro to physics",
        source_uri="imported-transcript://physics-01",
        language="en",
        duration_ms=12_000,
        segments=(
            TranscriptSegmentInput("Motion describes change in position.", 0, 3_000),
            TranscriptSegmentInput("Velocity includes direction.", 3_000, 6_000),
        ),
    )



def test_textbook_composition_persists_versioned_blocks_and_evidence(tmp_path: Path) -> None:
    source = OmniIntelStore(tmp_path / "book.db").import_transcript(sample())
    store = TextbookStore(tmp_path / "book.db")
    textbook_id = store.create_textbook(source.source_id, "Physics Foundations")
    version_id = store.create_version(textbook_id, "First edition")
    chapter_id = store.add_chapter(version_id, "Motion", ordinal=0, source_start_ms=0, source_end_ms=6000)
    block_id = store.add_block(
        chapter_id,
        BlockInput(
            block_type="DEFINITION",
            content={"term": "Velocity", "definition": "Rate of change of displacement."},
            provenance="EXPLANATION",
            review_status="NEEDS_REVIEW",
        ),
    )
    store.link_evidence(block_id, source.evidence_ids[1], relation="SUPPORTS")
    tree = store.get_version_tree(version_id)
    assert tree is not None
    assert tree["version"]["version_number"] == 1
    assert tree["chapters"][0]["blocks"][0]["content"]["term"] == "Velocity"
    assert tree["chapters"][0]["blocks"][0]["evidence"][0]["evidence_id"] == source.evidence_ids[1]


def test_textbook_rejects_cross_source_evidence(tmp_path: Path) -> None:
    path = tmp_path / "book.db"
    first = OmniIntelStore(path).import_transcript(sample())
    second = OmniIntelStore(path).import_transcript(
        TranscriptImport(title="Chemistry", segments=(TranscriptSegmentInput("Atoms matter.", 0, 1000),))
    )
    store = TextbookStore(path)
    book = store.create_textbook(first.source_id, "Physics")
    version = store.create_version(book, "Draft")
    chapter = store.add_chapter(version, "Motion", ordinal=0)
    block = store.add_block(chapter, BlockInput("PARAGRAPH", {"text": "Velocity changes."}, "EXPLANATION"))
    with pytest.raises(sqlite3.IntegrityError, match="same source"):
        store.link_evidence(block, second.evidence_ids[0])


def test_textbook_rejects_invalid_block_payload(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="finite JSON"):
        BlockInput("PARAGRAPH", {"bad": float("nan")}, "EXPLANATION").validate()


def test_textbook_parent_block_must_be_in_same_chapter(tmp_path: Path) -> None:
    path = tmp_path / "book.db"
    imported = OmniIntelStore(path).import_transcript(sample())
    store = TextbookStore(path)
    book = store.create_textbook(imported.source_id, "Physics")
    version = store.create_version(book, "Draft")
    chapter_a = store.add_chapter(version, "A", ordinal=0)
    chapter_b = store.add_chapter(version, "B", ordinal=1)
    parent = store.add_block(chapter_a, BlockInput("HEADING", {"text": "Heading"}, "EXPLANATION"))
    with pytest.raises(sqlite3.IntegrityError, match="same chapter"):
        store.add_block(chapter_b, BlockInput(
            "PARAGRAPH", {"text": "Body"}, "EXPLANATION", parent_block_id=parent
        ))




def test_textbook_block_hierarchy_rejects_cycles(tmp_path: Path) -> None:
    path = tmp_path / "book.db"
    imported = OmniIntelStore(path).import_transcript(sample())
    store = TextbookStore(path)
    book = store.create_textbook(imported.source_id, "Physics")
    version = store.create_version(book, "Draft")
    chapter = store.add_chapter(version, "Motion", ordinal=0)
    parent = store.add_block(chapter, BlockInput("HEADING", {"text": "Parent"}, "EXPLANATION"))
    child = store.add_block(
        chapter, BlockInput("PARAGRAPH", {"text": "Child"}, "EXPLANATION", parent_block_id=parent)
    )
    with connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="cannot contain a cycle"):
            conn.execute("UPDATE chapter_blocks SET parent_block_id=? WHERE id=?", (child, parent))
