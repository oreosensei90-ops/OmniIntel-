"""Normalize a single-source textbook tree to the portable Web/Android reader contract."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .database import connect, migrate


def to_reader_export(
    database_path: str | Path, tree: dict[str, Any], source_id: str
) -> dict[str, Any]:
    """Add source catalog and reader-safe evidence locators to a textbook tree."""
    with connect(database_path) as conn:
        migrate(conn)
        source = conn.execute(
            "SELECT id,title,source_uri,language,duration_ms FROM sources WHERE id=?",
            (source_id,),
        ).fetchone()
    if source is None:
        raise ValueError("Reader export source does not exist")
    result = dict(tree)
    normalized_chapters = []
    for entry in tree.get("chapters", []):
        chapter = entry.get("chapter")
        if not isinstance(chapter, dict):
            raise TypeError("Textbook chapter metadata is missing")
        normalized_blocks = []
        for block in entry.get("blocks", []):
            evidence: list[dict[str, Any]] = []
            for item in block.get("evidence", []):
                evidence.append(_normalize_evidence(item, source_id))
            for item in block.get("evidence_references", []):
                evidence.append(_normalize_evidence(item, source_id))
            normalized_blocks.append({**block, "evidence": evidence})
        normalized_chapters.append({"chapter": chapter, "blocks": normalized_blocks})
    if not normalized_chapters:
        raise ValueError("Reader export must contain at least one chapter")
    version = result.get("version")
    if not isinstance(version, dict) or not version.get("id"):
        raise ValueError("Reader export textbook version is missing")
    result["sources"] = [{
        "source_id": source["id"],
        "title": source["title"],
        "source_uri": source["source_uri"],
        "language": source["language"],
        "duration_ms": source["duration_ms"],
    }]
    result["anchor_source_id"] = source_id
    result["chapters"] = normalized_chapters
    result["alignment_policy"] = (
        "Single-source reader. All timestamps remain local to their original source; "
        "no cross-source clock mapping is inferred."
    )
    return result


def _normalize_evidence(item: dict[str, Any], fallback_source_id: str) -> dict[str, Any]:
    source_id = item.get("source_id") or fallback_source_id
    locator_kind = item.get("locator_kind")
    start = item.get("start_ms")
    end = item.get("end_ms")
    page_number = item.get("page_number")
    content = str(item.get("content") or item.get("element_text") or "")
    element_id = item.get("element_id")
    is_transcript = locator_kind == "TRANSCRIPT_INTERVAL" or (
        locator_kind is None and start is not None
    )
    is_document = locator_kind == "DOCUMENT_PAGE" or page_number is not None
    if not is_transcript and not is_document:
        raise ValueError("Evidence reference has no supported source locator")
    normalized: dict[str, Any] = {
        "source_id": source_id,
        "locator_kind": "TRANSCRIPT_INTERVAL" if is_transcript else "DOCUMENT_PAGE",
        "relation": item.get("relation") or "SUPPORTS",
        "review_state": item.get("review_state") or "PENDING",
        "local_start_ms": start if is_transcript else None,
        "local_end_ms": end if is_transcript else None,
        "seek_available": bool(is_transcript and start is not None and end is not None),
        "transcript_excerpt": (
            [{"text": content, "start_ms": start, "end_ms": end}] if is_transcript and content else []
        ),
        "document_page": (
            {"page_number": page_number, "text_content": content[:700]}
            if is_document else None
        ),
        "document_elements": (
            [{
                "id": element_id,
                "element_type": item.get("element_type") or "PARAGRAPH",
                "text_content": str(item.get("element_text") or content)[:4_000],
                "review_state": item.get("element_review_state") or "NEEDS_REVIEW",
            }] if is_document and element_id else []
        ),
    }
    return normalized
