from pathlib import Path

import pytest

from omniintel.store import OmniIntelStore
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.textbook import BlockInput, TextbookStore
from omniintel.textbook_audit import TextbookPublicationAuditor


def _book(tmp_path: Path):
    path = tmp_path / "publication.db"
    imported = OmniIntelStore(path).import_transcript(TranscriptImport(
        title="Foundations",
        segments=(TranscriptSegmentInput("A source statement.", 0, 2_000),),
        duration_ms=2_000,
    ))
    store = TextbookStore(path)
    textbook = store.create_textbook(imported.source_id, "Foundations")
    version = store.create_version(textbook, "Draft")
    chapter = store.add_chapter(version, "Chapter 1", ordinal=0)
    return path, imported, store, version, chapter


def test_publication_gate_accepts_reviewed_explanation_block(tmp_path: Path) -> None:
    path, imported, store, version, chapter = _book(tmp_path)
    block = store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "An explanation."}, "EXPLANATION",
        review_status="ACCEPTED",
    ))
    report = TextbookPublicationAuditor(path).audit(version)
    assert report.ready
    assert report.total_blocks == 1
    assert report.eligible_blocks == 1
    assert report.blocked_blocks == 0


def test_publication_gate_blocks_unreviewed_and_uncertain_blocks(tmp_path: Path) -> None:
    path, imported, store, version, chapter = _book(tmp_path)
    store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "Needs review."}, "EXPLANATION",
        review_status="NEEDS_REVIEW",
    ))
    store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "Uncertain."}, "UNCERTAIN",
        review_status="ACCEPTED",
    ))
    report = TextbookPublicationAuditor(path).audit(version)
    assert not report.ready
    assert report.blocked_blocks == 2
    codes = {finding.code for finding in report.findings}
    assert "BLOCK_NOT_ACCEPTED" in codes
    assert "UNCERTAIN_PROVENANCE" in codes


def test_publication_gate_requires_claim_support_to_be_carried(tmp_path: Path) -> None:
    from omniintel.knowledge import ClaimEvidenceInput, ClaimInput
    from omniintel.knowledge_store import KnowledgeStore

    path, imported, store, version, chapter = _book(tmp_path)
    knowledge = KnowledgeStore(path)
    claim_id = knowledge.create_claim(ClaimInput(
        "A supported claim.", provenance="EXPLANATION"
    ))
    claim_link = knowledge.link_evidence(ClaimEvidenceInput(
        claim_id, imported.evidence_ids[0], "SUPPORTS"
    ))
    assert knowledge.review_evidence_link(claim_link, "ACCEPTED") == "SUPPORTED"
    block = store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "A supported claim."}, "EXPLANATION",
        review_status="ACCEPTED", claim_id=claim_id,
    ))
    report = TextbookPublicationAuditor(path).audit(version)
    assert not report.ready
    assert report.blocked_blocks == 1
    assert any(f.code == "CLAIM_SUPPORT_NOT_CARRIED" for f in report.findings)

    store.link_evidence(block, imported.evidence_ids[0], relation="SUPPORTS",
                        review_state="ACCEPTED")
    report = TextbookPublicationAuditor(path).audit(version)
    assert report.ready
    assert report.eligible_blocks == 1
