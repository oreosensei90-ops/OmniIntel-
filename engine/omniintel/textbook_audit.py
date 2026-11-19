"""Deterministic publication gate for versioned textbook trees."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .database import connect, migrate


@dataclass(frozen=True, slots=True)
class PublicationFinding:
    severity: str
    code: str
    record_id: str
    message: str


@dataclass(frozen=True, slots=True)
class PublicationReport:
    version_id: str
    total_chapters: int
    total_blocks: int
    eligible_blocks: int
    blocked_blocks: int
    findings: tuple[PublicationFinding, ...]

    @property
    def ready(self) -> bool:
        return self.blocked_blocks == 0 and not any(
            finding.severity == "ERROR" for finding in self.findings
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["findings"] = [asdict(item) for item in self.findings]
        result["ready"] = self.ready
        return result


class TextbookPublicationAuditor:
    """Check structural/review gates; this does not prove semantic correctness."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def audit(self, version_id: str) -> PublicationReport:
        findings: list[PublicationFinding] = []
        with connect(self.database_path) as conn:
            version = conn.execute(
                "SELECT id,status FROM textbook_versions WHERE id=?", (version_id,)
            ).fetchone()
            if version is None:
                raise ValueError("Textbook version does not exist")
            chapters = conn.execute(
                "SELECT id,title FROM textbook_chapters WHERE version_id=? ORDER BY ordinal,id",
                (version_id,),
            ).fetchall()
            blocks = conn.execute(
                """SELECT b.*,c.id AS chapter_id,t.source_id
                   FROM chapter_blocks b
                   JOIN textbook_chapters c ON c.id=b.chapter_id
                   JOIN textbook_versions v ON v.id=c.version_id
                   JOIN textbooks t ON t.id=v.textbook_id
                   WHERE v.id=? ORDER BY c.ordinal,b.parent_block_id,b.ordinal,b.id""",
                (version_id,),
            ).fetchall()
            evidence_rows = conn.execute(
                """SELECT be.block_id,be.relation,be.review_state,e.id AS evidence_id,
                          e.source_id,e.provenance
                   FROM block_evidence be
                   JOIN chapter_blocks b ON b.id=be.block_id
                   JOIN textbook_chapters c ON c.id=b.chapter_id
                   JOIN evidence_items e ON e.id=be.evidence_id
                   WHERE c.version_id=? ORDER BY be.block_id,be.id""",
                (version_id,),
            ).fetchall()
            asset_rows = conn.execute(
                """SELECT ba.block_id,sa.id AS asset_id,sa.role,ab.media_type,ab.byte_size
                   FROM block_assets ba
                   JOIN source_assets sa ON sa.id=ba.asset_id
                   JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
                   JOIN chapter_blocks b ON b.id=ba.block_id
                   JOIN textbook_chapters ch ON ch.id=b.chapter_id
                   WHERE ch.version_id=? ORDER BY ba.block_id,ba.ordinal,ba.id""",
                (version_id,),
            ).fetchall()
            claim_rows = conn.execute(
                """SELECT c.id,c.status,c.provenance,ce.evidence_id,ce.relation,ce.review_state
                   FROM claims c
                   LEFT JOIN claim_evidence ce ON ce.claim_id=c.id
                   WHERE c.id IN (
                       SELECT claim_id FROM chapter_blocks b
                       JOIN textbook_chapters ch ON ch.id=b.chapter_id
                       WHERE ch.version_id=? AND claim_id IS NOT NULL
                   )
                   ORDER BY c.id,ce.id""",
                (version_id,),
            ).fetchall()

        assets_by_block: dict[str, list[dict[str, Any]]] = {}
        for row in asset_rows:
            assets_by_block.setdefault(row["block_id"], []).append(dict(row))

        by_block: dict[str, list[dict[str, Any]]] = {}
        for row in evidence_rows:
            by_block.setdefault(row["block_id"], []).append(dict(row))
        by_claim: dict[str, list[dict[str, Any]]] = {}
        claim_status: dict[str, dict[str, str]] = {}
        for row in claim_rows:
            claim_status[row["id"]] = {
                "status": row["status"], "provenance": row["provenance"]
            }
            if row["evidence_id"] is not None:
                by_claim.setdefault(row["id"], []).append(dict(row))

        blocked_ids: set[str] = set()
        if not blocks:
            findings.append(PublicationFinding(
                "ERROR", "EMPTY_TEXTBOOK", version_id,
                "A textbook version must contain at least one content block.",
            ))

        for chapter in chapters:
            if not any(block["chapter_id"] == chapter["id"] for block in blocks):
                findings.append(PublicationFinding(
                    "WARNING", "EMPTY_CHAPTER", chapter["id"],
                    "Chapter has no content blocks; confirm this is intentional.",
                ))

        for block in blocks:
            block_id = block["id"]
            reasons: list[tuple[str, str]] = []
            if block["review_status"] != "ACCEPTED":
                reasons.append(("BLOCK_NOT_ACCEPTED", "Block is not in ACCEPTED review state."))
            if block["provenance"] == "UNCERTAIN":
                reasons.append(("UNCERTAIN_PROVENANCE", "Uncertain content cannot be published."))
            links = by_block.get(block_id, [])
            attached_assets = assets_by_block.get(block_id, [])
            if block["block_type"] in {"IMAGE", "DIAGRAM"}:
                if not attached_assets:
                    reasons.append(("MISSING_VISUAL_ASSET",
                                    "IMAGE and DIAGRAM blocks require at least one linked image asset."))
                elif any(not item["media_type"].startswith("image/") for item in attached_assets):
                    reasons.append(("INVALID_VISUAL_ASSET",
                                    "Every linked visual asset must have an image media type."))
            if any(item["relation"] == "CONTRADICTS" and item["review_state"] == "ACCEPTED"
                   for item in links):
                reasons.append(("BLOCK_HAS_ACCEPTED_CONTRADICTION",
                                "Block has an accepted contradictory evidence link."))
            if any(item["review_state"] != "ACCEPTED" for item in links):
                reasons.append(("BLOCK_HAS_UNREVIEWED_EVIDENCE",
                                "Every attached evidence link must be reviewed before publication."))

            claim_id = block["claim_id"]
            if claim_id:
                status = claim_status.get(claim_id)
                claim_links = by_claim.get(claim_id, [])
                accepted_support_ids = {
                    item["evidence_id"] for item in claim_links
                    if item["relation"] == "SUPPORTS" and item["review_state"] == "ACCEPTED"
                }
                accepted_contradiction = any(
                    item["relation"] == "CONTRADICTS" and item["review_state"] == "ACCEPTED"
                    for item in claim_links
                )
                block_support_ids = {
                    item["evidence_id"] for item in links
                    if item["relation"] == "SUPPORTS" and item["review_state"] == "ACCEPTED"
                }
                if status is None or status["status"] != "SUPPORTED":
                    reasons.append(("CLAIM_NOT_SUPPORTED", "Referenced claim is not marked SUPPORTED."))
                if accepted_contradiction:
                    reasons.append(("CLAIM_CONTRADICTED", "Referenced claim has accepted contradictory evidence."))
                if not accepted_support_ids or not block_support_ids.intersection(accepted_support_ids):
                    reasons.append(("CLAIM_SUPPORT_NOT_CARRIED",
                                    "Block must carry at least one accepted support link from its claim."))

            elif block["provenance"] in {"SOURCE", "DERIVED", "EXTERNAL"} and not any(
                item["relation"] == "SUPPORTS" and item["review_state"] == "ACCEPTED"
                for item in links
            ):
                reasons.append(("MISSING_ACCEPTED_SUPPORT",
                                "Source, derived and external blocks require accepted supporting evidence."))

            if reasons:
                blocked_ids.add(block_id)
                for code, message in reasons:
                    findings.append(PublicationFinding("ERROR", code, block_id, message))

        return PublicationReport(
            version_id=version_id,
            total_chapters=len(chapters),
            total_blocks=len(blocks),
            eligible_blocks=len(blocks) - len(blocked_ids),
            blocked_blocks=len(blocked_ids),
            findings=tuple(findings),
        )
