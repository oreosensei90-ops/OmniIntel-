"""Bridge reviewed document structure into draft knowledge units without inventing claims."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .database import connect
from .knowledge import KnowledgeUnitInput
from .knowledge_store import KnowledgeStore


@dataclass(frozen=True, slots=True)
class DocumentKnowledgeImport:
    source_id: str
    candidate_unit_ids: tuple[str, ...]
    skipped_unreviewed_elements: int


def create_knowledge_candidates_from_document_elements(
    database_path: str | Path,
    source_id: str,
    *,
    accepted_elements_only: bool = True,
    max_elements: int = 10_000,
) -> DocumentKnowledgeImport:
    """Create idempotent draft knowledge units from structured, source-linked PDF elements.

    This is a handoff into knowledge reconstruction, not automated claim extraction.
    Every unit retains its exact element/page citation and stays NEEDS_REVIEW.
    """
    if not 1 <= max_elements <= 50_000:
        raise ValueError("Knowledge candidate limit must be between 1 and 50000")
    with connect(database_path) as conn:
        rows = conn.execute(
            """SELECT de.id,de.element_type,de.text_content,de.content_json,
                      de.provenance,de.review_state,de.evidence_ref_id,dp.page_number
               FROM document_elements de
               JOIN document_pages dp ON dp.id=de.page_id
               JOIN document_extractions dex ON dex.id=dp.extraction_id
               JOIN source_assets sa ON sa.id=dex.source_asset_id
               WHERE sa.source_id=?
               ORDER BY dp.page_number,de.ordinal,de.id
               LIMIT ?""",
            (source_id,max_elements + 1),
        ).fetchall()
    if len(rows) > max_elements:
        raise ValueError("Document exceeds the knowledge candidate element limit")
    accepted = [row for row in rows if row["review_state"] == "ACCEPTED"]
    skipped = len(rows) - len(accepted)
    selected = accepted if accepted_elements_only else list(rows)

    store = KnowledgeStore(database_path)
    ids: list[str] = []
    type_map = {
        "HEADING": "concept",
        "EQUATION": "formula",
        "TABLE": "comparison",
        "LIST_ITEM": "procedure",
        "PARAGRAPH": "reference",
        "CAPTION": "reference",
        "FIGURE": "reference",
    }
    for row in selected:
        content = json.loads(row["content_json"])
        body = row["text_content"].strip()
        if not body:
            body = json.dumps(content,ensure_ascii=False,sort_keys=True)
        title = row["text_content"].strip().splitlines()[0][:120] if row["text_content"].strip() else (
            f"{row['element_type'].title()} on page {row['page_number']}"
        )
        provenance = "UNCERTAIN" if row["provenance"] == "UNCERTAIN" else "DERIVED"
        unit_id = store.create_unit(KnowledgeUnitInput(
            unit_type=type_map[row["element_type"]],
            title=title,
            body=body,
            provenance=provenance,
            status="NEEDS_REVIEW",
            source_element_id=row["id"],
        ))
        store.link_unit_evidence_reference(
            unit_id,row["evidence_ref_id"],element_id=row["id"],
            relation="SOURCE_EXCERPT",review_state="PENDING",
        )
        ids.append(unit_id)
    return DocumentKnowledgeImport(source_id,tuple(ids),skipped)
