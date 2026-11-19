"""Versioned textbook composition model and persistence."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now

BlockType = Literal[
    "HEADING", "PARAGRAPH", "DEFINITION", "EQUATION", "TABLE", "DIAGRAM", "IMAGE",
    "CODE", "EXAMPLE", "WORKED_SOLUTION", "WARNING", "MISCONCEPTION", "SUMMARY",
    "EXERCISE", "SOURCE_REFERENCE", "FOOTNOTE",
]
Provenance = Literal["SOURCE", "EXPLANATION", "DERIVED", "EXTERNAL", "UNCERTAIN"]
CompositionMode = Literal["SOURCE_ORDER", "CONCEPTUAL", "HYBRID"]


@dataclass(frozen=True, slots=True)
class BlockInput:
    block_type: BlockType
    content: dict[str, Any]
    provenance: Provenance
    review_status: str = "DRAFT"
    parent_block_id: str | None = None
    ordinal: int = 0
    knowledge_unit_id: str | None = None
    claim_id: str | None = None

    def validate(self) -> None:
        allowed_types = {
            "HEADING", "PARAGRAPH", "DEFINITION", "EQUATION", "TABLE", "DIAGRAM", "IMAGE",
            "CODE", "EXAMPLE", "WORKED_SOLUTION", "WARNING", "MISCONCEPTION", "SUMMARY",
            "EXERCISE", "SOURCE_REFERENCE", "FOOTNOTE",
        }
        if self.block_type not in allowed_types:
            raise ValueError("Unsupported textbook block type")
        if not isinstance(self.content, dict):
            raise TypeError("Block content must be a JSON object")
        if self.provenance not in {"SOURCE", "EXPLANATION", "DERIVED", "EXTERNAL", "UNCERTAIN"}:
            raise ValueError("Unsupported block provenance")
        if self.review_status not in {"DRAFT", "NEEDS_REVIEW", "ACCEPTED", "REJECTED"}:
            raise ValueError("Unsupported block review status")
        if self.ordinal < 0:
            raise ValueError("Block ordinal must be non-negative")
        try:
            json.dumps(self.content, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Block content must be finite JSON data") from exc


class TextbookStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def create_textbook(self, source_id: str, title: str) -> str:
        if not title.strip():
            raise ValueError("Textbook title must not be empty")
        textbook_id, now = uuid7(), utc_now()
        with connect(self.database_path) as conn:
            if not conn.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
                raise ValueError("Source does not exist")
            conn.execute(
                "INSERT INTO textbooks(id,source_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                (textbook_id, source_id, title.strip(), now, now),
            )
        return textbook_id

    def create_version(
        self, textbook_id: str, title: str, *, composition_mode: CompositionMode = "HYBRID"
    ) -> str:
        if not title.strip():
            raise ValueError("Version title must not be empty")
        if composition_mode not in {"SOURCE_ORDER", "CONCEPTUAL", "HYBRID"}:
            raise ValueError("Unsupported composition mode")
        version_id, now = uuid7(), utc_now()
        with connect(self.database_path) as conn:
            if not conn.execute("SELECT 1 FROM textbooks WHERE id=?", (textbook_id,)).fetchone():
                raise ValueError("Textbook does not exist")
            number = conn.execute(
                "SELECT COALESCE(MAX(version_number),0)+1 FROM textbook_versions WHERE textbook_id=?",
                (textbook_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO textbook_versions
                   (id,textbook_id,version_number,title,status,composition_mode,created_at,updated_at)
                   VALUES(?,?,?,?,'DRAFT',?,?,?)""",
                (version_id, textbook_id, number, title.strip(), composition_mode, now, now),
            )
        return version_id

    def add_chapter(
        self, version_id: str, title: str, *, ordinal: int, summary: str = "",
        parent_chapter_id: str | None = None, source_start_ms: int | None = None,
        source_end_ms: int | None = None,
    ) -> str:
        if not title.strip() or ordinal < 0:
            raise ValueError("Chapter title and ordinal are invalid")
        if source_start_ms is not None and source_start_ms < 0:
            raise ValueError("Chapter source start must be non-negative")
        if source_end_ms is not None and source_end_ms <= 0:
            raise ValueError("Chapter source end must be positive")
        if source_start_ms is not None and source_end_ms is not None and source_end_ms <= source_start_ms:
            raise ValueError("Chapter source interval is invalid")
        chapter_id, now = uuid7(), utc_now()
        with connect(self.database_path) as conn:
            if not conn.execute("SELECT 1 FROM textbook_versions WHERE id=?", (version_id,)).fetchone():
                raise ValueError("Textbook version does not exist")
            conn.execute(
                """INSERT INTO textbook_chapters
                   (id,version_id,parent_chapter_id,title,summary,ordinal,source_start_ms,
                    source_end_ms,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (chapter_id, version_id, parent_chapter_id, title.strip(), summary.strip(),
                 ordinal, source_start_ms, source_end_ms, now, now),
            )
        return chapter_id

    def add_block(self, chapter_id: str, data: BlockInput) -> str:
        data.validate()
        block_id, now = uuid7(), utc_now()
        with connect(self.database_path) as conn:
            if not conn.execute("SELECT 1 FROM textbook_chapters WHERE id=?", (chapter_id,)).fetchone():
                raise ValueError("Chapter does not exist")
            conn.execute(
                """INSERT INTO chapter_blocks
                   (id,chapter_id,parent_block_id,ordinal,block_type,content_json,provenance,
                    review_status,knowledge_unit_id,claim_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (block_id, chapter_id, data.parent_block_id, data.ordinal, data.block_type,
                 json.dumps(data.content, ensure_ascii=False, allow_nan=False, sort_keys=True),
                 data.provenance, data.review_status, data.knowledge_unit_id, data.claim_id,
                 now, now),
            )
        return block_id

    def link_asset(
        self, block_id: str, asset_id: str, *, ordinal: int = 0, caption: str = ""
    ) -> str:
        """Attach a source-owned image asset to an IMAGE or DIAGRAM block."""
        if ordinal < 0:
            raise ValueError("Asset ordinal must be non-negative")
        if not isinstance(caption, str):
            raise TypeError("Asset caption must be text")
        link_id = uuid7()
        with connect(self.database_path) as conn:
            block = conn.execute(
                "SELECT block_type FROM chapter_blocks WHERE id=?", (block_id,)
            ).fetchone()
            if block is None:
                raise ValueError("Textbook block does not exist")
            if block["block_type"] not in {"IMAGE", "DIAGRAM"}:
                raise ValueError("Assets can only be attached to IMAGE or DIAGRAM blocks")
            conn.execute(
                """INSERT INTO block_assets
                   (id,block_id,asset_id,ordinal,caption,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (link_id, block_id, asset_id, ordinal, caption.strip(), utc_now()),
            )
        return link_id

    def link_evidence(
        self, block_id: str, evidence_id: str, *, relation: str = "SUPPORTS",
        review_state: str = "PENDING", rationale: str | None = None,
    ) -> str:
        if relation not in {"SUPPORTS", "ILLUSTRATES", "CONTEXTUALIZES", "CONTRADICTS"}:
            raise ValueError("Unsupported block/evidence relation")
        if review_state not in {"PENDING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
            raise ValueError("Unsupported evidence review state")
        link_id = uuid7()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO block_evidence
                   (id,block_id,evidence_id,relation,review_state,rationale,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (link_id, block_id, evidence_id, relation, review_state, rationale, utc_now()),
            )
        return link_id


    def link_evidence_reference(
        self, block_id: str, evidence_ref_id: str, *, relation: str = "SUPPORTS",
        review_state: str = "PENDING", rationale: str | None = None,
    ) -> str:
        """Attach a textbook block to a transcript interval or document page citation."""
        if relation not in {"SUPPORTS", "ILLUSTRATES", "CONTEXTUALIZES", "CONTRADICTS"}:
            raise ValueError("Unsupported block/evidence reference relation")
        if review_state not in {"PENDING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
            raise ValueError("Unsupported evidence review state")
        link_id = uuid7()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO block_evidence_refs
                   (id,block_id,evidence_ref_id,relation,review_state,rationale,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (link_id,block_id,evidence_ref_id,relation,review_state,rationale,utc_now()),
            )
        return link_id

    def get_version_tree(self, version_id: str) -> dict[str, Any] | None:
        with connect(self.database_path) as conn:
            version = conn.execute(
                """SELECT v.*,t.source_id,t.title AS textbook_title
                   FROM textbook_versions v JOIN textbooks t ON t.id=v.textbook_id
                   WHERE v.id=?""", (version_id,),
            ).fetchone()
            if version is None:
                return None
            chapters = conn.execute(
                """SELECT * FROM textbook_chapters WHERE version_id=? ORDER BY ordinal,id""",
                (version_id,),
            ).fetchall()
            chapter_items = []
            for chapter in chapters:
                blocks = conn.execute(
                    """SELECT * FROM chapter_blocks WHERE chapter_id=?
                       ORDER BY parent_block_id,ordinal,id""", (chapter["id"],),
                ).fetchall()
                block_items = []
                for block in blocks:
                    evidence = conn.execute(
                        """SELECT be.id,be.relation,be.review_state,be.rationale,
                                  e.id AS evidence_id,e.content,e.start_ms,e.end_ms,
                                  e.source_id,e.provenance,er.id AS evidence_ref_id,
                                  er.locator_kind,er.page_number
                           FROM block_evidence be JOIN evidence_items e ON e.id=be.evidence_id
                           LEFT JOIN evidence_refs er ON er.evidence_item_id=e.id
                           WHERE be.block_id=? ORDER BY be.created_at,be.id""", (block["id"],),
                    ).fetchall()
                    evidence_references = conn.execute(
                        """SELECT ber.id,ber.relation,ber.review_state,ber.rationale,
                                  er.id AS evidence_ref_id,er.locator_kind,er.start_ms,
                                  er.end_ms,er.page_number,er.source_id,er.source_asset_id,
                                  COALESCE(e.content,dp.text_content) AS content
                           FROM block_evidence_refs ber
                           JOIN evidence_refs er ON er.id=ber.evidence_ref_id
                           LEFT JOIN evidence_items e ON e.id=er.evidence_item_id
                           LEFT JOIN document_pages dp ON dp.id=er.document_page_id
                           WHERE ber.block_id=? ORDER BY ber.created_at,ber.id""",
                        (block["id"],),
                    ).fetchall()
                    item = dict(block)
                    assets = conn.execute(
                        """SELECT ba.id,ba.asset_id,ba.ordinal,ba.caption,
                                  sa.role,sa.display_name,sa.source_id,
                                  ab.sha256,ab.media_type,ab.byte_size,ab.storage_key
                           FROM block_assets ba
                           JOIN source_assets sa ON sa.id=ba.asset_id
                           JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
                           WHERE ba.block_id=? ORDER BY ba.ordinal,ba.id""",
                        (block["id"],),
                    ).fetchall()
                    item["content"] = json.loads(item.pop("content_json"))
                    item["evidence"] = [dict(row) for row in evidence]
                    item["evidence_references"] = [dict(row) for row in evidence_references]
                    item["assets"] = [dict(row) for row in assets]
                    block_items.append(item)
                chapter_items.append({"chapter": dict(chapter), "blocks": block_items})
        return {"version": dict(version), "chapters": chapter_items}

    def compose_from_accepted_topics(
        self, source_id: str, title: str, *,
        composition_mode: CompositionMode = "HYBRID",
        version_title: str = "Draft 1",
    ) -> str:
        """Create a deterministic outline using only reviewed topics and supported claims.

        Claims are placed in a topic only when the same evidence item has an
        accepted topic link and an accepted SUPPORTS link for a publishable claim.
        No prose is generated or inferred by this method.
        """
        with connect(self.database_path) as conn:
            topic_rows = conn.execute(
                "SELECT * FROM topics WHERE source_id=? ORDER BY start_ms,ordinal,id",
                (source_id,),
            ).fetchall()
        all_topics = {row["id"]: dict(row) for row in topic_rows}
        pending = {
            row["id"]: dict(row) for row in topic_rows if row["status"] == "ACCEPTED"
        }
        textbook_id = self.create_textbook(source_id, title)
        version_id = self.create_version(
            textbook_id, version_title, composition_mode=composition_mode
        )
        chapter_ids: dict[str, str] = {}

        while pending:
            ready = [
                row for row in pending.values()
                if row["parent_topic_id"] is None
                or row["parent_topic_id"] in chapter_ids
                or row["parent_topic_id"] not in pending
            ]
            if not ready:
                raise ValueError("Accepted topic hierarchy contains a cycle")
            ready.sort(key=lambda row: (row["start_ms"], row["ordinal"], row["id"]))
            for topic in ready:
                parent_topic_id = topic["parent_topic_id"]
                while parent_topic_id and parent_topic_id not in chapter_ids:
                    parent = all_topics.get(parent_topic_id)
                    parent_topic_id = parent["parent_topic_id"] if parent else None
                chapter_id = self.add_chapter(
                    version_id,
                    topic["title"],
                    ordinal=topic["ordinal"],
                    summary=topic["description"],
                    parent_chapter_id=chapter_ids.get(parent_topic_id),
                    source_start_ms=topic["start_ms"],
                    source_end_ms=topic["end_ms"],
                )
                chapter_ids[topic["id"]] = chapter_id
                with connect(self.database_path) as conn:
                    rows = conn.execute(
                        """SELECT c.id AS claim_id,c.statement,c.provenance,c.knowledge_unit_id,
                                  ce.evidence_id
                           FROM topic_evidence te
                           JOIN claim_evidence ce ON ce.evidence_id=te.evidence_id
                           JOIN claims c ON c.id=ce.claim_id
                           WHERE te.topic_id=? AND te.review_state='ACCEPTED'
                             AND ce.relation='SUPPORTS' AND ce.review_state='ACCEPTED'
                             AND c.status='SUPPORTED'
                             AND NOT EXISTS (
                               SELECT 1 FROM claim_evidence cx
                               WHERE cx.claim_id=c.id AND cx.relation='CONTRADICTS'
                                 AND cx.review_state='ACCEPTED'
                             )
                           ORDER BY c.created_at,c.id,ce.evidence_id""",
                        (topic["id"],),
                    ).fetchall()
                grouped: dict[str, dict[str, Any]] = {}
                for row in rows:
                    claim = grouped.setdefault(
                        row["claim_id"],
                        {
                            "statement": row["statement"],
                            "provenance": row["provenance"],
                            "knowledge_unit_id": row["knowledge_unit_id"],
                            "evidence_ids": [],
                        },
                    )
                    if row["evidence_id"] not in claim["evidence_ids"]:
                        claim["evidence_ids"].append(row["evidence_id"])
                for ordinal, (claim_id, claim) in enumerate(grouped.items()):
                    block_id = self.add_block(
                        chapter_id,
                        BlockInput(
                            block_type="PARAGRAPH",
                            content={"text": claim["statement"], "claim_id": claim_id},
                            provenance=claim["provenance"],
                            review_status="ACCEPTED",
                            ordinal=ordinal,
                            knowledge_unit_id=claim["knowledge_unit_id"],
                            claim_id=claim_id,
                        ),
                    )
                    for evidence_id in claim["evidence_ids"]:
                        self.link_evidence(
                            block_id, evidence_id, relation="SUPPORTS", review_state="ACCEPTED"
                        )
                del pending[topic["id"]]
        return version_id


    def compose_from_accepted_document_topics(
        self, source_id: str, title: str, *,
        composition_mode: CompositionMode = "HYBRID",
        version_title: str = "Draft 1",
    ) -> str:
        """Compose page-native chapters only from reviewed topics and shared accepted citations.

        A claim is placed only when the same evidence-reference ID has accepted topic alignment
        and accepted SUPPORTS links for a SUPPORTED claim without accepted contradictions.
        The method creates structure and reuses claim statements; it does not generate prose.
        """
        with connect(self.database_path) as conn:
            topic_rows = conn.execute(
                """SELECT * FROM document_topics
                   WHERE source_id=? ORDER BY ordinal,id""",
                (source_id,),
            ).fetchall()
        all_topics = {row["id"]: dict(row) for row in topic_rows}
        pending = {
            row["id"]: dict(row) for row in topic_rows if row["status"] == "ACCEPTED"
        }
        textbook_id = self.create_textbook(source_id, title)
        version_id = self.create_version(
            textbook_id, version_title, composition_mode=composition_mode
        )
        chapter_ids: dict[str, str] = {}

        while pending:
            ready = [
                row for row in pending.values()
                if row["parent_topic_id"] is None
                or row["parent_topic_id"] in chapter_ids
                or row["parent_topic_id"] not in pending
            ]
            if not ready:
                raise ValueError("Accepted document topic hierarchy contains a cycle")
            ready.sort(key=lambda row: (row["ordinal"], row["id"]))
            for topic in ready:
                parent_topic_id = topic["parent_topic_id"]
                while parent_topic_id and parent_topic_id not in chapter_ids:
                    parent = all_topics.get(parent_topic_id)
                    parent_topic_id = parent["parent_topic_id"] if parent else None
                chapter_id = self.add_chapter(
                    version_id,
                    topic["title"],
                    ordinal=topic["ordinal"],
                    summary=topic["description"],
                    parent_chapter_id=chapter_ids.get(parent_topic_id),
                )
                chapter_ids[topic["id"]] = chapter_id
                with connect(self.database_path) as conn:
                    rows = conn.execute(
                        """SELECT c.id AS claim_id,c.statement,c.provenance,c.knowledge_unit_id,
                                  cer.evidence_ref_id
                           FROM document_topic_evidence_refs te
                           JOIN claim_evidence_refs cer
                             ON cer.evidence_ref_id=te.evidence_ref_id
                           JOIN claims c ON c.id=cer.claim_id
                           WHERE te.topic_id=? AND te.review_state='ACCEPTED'
                             AND cer.relation='SUPPORTS' AND cer.review_state='ACCEPTED'
                             AND c.status='SUPPORTED'
                             AND NOT EXISTS (
                               SELECT 1 FROM claim_evidence cx
                               WHERE cx.claim_id=c.id AND cx.relation='CONTRADICTS'
                                 AND cx.review_state='ACCEPTED'
                             )
                             AND NOT EXISTS (
                               SELECT 1 FROM claim_evidence_refs cx
                               WHERE cx.claim_id=c.id AND cx.relation='CONTRADICTS'
                                 AND cx.review_state='ACCEPTED'
                             )
                           ORDER BY c.created_at,c.id,cer.evidence_ref_id""",
                        (topic["id"],),
                    ).fetchall()
                grouped: dict[str, dict[str, Any]] = {}
                for row in rows:
                    claim = grouped.setdefault(
                        row["claim_id"],
                        {
                            "statement": row["statement"],
                            "provenance": row["provenance"],
                            "knowledge_unit_id": row["knowledge_unit_id"],
                            "evidence_ref_ids": [],
                        },
                    )
                    if row["evidence_ref_id"] not in claim["evidence_ref_ids"]:
                        claim["evidence_ref_ids"].append(row["evidence_ref_id"])
                for ordinal, (claim_id, claim) in enumerate(grouped.items()):
                    block_id = self.add_block(
                        chapter_id,
                        BlockInput(
                            block_type="PARAGRAPH",
                            content={"text": claim["statement"], "claim_id": claim_id},
                            provenance=claim["provenance"],
                            review_status="ACCEPTED",
                            ordinal=ordinal,
                            knowledge_unit_id=claim["knowledge_unit_id"],
                            claim_id=claim_id,
                        ),
                    )
                    for evidence_ref_id in claim["evidence_ref_ids"]:
                        self.link_evidence_reference(
                            block_id,evidence_ref_id,
                            relation="SUPPORTS",review_state="ACCEPTED",
                        )
                del pending[topic["id"]]
        return version_id

