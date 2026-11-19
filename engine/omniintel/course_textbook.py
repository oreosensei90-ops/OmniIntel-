"""Collection-level textbooks that preserve per-source evidence ownership."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now


class CourseTextbookStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def create(self, collection_id: str, title: str) -> str:
        if not title.strip():
            raise ValueError("Course textbook title is required")
        book_id, now = uuid7(), utc_now()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO course_textbooks(id,collection_id,title,created_at,updated_at)
                   VALUES(?,?,?,?,?)""",(book_id,collection_id,title.strip(),now,now)
            )
        return book_id

    def create_version(self, textbook_id: str, title: str, *, composition_mode: str = "HYBRID") -> str:
        if not title.strip() or composition_mode not in {"SOURCE_ORDER","CONCEPTUAL","HYBRID"}:
            raise ValueError("Invalid course textbook version")
        version_id, now = uuid7(), utc_now()
        with connect(self.database_path) as conn:
            number = conn.execute(
                "SELECT COALESCE(MAX(version_number),0)+1 FROM course_textbook_versions WHERE textbook_id=?",
                (textbook_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO course_textbook_versions
                   (id,textbook_id,version_number,title,status,composition_mode,created_at)
                   VALUES(?,?,?,?,'DRAFT',?,?)""",
                (version_id,textbook_id,number,title.strip(),composition_mode,now),
            )
        return version_id

    def add_chapter(
        self, version_id: str, title: str, *, ordinal: int,
        source_id: str | None = None, summary: str = "",
    ) -> str:
        if not title.strip() or ordinal < 0:
            raise ValueError("Chapter title and ordinal are invalid")
        chapter_id = uuid7()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO course_textbook_chapters
                   (id,version_id,title,summary,ordinal,source_id,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (chapter_id,version_id,title.strip(),summary.strip(),ordinal,source_id,utc_now()),
            )
        return chapter_id

    def add_block(
        self, chapter_id: str, block_type: str, content: dict[str, Any], *,
        provenance: str = "EXPLANATION", review_status: str = "DRAFT",
        claim_id: str | None = None, ordinal: int = 0,
    ) -> str:
        if not block_type or not isinstance(content,dict) or ordinal < 0:
            raise ValueError("Invalid course textbook block")
        if provenance not in {"SOURCE","EXPLANATION","DERIVED","EXTERNAL","UNCERTAIN"}:
            raise ValueError("Invalid block provenance")
        if review_status not in {"DRAFT","NEEDS_REVIEW","ACCEPTED","REJECTED"}:
            raise ValueError("Invalid block review state")
        encoded = json.dumps(content,ensure_ascii=False,sort_keys=True,allow_nan=False)
        block_id = uuid7()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO course_textbook_blocks
                   (id,chapter_id,ordinal,block_type,content_json,provenance,review_status,claim_id,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (block_id,chapter_id,ordinal,block_type,encoded,provenance,review_status,claim_id,utc_now()),
            )
        return block_id

    def link_evidence(
        self, block_id: str, evidence_ref_id: str, *, relation: str = "SUPPORTS",
        review_state: str = "PENDING", rationale: str | None = None,
    ) -> str:
        if relation not in {"SUPPORTS","ILLUSTRATES","CONTEXTUALIZES","CONTRADICTS"}:
            raise ValueError("Invalid course textbook evidence relation")
        if review_state not in {"PENDING","ACCEPTED","REJECTED","NEEDS_REVIEW"}:
            raise ValueError("Invalid evidence review state")
        link_id = uuid7()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO course_textbook_block_evidence
                   (id,block_id,evidence_ref_id,relation,review_state,rationale,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (link_id,block_id,evidence_ref_id,relation,review_state,rationale,utc_now()),
            )
        return link_id

    def review_evidence(self, link_id: str, state: str) -> str:
        if state not in {"ACCEPTED","REJECTED","NEEDS_REVIEW"}:
            raise ValueError("Invalid evidence review state")
        with connect(self.database_path) as conn:
            cur=conn.execute(
                "UPDATE course_textbook_block_evidence SET review_state=? WHERE id=?",
                (state,link_id),
            )
            if cur.rowcount != 1:
                raise ValueError("Course textbook evidence link does not exist")
        return state

    def get_version(self, version_id: str) -> dict[str, Any] | None:
        with connect(self.database_path) as conn:
            version=conn.execute(
                """SELECT v.*,t.collection_id,t.title AS textbook_title
                   FROM course_textbook_versions v JOIN course_textbooks t ON t.id=v.textbook_id
                   WHERE v.id=?""",(version_id,)
            ).fetchone()
            if version is None:
                return None
            chapters=conn.execute(
                "SELECT * FROM course_textbook_chapters WHERE version_id=? ORDER BY ordinal,id",
                (version_id,),
            ).fetchall()
            result=[]
            for chapter in chapters:
                blocks=conn.execute(
                    "SELECT * FROM course_textbook_blocks WHERE chapter_id=? ORDER BY ordinal,id",
                    (chapter["id"],),
                ).fetchall()
                chapter_data=[]
                for block in blocks:
                    links=conn.execute(
                        """SELECT l.*,er.source_id,er.locator_kind,er.start_ms,er.end_ms,
                                  er.page_number,er.id AS citation_id
                           FROM course_textbook_block_evidence l
                           JOIN evidence_refs er ON er.id=l.evidence_ref_id
                           WHERE l.block_id=? ORDER BY l.created_at,l.id""",(block["id"],)
                    ).fetchall()
                    item=dict(block); item["content"]=json.loads(item.pop("content_json"))
                    item["evidence"]=[dict(link) for link in links]
                    chapter_data.append(item)
                result.append({"chapter":dict(chapter),"blocks":chapter_data})
        return {"version":dict(version),"chapters":result}

    def audit(self, version_id: str) -> dict[str, Any]:
        tree=self.get_version(version_id)
        if tree is None:
            raise ValueError("Course textbook version does not exist")
        findings=[]
        total=eligible=0
        for chapter in tree["chapters"]:
            for block in chapter["blocks"]:
                total+=1
                reasons=[]
                if block["review_status"]!="ACCEPTED":
                    reasons.append("BLOCK_NOT_ACCEPTED")
                if block["provenance"]=="UNCERTAIN":
                    reasons.append("UNCERTAIN_PROVENANCE")
                links=block["evidence"]
                if any(x["review_state"]!="ACCEPTED" for x in links):
                    reasons.append("UNREVIEWED_EVIDENCE")
                if any(x["relation"]=="CONTRADICTS" and x["review_state"]=="ACCEPTED" for x in links):
                    reasons.append("ACCEPTED_CONTRADICTION")
                if block["provenance"] in {"SOURCE","DERIVED","EXTERNAL"} and not any(
                    x["relation"]=="SUPPORTS" and x["review_state"]=="ACCEPTED" for x in links
                ):
                    reasons.append("MISSING_ACCEPTED_SUPPORT")
                if block["claim_id"]:
                    with connect(self.database_path) as conn:
                        claim=conn.execute("SELECT status FROM claims WHERE id=?",(block["claim_id"],)).fetchone()
                        claim_refs=conn.execute(
                            """SELECT evidence_ref_id,relation,review_state FROM claim_evidence_refs
                               WHERE claim_id=?""",(block["claim_id"],)
                        ).fetchall()
                        claim_items=conn.execute(
                            """SELECT er.id AS evidence_ref_id,ce.relation,ce.review_state
                               FROM claim_evidence ce JOIN evidence_refs er
                                 ON er.evidence_item_id=ce.evidence_id
                               WHERE ce.claim_id=?""",(block["claim_id"],)
                        ).fetchall()
                    accepted_claim_support={row["evidence_ref_id"] for row in list(claim_refs)+list(claim_items)
                                            if row["relation"]=="SUPPORTS" and row["review_state"]=="ACCEPTED"}
                    accepted_block_support={row["evidence_ref_id"] for row in links
                                            if row["relation"]=="SUPPORTS" and row["review_state"]=="ACCEPTED"}
                    claim_contradiction=any(row["relation"]=="CONTRADICTS" and row["review_state"]=="ACCEPTED"
                                            for row in list(claim_refs)+list(claim_items))
                    if claim is None or claim["status"]!="SUPPORTED":
                        reasons.append("CLAIM_NOT_SUPPORTED")
                    elif not accepted_claim_support.intersection(accepted_block_support):
                        reasons.append("CLAIM_SUPPORT_NOT_CARRIED")
                    if claim_contradiction:
                        reasons.append("CLAIM_CONTRADICTED")
                if reasons:
                    findings.append({"block_id":block["id"],"errors":reasons})
                else:
                    eligible+=1
        if total==0:
            findings.append({"block_id":None,"errors":["EMPTY_TEXTBOOK"]})
        return {"version_id":version_id,"total_blocks":total,"eligible_blocks":eligible,
                "blocked_blocks":total-eligible,"publishable":total>0 and total==eligible,
                "findings":findings}
