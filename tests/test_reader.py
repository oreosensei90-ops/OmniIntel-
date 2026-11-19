from pathlib import Path

from omniintel.alignment import AlignmentStore, estimate_offset
from omniintel.collections import CollectionStore
from omniintel.course_textbook import CourseTextbookStore
from omniintel.database import connect
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
    signal_a=[0,1,0,0,2,0,0,1,0,0,3,0,0,1,0,0]
    signal_b=[0,0,0,1,0,0,0,2,0,0,1,0,0,3,0,0]
    estimate=estimate_offset(signal_a,signal_b,sample_interval_ms=100,max_lag_samples=4)
    alignment=AlignmentStore(db).propose(
        course,a.source_id,b.source_id,estimate,rationale="Measured shared audio envelope",
        signal_a=signal_a,signal_b=signal_b,
    )
    reader=SynchronizedReader(db)
    before=reader.open_version(version,anchor_source_id=a.source_id)
    ev=before["chapters"][0]["blocks"][0]["evidence"][0]
    assert ev["course_time_ms"] is None
    AlignmentStore(db).review(alignment,"ACCEPTED")
    after=reader.open_version(version,anchor_source_id=a.source_id)
    import json
    from jsonschema import validate

    schema_path=Path(__file__).parents[1]/"schemas"/"reader-export.schema.json"
    validate(after,json.loads(schema_path.read_text(encoding="utf-8")))
    ev=after["chapters"][0]["blocks"][0]["evidence"][0]
    assert ev["course_time_ms"]==-300
    assert ev["course_end_time_ms"]==4700
    assert ev["clock_offset_ms"]==-300
    assert ev["alignment_status"]=="ALIGNED"
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


def test_reader_fails_closed_on_inconsistent_accepted_alignment_cycle(tmp_path: Path) -> None:
    db=tmp_path/"cycle.sqlite"
    a,b,c=(add_source(db,name) for name in ("A","B","C"))
    collection=CollectionStore(db).create("Three recordings")
    for item in (a,b,c):
        CollectionStore(db).add_source(collection,item.source_id)
    with connect(db) as conn:
        for index,(left,right,offset) in enumerate((
            (a.source_id,b.source_id,100),
            (a.source_id,c.source_id,500),
            (b.source_id,c.source_id,100),
        )):
            conn.execute(
                """INSERT INTO source_clock_alignments
                   (id,collection_id,source_a_id,source_b_id,offset_ms,sample_interval_ms,
                    correlation,runner_up_correlation,method,algorithm_version,input_hash,
                    rationale,review_state,created_at)
                   VALUES(?,?,?,?,?,100,0.95,0.2,'TEST','1',?,'fixture','ACCEPTED','now')""",
                (f"alignment-{index}",collection,left,right,offset,str(index)*64),
            )
    offsets=SynchronizedReader(db)._clock_offsets(collection,a.source_id)
    assert offsets[a.source_id] is None
    assert offsets[b.source_id] is None
    assert offsets[c.source_id] is None


def test_reader_returns_page_native_pdf_text_without_fake_timestamp(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    from omniintel.document_pdf import extract_pdf
    from omniintel.local_files import import_local_file

    pdf=tmp_path/"slides.pdf"
    output=canvas.Canvas(str(pdf))
    output.setFont("Helvetica",12)
    output.drawString(72,720,"Momentum is conserved in an isolated system.")
    output.showPage()
    output.save()
    db=tmp_path/"reader-pdf.sqlite"
    assets=tmp_path/"assets"
    imported=import_local_file(db,assets,pdf,title="Lecture slides")
    extracted=extract_pdf(db,assets,imported.asset.id)
    course=CollectionStore(db).create("Mechanics")
    CollectionStore(db).add_source(course,imported.source_id,role="SLIDE_DECK")
    books=CourseTextbookStore(db)
    version=books.create_version(books.create(course,"Mechanics book"),"v1")
    chapter=books.add_chapter(version,"Momentum",ordinal=0,source_id=imported.source_id)
    block=books.add_block(chapter,"PARAGRAPH",{"text":"Momentum is conserved."},
                          provenance="SOURCE",review_status="ACCEPTED")
    link=books.link_evidence(block,extracted.evidence_ref_ids[0])
    books.review_evidence(link,"ACCEPTED")
    opened=SynchronizedReader(db).open_version(version)
    evidence=opened["chapters"][0]["blocks"][0]["evidence"][0]
    assert evidence["document_page"]["page_number"]==1
    assert "Momentum is conserved" in evidence["document_page"]["text_content"]
    assert evidence["course_time_ms"] is None
    assert evidence["seek_available"] is False
