"""Durable course/collection membership without merging source identity."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now

_COLLECTION_TYPES = {"COURSE", "PLAYLIST", "PROJECT", "RESEARCH_SET"}
_SOURCE_ROLES = {"LEARNING_SOURCE", "SLIDE_DECK", "CAPTIONS", "REFERENCE", "NOTES"}


class CollectionStore:
    """Group independent source records into courses or research collections."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def create(
        self,
        title: str,
        *,
        collection_type: str = "COURSE",
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        normalized = title.strip()
        if not normalized:
            raise ValueError("Collection title must not be empty")
        if collection_type not in _COLLECTION_TYPES:
            raise ValueError("Unsupported collection type")
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("Collection metadata must be a JSON object")
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        now = utc_now()
        collection_id = uuid7()
        with connect(self.database_path) as conn:
            migrate(conn)
            conn.execute(
                """INSERT INTO source_collections
                   (id,title,collection_type,description,metadata_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (collection_id, normalized, collection_type, description,
                 metadata_json, now, now),
            )
        return collection_id

    def add_source(
        self,
        collection_id: str,
        source_id: str,
        *,
        role: str = "LEARNING_SOURCE",
        ordinal: int | None = None,
    ) -> int:
        if role not in _SOURCE_ROLES:
            raise ValueError("Unsupported collection source role")
        with connect(self.database_path) as conn:
            migrate(conn)
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM source_collections WHERE id=?", (collection_id,)
            ).fetchone() is None:
                raise ValueError("Collection does not exist")
            if conn.execute(
                "SELECT 1 FROM sources WHERE id=?", (source_id,)
            ).fetchone() is None:
                raise ValueError("Source does not exist")
            if conn.execute(
                "SELECT 1 FROM collection_sources WHERE collection_id=? AND source_id=?",
                (collection_id, source_id),
            ).fetchone() is not None:
                raise ValueError("Source is already a member of this collection")
            if ordinal is None:
                ordinal = conn.execute(
                    "SELECT COALESCE(MAX(ordinal)+1,0) FROM collection_sources WHERE collection_id=?",
                    (collection_id,),
                ).fetchone()[0]
            if not isinstance(ordinal, int) or ordinal < 0:
                raise ValueError("Collection source ordinal must be a non-negative integer")
            conn.execute(
                """INSERT INTO collection_sources
                   (collection_id,source_id,role,ordinal,added_at)
                   VALUES(?,?,?,?,?)""",
                (collection_id, source_id, role, ordinal, utc_now()),
            )
            conn.execute(
                "UPDATE source_collections SET updated_at=? WHERE id=?",
                (utc_now(), collection_id),
            )
        return ordinal

    def list_sources(self, collection_id: str) -> list[dict[str, Any]]:
        with connect(self.database_path) as conn:
            if conn.execute(
                "SELECT 1 FROM source_collections WHERE id=?", (collection_id,)
            ).fetchone() is None:
                raise ValueError("Collection does not exist")
            rows = conn.execute(
                """SELECT s.id AS source_id,s.title,s.language,s.duration_ms,
                          cs.role,cs.ordinal,cs.added_at
                   FROM collection_sources cs
                   JOIN sources s ON s.id=cs.source_id
                   WHERE cs.collection_id=?
                   ORDER BY cs.ordinal,cs.added_at,s.id""",
                (collection_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get(self, collection_id: str) -> dict[str, Any] | None:
        with connect(self.database_path) as conn:
            row = conn.execute(
                """SELECT id,title,collection_type,description,metadata_json,
                          created_at,updated_at
                   FROM source_collections WHERE id=?""",
                (collection_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json"))
        result["sources"] = self.list_sources(collection_id)
        return result
