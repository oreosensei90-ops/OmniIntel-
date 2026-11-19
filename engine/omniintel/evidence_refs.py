"""Unified, source-bound citation references across transcript and document locations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now

LocatorKind = Literal["TRANSCRIPT_INTERVAL", "DOCUMENT_PAGE"]


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    id: str
    source_id: str
    locator_kind: LocatorKind
    evidence_item_id: str | None
    document_page_id: str | None
    source_asset_id: str | None
    start_ms: int | None
    end_ms: int | None
    page_number: int | None


def register_transcript_references(
    database_path: str | Path, evidence_ids: tuple[str, ...] | list[str]
) -> tuple[str, ...]:
    """Create stable citation handles for existing transcript evidence records."""
    refs: list[str] = []
    with connect(database_path) as conn:
        migrate(conn)
        conn.execute("BEGIN IMMEDIATE")
        for evidence_id in evidence_ids:
            row = conn.execute(
                "SELECT source_id,start_ms,end_ms FROM evidence_items WHERE id=?",
                (evidence_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Transcript evidence does not exist: {evidence_id}")
            existing = conn.execute(
                "SELECT id FROM evidence_refs WHERE evidence_item_id=?", (evidence_id,)
            ).fetchone()
            ref_id = existing["id"] if existing else uuid7()
            if not existing:
                conn.execute(
                    """INSERT INTO evidence_refs
                       (id,source_id,locator_kind,evidence_item_id,start_ms,end_ms,created_at)
                       VALUES(?,?,'TRANSCRIPT_INTERVAL',?,?,?,?)""",
                    (ref_id,row["source_id"],evidence_id,row["start_ms"],row["end_ms"],utc_now()),
                )
            refs.append(ref_id)
    return tuple(refs)


def register_document_page_references(
    database_path: str | Path, extraction_id: str
) -> tuple[str, ...]:
    """Create stable citation handles for every page in one completed extraction."""
    refs: list[str] = []
    with connect(database_path) as conn:
        migrate(conn)
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """SELECT dp.id AS page_id,dp.page_number,sa.source_id,sa.id AS asset_id
               FROM document_pages dp
               JOIN document_extractions de ON de.id=dp.extraction_id
               JOIN source_assets sa ON sa.id=de.source_asset_id
               WHERE dp.extraction_id=? ORDER BY dp.page_number""",
            (extraction_id,),
        ).fetchall()
        if not rows:
            raise ValueError("Document extraction has no stored pages")
        for row in rows:
            existing = conn.execute(
                "SELECT id FROM evidence_refs WHERE document_page_id=?",
                (row["page_id"],),
            ).fetchone()
            ref_id = existing["id"] if existing else uuid7()
            if not existing:
                conn.execute(
                    """INSERT INTO evidence_refs
                       (id,source_id,locator_kind,document_page_id,source_asset_id,
                        page_number,created_at)
                       VALUES(?,?,'DOCUMENT_PAGE',?,?,?,?)""",
                    (ref_id,row["source_id"],row["page_id"],row["asset_id"],
                     row["page_number"],utc_now()),
                )
            refs.append(ref_id)
    return tuple(refs)


def get_evidence_reference(
    database_path: str | Path, reference_id: str
) -> dict[str, object] | None:
    """Resolve a citation handle to source, content and its native locator."""
    with connect(database_path) as conn:
        row = conn.execute(
            """SELECT er.id,er.source_id,s.title,er.locator_kind,
                      er.evidence_item_id,er.document_page_id,er.source_asset_id,
                      er.start_ms,er.end_ms,er.page_number,
                      COALESCE(e.content,dp.text_content) AS content,
                      COALESCE(e.provenance,'SOURCE') AS provenance,
                      dp.content_sha256
               FROM evidence_refs er
               JOIN sources s ON s.id=er.source_id
               LEFT JOIN evidence_items e ON e.id=er.evidence_item_id
               LEFT JOIN document_pages dp ON dp.id=er.document_page_id
               WHERE er.id=?""",
            (reference_id,),
        ).fetchone()
    return dict(row) if row else None


def search_evidence_references(
    database_path: str | Path, query: str, *, limit: int = 50
) -> list[dict[str, object]]:
    """Search transcript and PDF-page evidence through one indexed result shape."""
    if not 1 <= limit <= 200:
        raise ValueError("Search limit must be between 1 and 200")
    terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
    if not terms:
        return []
    match_query = " AND ".join(f'"{term}"' for term in terms)
    with connect(database_path) as conn:
        rows = conn.execute(
            """SELECT er.id,er.source_id,s.title,er.locator_kind,
                      er.evidence_item_id,er.document_page_id,er.source_asset_id,
                      er.start_ms,er.end_ms,er.page_number,
                      snippet(evidence_refs_fts,1,'[',']','…',24) AS excerpt,
                      bm25(evidence_refs_fts) AS rank
               FROM evidence_refs_fts
               JOIN evidence_refs er ON er.id=evidence_refs_fts.evidence_ref_id
               JOIN sources s ON s.id=er.source_id
               WHERE evidence_refs_fts MATCH ?
               ORDER BY rank,s.created_at DESC,er.locator_kind,er.start_ms,er.page_number
               LIMIT ?""",
            (match_query,limit),
        ).fetchall()
    return [dict(row) for row in rows]
