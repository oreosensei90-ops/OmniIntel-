import sqlite3
from pathlib import Path

import pytest

from omniintel.collections import CollectionStore
from omniintel.course_textbook import CourseTextbookStore
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore


def imported(db: Path, title: str):
    return OmniIntelStore(db).import_transcript(TranscriptImport(
        title=title,segments=(TranscriptSegmentInput(f"Evidence from {title}",0,1000),)
    ))


def test_course_textbook_keeps_evidence_source_specific_and_auditable(tmp_path: Path) -> None:
    db=tmp_path/"course.sqlite"
    first,second=imported(db,"Lecture 1"),imported(db,"Lecture 2")
    collections=CollectionStore(db)
    course=collections.create("Physics")
    collections.add_source(course,first.source_id)
    collections.add_source(course,second.source_id)
    books=CourseTextbookStore(db)
    book=books.create(course,"Physics: Complete Course")
    version=books.create_version(book,"Draft")
    chapter_a=books.add_chapter(version,"Kinematics",ordinal=0,source_id=first.source_id)
    chapter_b=books.add_chapter(version,"Dynamics",ordinal=1,source_id=second.source_id)
    block_a=books.add_block(chapter_a,"PARAGRAPH",{"text":"Kinematics source note"},provenance="SOURCE")
    link=books.link_evidence(block_a,first.evidence_ref_ids[0])
    assert books.audit(version)["publishable"] is False
    books.review_evidence(link,"ACCEPTED")
    # Block itself must also be accepted.
    from omniintel.database import connect
    with connect(db) as conn:
        conn.execute("UPDATE course_textbook_blocks SET review_status='ACCEPTED' WHERE id=?",(block_a,))
    report=books.audit(version)
    assert report["eligible_blocks"]==1
    assert report["blocked_blocks"]==0
    assert books.get_version(version)["chapters"][1]["chapter"]["source_id"]==second.source_id
    with pytest.raises(sqlite3.IntegrityError,match="chapter source"):
        books.add_chapter(version,"Foreign source",ordinal=2,source_id="not-a-course-source")
    with pytest.raises(sqlite3.IntegrityError,match="chapter source"):
        books.link_evidence(block_a,second.evidence_ref_ids[0])


def test_course_textbook_blocks_unreviewed_and_uncertain_content(tmp_path: Path) -> None:
    db=tmp_path/"course.sqlite"
    source_data=imported(db,"Lecture")
    collection=CollectionStore(db).create("Course")
    CollectionStore(db).add_source(collection,source_data.source_id)
    store=CourseTextbookStore(db)
    book=store.create(collection,"Book")
    version=store.create_version(book,"Draft")
    chapter=store.add_chapter(version,"Chapter",ordinal=0,source_id=source_data.source_id)
    store.add_block(chapter,"PARAGRAPH",{"text":"uncertain"},provenance="UNCERTAIN",review_status="DRAFT")
    report=store.audit(version)
    assert report["publishable"] is False
    assert {"BLOCK_NOT_ACCEPTED","UNCERTAIN_PROVENANCE"} <= set(report["findings"][0]["errors"])
