import sqlite3
from pathlib import Path

import pytest

from omniintel.knowledge import (
    ClaimEvidenceInput,
    ClaimInput,
    KnowledgeUnitInput,
    derive_claim_status,
    is_publishable_claim,
)
from omniintel.knowledge_store import KnowledgeStore
from omniintel.knowledge_audit import KnowledgeAuditor
from omniintel.topics import TopicEvidenceInput, TopicInput, TopicStore
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore


def imported_evidence(tmp_path: Path):
    path = tmp_path / "knowledge.db"
    result = OmniIntelStore(path).import_transcript(
        TranscriptImport(
            title="Physics lecture",
            duration_ms=10_000,
            segments=(TranscriptSegmentInput("Energy is conserved.", 100, 900),),
        )
    )
    return path, result.evidence_ids[0]


def test_claim_requires_reviewed_support_before_publish(tmp_path: Path):
    path, evidence_id = imported_evidence(tmp_path)
    store = KnowledgeStore(path)
    claim_id = store.create_claim(
        ClaimInput("The lecture states that energy is conserved.", provenance="EXPLANATION")
    )
    link_id = store.link_evidence(
        ClaimEvidenceInput(claim_id, evidence_id, "SUPPORTS", 0.98, "Direct transcript match")
    )
    assert store.get_claim_bundle(claim_id)["claim"]["status"] == "DRAFT"
    assert store.publishable_claims() == []
    assert store.review_evidence_link(link_id, "ACCEPTED") == "SUPPORTED"
    assert store.publishable_claims()[0]["id"] == claim_id


def test_accepted_contradiction_blocks_publication(tmp_path: Path):
    path, evidence_id = imported_evidence(tmp_path)
    store = KnowledgeStore(path)
    claim_id = store.create_claim(ClaimInput("A claim that is challenged"))
    support = store.link_evidence(
        ClaimEvidenceInput(claim_id, evidence_id, "SUPPORTS", 0.9)
    )
    assert store.review_evidence_link(support, "ACCEPTED") == "SUPPORTED"
    contradiction = store.link_evidence(
        ClaimEvidenceInput(claim_id, evidence_id, "CONTRADICTS", 0.7)
    )
    assert store.review_evidence_link(contradiction, "ACCEPTED") == "CONTESTED"
    assert store.publishable_claims() == []


def test_pending_or_rejected_evidence_never_counts_as_support():
    pending = [{"relation": "SUPPORTS", "review_state": "PENDING"}]
    rejected = [{"relation": "SUPPORTS", "review_state": "REJECTED"}]
    assert derive_claim_status(pending, "EXPLANATION") == "DRAFT"
    assert derive_claim_status(rejected, "EXPLANATION") == "DRAFT"
    assert not is_publishable_claim("DRAFT")


def test_uncertain_claim_remains_uncertain_even_with_support():
    accepted = [{"relation": "SUPPORTS", "review_state": "ACCEPTED"}]
    assert derive_claim_status(accepted, "UNCERTAIN") == "UNCERTAIN"


def test_knowledge_unit_and_relationship_persist(tmp_path: Path):
    store = KnowledgeStore(tmp_path / "graph.db")
    first = store.create_unit(KnowledgeUnitInput("concept", "Energy", "A physical quantity."))
    second = store.create_unit(
        KnowledgeUnitInput("principle", "Conservation", "Energy is conserved.", "DERIVED")
    )
    relation_id = store.add_relationship(first, second, "EXPLAINS")
    assert relation_id
    with pytest.raises(ValueError):
        store.add_relationship(first, first, "EXPLAINS")


def test_knowledge_unit_cannot_claim_source_provenance():
    with pytest.raises(ValueError):
        KnowledgeUnitInput("concept", "X", "Y", "SOURCE").validate()



def test_audit_reports_evidence_coverage_without_claiming_source_completeness(tmp_path: Path):
    path, evidence_id = imported_evidence(tmp_path)
    store = KnowledgeStore(path)
    supported = store.create_claim(ClaimInput("Supported claim"))
    link = store.link_evidence(
        ClaimEvidenceInput(supported, evidence_id, "SUPPORTS", 0.95)
    )
    store.review_evidence_link(link, "ACCEPTED")
    store.create_claim(ClaimInput("Unreviewed claim"))
    report = KnowledgeAuditor(path).audit()
    assert report.total_claims == 2
    assert report.claims_with_accepted_support == 1
    assert report.publishable_claims == 1
    assert report.claims_without_evidence == 1
    assert report.accepted_support_ratio == 0.5
    assert "not source coverage" in report.to_dict()["ratio_note"]



