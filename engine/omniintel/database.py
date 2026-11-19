"""SQLite initialization and immutable, checksum-verified migrations."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Iterable


MIGRATIONS: tuple[tuple[str, str], ...] = (
    (
        "0001_source_transcript_evidence",
        """
        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL CHECK(length(trim(title)) > 0),
            source_uri TEXT,
            language TEXT,
            duration_ms INTEGER CHECK(duration_ms IS NULL OR duration_ms > 0),
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE transcript_segments (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            text TEXT NOT NULL CHECK(length(trim(text)) > 0),
            start_ms INTEGER NOT NULL CHECK(start_ms >= 0),
            end_ms INTEGER NOT NULL CHECK(end_ms > start_ms),
            language TEXT,
            speaker_id TEXT,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            created_at TEXT NOT NULL,
            UNIQUE(source_id, ordinal)
        );
        CREATE INDEX idx_transcript_source_time
            ON transcript_segments(source_id, start_ms, end_ms);
        CREATE TABLE evidence_items (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            segment_id TEXT REFERENCES transcript_segments(id) ON DELETE RESTRICT,
            evidence_type TEXT NOT NULL CHECK(evidence_type IN ('caption','transcript')),
            content TEXT NOT NULL,
            start_ms INTEGER NOT NULL CHECK(start_ms >= 0),
            end_ms INTEGER NOT NULL CHECK(end_ms > start_ms),
            provenance TEXT NOT NULL CHECK(provenance = 'SOURCE'),
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_evidence_source_time ON evidence_items(source_id, start_ms);
        """,
    ),
)


class MigrationError(RuntimeError):
    pass


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def migrate(conn: sqlite3.Connection, migrations: Iterable[tuple[str, str]] = MIGRATIONS) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    for name, sql in migrations:
        checksum = _checksum(sql)
        existing = conn.execute(
            "SELECT checksum FROM schema_migrations WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            if existing["checksum"] != checksum:
                raise MigrationError(f"Applied migration {name!r} was modified")
            continue
        try:
            conn.executescript(
                "BEGIN IMMEDIATE;\n"
                + sql
                + f"\nINSERT INTO schema_migrations(name, checksum) VALUES('{name}', '{checksum}');\nCOMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.rollback()
            raise
