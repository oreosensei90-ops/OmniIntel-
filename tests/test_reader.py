from pathlib import Path

from omniintel.alignment import AlignmentStore
from omniintel.collections import CollectionStore
from omniintel.course_textbook import CourseTextbookStore
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.reader import SynchronizedReader
from omniintel.store import OmniIntelStore


def add_source(db: Path, title: str):
    return OmniIntelStore(db).import_transcript(TranscriptImport(
        title=title,segments=(TranscriptSegmentInput(f"Spoken words: {title}",0,5000),)
    ))


def test_reader_uses_only_accepted_clock_alignment_and_persists_position(tmp_path: Path) -> None:
    db=tmp_path/"reader.sqlite"
    a,b=add_source(db,"Anchor lecture"),add_source(db,"Second recording")
    collections=CollectionStore(db)
    course=collections.create("Course")
    collections.add_source(course,a.source_id)
    collections.add_source(course,b.source_id)
    books=CourseTextbookStore(db)
    book=books.create(course,"Course textbook")
    version=books.create_version(book,"v1")
    chapter=books.add_chapter(version,"Second recording chapter",ordinal=0,source_id=b.source_id)
    block=books.add_block(chapter,"PARAGRAPH",{"text":"A grounded paragraph"},provenance="SOURCE",review_status="ACCEPTED")
    link=books.link_evidence(block,b.evidence_ref_ids[0])
    books.review_evidence(link,"ACCEPTED")
    estimate={"offset_ms":1200,"sample_interval_ms":100,"correlation":0.95,"runner_up_correlation":0.4}
    alignment=AlignmentStore(db).propose(
        course,a.source_id,b.source_id,estimate,rationale="Measured shared audio envelope",
        signal_a=[0,1,0,2,0,1,0,2],signal_b=[0,1,0,2,0,1,0,2],
    )
    reader=SynchronizedReader(db)
    before=reader.open_version(version,anchor_source_id=a.source_id)
    ev=before["chapters"][0]["blocks"][0]["evidence"][0]
    assert ev["course_time_ms"] is None
    AlignmentStore(db).review(alignment,"ACCEPTED")
    after=reader.open_version(version,anchor_source_id=a.source_id)
    ev=after["chapters"][0]["blocks"][0]["evidence"][0]
    assert ev["course_time_ms"]==1200
    assert ev["source"]["title"]=="Second recording"
    assert ev["transcript_excerpt"][0]["text"]=="Spoken words: Second recording"
    reader.save_position("session-1",version,anchor_source_id=a.source_id,
                         current_source_id=b.source_id,position_ms=1200,chapter_id=chapter,block_id=block)
    assert reader.resume("session-1")["position_ms"]==1200


def test_reader_rejects_foreign_session_source(tmp_path: Path) -> None:
    db=tmp_path/"reader.sqlite"
    source=add_source(db,"Lecture")
    foreign=add_source(db,"Foreign")
    course=CollectionStore(db).create("Course")
    CollectionStore(db).add_source(course,source.source_id)
    books=CourseTextbookStore(db)
    version=books.create_version(books.create(course,"Book"),"v1")
    reader=SynchronizedReader(db)
    import pytest
    from omniintel.reader import ReaderError
    with pytest.raises(ReaderError,match="not in the course"):
        reader.save_position("session",version,anchor_source_id=foreign.source_id,
                             current_source_id=source.source_id,position_ms=0)
