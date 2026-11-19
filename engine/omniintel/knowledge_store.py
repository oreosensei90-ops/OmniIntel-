"""Persistence API for provider-neutral knowledge and evidence relationships."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .database import connect, migrate
from .ids import uuid7
from .knowledge import (
    ClaimEvidenceInput,
    ClaimInput,
    KnowledgeUnitInput,
    derive_claim_status,
)
from .models import utc_now


class KnowledgeStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def create_unit(self, data: KnowledgeUnitInput) -> str:
        data.validate()
        unit_id = uuid7()
        now = utc_now()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO knowledge_units
                   (id,unit_type,title,body,provenance,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (unit_id, data.unit_type, data.title.strip(), data.body.strip(),
                 data.provenance, data.status, now, now),
            )
        return unit_id

    def create_claim(self, data: ClaimInput) -> str:
        data.validate()
        claim_id = uuid7()
        now = utc_now()
        with connect(self.database_path) as conn:
            if data.knowledge_unit_id is not None and not conn.execute(
                "SELECT 1 FROM knowledge_units WHERE id=?", (data.knowledge_unit_id,)
            ).fetchone():
                raise ValueError("Knowledge unit does not exist")
            conn.execute(
                """INSERT INTO claims
                   (id,knowledge_unit_id,statement,provenance,status,confidence,created_at,updated_at)
                   VALUES(?,?,?,?,'DRAFT',?,?,?)""",
                (claim_id, data.knowledge_unit_id, data.statement.strip(),
                 data.provenance, data.confidence, now, now),
            )
        return claim_id

    def link_evidence(self, data: ClaimEvidenceInput) -> str:
        data.validate()
        link_id = uuid7()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO claim_evidence
                   (id,claim_id,evidence_id,relation,review_state,relevance_score,rationale,created_at)
                   VALUES(?,?,?,?,'PENDING',?,?,?)""",
                (link_id, data.claim_id, data.evidence_id, data.relation,
                 data.relevance_score, data.rationale, utc_now()),
            )
        return link_id

    def review_evidence_link(
        self, link_id: str, review_state: str, *, rationale: str | None = None
    ) -> str:
        if review_state not in {"ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
            raise ValueError("Review state must be ACCEPTED, REJECTED or NEEDS_REVIEW")
        now = utc_now()
        with connect(self.database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            link = conn.execute(
                "SELECT claim_id FROM claim_evidence WHERE id=?", (link_id,)
            ).fetchone()
            if link is None:
                raise ValueError("Claim/evidence link does not exist")
            conn.execute(
                """UPDATE claim_evidence SET review_state=?,rationale=COALESCE(?,rationale),
                   reviewed_at=? WHERE id=?""",
                (review_state, rationale, now, link_id),
            )
            claim = conn.execute(
                "SELECT provenance FROM claims WHERE id=?", (link["claim_id"],)
            ).fetchone()
            relations = [
                dict(row) for row in conn.execute(
                    "SELECT relation,review_state FROM claim_evidence WHERE claim_id=?",
                    (link["claim_id"],),
                ).fetchall()
            ]
            status = derive_claim_status(relations, claim["provenance"])
            conn.execute(
                "UPDATE claims SET status=?,updated_at=? WHERE id=?",
                (status, now, link["claim_id"]),
            )
        return status

    def add_relationship(
        self, from_unit_id: str, to_unit_id: str, relation: str,
        *, rationale: str | None = None,
    ) -> str:
        allowed = {
            "REQUIRES", "EXPLAINS", "DERIVED_FROM", "CONTRASTS_WITH",
            "PART_OF", "APPLIED_IN", "ILLUSTRATED_BY", "CONTRADICTS",
        }
        if relation not in allowed:
            raise ValueError("Unsupported knowledge relationship")
        if from_unit_id == to_unit_id:
            raise ValueError("A knowledge unit cannot relate to itself")
        relation_id = uuid7()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO knowledge_relationships
                   (id,from_unit_id,to_unit_id,relation,rationale,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (relation_id, from_unit_id, to_unit_id, relation, rationale, utc_now()),
            )
        return relation_id

    def get_claim_bundle(self, claim_id: str) -> dict[str, Any] | None:
        with connect(self.database_path) as conn:
            claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
            if claim is None:
                return None
            evidence = conn.execute(
                """SELECT ce.id AS link_id,ce.relation,ce.review_state,ce.relevance_score,
                          ce.rationale,ce.reviewed_at,e.id AS evidence_id,e.evidence_type,
                          e.content,e.start_ms,e.end_ms,e.provenance AS evidence_provenance,
                          e.source_id
                   FROM claim_evidence ce JOIN evidence_items e ON e.id=ce.evidence_id
                   WHERE ce.claim_id=? ORDER BY ce.created_at,ce.id""",
                (claim_id,),
            ).fetchall()
        return {"claim": dict(claim), "evidence": [dict(row) for row in evidence]}

    def publishable_claims(self) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """SELECT c.* FROM claims c
                   WHERE c.status='SUPPORTED'
                     AND EXISTS (
                       SELECT 1 FROM claim_evidence ce
                       WHERE ce.claim_id=c.id AND ce.relation='SUPPORTS'
                         AND ce.review_state='ACCEPTED'
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM claim_evidence ce
                       WHERE ce.claim_id=c.id AND ce.relation='CONTRADICTS'
                         AND ce.review_state='ACCEPTED'
                     )
                   ORDER BY c.created_at,c.id"""
            ).fetchall()
        return [dict(row) for row in rows]