def test_topic_outline_requires_reviewed_source_evidence(tmp_path: Path):
    path, evidence_id = imported_evidence(tmp_path)
    with sqlite3.connect(path) as conn:
        source_id = conn.execute(
            "SELECT source_id FROM evidence_items WHERE id=?", (evidence_id,)
        ).fetchone()[0]
    topics = TopicStore(path)
    root = topics.create_topic(
        TopicInput(source_id, "Energy conservation", 0, 1_000, 0)
    )
    child = topics.create_topic(
        TopicInput(
            source_id, "Worked example", 100, 900, 1,
            parent_topic_id=root, provenance="DERIVED",
        )
    )
    link = topics.link_evidence(
        TopicEvidenceInput(child, evidence_id, "DEMONSTRATES", 0.9)
    )
    outline = topics.get_outline(source_id)
    assert outline[1]["status"] == "DRAFT"
    assert topics.review_link(link, "ACCEPTED") == "ACCEPTED"


def test_topic_cannot_exceed_source_duration_or_link_other_source(tmp_path: Path):
    path, evidence_id = imported_evidence(tmp_path)
    other = OmniIntelStore(path).import_transcript(
        TranscriptImport(
            title="Second source",
            duration_ms=10_000,
            segments=(TranscriptSegmentInput("Different source evidence.", 100, 900),),
        )
    )
    with sqlite3.connect(path) as conn:
        source_id = conn.execute(
            "SELECT source_id FROM evidence_items WHERE id=?", (evidence_id,)
        ).fetchone()[0]
    topics = TopicStore(path)
    with pytest.raises(sqlite3.IntegrityError):
        topics.create_topic(TopicInput(source_id, "Too long", 0, 20_000, 0))
    topic_id = topics.create_topic(
        TopicInput(source_id, "Valid topic", 0, 1_000, 0)
    )
    with pytest.raises(sqlite3.IntegrityError):
        topics.link_evidence(
            TopicEvidenceInput(topic_id, other.evidence_ids[0], "DEVELOPS")
        )


def test_uncertain_topic_never_becomes_accepted(tmp_path: Path):
    path, evidence_id = imported_evidence(tmp_path)
    with sqlite3.connect(path) as conn:
        source_id = conn.execute(
            "SELECT source_id FROM evidence_items WHERE id=?", (evidence_id,)
        ).fetchone()[0]
    topics = TopicStore(path)
    topic_id = topics.create_topic(
        TopicInput(source_id, "Uncertain topic", 0, 1_000, 0, provenance="UNCERTAIN")
    )
    link = topics.link_evidence(
        TopicEvidenceInput(topic_id, evidence_id, "INTRODUCES")
    )
    assert topics.review_link(link, "ACCEPTED") == "NEEDS_REVIEW"



def test_topic_evidence_must_overlap_topic_time_range(tmp_path: Path):
    path, evidence_id = imported_evidence(tmp_path)
    with sqlite3.connect(path) as conn:
        source_id = conn.execute(
            "SELECT source_id FROM evidence_items WHERE id=?", (evidence_id,)
        ).fetchone()[0]
    topics = TopicStore(path)
    topic_id = topics.create_topic(
        TopicInput(source_id, "Unrelated time window", 2_000, 3_000, 0)
    )
    with pytest.raises(sqlite3.IntegrityError):
        topics.link_evidence(
            TopicEvidenceInput(topic_id, evidence_id, "DEVELOPS")
        )

