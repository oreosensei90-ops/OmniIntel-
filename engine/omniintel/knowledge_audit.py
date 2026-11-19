"""Deterministic audits for evidence coverage and source-boundary integrity."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .database import connect, migrate


@dataclass(frozen=True, slots=True)
class AuditFinding:
    severity: str
    code: str
    record_id: str
    message: str


@dataclass(frozen=True, slots=True)
class KnowledgeAuditReport:
    total_claims: int
    claims_with_evidence: int
    claims_with_accepted_support: int
    publishable_claims: int
    contested_claims: int
    uncertain_claims: int
    claims_without_evidence: int
    accepted_contradictions: int
    evidence_out_of_source_bounds: int
    unused_knowledge_units: int
    findings: tuple[AuditFinding, ...]

    @property
    def accepted_support_ratio(self) -> float:
        """Ratio of claims with reviewed support; not a measure of source completeness."""
        if self.total_claims == 0:
            return 0.0
        return self.claims_with_accepted_support / self.total_claims

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["findings"] = [asdict(item) for item in self.findings]
        result["accepted_support_ratio"] = self.accepted_support_ratio
        result["ratio_note"] = (
            "Share of stored claims with at least one accepted SUPPORTS link; "
            "not source coverage, factual truth or subject completeness."
        )
        return result


class KnowledgeAuditor:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def audit(self) -> KnowledgeAuditReport:
        findings: list[AuditFinding] = []
        with connect(self.database_path) as conn:
            claims = conn.execute("SELECT id,status FROM claims ORDER BY id").fetchall()
            links = conn.execute(
                """SELECT ce.claim_id,ce.relation,ce.review_state,e.id AS evidence_id,
                          e.start_ms,e.end_ms,s.duration_ms
                   FROM claim_evidence ce
                   JOIN evidence_items e ON e.id=ce.evidence_id
                   JOIN sources s ON s.id=e.source_id
                   ORDER BY ce.claim_id,ce.id"""
            ).fetchall()
            bounds = conn.execute(
                """SELECT e.id,e.start_ms,e.end_ms,s.duration_ms
                   FROM evidence_items e JOIN sources s ON s.id=e.source_id
                   WHERE s.duration_ms IS NOT NULL
                     AND (e.start_ms < 0 OR e.end_ms <= e.start_ms OR e.end_ms > s.duration_ms)"""
            ).fetchall()
            unused_units = conn.execute(
                """SELECT u.id FROM knowledge_units u
                   WHERE NOT EXISTS (SELECT 1 FROM claims c WHERE c.knowledge_unit_id=u.id)"""
            ).fetchall()

        by_claim: dict[str, list[dict[str, Any]]] = {}
        for row in links:
            by_claim.setdefault(row["claim_id"], []).append(dict(row))

        with_support = 0
        publishable = 0
        contested = 0
        uncertain = 0
        without_evidence = 0
        accepted_contradictions = 0

        for claim in claims:
            claim_id = claim["id"]
            relations = by_claim.get(claim_id, [])
            if not relations:
                without_evidence += 1
                findings.append(AuditFinding(
                    "WARNING", "CLAIM_WITHOUT_EVIDENCE", claim_id,
                    "Claim has no linked source evidence.",
                ))
            support = any(
                row["relation"] == "SUPPORTS" and row["review_state"] == "ACCEPTED"
                for row in relations
            )
            contradiction = any(
                row["relation"] == "CONTRADICTS" and row["review_state"] == "ACCEPTED"
                for row in relations
            )
            if support:
                with_support += 1
            if contradiction:
                accepted_contradictions += 1
                findings.append(AuditFinding(
                    "ERROR", "ACCEPTED_CONTRADICTION", claim_id,
                    "Claim has at least one accepted contradictory evidence link.",
                ))
            if claim["status"] == "SUPPORTED" and support and not contradiction:
                publishable += 1
            elif claim["status"] == "SUPPORTED" and not support:
                findings.append(AuditFinding(
                    "ERROR", "SUPPORTED_WITHOUT_ACCEPTED_SUPPORT", claim_id,
                    "Claim status says SUPPORTED but no accepted SUPPORTS link exists.",
                ))
            if claim["status"] == "CONTESTED":
                contested += 1
            if claim["status"] == "UNCERTAIN":
                uncertain += 1

        for row in bounds:
            findings.append(AuditFinding(
                "ERROR", "EVIDENCE_OUT_OF_SOURCE_BOUNDS", row["id"],
                "Evidence timestamps exceed the known source duration or form an invalid interval.",
            ))
        for row in unused_units:
            findings.append(AuditFinding(
                "INFO", "UNREFERENCED_KNOWLEDGE_UNIT", row["id"],
                "Knowledge unit is not yet linked to a claim.",
            ))

        return KnowledgeAuditReport(
            total_claims=len(claims),
            claims_with_evidence=sum(bool(by_claim.get(row["id"])) for row in claims),
            claims_with_accepted_support=with_support,
            publishable_claims=publishable,
            contested_claims=contested,
            uncertain_claims=uncertain,
            claims_without_evidence=without_evidence,
            accepted_contradictions=accepted_contradictions,
            evidence_out_of_source_bounds=len(bounds),
            unused_knowledge_units=len(unused_units),
            findings=tuple(findings),
        )
