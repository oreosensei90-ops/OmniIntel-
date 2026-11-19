"""Deterministic transcript ingestion into source and evidence records."""
from __future__ import annotations

import json
from pathlib import Path

from .database import connect, migrate
from .ids import uuid7
from .models import ImportResult, TranscriptImport, utc_now
from .evidence_refs import register_transcript_references


class OmniIntelStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        with connect(self.database_path) as conn:
            migrate(conn)

    def import_transcript(self, data: TranscriptImport) -> ImportResult:
        data.validate()
        source_id = uuid7()
        segment_ids: list[str] = []
        evidence_ids: list[str] = []
        created_at = utc_now()
        with connect(self.database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO sources(id,title,source_uri,language,duration_ms,metadata_json,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    source_id, data.title.strip(), data.source_uri, data.language,
                    data.duration_ms,
                    json.dumps(data.metadata, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            for ordinal, segment in enumerate(data.segments):
                segment_id, evidence_id = uuid7(), uuid7()
                segment_ids.append(segment_id)
                evidence_ids.append(evidence_id)
                conn.execute(
                    "INSERT INTO transcript_segments "
                    "(id,source_id,text,start_ms,end_ms,language,speaker_id,ordinal,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        segment_id, source_id, segment.text, segment.start_ms, segment.end_ms,
                        segment.language or data.language, segment.speaker_id, ordinal, created_at,
                    ),
                )
                conn.execute(
                    "INSERT INTO evidence_items "
                    "(id,source_id,segment_id,evidence_type,content,start_ms,end_ms,provenance,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        evidence_id, source_id, segment_id, "transcript", segment.text,
                        segment.start_ms, segment.end_ms, "SOURCE", created_at,
                    ),
                )
        reference_ids = register_transcript_references(self.database_path, evidence_ids)
        return ImportResult(source_id, tuple(segment_ids), tuple(evidence_ids), reference_ids)

    def get_transcript(self, source_id: str) -> list[dict[str, object]]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT id,text,start_ms,end_ms,language,speaker_id,ordinal "
                "FROM transcript_segments WHERE source_id=? ORDER BY ordinal",
                (source_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_transcripts(self, query: str) -> list[dict[str, object]]:
        if not query.strip():
            return []
        with connect(self.database_path) as conn:
            rows = conn.execute(
                "SELECT s.id AS source_id,s.title,t.id AS segment_id,t.text,t.start_ms,t.end_ms "
                "FROM transcript_segments t JOIN sources s ON s.id=t.source_id "
                "WHERE t.text LIKE ? ORDER BY s.created_at DESC,t.ordinal LIMIT 50",
                (f"%{query.strip()}%",),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_source(
        self,
        *,
        title: str,
        source_uri: str | None = None,
        language: str | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> str:
        """Create a source record before attaching its original assets or evidence."""
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("Source title must not be empty")
        if duration_ms is not None and duration_ms <= 0:
            raise ValueError("Source duration must be positive")
        source_id = uuid7()
        with connect(self.database_path) as conn:
            conn.execute(
                """INSERT INTO sources
                   (id,title,source_uri,language,duration_ms,metadata_json,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    source_id, normalized_title, source_uri, language, duration_ms,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    utc_now(),
                ),
            )
        return source_id

    def delete_empty_source(self, source_id: str) -> None:
        """Remove a just-created source only when no records depend on it."""
        with connect(self.database_path) as conn:
            cursor = conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
            if cursor.rowcount != 1:
                return
