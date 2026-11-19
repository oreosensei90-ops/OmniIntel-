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
    (
        "0004_topic_map",
        """
        CREATE TABLE topics (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            parent_topic_id TEXT REFERENCES topics(id) ON DELETE RESTRICT,
            title TEXT NOT NULL CHECK(length(trim(title)) > 0),
            description TEXT NOT NULL DEFAULT '',
            start_ms INTEGER NOT NULL CHECK(start_ms >= 0),
            end_ms INTEGER NOT NULL CHECK(end_ms > start_ms),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            provenance TEXT NOT NULL CHECK(provenance IN ('EXPLANATION','DERIVED','UNCERTAIN')),
            status TEXT NOT NULL CHECK(status IN ('DRAFT','NEEDS_REVIEW','ACCEPTED','REJECTED')),
            confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_id,ordinal),
            CHECK(parent_topic_id IS NULL OR parent_topic_id <> id)
        );
        CREATE INDEX idx_topics_source_time ON topics(source_id,start_ms,end_ms);
        CREATE INDEX idx_topics_parent ON topics(parent_topic_id,ordinal);
        CREATE TABLE topic_evidence (
            id TEXT PRIMARY KEY,
            topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE RESTRICT,
            evidence_id TEXT NOT NULL REFERENCES evidence_items(id) ON DELETE RESTRICT,
            relation TEXT NOT NULL CHECK(relation IN (
                'INTRODUCES','DEVELOPS','RECAPITULATES','DEMONSTRATES','CONTRASTS'
            )),
            review_state TEXT NOT NULL CHECK(review_state IN (
                'PENDING','ACCEPTED','REJECTED','NEEDS_REVIEW'
            )),
            relevance_score REAL CHECK(relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 1)),
            rationale TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            UNIQUE(topic_id,evidence_id,relation)
        );
        CREATE INDEX idx_topic_evidence_topic ON topic_evidence(topic_id,review_state);
        CREATE TRIGGER topics_validate_source_bounds_insert
        BEFORE INSERT ON topics
        BEGIN
            SELECT CASE WHEN
                (SELECT duration_ms FROM sources WHERE id=NEW.source_id) IS NOT NULL
                AND NEW.end_ms > (SELECT duration_ms FROM sources WHERE id=NEW.source_id)
                THEN RAISE(ABORT,'topic exceeds source duration') END;
            SELECT CASE WHEN NEW.parent_topic_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM topics WHERE id=NEW.parent_topic_id AND source_id=NEW.source_id
            ) THEN RAISE(ABORT,'parent topic must belong to the same source') END;
        END;
        CREATE TRIGGER topics_validate_source_bounds_update
        BEFORE UPDATE OF source_id,parent_topic_id,start_ms,end_ms ON topics
        BEGIN
            SELECT CASE WHEN
                (SELECT duration_ms FROM sources WHERE id=NEW.source_id) IS NOT NULL
                AND NEW.end_ms > (SELECT duration_ms FROM sources WHERE id=NEW.source_id)
                THEN RAISE(ABORT,'topic exceeds source duration') END;
            SELECT CASE WHEN NEW.parent_topic_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM topics WHERE id=NEW.parent_topic_id AND source_id=NEW.source_id
            ) THEN RAISE(ABORT,'parent topic must belong to the same source') END;
        END;
        CREATE TRIGGER topic_evidence_validate_source_insert
        BEFORE INSERT ON topic_evidence
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM topics t JOIN evidence_items e ON e.id=NEW.evidence_id
                WHERE t.id=NEW.topic_id AND t.source_id=e.source_id
            ) THEN RAISE(ABORT,'topic evidence must belong to the topic source') END;
        END;
        """,
    ),
    (
        "0005_topic_evidence_time_alignment",
        """
        CREATE TRIGGER topic_evidence_validate_overlap_insert
        BEFORE INSERT ON topic_evidence
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM topics t JOIN evidence_items e ON e.id=NEW.evidence_id
                WHERE t.id=NEW.topic_id AND t.source_id=e.source_id
                  AND e.start_ms < t.end_ms AND e.end_ms > t.start_ms
            ) THEN RAISE(ABORT,'topic evidence must overlap the topic time range') END;
        END;
        CREATE TRIGGER topic_evidence_validate_overlap_update
        BEFORE UPDATE OF topic_id,evidence_id ON topic_evidence
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM topics t JOIN evidence_items e ON e.id=NEW.evidence_id
                WHERE t.id=NEW.topic_id AND t.source_id=e.source_id
                  AND e.start_ms < t.end_ms AND e.end_ms > t.start_ms
            ) THEN RAISE(ABORT,'topic evidence must overlap the topic time range') END;
        END;
        """,
    ),
    (
        "0006_textbook_composition",
        """
        CREATE TABLE textbooks (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            title TEXT NOT NULL CHECK(length(trim(title)) > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE textbook_versions (
            id TEXT PRIMARY KEY,
            textbook_id TEXT NOT NULL REFERENCES textbooks(id) ON DELETE RESTRICT,
            version_number INTEGER NOT NULL CHECK(version_number > 0),
            title TEXT NOT NULL CHECK(length(trim(title)) > 0),
            status TEXT NOT NULL CHECK(status IN ('DRAFT','IN_REVIEW','READY','PUBLISHED','ARCHIVED')),
            composition_mode TEXT NOT NULL CHECK(composition_mode IN ('SOURCE_ORDER','CONCEPTUAL','HYBRID')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(textbook_id,version_number)
        );
        CREATE INDEX idx_textbook_versions_status ON textbook_versions(textbook_id,status);
        CREATE TABLE textbook_chapters (
            id TEXT PRIMARY KEY,
            version_id TEXT NOT NULL REFERENCES textbook_versions(id) ON DELETE RESTRICT,
            parent_chapter_id TEXT REFERENCES textbook_chapters(id) ON DELETE RESTRICT,
            title TEXT NOT NULL CHECK(length(trim(title)) > 0),
            summary TEXT NOT NULL DEFAULT '',
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            source_start_ms INTEGER CHECK(source_start_ms IS NULL OR source_start_ms >= 0),
            source_end_ms INTEGER CHECK(source_end_ms IS NULL OR source_end_ms > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(version_id,ordinal),
            CHECK(source_start_ms IS NULL OR source_end_ms IS NULL OR source_end_ms > source_start_ms),
            CHECK(parent_chapter_id IS NULL OR parent_chapter_id <> id)
        );
        CREATE INDEX idx_textbook_chapters_order ON textbook_chapters(version_id,ordinal);
        CREATE TABLE chapter_blocks (
            id TEXT PRIMARY KEY,
            chapter_id TEXT NOT NULL REFERENCES textbook_chapters(id) ON DELETE RESTRICT,
            parent_block_id TEXT REFERENCES chapter_blocks(id) ON DELETE RESTRICT,
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            block_type TEXT NOT NULL CHECK(block_type IN (
                'HEADING','PARAGRAPH','DEFINITION','EQUATION','TABLE','DIAGRAM','IMAGE',
                'CODE','EXAMPLE','WORKED_SOLUTION','WARNING','MISCONCEPTION','SUMMARY',
                'EXERCISE','SOURCE_REFERENCE','FOOTNOTE'
            )),
            content_json TEXT NOT NULL CHECK(json_valid(content_json) AND json_type(content_json)='object'),
            provenance TEXT NOT NULL CHECK(provenance IN ('SOURCE','EXPLANATION','DERIVED','EXTERNAL','UNCERTAIN')),
            review_status TEXT NOT NULL CHECK(review_status IN ('DRAFT','NEEDS_REVIEW','ACCEPTED','REJECTED')),
            knowledge_unit_id TEXT REFERENCES knowledge_units(id) ON DELETE RESTRICT,
            claim_id TEXT REFERENCES claims(id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(chapter_id,parent_block_id,ordinal),
            CHECK(parent_block_id IS NULL OR parent_block_id <> id)
        );
        CREATE INDEX idx_chapter_blocks_order ON chapter_blocks(chapter_id,parent_block_id,ordinal);
        CREATE TABLE block_evidence (
            id TEXT PRIMARY KEY,
            block_id TEXT NOT NULL REFERENCES chapter_blocks(id) ON DELETE RESTRICT,
            evidence_id TEXT NOT NULL REFERENCES evidence_items(id) ON DELETE RESTRICT,
            relation TEXT NOT NULL CHECK(relation IN ('SUPPORTS','ILLUSTRATES','CONTEXTUALIZES','CONTRADICTS')),
            review_state TEXT NOT NULL CHECK(review_state IN ('PENDING','ACCEPTED','REJECTED','NEEDS_REVIEW')),
            rationale TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(block_id,evidence_id,relation)
        );
        CREATE INDEX idx_block_evidence_block ON block_evidence(block_id,review_state);
        CREATE TRIGGER chapter_parent_same_version_insert
        BEFORE INSERT ON textbook_chapters
        WHEN NEW.parent_chapter_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM textbook_chapters p
                WHERE p.id=NEW.parent_chapter_id AND p.version_id=NEW.version_id
            ) THEN RAISE(ABORT,'parent chapter must belong to the same version') END;
        END;
        CREATE TRIGGER block_parent_same_chapter_insert
        BEFORE INSERT ON chapter_blocks
        WHEN NEW.parent_block_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM chapter_blocks p
                WHERE p.id=NEW.parent_block_id AND p.chapter_id=NEW.chapter_id
            ) THEN RAISE(ABORT,'parent block must belong to the same chapter') END;
        END;
        CREATE TRIGGER block_evidence_same_source_insert
        BEFORE INSERT ON block_evidence
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM chapter_blocks b
                JOIN textbook_chapters c ON c.id=b.chapter_id
                JOIN textbook_versions v ON v.id=c.version_id
                JOIN textbooks t ON t.id=v.textbook_id
                JOIN evidence_items e ON e.id=NEW.evidence_id
                WHERE b.id=NEW.block_id AND t.source_id=e.source_id
            ) THEN RAISE(ABORT,'block evidence must belong to the textbook source') END;
        END;
        """
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
    for character in sql:
        statement += character
        if character == ";" and sqlite3.complete_statement(statement):
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
