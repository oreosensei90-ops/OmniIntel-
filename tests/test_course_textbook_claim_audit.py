from pathlib import Path

from omniintel.collections import CollectionStore
from omniintel.course_textbook import CourseTextbookStore
from omniintel.database import connect
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore


def test_claim_requires_same_accepted_support_as_course_block(tmp_path: Path) -> None:
    db=tmp_path/"claims.sqlite"
    imported=OmniIntelStore(db).import_transcript(TranscriptImport(
        title="Lecture",segments=(TranscriptSegmentInput("Evidence sentence",0,1000),)
    ))
    course=CollectionStore(db).create("Course")
    CollectionStore(db).add_source(course,imported.source_id)
    books=CourseTextbookStore(db)
    version=books.create_version(books.create(course,"Book"),"Draft")
    chapter=books.add_chapter(version,"Chapter",ordinal=0,source_id=imported.source_id)
    with connect(db) as conn:
        conn.execute(
            """INSERT INTO claims(id,statement,provenance,status,created_at,updated_at)
               VALUES('claim-1','A grounded claim','EXPLANATION','SUPPORTED','now','now')"""
        )
        conn.execute(
            """INSERT INTO claim_evidence_refs
               (id,claim_id,evidence_ref_id,relation,review_state,created_at)
               VALUES('claim-link','claim-1',?,'SUPPORTS','ACCEPTED','now')""",
            (imported.evidence_ref_ids[0],),
        )
    block=books.add_block(chapter,"PARAGRAPH",{"text":"Claim"},provenance="DERIVED",
                          review_status="ACCEPTED",claim_id="claim-1")
    books.link_evidence(block,imported.evidence_ref_ids[0],review_state="ACCEPTED")
    assert books.audit(version)["publishable"] is True
    # A claim with accepted support from another source cannot borrow the chapter's evidence.
    other=OmniIntelStore(db).import_transcript(TranscriptImport(
        title="Other",segments=(TranscriptSegmentInput("Unrelated sentence",0,1000),)
    ))
    # The block link itself remains source-bound by the chapter; support identity is audited.
    with connect(db) as conn:
        conn.execute("UPDATE claim_evidence_refs SET evidence_ref_id=? WHERE id='claim-link'",
                     (other.evidence_ref_ids[0],))
    report=books.audit(version)
    assert report["publishable"] is False
    assert "CLAIM_SUPPORT_NOT_CARRIED" in report["findings"][0]["errors"]