def test_document_page_reference_can_support_and_contest_claim(tmp_path: Path):
    from reportlab.pdfgen import canvas

    from omniintel.document_pdf import extract_pdf
    from omniintel.evidence_refs import register_document_page_references
    from omniintel.local_files import import_local_file
    from omniintel.knowledge import ClaimEvidenceReferenceInput

    pdf = tmp_path / "lecture.pdf"
    output = canvas.Canvas(str(pdf))
    output.drawString(72, 720, "Momentum is conserved in an isolated system.")
    output.showPage()
    output.save()
    database = tmp_path / "knowledge.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database, assets, pdf)
    extraction = extract_pdf(database, assets, imported.asset.id)
    refs = register_document_page_references(database, extraction.extraction_id)
    assert refs == extraction.evidence_ref_ids

    store = KnowledgeStore(database)
    claim = store.create_claim(ClaimInput("Momentum is conserved in an isolated system."))
    support = store.link_evidence_reference(
        ClaimEvidenceReferenceInput(claim, refs[0], "SUPPORTS", 0.99)
    )
    assert store.review_evidence_reference_link(support, "ACCEPTED") == "SUPPORTED"
    bundle = store.get_claim_bundle(claim)
    assert bundle["evidence_references"][0]["page_number"] == 1
    assert store.publishable_claims()[0]["id"] == claim
    audit = KnowledgeAuditor(database).audit()
    assert audit.claims_with_accepted_support == 1
    assert audit.publishable_claims == 1

    contradiction = store.link_evidence_reference(
        ClaimEvidenceReferenceInput(claim, refs[0], "CONTRADICTS", 0.8)
    )
    assert store.review_evidence_reference_link(contradiction, "ACCEPTED") == "CONTESTED"
    assert store.publishable_claims() == []

def test_document_topics_use_page_references_without_fake_timestamps(tmp_path: Path):
    from reportlab.pdfgen import canvas

    from omniintel.document_pdf import extract_pdf
    from omniintel.local_files import import_local_file
    from omniintel.topics import (
        DocumentTopicEvidenceInput,
        DocumentTopicInput,
    )

    pdf = tmp_path / "chapters.pdf"
    output = canvas.Canvas(str(pdf))
    output.drawString(72, 720, "Newton laws of motion")
    output.showPage()
    output.drawString(72, 720, "Conservation of momentum")
    output.showPage()
    output.save()
    database = tmp_path / "topics.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database, assets, pdf)
    extraction = extract_pdf(database, assets, imported.asset.id)

    topics = TopicStore(database)
    root = topics.create_document_topic(
        DocumentTopicInput(imported.source_id, "Classical mechanics", 0)
    )
    child = topics.create_document_topic(
        DocumentTopicInput(
            imported.source_id, "Newton's laws", 1, parent_topic_id=root,
            provenance="DERIVED",
        )
    )
    link = topics.link_document_evidence(
        DocumentTopicEvidenceInput(child, extraction.evidence_ref_ids[0], "INTRODUCES", 0.98)
    )
    assert topics.get_document_outline(imported.source_id)[1]["status"] == "DRAFT"
    assert topics.review_document_evidence_link(link, "ACCEPTED") == "ACCEPTED"
    outline = topics.get_document_outline(imported.source_id)
    citation = outline[1]["evidence_references"][0]
    assert citation["locator_kind"] == "DOCUMENT_PAGE"
    assert citation["page_number"] == 1
    assert citation["start_ms"] is None and citation["end_ms"] is None


def test_document_topic_rejects_evidence_from_another_source(tmp_path: Path):
    from reportlab.pdfgen import canvas

    from omniintel.document_pdf import extract_pdf
    from omniintel.local_files import import_local_file
    from omniintel.topics import DocumentTopicEvidenceInput, DocumentTopicInput

    pdf = tmp_path / "one.pdf"
    output = canvas.Canvas(str(pdf))
    output.drawString(72, 720, "Source one page")
    output.showPage()
    output.save()
    database = tmp_path / "topics.db"
    assets = tmp_path / "assets"
    first = import_local_file(database, assets, pdf, title="First")
    second = import_local_file(database, assets, pdf, title="Second")
    extraction = extract_pdf(database, assets, first.asset.id)
    topic_id = TopicStore(database).create_document_topic(
        DocumentTopicInput(second.source_id, "Other source", 0)
    )
    with pytest.raises(sqlite3.IntegrityError, match="same source"):
        TopicStore(database).link_document_evidence(
            DocumentTopicEvidenceInput(topic_id, extraction.evidence_ref_ids[0], "DEVELOPS")
        )

