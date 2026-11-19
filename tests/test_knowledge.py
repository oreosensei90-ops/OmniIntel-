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
