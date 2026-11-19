"""Source-scoped topic hierarchy and reviewed topic/evidence alignment."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now

TopicProvenance = Literal["EXPLANATION", "DERIVED", "UNCERTAIN"]
TopicRelation = Literal["INTRODUCES", "DEVELOPS", "RECAPITULATES", "DEMONSTRATES", "CONTRASTS"]


@dataclass(frozen=True, slots=True)
class TopicInput:
    source_id: str
    title: str
    start_ms: int
    end_ms: int
    ordinal: int
    parent_topic_id: str | None = None
    description: str = ""
    provenance: TopicProvenance = "EXPLANATION"
    confidence: float | None = None

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("Topic title must not be empty")
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("Topic interval must satisfy 0 <= start_ms < end_ms")
        if self.ordinal < 0:
            raise ValueError("Topic ordinal must be non-negative")
        if self.provenance not in {"EXPLANATION", "DERIVED", "UNCERTAIN"}:
            raise ValueError("Topic provenance cannot be SOURCE")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("Topic confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class TopicEvidenceInput:
    topic_id: str
    evidence_id: str
    relation: TopicRelation
    relevance_score: float | None = None
    rationale: str | None = None

    def validate(self) -> None:
        if self.relation not in {
            "INTRODUCES", "DEVELOPS", "RECAPITULATES", "DEMONSTRATES", "CONTRASTS",
        }:
            raise ValueError("Unsupported topic/evidence relation")
        if self.relevance_score is not None and not 0 <= self.relevance_score <= 1:
            raise ValueError("Topic evidence relevance must be between zero and one")


class TopicStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def create_topic(self, data: TopicInput) -> str:
        data.validate()
        topic_id = uuid7()
        now = utc_now()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO topics
                   (id,source_id,parent_topic_id,title,description,start_ms,end_ms,ordinal,
                    provenance,status,confidence,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,'DRAFT',?,?,?)""",
                (topic_id, data.source_id, data.parent_topic_id, data.title.strip(),
                 data.description.strip(), data.start_ms, data.end_ms, data.ordinal,
                 data.provenance, data.confidence, now, now),
            )
        return topic_id

    def link_evidence(self, data: TopicEvidenceInput) -> str:
        data.validate()
        link_id = uuid7()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO topic_evidence
                   (id,topic_id,evidence_id,relation,review_state,relevance_score,rationale,created_at)
                   VALUES(?,?,?,?,'PENDING',?,?,?)""",
                (link_id, data.topic_id, data.evidence_id, data.relation,
                 data.relevance_score, data.rationale, utc_now()),
            )
        return link_id

    def review_link(self, link_id: str, review_state: str, *, rationale: str | None = None) -> str:
        if review_state not in {"ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
            raise ValueError("Invalid topic evidence review state")
        now = utc_now()
        with connect(self.database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            link = conn.execute(
                "SELECT topic_id FROM topic_evidence WHERE id=?", (link_id,)
            ).fetchone()
            if link is None:
                raise ValueError("Topic/evidence link does not exist")
            conn.execute(
                """UPDATE topic_evidence SET review_state=?,rationale=COALESCE(?,rationale),
                   reviewed_at=? WHERE id=?""",
                (review_state, rationale, now, link_id),
            )
            topic = conn.execute(
                "SELECT provenance FROM topics WHERE id=?", (link["topic_id"],)
            ).fetchone()
            accepted = conn.execute(
                """SELECT count(*) FROM topic_evidence
                   WHERE topic_id=? AND review_state='ACCEPTED'""",
                (link["topic_id"],),
            ).fetchone()[0]
            status = "NEEDS_REVIEW" if topic["provenance"] == "UNCERTAIN" else (
                "ACCEPTED" if accepted else "DRAFT"
            )
            conn.execute(
                "UPDATE topics SET status=?,updated_at=? WHERE id=?",
                (status, now, link["topic_id"]),
            )
        return status

    def get_outline(self, source_id: str) -> list[dict[str, object]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """SELECT t.id,t.parent_topic_id,t.title,t.description,t.start_ms,t.end_ms,
                          t.ordinal,t.provenance,t.status,t.confidence,
                          count(CASE WHEN te.review_state='ACCEPTED' THEN 1 END) AS accepted_evidence
                   FROM topics t LEFT JOIN topic_evidence te ON te.topic_id=t.id
                   WHERE t.source_id=?
                   GROUP BY t.id
                   ORDER BY t.start_ms,t.ordinal,t.id""",
                (source_id,),
            ).fetchall()
        return [dict(row) for row in rows]
