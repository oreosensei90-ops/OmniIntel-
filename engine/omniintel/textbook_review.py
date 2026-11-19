"""Explicit human review workflow for textbook blocks and evidence links."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now
from .textbook_audit import TextbookPublicationAuditor


class TextbookReviewStore:
    """Version-scoped human review with an immutable decision trail."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def list_pending(self, version_id: str) -> dict[str, Any]:
        with connect(self.database_path) as conn:
            if not conn.execute(
                "SELECT 1 FROM textbook_versions WHERE id=?", (version_id,)
            ).fetchone():
                raise ValueError("Textbook version does not exist")
            blocks = conn.execute(
                """SELECT b.id,b.block_type,b.provenance,b.review_status,b.content_json,
                          c.id AS chapter_id,c.title AS chapter_title
                   FROM chapter_blocks b JOIN textbook_chapters c ON c.id=b.chapter_id
                   WHERE c.version_id=? AND b.review_status IN ('DRAFT','NEEDS_REVIEW')
                   ORDER BY c.ordinal,b.ordinal,b.id""", (version_id,),
            ).fetchall()
            evidence = conn.execute(
                """SELECT 'BLOCK_EVIDENCE' AS table_name,be.id,be.block_id,
                          be.evidence_id AS reference_id,be.relation,be.review_state,
                          be.rationale,e.content AS excerpt,e.start_ms,e.end_ms
                   FROM block_evidence be
                   JOIN chapter_blocks b ON b.id=be.block_id
                   JOIN textbook_chapters c ON c.id=b.chapter_id
                   JOIN evidence_items e ON e.id=be.evidence_id
                   WHERE c.version_id=? AND be.review_state IN ('PENDING','NEEDS_REVIEW')
                   UNION ALL
                   SELECT 'BLOCK_EVIDENCE_REF',ber.id,ber.block_id,
                          ber.evidence_ref_id,ber.relation,ber.review_state,
                          ber.rationale,
                          COALESCE(e.content,dp.text_content,ocr.text_content),
                          er.start_ms,er.end_ms
                   FROM block_evidence_refs ber
                   JOIN chapter_blocks b ON b.id=ber.block_id
                   JOIN textbook_chapters c ON c.id=b.chapter_id
                   JOIN evidence_refs er ON er.id=ber.evidence_ref_id
                   LEFT JOIN evidence_items e ON e.id=er.evidence_item_id
                   LEFT JOIN document_pages dp ON dp.id=er.document_page_id
                   LEFT JOIN document_ocr_pages ocr ON ocr.page_id=dp.id
                   WHERE c.version_id=? AND ber.review_state IN ('PENDING','NEEDS_REVIEW')
                   ORDER BY 1,2""", (version_id,version_id),
            ).fetchall()
        return {
            "version_id": version_id,
            "pending_blocks": [
                {**dict(row), "content": json.loads(row["content_json"])}
                for row in blocks
            ],
            "pending_evidence_links": [dict(row) for row in evidence],
        }

    def review_block(
        self, version_id: str, block_id: str, state: str, *,
        reviewer: str, rationale: str,
    ) -> str:
        if state not in {"ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
            raise ValueError("Unsupported block review decision")
        self._validate_reviewer(reviewer, rationale)
        with connect(self.database_path) as conn:
            row = conn.execute(
                """SELECT b.review_status FROM chapter_blocks b
                   JOIN textbook_chapters c ON c.id=b.chapter_id
                   WHERE b.id=? AND c.version_id=?""", (block_id,version_id),
            ).fetchone()
            if row is None:
                raise ValueError("Block does not belong to the selected textbook version")
            self._record(
                conn,version_id,"BLOCK",block_id,row["review_status"],state,
                reviewer,rationale,
            )
            conn.execute(
                "UPDATE chapter_blocks SET review_status=?,updated_at=? WHERE id=?",
                (state,utc_now(),block_id),
            )
        return state

    def review_evidence(
        self, version_id: str, link_id: str, state: str, *,
        reviewer: str, rationale: str,
    ) -> str:
        if state not in {"ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
            raise ValueError("Unsupported evidence review decision")
        self._validate_reviewer(reviewer, rationale)
        with connect(self.database_path) as conn:
            row = conn.execute(
                """SELECT 'BLOCK_EVIDENCE' AS table_name,be.review_state
                   FROM block_evidence be
                   JOIN chapter_blocks b ON b.id=be.block_id
                   JOIN textbook_chapters c ON c.id=b.chapter_id
                   WHERE be.id=? AND c.version_id=?
                   UNION ALL
                   SELECT 'BLOCK_EVIDENCE_REF',ber.review_state
                   FROM block_evidence_refs ber
                   JOIN chapter_blocks b ON b.id=ber.block_id
                   JOIN textbook_chapters c ON c.id=b.chapter_id
                   WHERE ber.id=? AND c.version_id=?""",
                (link_id,version_id,link_id,version_id),
            ).fetchone()
            if row is None:
                raise ValueError("Evidence link does not belong to the selected textbook version")
            self._record(
                conn,version_id,"EVIDENCE",link_id,row["review_state"],state,
                reviewer,rationale,
            )
            table = row["table_name"]
            conn.execute(
                f"UPDATE {table} SET review_state=?,rationale=? WHERE id=?",
                (state,rationale,link_id),
            )
        return state

    @staticmethod
    def _validate_reviewer(reviewer: str, rationale: str) -> None:
        if not reviewer.strip() or not rationale.strip():
            raise ValueError("Reviewer identity and decision rationale are required")

    @staticmethod
    def _record(
        conn, version_id: str, target_type: str, target_id: str,
        previous: str, new: str, reviewer: str, rationale: str,
    ) -> None:
        conn.execute(
            """INSERT INTO textbook_review_events
               (id,version_id,target_type,target_id,previous_state,new_state,
                reviewer,rationale,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (uuid7(),version_id,target_type,target_id,previous,new,
             reviewer.strip(),rationale.strip(),utc_now()),
        )

    def history(self, version_id: str) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            if not conn.execute(
                "SELECT 1 FROM textbook_versions WHERE id=?", (version_id,)
            ).fetchone():
                raise ValueError("Textbook version does not exist")
            rows = conn.execute(
                """SELECT * FROM textbook_review_events
                   WHERE version_id=? ORDER BY created_at,id""", (version_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(prog="omniintel-textbook-review")
    sub = parser.add_subparsers(dest="command", required=True)
    pending = sub.add_parser("pending", help="List blocks and citations awaiting human review")
    pending.add_argument("database", type=Path)
    pending.add_argument("version_id")
    for command, help_text in (
        ("review-block", "Accept or reject a generated textbook block"),
        ("review-evidence", "Accept or reject a block-to-evidence citation"),
    ):
        item = sub.add_parser(command, help=help_text)
        item.add_argument("database", type=Path)
        item.add_argument("version_id")
        item.add_argument("record_id")
        item.add_argument("state", choices=["ACCEPTED","REJECTED","NEEDS_REVIEW"])
        item.add_argument("--reviewer", required=True)
        item.add_argument("--rationale", required=True)
    history = sub.add_parser("history", help="Show immutable human review decisions")
    history.add_argument("database", type=Path)
    history.add_argument("version_id")
    audit = sub.add_parser("audit", help="Run the publication gate after review")
    audit.add_argument("database", type=Path)
    audit.add_argument("version_id")
    args = parser.parse_args()
    store = TextbookReviewStore(args.database)
    if args.command == "pending":
        result = store.list_pending(args.version_id)
    elif args.command == "review-block":
        state = store.review_block(
            args.version_id,args.record_id,args.state,
            reviewer=args.reviewer,rationale=args.rationale,
        )
        result = {"block_id":args.record_id,"review_status":state}
    elif args.command == "review-evidence":
        state = store.review_evidence(
            args.version_id,args.record_id,args.state,
            reviewer=args.reviewer,rationale=args.rationale,
        )
        result = {"link_id":args.record_id,"review_state":state}
    elif args.command == "history":
        result = {"events":store.history(args.version_id)}
    else:
        report = TextbookPublicationAuditor(args.database).audit(args.version_id)
        result = report.to_dict()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.command == "audit" and not result["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
