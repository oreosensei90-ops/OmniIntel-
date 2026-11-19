from pathlib import Path
import sqlite3

import pytest

from omniintel.database import connect
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore
from omniintel.textbook import BlockInput, TextbookStore
from omniintel.textbook_audit import TextbookPublicationAuditor
from omniintel.textbook_review import TextbookReviewStore


def _fixture(tmp_path: Path):
    db = tmp_path / "review.db"
    imported = OmniIntelStore(db).import_transcript(TranscriptImport(
        title="Review source",
        segments=(TranscriptSegmentInput("A grounded statement.",0,1500),),
        duration_ms=1500,
    ))
    book = TextbookStore(db)
    textbook = book.create_textbook(imported.source_id,"Review book")
    version = book.create_version(textbook,"Draft")
    chapter = book.add_chapter(version,"Chapter",ordinal=0)
    block = book.add_block(chapter,BlockInput(
        "PARAGRAPH",{"text":"A grounded statement."},"EXPLANATION",
        review_status="NEEDS_REVIEW",
    ))
    link = book.link_evidence(block,imported.evidence_ids[0])
    return db,version,block,link


def test_review_workflow_lists_and_audits_pending_items(tmp_path: Path):
    db,version,block,link = _fixture(tmp_path)
    review = TextbookReviewStore(db)
    pending = review.list_pending(version)
    assert [item["id"] for item in pending["pending_blocks"]] == [block]
    assert [item["id"] for item in pending["pending_evidence_links"]] == [link]
    assert not TextbookPublicationAuditor(db).audit(version).ready


def test_review_workflow_requires_reviewer_and_rationale(tmp_path: Path):
    db,version,block,_ = _fixture(tmp_path)
    with pytest.raises(ValueError,match="identity and decision rationale"):
        TextbookReviewStore(db).review_block(
            version,block,"ACCEPTED",reviewer=" ",rationale="Looks fine",
        )


def test_review_workflow_acceptance_is_explicit_and_audited(tmp_path: Path):
    db,version,block,link = _fixture(tmp_path)
    review = TextbookReviewStore(db)
    review.review_evidence(
        version,link,"ACCEPTED",reviewer="human",rationale="Citation matches the excerpt.",
    )
    review.review_block(
        version,block,"ACCEPTED",reviewer="human",rationale="Reviewed against source.",
    )
    assert TextbookPublicationAuditor(db).audit(version).ready
    events = review.history(version)
    assert len(events) == 2
    assert {event["new_state"] for event in events} == {"ACCEPTED"}


def test_review_workflow_rejects_cross_version_ids(tmp_path: Path):
    db,_version,block,link = _fixture(tmp_path)
    with connect(db) as conn:
        conn.execute("INSERT INTO textbooks(id,source_id,title,created_at,updated_at) "
                     "SELECT 'other-book',source_id,'Other',created_at,updated_at "
                     "FROM textbooks LIMIT 1")
        conn.execute("INSERT INTO textbook_versions "
                     "(id,textbook_id,version_number,title,status,composition_mode,created_at,updated_at) "
                     "SELECT 'other-version','other-book',1,'Other','DRAFT','HYBRID',created_at,updated_at "
                     "FROM textbook_versions LIMIT 1")
    review = TextbookReviewStore(db)
    with pytest.raises(ValueError,match="selected textbook version"):
        review.review_block("other-version",block,"ACCEPTED",reviewer="human",rationale="No")
    with pytest.raises(ValueError,match="selected textbook version"):
        review.review_evidence("other-version",link,"ACCEPTED",reviewer="human",rationale="No")


def test_rejected_evidence_keeps_publication_blocked(tmp_path: Path):
    db,version,block,link = _fixture(tmp_path)
    review = TextbookReviewStore(db)
    review.review_evidence(
        version,link,"REJECTED",reviewer="human",rationale="Does not support this paragraph.",
    )
    review.review_block(
        version,block,"ACCEPTED",reviewer="human",rationale="Text checked separately.",
    )
    report = TextbookPublicationAuditor(db).audit(version)
    assert not report.ready
    assert any(item.code == "BLOCK_HAS_UNREVIEWED_EVIDENCE" for item in report.findings)


def test_review_history_cannot_be_modified_or_deleted(tmp_path: Path):
    db,version,block,_ = _fixture(tmp_path)
    review = TextbookReviewStore(db)
    review.review_block(
        version,block,"REJECTED",reviewer="human",rationale="The block is inaccurate.",
    )
    with connect(db) as conn:
        event_id = conn.execute(
            "SELECT id FROM textbook_review_events WHERE version_id=?", (version,)
        ).fetchone()["id"]
        with pytest.raises(sqlite3.IntegrityError,match="immutable"):
            conn.execute(
                "UPDATE textbook_review_events SET rationale='changed' WHERE id=?",
                (event_id,),
            )
        with pytest.raises(sqlite3.IntegrityError,match="immutable"):
            conn.execute("DELETE FROM textbook_review_events WHERE id=?", (event_id,))
