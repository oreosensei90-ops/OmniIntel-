from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from omniintel.collections import CollectionStore
from omniintel.store import OmniIntelStore


def _source(database: Path, title: str) -> str:
    return OmniIntelStore(database).create_source(
        title=title, metadata={"ingestion_method": "test"},
    )


def test_course_collection_keeps_sources_independent_and_ordered(tmp_path: Path) -> None:
    database = tmp_path / "omniintel.db"
    first = _source(database, "Lecture 01")
    second = _source(database, "Slides")
    store = CollectionStore(database)
    course = store.create(
        "Physics 101", description="First semester",
        metadata={"language": "en", "term": "2026"},
    )

    assert store.add_source(course, first) == 0
    assert store.add_source(course, second, role="SLIDE_DECK") == 1
    result = store.get(course)

    assert result is not None
    assert result["title"] == "Physics 101"
    assert result["metadata"]["language"] == "en"
    assert [item["source_id"] for item in result["sources"]] == [first, second]
    assert result["sources"][1]["role"] == "SLIDE_DECK"
    assert store.list_sources(course)[0]["title"] == "Lecture 01"


def test_one_source_can_belong_to_multiple_collections(tmp_path: Path) -> None:
    database = tmp_path / "omniintel.db"
    source = _source(database, "Shared lecture")
    store = CollectionStore(database)
    course = store.create("Course")
    research = store.create("Research set", collection_type="RESEARCH_SET")

    store.add_source(course, source)
    store.add_source(research, source, role="REFERENCE")
    assert len(store.list_sources(course)) == 1
    assert len(store.list_sources(research)) == 1


def test_collection_membership_rejects_duplicates_and_unknown_records(tmp_path: Path) -> None:
    database = tmp_path / "omniintel.db"
    store = CollectionStore(database)
    course = store.create("Course")
    source = _source(database, "Lecture")
    store.add_source(course, source)

    with pytest.raises(ValueError, match="already"):
        store.add_source(course, source)
    with pytest.raises(ValueError, match="does not exist"):
        store.add_source(course, "missing-source")
    with pytest.raises(ValueError, match="does not exist"):
        store.add_source("missing-collection", source)


def test_collection_validates_title_type_metadata_and_order(tmp_path: Path) -> None:
    database = tmp_path / "omniintel.db"
    store = CollectionStore(database)
    with pytest.raises(ValueError, match="title"):
        store.create(" ")
    with pytest.raises(ValueError, match="type"):
        store.create("Course", collection_type="UNKNOWN")
    with pytest.raises(TypeError, match="JSON object"):
        store.create("Course", metadata=["not", "an", "object"])
    course = store.create("Course")
    source = _source(database, "Lecture")
    with pytest.raises(ValueError, match="ordinal"):
        store.add_source(course, source, ordinal=-1)


def test_collection_membership_order_is_unique(tmp_path: Path) -> None:
    database = tmp_path / "omniintel.db"
    first = _source(database, "First")
    second = _source(database, "Second")
    store = CollectionStore(database)
    course = store.create("Course")
    store.add_source(course, first, ordinal=3)
    with pytest.raises(sqlite3.IntegrityError):
        store.add_source(course, second, ordinal=3)
