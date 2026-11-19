"""Provider-neutral knowledge records and evidence-grounding rules."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

UnitType = Literal[
    "concept", "definition", "principle", "formula", "procedure", "example",
    "worked_solution", "observation", "comparison", "warning", "question", "reference",
]
Provenance = Literal["EXPLANATION", "DERIVED", "UNCERTAIN"]
ClaimRelation = Literal["SUPPORTS", "CONTRADICTS", "QUALIFIES", "CONTEXTUALIZES", "ILLUSTRATES"]
ReviewState = Literal["PENDING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW"]
ClaimStatus = Literal["DRAFT", "SUPPORTED", "CONTESTED", "UNCERTAIN", "REJECTED"]


@dataclass(frozen=True, slots=True)
class KnowledgeUnitInput:
    unit_type: UnitType
    title: str
    body: str
    provenance: Provenance = "EXPLANATION"
    status: Literal["DRAFT", "VALIDATED", "NEEDS_REVIEW", "REJECTED"] = "DRAFT"

    def validate(self) -> None:
        if self.unit_type not in {
            "concept", "definition", "principle", "formula", "procedure", "example",
            "worked_solution", "observation", "comparison", "warning", "question", "reference",
        }:
            raise ValueError("Unsupported knowledge unit type")
        if not self.title.strip() or not self.body.strip():
            raise ValueError("Knowledge unit title and body must not be empty")
        if self.provenance not in {"EXPLANATION", "DERIVED", "UNCERTAIN"}:
            raise ValueError("Knowledge unit provenance must not impersonate source evidence")


@dataclass(frozen=True, slots=True)
class ClaimInput:
    statement: str
    knowledge_unit_id: str | None = None
    provenance: Provenance = "EXPLANATION"
    confidence: float | None = None

    def validate(self) -> None:
        if not self.statement.strip():
            raise ValueError("Claim statement must not be empty")
        if self.provenance not in {"EXPLANATION", "DERIVED", "UNCERTAIN"}:
            raise ValueError("Claims must be labeled as interpretation, derivation or uncertainty")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("Claim confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class ClaimEvidenceInput:
    claim_id: str
    evidence_id: str
    relation: ClaimRelation
    relevance_score: float | None = None
    rationale: str | None = None

    def validate(self) -> None:
        if self.relation not in {
            "SUPPORTS", "CONTRADICTS", "QUALIFIES", "CONTEXTUALIZES", "ILLUSTRATES",
        }:
            raise ValueError("Unsupported claim/evidence relation")
        if self.relevance_score is not None and not 0 <= self.relevance_score <= 1:
            raise ValueError("Evidence relevance must be between zero and one")


def derive_claim_status(relations: list[dict[str, object]], provenance: str) -> ClaimStatus:
    """Compute conservative status using accepted, reviewed evidence links only."""
    accepted = [item for item in relations if item["review_state"] == "ACCEPTED"]
    supports = any(item["relation"] == "SUPPORTS" for item in accepted)
    contradicts = any(item["relation"] == "CONTRADICTS" for item in accepted)
    qualifies = any(item["relation"] == "QUALIFIES" for item in accepted)
    if contradicts and supports:
        return "CONTESTED"
    if contradicts:
        return "CONTESTED"
    if provenance == "UNCERTAIN" or qualifies:
        return "UNCERTAIN"
    if supports:
        return "SUPPORTED"
    return "DRAFT"


def is_publishable_claim(status: str) -> bool:
    """Only supported claims without accepted contradictions are publishable."""
    return status == "SUPPORTED"

@dataclass(frozen=True, slots=True)
class ClaimEvidenceReferenceInput:
    claim_id: str
    evidence_ref_id: str
    relation: ClaimRelation
    relevance_score: float | None = None
    rationale: str | None = None
    element_id: str | None = None

    def validate(self) -> None:
        if not self.claim_id or not self.evidence_ref_id:
            raise ValueError("Claim and evidence reference IDs are required")
        if self.relation not in {
            "SUPPORTS", "CONTRADICTS", "QUALIFIES", "CONTEXTUALIZES", "ILLUSTRATES",
        }:
            raise ValueError("Unsupported claim/evidence reference relation")
        if self.relevance_score is not None and not 0 <= self.relevance_score <= 1:
            raise ValueError("Evidence relevance must be between zero and one")

