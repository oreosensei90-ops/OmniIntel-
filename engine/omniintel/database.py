"""SQLite initialization and immutable, checksum-verified migrations."""
from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from pathlib import Path


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
    (
        "0002_durable_jobs",
        """
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL CHECK(length(trim(job_type)) > 0),
            payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
            state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','RETRYING','COMPLETED','FAILED','CANCELLED')),
            idempotency_key TEXT UNIQUE,
            payload_hash TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts > 0),
            available_at_ms INTEGER NOT NULL,
            lease_owner TEXT,
            lease_token TEXT,
            lease_expires_at_ms INTEGER,
            result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            CHECK (
                (state = 'RUNNING' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL
                 AND lease_expires_at_ms IS NOT NULL)
                OR
                (state <> 'RUNNING' AND lease_owner IS NULL AND lease_token IS NULL
                 AND lease_expires_at_ms IS NULL)
            )
        );
        CREATE INDEX idx_jobs_ready ON jobs(state, available_at_ms, created_at);
        CREATE INDEX idx_jobs_lease ON jobs(state, lease_expires_at_ms);
        """,
    ),
    (
        "0003_knowledge_reconstruction",
        """
        CREATE TABLE knowledge_units (
            id TEXT PRIMARY KEY,
            unit_type TEXT NOT NULL CHECK(unit_type IN (
                'concept','definition','principle','formula','procedure','example',
                'worked_solution','observation','comparison','warning','question','reference'
            )),
            title TEXT NOT NULL CHECK(length(trim(title)) > 0),
            body TEXT NOT NULL CHECK(length(trim(body)) > 0),
            provenance TEXT NOT NULL CHECK(provenance IN ('EXPLANATION','DERIVED','UNCERTAIN')),
            status TEXT NOT NULL CHECK(status IN ('DRAFT','VALIDATED','NEEDS_REVIEW','REJECTED')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_knowledge_units_type_status ON knowledge_units(unit_type,status);
        CREATE TABLE claims (
            id TEXT PRIMARY KEY,
            knowledge_unit_id TEXT REFERENCES knowledge_units(id) ON DELETE RESTRICT,
            statement TEXT NOT NULL CHECK(length(trim(statement)) > 0),
            provenance TEXT NOT NULL CHECK(provenance IN ('EXPLANATION','DERIVED','UNCERTAIN')),
            status TEXT NOT NULL CHECK(status IN ('DRAFT','SUPPORTED','CONTESTED','UNCERTAIN','REJECTED')),
            confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_claims_status ON claims(status);
        CREATE TABLE claim_evidence (
            id TEXT PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id) ON DELETE RESTRICT,
            evidence_id TEXT NOT NULL REFERENCES evidence_items(id) ON DELETE RESTRICT,
            relation TEXT NOT NULL CHECK(relation IN (
                'SUPPORTS','CONTRADICTS','QUALIFIES','CONTEXTUALIZES','ILLUSTRATES'
            )),
            review_state TEXT NOT NULL CHECK(review_state IN (
                'PENDING','ACCEPTED','REJECTED','NEEDS_REVIEW'
            )),
            relevance_score REAL CHECK(relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 1)),
            rationale TEXT,
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(claim_id,evidence_id,relation)
        );
        CREATE INDEX idx_claim_evidence_claim ON claim_evidence(claim_id,review_state);
        CREATE INDEX idx_claim_evidence_evidence ON claim_evidence(evidence_id);
        CREATE TABLE knowledge_relationships (
            id TEXT PRIMARY KEY,
            from_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE RESTRICT,
            to_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE RESTRICT,
            relation TEXT NOT NULL CHECK(relation IN (
                'REQUIRES','EXPLAINS','DERIVED_FROM','CONTRASTS_WITH','PART_OF',
                'APPLIED_IN','ILLUSTRATED_BY','CONTRADICTS'
            )),
            rationale TEXT,
            created_at TEXT NOT NULL,
            CHECK(from_unit_id <> to_unit_id),
            UNIQUE(from_unit_id,to_unit_id,relation)
        );
        CREATE INDEX idx_knowledge_relationships_from ON knowledge_relationships(from_unit_id,relation);
        CREATE INDEX idx_knowledge_relationships_to ON knowledge_relationships(to_unit_id,relation);
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


def _execute_statements(conn: sqlite3.Connection, sql: str) -> None:
    """Execute a static migration script without executescript's implicit commits."""
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            if statement.strip():
                conn.execute(statement)
            statement = ""
    if statement.strip():
        raise MigrationError("Migration contains an incomplete SQL statement")


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
            conn.execute("BEGIN IMMEDIATE")
            _execute_statements(conn, sql)
            conn.execute(
                "INSERT INTO schema_migrations(name, checksum) VALUES(?, ?)",
                (name, checksum),
            )
            conn.commit()
        except (sqlite3.Error, MigrationError):
            if conn.in_transaction:
                conn.rollback()
            raise
