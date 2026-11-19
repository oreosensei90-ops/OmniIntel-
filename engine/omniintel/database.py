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
    (
        "0007_textbook_integrity_guards",
        """
        CREATE UNIQUE INDEX idx_chapter_blocks_root_order
            ON chapter_blocks(chapter_id,ordinal) WHERE parent_block_id IS NULL;
        CREATE UNIQUE INDEX idx_chapter_blocks_child_order
            ON chapter_blocks(chapter_id,parent_block_id,ordinal) WHERE parent_block_id IS NOT NULL;
        CREATE TRIGGER chapter_parent_same_version_update
        BEFORE UPDATE OF version_id,parent_chapter_id ON textbook_chapters
        WHEN NEW.parent_chapter_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM textbook_chapters p
                WHERE p.id=NEW.parent_chapter_id AND p.version_id=NEW.version_id
            ) THEN RAISE(ABORT,'parent chapter must belong to the same version') END;
        END;
        CREATE TRIGGER block_parent_same_chapter_update
        BEFORE UPDATE OF chapter_id,parent_block_id ON chapter_blocks
        WHEN NEW.parent_block_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM chapter_blocks p
                WHERE p.id=NEW.parent_block_id AND p.chapter_id=NEW.chapter_id
            ) THEN RAISE(ABORT,'parent block must belong to the same chapter') END;
        END;
        CREATE TRIGGER block_evidence_same_source_update
        BEFORE UPDATE OF block_id,evidence_id ON block_evidence
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
    (
        "0008_textbook_hierarchy_cycle_guards",
        """
        CREATE TRIGGER chapter_parent_no_cycle
        BEFORE UPDATE OF parent_chapter_id ON textbook_chapters
        WHEN NEW.parent_chapter_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN EXISTS(
                WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM textbook_chapters WHERE parent_chapter_id=NEW.id
                    UNION ALL
                    SELECT c.id FROM textbook_chapters c
                    JOIN descendants d ON c.parent_chapter_id=d.id
                )
                SELECT 1 FROM descendants WHERE id=NEW.parent_chapter_id
            ) THEN RAISE(ABORT,'chapter hierarchy cannot contain a cycle') END;
        END;
        CREATE TRIGGER block_parent_no_cycle
        BEFORE UPDATE OF parent_block_id ON chapter_blocks
        WHEN NEW.parent_block_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN EXISTS(
                WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM chapter_blocks WHERE parent_block_id=NEW.id
                    UNION ALL
                    SELECT b.id FROM chapter_blocks b
                    JOIN descendants d ON b.parent_block_id=d.id
                )
                SELECT 1 FROM descendants WHERE id=NEW.parent_block_id
            ) THEN RAISE(ABORT,'block hierarchy cannot contain a cycle') END;
        END;
        """
    ),
    (
        "0009_content_addressed_assets",
        """
        CREATE TABLE asset_blobs (
            sha256 TEXT PRIMARY KEY CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
            media_type TEXT NOT NULL CHECK(length(trim(media_type)) > 0),
            byte_size INTEGER NOT NULL CHECK(byte_size > 0),
            storage_key TEXT NOT NULL UNIQUE CHECK(length(trim(storage_key)) > 0),
            created_at TEXT NOT NULL
        );
        CREATE TABLE source_assets (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            blob_sha256 TEXT NOT NULL REFERENCES asset_blobs(sha256) ON DELETE RESTRICT,
            role TEXT NOT NULL CHECK(role IN (
                'THUMBNAIL','FRAME','SLIDE','AUDIO','VIDEO','DOCUMENT','DIAGRAM','ATTACHMENT'
            )),
            display_name TEXT NOT NULL CHECK(length(trim(display_name)) > 0),
            created_at TEXT NOT NULL,
            UNIQUE(source_id,blob_sha256,role)
        );
        CREATE INDEX idx_source_assets_source ON source_assets(source_id,role,created_at);
        """
    ),
    (
        "0010_textbook_asset_links",
        """
        CREATE TABLE block_assets (
            id TEXT PRIMARY KEY,
            block_id TEXT NOT NULL REFERENCES chapter_blocks(id) ON DELETE RESTRICT,
            asset_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE RESTRICT,
            ordinal INTEGER NOT NULL DEFAULT 0 CHECK(ordinal >= 0),
            caption TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(block_id,asset_id),
            UNIQUE(block_id,ordinal)
        );
        CREATE INDEX idx_block_assets_block ON block_assets(block_id,ordinal);
        CREATE TRIGGER block_asset_validate_source_insert
        BEFORE INSERT ON block_assets
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM chapter_blocks b
                JOIN textbook_chapters ch ON ch.id=b.chapter_id
                JOIN textbook_versions v ON v.id=ch.version_id
                JOIN textbooks t ON t.id=v.textbook_id
                JOIN source_assets sa ON sa.id=NEW.asset_id
                JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
                WHERE b.id=NEW.block_id AND t.source_id=sa.source_id
                  AND b.block_type IN ('IMAGE','DIAGRAM')
                  AND ab.media_type LIKE 'image/%'
                  AND (
                    (b.block_type='IMAGE' AND sa.role IN ('THUMBNAIL','FRAME','SLIDE','DIAGRAM'))
                    OR (b.block_type='DIAGRAM' AND sa.role IN ('DIAGRAM','FRAME','SLIDE'))
                  )
            ) THEN RAISE(ABORT,'textbook asset must be a compatible image from the same source') END;
        END;
        CREATE TRIGGER block_asset_validate_source_update
        BEFORE UPDATE OF block_id,asset_id ON block_assets
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM chapter_blocks b
                JOIN textbook_chapters ch ON ch.id=b.chapter_id
                JOIN textbook_versions v ON v.id=ch.version_id
                JOIN textbooks t ON t.id=v.textbook_id
                JOIN source_assets sa ON sa.id=NEW.asset_id
                JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
                WHERE b.id=NEW.block_id AND t.source_id=sa.source_id
                  AND b.block_type IN ('IMAGE','DIAGRAM')
                  AND ab.media_type LIKE 'image/%'
                  AND (
                    (b.block_type='IMAGE' AND sa.role IN ('THUMBNAIL','FRAME','SLIDE','DIAGRAM'))
                    OR (b.block_type='DIAGRAM' AND sa.role IN ('DIAGRAM','FRAME','SLIDE'))
                  )
            ) THEN RAISE(ABORT,'textbook asset must be a compatible image from the same source') END;
        END;
        """
    ),
    (
        "0011_pdf_page_extraction",
        """
        CREATE TABLE document_extractions (
            id TEXT PRIMARY KEY,
            source_asset_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE RESTRICT,
            parser_name TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('COMPLETED','COMPLETED_WITH_EMPTY_PAGES')),
            page_count INTEGER NOT NULL CHECK(page_count > 0),
            extracted_at TEXT NOT NULL,
            UNIQUE(source_asset_id,parser_name,parser_version)
        );
        CREATE TABLE document_pages (
            id TEXT PRIMARY KEY,
            extraction_id TEXT NOT NULL REFERENCES document_extractions(id) ON DELETE RESTRICT,
            page_number INTEGER NOT NULL CHECK(page_number > 0),
            text_content TEXT NOT NULL,
            char_count INTEGER NOT NULL CHECK(char_count >= 0),
            content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
            extraction_status TEXT NOT NULL CHECK(extraction_status IN ('TEXT_EXTRACTED','EMPTY')),
            created_at TEXT NOT NULL,
            UNIQUE(extraction_id,page_number),
            CHECK(char_count=length(text_content))
        );
        CREATE INDEX idx_document_pages_extraction_order
            ON document_pages(extraction_id,page_number);
        """
    ),
    (
        "0012_document_page_search",
        """
        CREATE VIRTUAL TABLE document_pages_fts USING fts5(
            text_content,
            content='document_pages',
            content_rowid='rowid',
            tokenize='unicode61 remove_diacritics 2'
        );
        INSERT INTO document_pages_fts(document_pages_fts) VALUES('rebuild');
        CREATE TRIGGER document_pages_fts_insert
        AFTER INSERT ON document_pages
        BEGIN
            INSERT INTO document_pages_fts(rowid,text_content)
            VALUES(NEW.rowid,NEW.text_content);
        END;
        CREATE TRIGGER document_pages_fts_delete
        AFTER DELETE ON document_pages
        BEGIN
            INSERT INTO document_pages_fts(document_pages_fts,rowid,text_content)
            VALUES('delete',OLD.rowid,OLD.text_content);
        END;
        CREATE TRIGGER document_pages_fts_update
        AFTER UPDATE OF text_content ON document_pages
        BEGIN
            INSERT INTO document_pages_fts(document_pages_fts,rowid,text_content)
            VALUES('delete',OLD.rowid,OLD.text_content);
            INSERT INTO document_pages_fts(rowid,text_content)
            VALUES(NEW.rowid,NEW.text_content);
        END;
        """
    ),
    (
        "0013_unified_evidence_references",
        """
        CREATE TABLE evidence_refs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            locator_kind TEXT NOT NULL CHECK(locator_kind IN ('TRANSCRIPT_INTERVAL','DOCUMENT_PAGE')),
            evidence_item_id TEXT UNIQUE REFERENCES evidence_items(id) ON DELETE RESTRICT,
            document_page_id TEXT UNIQUE REFERENCES document_pages(id) ON DELETE RESTRICT,
            source_asset_id TEXT REFERENCES source_assets(id) ON DELETE RESTRICT,
            start_ms INTEGER CHECK(start_ms IS NULL OR start_ms >= 0),
            end_ms INTEGER CHECK(end_ms IS NULL OR end_ms > 0),
            page_number INTEGER CHECK(page_number IS NULL OR page_number > 0),
            created_at TEXT NOT NULL,
            CHECK(
                (locator_kind='TRANSCRIPT_INTERVAL'
                 AND evidence_item_id IS NOT NULL AND document_page_id IS NULL
                 AND source_asset_id IS NULL AND start_ms IS NOT NULL
                 AND end_ms IS NOT NULL AND end_ms > start_ms AND page_number IS NULL)
                OR
                (locator_kind='DOCUMENT_PAGE'
                 AND evidence_item_id IS NULL AND document_page_id IS NOT NULL
                 AND source_asset_id IS NOT NULL AND start_ms IS NULL
                 AND end_ms IS NULL AND page_number IS NOT NULL)
            )
        );
        CREATE INDEX idx_evidence_refs_source ON evidence_refs(source_id,locator_kind,created_at);
        CREATE INDEX idx_evidence_refs_time ON evidence_refs(source_id,start_ms,end_ms);
        CREATE INDEX idx_evidence_refs_page ON evidence_refs(source_asset_id,page_number);
        CREATE TRIGGER evidence_refs_validate_insert
        BEFORE INSERT ON evidence_refs
        BEGIN
            SELECT CASE WHEN NEW.locator_kind='TRANSCRIPT_INTERVAL' AND NOT EXISTS(
                SELECT 1 FROM evidence_items e
                WHERE e.id=NEW.evidence_item_id AND e.source_id=NEW.source_id
                  AND e.start_ms=NEW.start_ms AND e.end_ms=NEW.end_ms
            ) THEN RAISE(ABORT,'transcript evidence reference does not match source interval') END;
            SELECT CASE WHEN NEW.locator_kind='DOCUMENT_PAGE' AND NOT EXISTS(
                SELECT 1 FROM document_pages dp
                JOIN document_extractions de ON de.id=dp.extraction_id
                JOIN source_assets sa ON sa.id=de.source_asset_id
                WHERE dp.id=NEW.document_page_id AND dp.page_number=NEW.page_number
                  AND sa.id=NEW.source_asset_id AND sa.source_id=NEW.source_id
            ) THEN RAISE(ABORT,'document page reference does not match source asset and page') END;
        END;
        CREATE TRIGGER evidence_refs_validate_update
        BEFORE UPDATE OF source_id,locator_kind,evidence_item_id,document_page_id,
                         source_asset_id,start_ms,end_ms,page_number ON evidence_refs
        BEGIN
            SELECT CASE WHEN NEW.locator_kind='TRANSCRIPT_INTERVAL' AND NOT EXISTS(
                SELECT 1 FROM evidence_items e
                WHERE e.id=NEW.evidence_item_id AND e.source_id=NEW.source_id
                  AND e.start_ms=NEW.start_ms AND e.end_ms=NEW.end_ms
            ) THEN RAISE(ABORT,'transcript evidence reference does not match source interval') END;
            SELECT CASE WHEN NEW.locator_kind='DOCUMENT_PAGE' AND NOT EXISTS(
                SELECT 1 FROM document_pages dp
                JOIN document_extractions de ON de.id=dp.extraction_id
                JOIN source_assets sa ON sa.id=de.source_asset_id
                WHERE dp.id=NEW.document_page_id AND dp.page_number=NEW.page_number
                  AND sa.id=NEW.source_asset_id AND sa.source_id=NEW.source_id
            ) THEN RAISE(ABORT,'document page reference does not match source asset and page') END;
        END;
        """
    ),
    (
        "0014_claim_and_block_evidence_references",
        """
        CREATE TABLE claim_evidence_refs (
            id TEXT PRIMARY KEY,
            claim_id TEXT NOT NULL REFERENCES claims(id) ON DELETE RESTRICT,
            evidence_ref_id TEXT NOT NULL REFERENCES evidence_refs(id) ON DELETE RESTRICT,
            relation TEXT NOT NULL CHECK(relation IN (
                'SUPPORTS','CONTRADICTS','QUALIFIES','CONTEXTUALIZES','ILLUSTRATES'
            )),
            review_state TEXT NOT NULL CHECK(review_state IN (
                'PENDING','ACCEPTED','REJECTED','NEEDS_REVIEW'
            )),
            relevance_score REAL CHECK(relevance_score IS NULL OR
                (relevance_score >= 0 AND relevance_score <= 1)),
            rationale TEXT,
            reviewed_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(claim_id,evidence_ref_id,relation)
        );
        CREATE INDEX idx_claim_evidence_refs_claim
            ON claim_evidence_refs(claim_id,review_state);
        CREATE INDEX idx_claim_evidence_refs_ref
            ON claim_evidence_refs(evidence_ref_id);
        CREATE TABLE block_evidence_refs (
            id TEXT PRIMARY KEY,
            block_id TEXT NOT NULL REFERENCES chapter_blocks(id) ON DELETE RESTRICT,
            evidence_ref_id TEXT NOT NULL REFERENCES evidence_refs(id) ON DELETE RESTRICT,
            relation TEXT NOT NULL CHECK(relation IN (
                'SUPPORTS','ILLUSTRATES','CONTEXTUALIZES','CONTRADICTS'
            )),
            review_state TEXT NOT NULL CHECK(review_state IN (
                'PENDING','ACCEPTED','REJECTED','NEEDS_REVIEW'
            )),
            rationale TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(block_id,evidence_ref_id,relation)
        );
        CREATE INDEX idx_block_evidence_refs_block
            ON block_evidence_refs(block_id,review_state);
        CREATE TRIGGER block_evidence_refs_validate_insert
        BEFORE INSERT ON block_evidence_refs
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM chapter_blocks b
                JOIN textbook_chapters ch ON ch.id=b.chapter_id
                JOIN textbook_versions v ON v.id=ch.version_id
                JOIN textbooks t ON t.id=v.textbook_id
                JOIN evidence_refs er ON er.id=NEW.evidence_ref_id
                WHERE b.id=NEW.block_id AND t.source_id=er.source_id
            ) THEN RAISE(ABORT,'block evidence reference must belong to the textbook source') END;
        END;
        CREATE TRIGGER block_evidence_refs_validate_update
        BEFORE UPDATE OF block_id,evidence_ref_id ON block_evidence_refs
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM chapter_blocks b
                JOIN textbook_chapters ch ON ch.id=b.chapter_id
                JOIN textbook_versions v ON v.id=ch.version_id
                JOIN textbooks t ON t.id=v.textbook_id
                JOIN evidence_refs er ON er.id=NEW.evidence_ref_id
                WHERE b.id=NEW.block_id AND t.source_id=er.source_id
            ) THEN RAISE(ABORT,'block evidence reference must belong to the textbook source') END;
        END;
        """
    ),
    (
        "0015_unified_evidence_full_text_search",
        """
        CREATE VIRTUAL TABLE evidence_refs_fts USING fts5(
            evidence_ref_id UNINDEXED,
            content,
            locator_kind UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        );
        INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
        SELECT er.id,COALESCE(e.content,dp.text_content),er.locator_kind
        FROM evidence_refs er
        LEFT JOIN evidence_items e ON e.id=er.evidence_item_id
        LEFT JOIN document_pages dp ON dp.id=er.document_page_id;
        CREATE TRIGGER evidence_refs_fts_insert
        AFTER INSERT ON evidence_refs
        BEGIN
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT NEW.id,COALESCE(e.content,dp.text_content),NEW.locator_kind
            FROM evidence_refs er
            LEFT JOIN evidence_items e ON e.id=er.evidence_item_id
            LEFT JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.id;
        END;
        CREATE TRIGGER evidence_refs_fts_delete
        AFTER DELETE ON evidence_refs
        BEGIN
            DELETE FROM evidence_refs_fts WHERE evidence_ref_id=OLD.id;
        END;
        CREATE TRIGGER evidence_refs_fts_page_update
        AFTER UPDATE OF text_content ON document_pages
        BEGIN
            DELETE FROM evidence_refs_fts
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.id
            );
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,NEW.text_content,er.locator_kind
            FROM evidence_refs er WHERE er.document_page_id=NEW.id;
        END;
        """
    ),
    (
        "0016_document_topic_maps",
        """
        CREATE TABLE document_topics (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            parent_topic_id TEXT REFERENCES document_topics(id) ON DELETE RESTRICT,
            title TEXT NOT NULL CHECK(length(trim(title)) > 0),
            description TEXT NOT NULL DEFAULT '',
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            provenance TEXT NOT NULL CHECK(provenance IN ('EXPLANATION','DERIVED','UNCERTAIN')),
            status TEXT NOT NULL CHECK(status IN ('DRAFT','NEEDS_REVIEW','ACCEPTED','REJECTED')),
            confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_id,ordinal),
            CHECK(parent_topic_id IS NULL OR parent_topic_id <> id)
        );
        CREATE INDEX idx_document_topics_source_order
            ON document_topics(source_id,ordinal);
        CREATE TABLE document_topic_evidence_refs (
            id TEXT PRIMARY KEY,
            topic_id TEXT NOT NULL REFERENCES document_topics(id) ON DELETE RESTRICT,
            evidence_ref_id TEXT NOT NULL REFERENCES evidence_refs(id) ON DELETE RESTRICT,
            relation TEXT NOT NULL CHECK(relation IN (
                'INTRODUCES','DEVELOPS','RECAPITULATES','DEMONSTRATES','CONTRASTS'
            )),
            review_state TEXT NOT NULL CHECK(review_state IN (
                'PENDING','ACCEPTED','REJECTED','NEEDS_REVIEW'
            )),
            relevance_score REAL CHECK(relevance_score IS NULL OR
                (relevance_score >= 0 AND relevance_score <= 1)),
            rationale TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            UNIQUE(topic_id,evidence_ref_id,relation)
        );
        CREATE INDEX idx_document_topic_evidence_topic
            ON document_topic_evidence_refs(topic_id,review_state);
        CREATE TRIGGER document_topic_parent_same_source_insert
        BEFORE INSERT ON document_topics
        WHEN NEW.parent_topic_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_topics p
                WHERE p.id=NEW.parent_topic_id AND p.source_id=NEW.source_id
            ) THEN RAISE(ABORT,'parent document topic must belong to the same source') END;
        END;
        CREATE TRIGGER document_topic_parent_no_cycle
        BEFORE UPDATE OF parent_topic_id ON document_topics
        WHEN NEW.parent_topic_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN EXISTS(
                WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM document_topics WHERE parent_topic_id=NEW.id
                    UNION ALL
                    SELECT t.id FROM document_topics t
                    JOIN descendants d ON t.parent_topic_id=d.id
                )
                SELECT 1 FROM descendants WHERE id=NEW.parent_topic_id
            ) THEN RAISE(ABORT,'document topic hierarchy cannot contain a cycle') END;
        END;
        CREATE TRIGGER document_topic_evidence_same_source_insert
        BEFORE INSERT ON document_topic_evidence_refs
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_topics t
                JOIN evidence_refs er ON er.id=NEW.evidence_ref_id
                WHERE t.id=NEW.topic_id AND t.source_id=er.source_id
            ) THEN RAISE(ABORT,'document topic evidence must belong to the topic source') END;
        END;
        """
    ),
    (
        "0017_document_topic_update_guards",
        """
        CREATE TRIGGER document_topic_parent_same_source_update
        BEFORE UPDATE OF source_id,parent_topic_id ON document_topics
        WHEN NEW.parent_topic_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_topics p
                WHERE p.id=NEW.parent_topic_id AND p.source_id=NEW.source_id
            ) THEN RAISE(ABORT,'parent document topic must belong to the same source') END;
        END;
        CREATE TRIGGER document_topic_evidence_same_source_update
        BEFORE UPDATE OF topic_id,evidence_ref_id ON document_topic_evidence_refs
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_topics t
                JOIN evidence_refs er ON er.id=NEW.evidence_ref_id
                WHERE t.id=NEW.topic_id AND t.source_id=er.source_id
            ) THEN RAISE(ABORT,'document topic evidence must belong to the topic source') END;
        END;
        """
    ),
    (
        "0018_document_ocr_pages",
        """
        CREATE TABLE document_ocr_pages (
            page_id TEXT PRIMARY KEY REFERENCES document_pages(id) ON DELETE RESTRICT,
            rendered_asset_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE RESTRICT,
            engine_name TEXT NOT NULL,
            engine_version TEXT NOT NULL,
            text_content TEXT NOT NULL,
            words_json TEXT NOT NULL CHECK(json_valid(words_json)),
            mean_confidence REAL CHECK(mean_confidence IS NULL OR
                (mean_confidence >= 0 AND mean_confidence <= 100)),
            status TEXT NOT NULL CHECK(status IN (
                'NEEDS_REVIEW','ACCEPTED','REJECTED','EMPTY','FAILED'
            )),
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        );
        CREATE INDEX idx_document_ocr_status ON document_ocr_pages(status);
        DROP TRIGGER evidence_refs_fts_page_update;
        CREATE TRIGGER evidence_refs_fts_page_update
        AFTER UPDATE OF text_content ON document_pages
        BEGIN
            DELETE FROM evidence_refs_fts
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.id
            );
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,
                   trim(COALESCE(NEW.text_content,'') || ' ' ||
                        COALESCE((SELECT o.text_content FROM document_ocr_pages o
                                  WHERE o.page_id=NEW.id),''))
                   ,er.locator_kind
            FROM evidence_refs er WHERE er.document_page_id=NEW.id;
        END;
        CREATE TRIGGER document_ocr_fts_insert
        AFTER INSERT ON document_ocr_pages
        BEGIN
            DELETE FROM evidence_refs_fts
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            );
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,
                   trim(COALESCE(dp.text_content,'') || ' ' || NEW.text_content),
                   er.locator_kind
            FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.document_page_id=NEW.page_id;
        END;
        CREATE TRIGGER document_ocr_fts_update
        AFTER UPDATE OF text_content ON document_ocr_pages
        BEGIN
            DELETE FROM evidence_refs_fts
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            );
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,
                   trim(COALESCE(dp.text_content,'') || ' ' || NEW.text_content),
                   er.locator_kind
            FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.document_page_id=NEW.page_id;
        END;
        CREATE TRIGGER document_ocr_fts_delete
        AFTER DELETE ON document_ocr_pages
        BEGIN
            DELETE FROM evidence_refs_fts
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=OLD.page_id
            );
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,dp.text_content,er.locator_kind
            FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.document_page_id=OLD.page_id;
        END;
        """
    ),
    (
        "0019_document_structure_elements",
        """
        CREATE TABLE document_elements (
            id TEXT PRIMARY KEY,
            page_id TEXT NOT NULL REFERENCES document_pages(id) ON DELETE RESTRICT,
            evidence_ref_id TEXT NOT NULL REFERENCES evidence_refs(id) ON DELETE RESTRICT,
            parser_name TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            element_type TEXT NOT NULL CHECK(element_type IN (
                'HEADING','PARAGRAPH','EQUATION','TABLE','FIGURE','CAPTION','LIST_ITEM'
            )),
            ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
            text_content TEXT NOT NULL DEFAULT '',
            content_json TEXT NOT NULL CHECK(json_valid(content_json)),
            x0 REAL CHECK(x0 IS NULL OR (x0 >= 0 AND x0 <= 1)),
            y0 REAL CHECK(y0 IS NULL OR (y0 >= 0 AND y0 <= 1)),
            x1 REAL CHECK(x1 IS NULL OR (x1 >= 0 AND x1 <= 1)),
            y1 REAL CHECK(y1 IS NULL OR (y1 >= 0 AND y1 <= 1)),
            asset_id TEXT REFERENCES source_assets(id) ON DELETE RESTRICT,
            confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
            provenance TEXT NOT NULL CHECK(provenance IN ('SOURCE','DERIVED','UNCERTAIN')),
            review_state TEXT NOT NULL CHECK(review_state IN (
                'PENDING','ACCEPTED','REJECTED','NEEDS_REVIEW'
            )),
            review_rationale TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            UNIQUE(page_id,parser_name,parser_version,ordinal),
            CHECK(x0 IS NULL OR x1 IS NULL OR x1 >= x0),
            CHECK(y0 IS NULL OR y1 IS NULL OR y1 >= y0)
        );
        CREATE INDEX idx_document_elements_page_order
            ON document_elements(page_id,parser_name,parser_version,ordinal);
        CREATE INDEX idx_document_elements_type_review
            ON document_elements(element_type,review_state);
        ALTER TABLE claim_evidence_refs ADD COLUMN element_id TEXT
            REFERENCES document_elements(id) ON DELETE RESTRICT;
        ALTER TABLE block_evidence_refs ADD COLUMN element_id TEXT
            REFERENCES document_elements(id) ON DELETE RESTRICT;
        ALTER TABLE document_topic_evidence_refs ADD COLUMN element_id TEXT
            REFERENCES document_elements(id) ON DELETE RESTRICT;
        CREATE TRIGGER claim_element_reference_validate_insert
        BEFORE INSERT ON claim_evidence_refs
        WHEN NEW.element_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.evidence_ref_id=NEW.evidence_ref_id
            ) THEN RAISE(ABORT,'claim element must belong to its evidence reference') END;
            SELECT CASE WHEN NEW.review_state='ACCEPTED' AND NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.review_state='ACCEPTED'
            ) THEN RAISE(ABORT,'claim element must be accepted before evidence link') END;
        END;
        CREATE TRIGGER claim_element_reference_validate_update
        BEFORE UPDATE OF element_id,evidence_ref_id,review_state ON claim_evidence_refs
        WHEN NEW.element_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.evidence_ref_id=NEW.evidence_ref_id
            ) THEN RAISE(ABORT,'claim element must belong to its evidence reference') END;
            SELECT CASE WHEN NEW.review_state='ACCEPTED' AND NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.review_state='ACCEPTED'
            ) THEN RAISE(ABORT,'claim element must be accepted before evidence link') END;
        END;
        CREATE TRIGGER block_element_reference_validate_insert
        BEFORE INSERT ON block_evidence_refs
        WHEN NEW.element_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.evidence_ref_id=NEW.evidence_ref_id
            ) THEN RAISE(ABORT,'block element must belong to its evidence reference') END;
            SELECT CASE WHEN NEW.review_state='ACCEPTED' AND NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.review_state='ACCEPTED'
            ) THEN RAISE(ABORT,'block element must be accepted before evidence link') END;
        END;
        CREATE TRIGGER block_element_reference_validate_update
        BEFORE UPDATE OF element_id,evidence_ref_id,review_state ON block_evidence_refs
        WHEN NEW.element_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.evidence_ref_id=NEW.evidence_ref_id
            ) THEN RAISE(ABORT,'block element must belong to its evidence reference') END;
            SELECT CASE WHEN NEW.review_state='ACCEPTED' AND NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.review_state='ACCEPTED'
            ) THEN RAISE(ABORT,'block element must be accepted before evidence link') END;
        END;
        CREATE TRIGGER topic_element_reference_validate_insert
        BEFORE INSERT ON document_topic_evidence_refs
        WHEN NEW.element_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.evidence_ref_id=NEW.evidence_ref_id
            ) THEN RAISE(ABORT,'topic element must belong to its evidence reference') END;
            SELECT CASE WHEN NEW.review_state='ACCEPTED' AND NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.review_state='ACCEPTED'
            ) THEN RAISE(ABORT,'topic element must be accepted before evidence link') END;
        END;
        CREATE TRIGGER topic_element_reference_validate_update
        BEFORE UPDATE OF element_id,evidence_ref_id,review_state ON document_topic_evidence_refs
        WHEN NEW.element_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.evidence_ref_id=NEW.evidence_ref_id
            ) THEN RAISE(ABORT,'topic element must belong to its evidence reference') END;
            SELECT CASE WHEN NEW.review_state='ACCEPTED' AND NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.review_state='ACCEPTED'
            ) THEN RAISE(ABORT,'topic element must be accepted before evidence link') END;
        END;
        CREATE TRIGGER document_element_review_demotion
        AFTER UPDATE OF review_state ON document_elements
        WHEN NEW.review_state <> 'ACCEPTED'
        BEGIN
            UPDATE claim_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
            UPDATE block_evidence_refs SET review_state='NEEDS_REVIEW'
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
            UPDATE document_topic_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
        END;
        CREATE VIRTUAL TABLE document_elements_fts USING fts5(
            element_id UNINDEXED,
            page_id UNINDEXED,
            evidence_ref_id UNINDEXED,
            element_type UNINDEXED,
            content,
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER document_elements_fts_insert
        AFTER INSERT ON document_elements
        WHEN length(trim(NEW.text_content)) > 0
        BEGIN
            INSERT INTO document_elements_fts(
                element_id,page_id,evidence_ref_id,element_type,content
            ) VALUES(
                NEW.id,NEW.page_id,NEW.evidence_ref_id,NEW.element_type,NEW.text_content
            );
            DELETE FROM evidence_refs_fts WHERE evidence_ref_id=NEW.evidence_ref_id;
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,
                   trim(COALESCE(dp.text_content,'') || ' ' ||
                        COALESCE(ocr.text_content,'') || ' ' ||
                        COALESCE((SELECT group_concat(de.text_content,' ')
                                  FROM document_elements de
                                  WHERE de.evidence_ref_id=er.id),''))
                   ,er.locator_kind
            FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            LEFT JOIN document_ocr_pages ocr ON ocr.page_id=dp.id
            WHERE er.id=NEW.evidence_ref_id;
        END;
        CREATE TRIGGER document_elements_fts_delete
        AFTER DELETE ON document_elements
        BEGIN
            DELETE FROM document_elements_fts WHERE element_id=OLD.id;
            DELETE FROM evidence_refs_fts WHERE evidence_ref_id=OLD.evidence_ref_id;
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,
                   trim(COALESCE(dp.text_content,'') || ' ' ||
                        COALESCE(ocr.text_content,'') || ' ' ||
                        COALESCE((SELECT group_concat(de.text_content,' ')
                                  FROM document_elements de
                                  WHERE de.evidence_ref_id=er.id),''))
                   ,er.locator_kind
            FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            LEFT JOIN document_ocr_pages ocr ON ocr.page_id=dp.id
            WHERE er.id=OLD.evidence_ref_id;
        END;
        """
    ),
    (
        "0020_document_review_and_search_guards",
        """
        CREATE TRIGGER document_elements_fts_update
        AFTER UPDATE OF text_content,element_type ON document_elements
        BEGIN
            DELETE FROM document_elements_fts WHERE element_id=NEW.id;
            INSERT INTO document_elements_fts(
                element_id,page_id,evidence_ref_id,element_type,content
            )
            SELECT NEW.id,NEW.page_id,NEW.evidence_ref_id,NEW.element_type,NEW.text_content
            WHERE length(trim(NEW.text_content)) > 0;
            DELETE FROM evidence_refs_fts WHERE evidence_ref_id=NEW.evidence_ref_id;
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,
                   trim(COALESCE(dp.text_content,'') || ' ' ||
                        COALESCE(ocr.text_content,'') || ' ' ||
                        COALESCE((SELECT group_concat(de.text_content,' ')
                                  FROM document_elements de
                                  WHERE de.evidence_ref_id=er.id),''))
                   ,er.locator_kind
            FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            LEFT JOIN document_ocr_pages ocr ON ocr.page_id=dp.id
            WHERE er.id=NEW.evidence_ref_id;
        END;
        DROP TRIGGER document_ocr_fts_insert;
        DROP TRIGGER document_ocr_fts_update;
        DROP TRIGGER document_ocr_fts_delete;
        CREATE TRIGGER document_ocr_fts_insert
        AFTER INSERT ON document_ocr_pages
        BEGIN
            DELETE FROM evidence_refs_fts
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            );
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,
                   trim(COALESCE(dp.text_content,'') || ' ' || NEW.text_content || ' ' ||
                        COALESCE((SELECT group_concat(de.text_content,' ')
                                  FROM document_elements de
                                  WHERE de.evidence_ref_id=er.id),''))
                   ,er.locator_kind
            FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.document_page_id=NEW.page_id;
        END;
        CREATE TRIGGER document_ocr_fts_update
        AFTER UPDATE OF text_content ON document_ocr_pages
        BEGIN
            DELETE FROM evidence_refs_fts
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            );
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,
                   trim(COALESCE(dp.text_content,'') || ' ' || NEW.text_content || ' ' ||
                        COALESCE((SELECT group_concat(de.text_content,' ')
                                  FROM document_elements de
                                  WHERE de.evidence_ref_id=er.id),''))
                   ,er.locator_kind
            FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.document_page_id=NEW.page_id;
        END;
        CREATE TRIGGER document_ocr_fts_delete
        AFTER DELETE ON document_ocr_pages
        BEGIN
            DELETE FROM evidence_refs_fts
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=OLD.page_id
            );
            INSERT INTO evidence_refs_fts(evidence_ref_id,content,locator_kind)
            SELECT er.id,
                   trim(COALESCE(dp.text_content,'') || ' ' ||
                        COALESCE((SELECT group_concat(de.text_content,' ')
                                  FROM document_elements de
                                  WHERE de.evidence_ref_id=er.id),''))
                   ,er.locator_kind
            FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.document_page_id=OLD.page_id;
        END;
        CREATE TRIGGER claim_ocr_review_guard_insert
        BEFORE INSERT ON claim_evidence_refs
        WHEN NEW.review_state='ACCEPTED' AND EXISTS(
            SELECT 1 FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.evidence_ref_id AND length(trim(dp.text_content))=0
              AND NOT EXISTS(
                SELECT 1 FROM document_ocr_pages o
                WHERE o.page_id=dp.id AND o.status='ACCEPTED'
                  AND length(trim(o.text_content))>0
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'OCR page must be accepted before claim evidence link');
        END;
        CREATE TRIGGER claim_ocr_review_guard_update
        BEFORE UPDATE OF review_state,evidence_ref_id ON claim_evidence_refs
        WHEN NEW.review_state='ACCEPTED' AND EXISTS(
            SELECT 1 FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.evidence_ref_id AND length(trim(dp.text_content))=0
              AND NOT EXISTS(
                SELECT 1 FROM document_ocr_pages o
                WHERE o.page_id=dp.id AND o.status='ACCEPTED'
                  AND length(trim(o.text_content))>0
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'OCR page must be accepted before claim evidence link');
        END;
        CREATE TRIGGER block_ocr_review_guard_insert
        BEFORE INSERT ON block_evidence_refs
        WHEN NEW.review_state='ACCEPTED' AND EXISTS(
            SELECT 1 FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.evidence_ref_id AND length(trim(dp.text_content))=0
              AND NOT EXISTS(
                SELECT 1 FROM document_ocr_pages o
                WHERE o.page_id=dp.id AND o.status='ACCEPTED'
                  AND length(trim(o.text_content))>0
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'OCR page must be accepted before block evidence link');
        END;
        CREATE TRIGGER block_ocr_review_guard_update
        BEFORE UPDATE OF review_state,evidence_ref_id ON block_evidence_refs
        WHEN NEW.review_state='ACCEPTED' AND EXISTS(
            SELECT 1 FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.evidence_ref_id AND length(trim(dp.text_content))=0
              AND NOT EXISTS(
                SELECT 1 FROM document_ocr_pages o
                WHERE o.page_id=dp.id AND o.status='ACCEPTED'
                  AND length(trim(o.text_content))>0
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'OCR page must be accepted before block evidence link');
        END;
        CREATE TRIGGER topic_ocr_review_guard_insert
        BEFORE INSERT ON document_topic_evidence_refs
        WHEN NEW.review_state='ACCEPTED' AND EXISTS(
            SELECT 1 FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.evidence_ref_id AND length(trim(dp.text_content))=0
              AND NOT EXISTS(
                SELECT 1 FROM document_ocr_pages o
                WHERE o.page_id=dp.id AND o.status='ACCEPTED'
                  AND length(trim(o.text_content))>0
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'OCR page must be accepted before topic evidence link');
        END;
        CREATE TRIGGER topic_ocr_review_guard_update
        BEFORE UPDATE OF review_state,evidence_ref_id ON document_topic_evidence_refs
        WHEN NEW.review_state='ACCEPTED' AND EXISTS(
            SELECT 1 FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.evidence_ref_id AND length(trim(dp.text_content))=0
              AND NOT EXISTS(
                SELECT 1 FROM document_ocr_pages o
                WHERE o.page_id=dp.id AND o.status='ACCEPTED'
                  AND length(trim(o.text_content))>0
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'OCR page must be accepted before topic evidence link');
        END;
        CREATE TRIGGER document_ocr_review_demotion
        AFTER UPDATE OF status ON document_ocr_pages
        WHEN NEW.status <> 'ACCEPTED'
        BEGIN
            UPDATE claim_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
            UPDATE block_evidence_refs SET review_state='NEEDS_REVIEW'
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
            UPDATE document_topic_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
        END;
        """
    ),
    (
        "0021_document_visual_source_guards",
        """
        CREATE TRIGGER document_ocr_asset_source_insert
        BEFORE INSERT ON document_ocr_pages
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_pages dp
                JOIN document_extractions de ON de.id=dp.extraction_id
                JOIN source_assets original ON original.id=de.source_asset_id
                JOIN source_assets rendered ON rendered.id=NEW.rendered_asset_id
                WHERE dp.id=NEW.page_id AND original.source_id=rendered.source_id
            ) THEN RAISE(ABORT,'OCR render asset must belong to the PDF source') END;
        END;
        CREATE TRIGGER document_ocr_asset_source_update
        BEFORE UPDATE OF page_id,rendered_asset_id ON document_ocr_pages
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_pages dp
                JOIN document_extractions de ON de.id=dp.extraction_id
                JOIN source_assets original ON original.id=de.source_asset_id
                JOIN source_assets rendered ON rendered.id=NEW.rendered_asset_id
                WHERE dp.id=NEW.page_id AND original.source_id=rendered.source_id
            ) THEN RAISE(ABORT,'OCR render asset must belong to the PDF source') END;
        END;
        CREATE TRIGGER document_element_source_validate_insert
        BEFORE INSERT ON document_elements
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_pages dp
                JOIN evidence_refs er ON er.id=NEW.evidence_ref_id
                WHERE dp.id=NEW.page_id AND er.document_page_id=dp.id
                  AND er.locator_kind='DOCUMENT_PAGE'
            ) THEN RAISE(ABORT,'document element must use its own page citation') END;
            SELECT CASE WHEN NEW.asset_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM document_pages dp
                JOIN document_extractions de ON de.id=dp.extraction_id
                JOIN source_assets original ON original.id=de.source_asset_id
                JOIN source_assets visual ON visual.id=NEW.asset_id
                WHERE dp.id=NEW.page_id AND original.source_id=visual.source_id
                  AND visual.role IN ('DIAGRAM','SLIDE','FRAME')
            ) THEN RAISE(ABORT,'document visual asset must belong to the same source') END;
        END;
        CREATE TRIGGER document_element_source_validate_update
        BEFORE UPDATE OF page_id,evidence_ref_id,asset_id ON document_elements
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_pages dp
                JOIN evidence_refs er ON er.id=NEW.evidence_ref_id
                WHERE dp.id=NEW.page_id AND er.document_page_id=dp.id
                  AND er.locator_kind='DOCUMENT_PAGE'
            ) THEN RAISE(ABORT,'document element must use its own page citation') END;
            SELECT CASE WHEN NEW.asset_id IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM document_pages dp
                JOIN document_extractions de ON de.id=dp.extraction_id
                JOIN source_assets original ON original.id=de.source_asset_id
                JOIN source_assets visual ON visual.id=NEW.asset_id
                WHERE dp.id=NEW.page_id AND original.source_id=visual.source_id
                  AND visual.role IN ('DIAGRAM','SLIDE','FRAME')
            ) THEN RAISE(ABORT,'document visual asset must belong to the same source') END;
        END;
        """
    ),
    (
        "0022_recompute_claims_after_review_demotion",
        """
        CREATE TRIGGER document_ocr_claim_status_recompute
        AFTER UPDATE OF status ON document_ocr_pages
        WHEN NEW.status <> 'ACCEPTED'
        BEGIN
            UPDATE claims SET status=CASE
                WHEN provenance='UNCERTAIN' THEN 'UNCERTAIN'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='CONTRADICTS'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='CONTRADICTS'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'CONTESTED'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='QUALIFIES'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='QUALIFIES'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'UNCERTAIN'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='SUPPORTS'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='SUPPORTS'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'SUPPORTED'
                ELSE 'DRAFT' END,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id IN (
                SELECT claim_id FROM claim_evidence_refs
                WHERE evidence_ref_id IN (
                    SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
                )
            );
        END;
        CREATE TRIGGER document_element_claim_status_recompute
        AFTER UPDATE OF review_state ON document_elements
        WHEN NEW.review_state <> 'ACCEPTED'
        BEGIN
            UPDATE claims SET status=CASE
                WHEN provenance='UNCERTAIN' THEN 'UNCERTAIN'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='CONTRADICTS'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='CONTRADICTS'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'CONTESTED'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='QUALIFIES'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='QUALIFIES'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'UNCERTAIN'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='SUPPORTS'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='SUPPORTS'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'SUPPORTED'
                ELSE 'DRAFT' END,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id IN (
                SELECT claim_id FROM claim_evidence_refs WHERE element_id=NEW.id
            );
        END;
        """
    ),
    (
        "0023_ordered_claim_review_demotion",
        """
        DROP TRIGGER document_ocr_claim_status_recompute;
        DROP TRIGGER document_element_claim_status_recompute;
        CREATE TRIGGER document_ocr_claim_status_recompute
        AFTER UPDATE OF status ON document_ocr_pages
        WHEN NEW.status <> 'ACCEPTED'
        BEGIN
            UPDATE claim_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
            UPDATE claims SET status=CASE
                WHEN provenance='UNCERTAIN' THEN 'UNCERTAIN'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='CONTRADICTS'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='CONTRADICTS'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'CONTESTED'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='QUALIFIES'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='QUALIFIES'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'UNCERTAIN'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='SUPPORTS'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='SUPPORTS'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'SUPPORTED'
                ELSE 'DRAFT' END,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id IN (
                SELECT claim_id FROM claim_evidence_refs
                WHERE evidence_ref_id IN (
                    SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
                )
            );
        END;
        CREATE TRIGGER document_element_claim_status_recompute
        AFTER UPDATE OF review_state ON document_elements
        WHEN NEW.review_state <> 'ACCEPTED'
        BEGIN
            UPDATE claim_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
            UPDATE claims SET status=CASE
                WHEN provenance='UNCERTAIN' THEN 'UNCERTAIN'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='CONTRADICTS'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='CONTRADICTS'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'CONTESTED'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='QUALIFIES'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='QUALIFIES'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'UNCERTAIN'
                WHEN EXISTS(
                    SELECT 1 FROM claim_evidence ce
                    WHERE ce.claim_id=claims.id AND ce.relation='SUPPORTS'
                      AND ce.review_state='ACCEPTED'
                ) OR EXISTS(
                    SELECT 1 FROM claim_evidence_refs cer
                    WHERE cer.claim_id=claims.id AND cer.relation='SUPPORTS'
                      AND cer.review_state='ACCEPTED'
                ) THEN 'SUPPORTED'
                ELSE 'DRAFT' END,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id IN (
                SELECT claim_id FROM claim_evidence_refs WHERE element_id=NEW.id
            );
        END;
        """
    ),
    (
        "0024_document_knowledge_candidates",
        """
        ALTER TABLE knowledge_units ADD COLUMN source_element_id TEXT
            REFERENCES document_elements(id) ON DELETE RESTRICT;
        CREATE UNIQUE INDEX idx_knowledge_units_source_element
            ON knowledge_units(source_element_id) WHERE source_element_id IS NOT NULL;
        CREATE TABLE knowledge_unit_evidence_refs (
            id TEXT PRIMARY KEY,
            knowledge_unit_id TEXT NOT NULL REFERENCES knowledge_units(id) ON DELETE RESTRICT,
            evidence_ref_id TEXT NOT NULL REFERENCES evidence_refs(id) ON DELETE RESTRICT,
            element_id TEXT REFERENCES document_elements(id) ON DELETE RESTRICT,
            relation TEXT NOT NULL CHECK(relation IN (
                'SOURCE_EXCERPT','ILLUSTRATES','CONTEXTUALIZES'
            )),
            review_state TEXT NOT NULL CHECK(review_state IN (
                'PENDING','ACCEPTED','REJECTED','NEEDS_REVIEW'
            )),
            rationale TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            UNIQUE(knowledge_unit_id,evidence_ref_id,element_id,relation)
        );
        CREATE INDEX idx_knowledge_unit_evidence_unit
            ON knowledge_unit_evidence_refs(knowledge_unit_id,review_state);
        CREATE TRIGGER knowledge_unit_element_validate_insert
        BEFORE INSERT ON knowledge_unit_evidence_refs
        WHEN NEW.element_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.evidence_ref_id=NEW.evidence_ref_id
            ) THEN RAISE(ABORT,'knowledge unit element must belong to its evidence reference') END;
            SELECT CASE WHEN NEW.review_state='ACCEPTED' AND NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.review_state='ACCEPTED'
            ) THEN RAISE(ABORT,'knowledge unit element must be accepted before evidence link') END;
        END;
        CREATE TRIGGER knowledge_unit_element_validate_update
        BEFORE UPDATE OF element_id,evidence_ref_id,review_state ON knowledge_unit_evidence_refs
        WHEN NEW.element_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.evidence_ref_id=NEW.evidence_ref_id
            ) THEN RAISE(ABORT,'knowledge unit element must belong to its evidence reference') END;
            SELECT CASE WHEN NEW.review_state='ACCEPTED' AND NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.review_state='ACCEPTED'
            ) THEN RAISE(ABORT,'knowledge unit element must be accepted before evidence link') END;
        END;
        CREATE TRIGGER knowledge_unit_ocr_validate_insert
        BEFORE INSERT ON knowledge_unit_evidence_refs
        WHEN NEW.review_state='ACCEPTED' AND EXISTS(
            SELECT 1 FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.evidence_ref_id AND length(trim(dp.text_content))=0
              AND NOT EXISTS(
                SELECT 1 FROM document_ocr_pages o
                WHERE o.page_id=dp.id AND o.status='ACCEPTED'
                  AND length(trim(o.text_content))>0
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'OCR page must be accepted before knowledge evidence link');
        END;
        CREATE TRIGGER knowledge_unit_ocr_validate_update
        BEFORE UPDATE OF review_state,evidence_ref_id ON knowledge_unit_evidence_refs
        WHEN NEW.review_state='ACCEPTED' AND EXISTS(
            SELECT 1 FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.evidence_ref_id AND length(trim(dp.text_content))=0
              AND NOT EXISTS(
                SELECT 1 FROM document_ocr_pages o
                WHERE o.page_id=dp.id AND o.status='ACCEPTED'
                  AND length(trim(o.text_content))>0
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'OCR page must be accepted before knowledge evidence link');
        END;
        CREATE TRIGGER knowledge_unit_element_review_demotion
        AFTER UPDATE OF review_state ON document_elements
        WHEN NEW.review_state <> 'ACCEPTED'
        BEGIN
            UPDATE knowledge_unit_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
        END;
        CREATE TRIGGER knowledge_unit_ocr_review_demotion
        AFTER UPDATE OF status ON document_ocr_pages
        WHEN NEW.status <> 'ACCEPTED'
        BEGIN
            UPDATE knowledge_unit_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
        END;
        """
    ),
    (
        "0025_document_topic_element_multiplicity",
        """
        DROP TRIGGER document_topic_evidence_same_source_insert;
        DROP TRIGGER document_topic_evidence_same_source_update;
        DROP TRIGGER topic_element_reference_validate_insert;
        DROP TRIGGER topic_element_reference_validate_update;
        DROP TRIGGER topic_ocr_review_guard_insert;
        DROP TRIGGER topic_ocr_review_guard_update;
        DROP TRIGGER document_element_review_demotion;
        DROP TRIGGER document_ocr_review_demotion;
        ALTER TABLE document_topic_evidence_refs RENAME TO document_topic_evidence_refs_old;
        CREATE TABLE document_topic_evidence_refs (
            id TEXT PRIMARY KEY,
            topic_id TEXT NOT NULL REFERENCES document_topics(id) ON DELETE RESTRICT,
            evidence_ref_id TEXT NOT NULL REFERENCES evidence_refs(id) ON DELETE RESTRICT,
            relation TEXT NOT NULL CHECK(relation IN (
                'INTRODUCES','DEVELOPS','RECAPITULATES','DEMONSTRATES','CONTRASTS'
            )),
            review_state TEXT NOT NULL CHECK(review_state IN (
                'PENDING','ACCEPTED','REJECTED','NEEDS_REVIEW'
            )),
            relevance_score REAL CHECK(relevance_score IS NULL OR
                (relevance_score >= 0 AND relevance_score <= 1)),
            rationale TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            element_id TEXT REFERENCES document_elements(id) ON DELETE RESTRICT,
            UNIQUE(topic_id,evidence_ref_id,element_id,relation)
        );
        INSERT INTO document_topic_evidence_refs(
            id,topic_id,evidence_ref_id,relation,review_state,relevance_score,
            rationale,created_at,reviewed_at,element_id
        )
        SELECT id,topic_id,evidence_ref_id,relation,review_state,relevance_score,
               rationale,created_at,reviewed_at,NULL
        FROM document_topic_evidence_refs_old;
        DROP TABLE document_topic_evidence_refs_old;
        CREATE UNIQUE INDEX idx_document_topic_evidence_page_unique
            ON document_topic_evidence_refs(topic_id,evidence_ref_id,relation)
            WHERE element_id IS NULL;
        CREATE INDEX idx_document_topic_evidence_topic
            ON document_topic_evidence_refs(topic_id,review_state);
        CREATE TRIGGER document_topic_evidence_same_source_insert
        BEFORE INSERT ON document_topic_evidence_refs
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_topics t
                JOIN evidence_refs er ON er.id=NEW.evidence_ref_id
                WHERE t.id=NEW.topic_id AND t.source_id=er.source_id
            ) THEN RAISE(ABORT,'document topic evidence must belong to the topic source') END;
        END;
        CREATE TRIGGER document_topic_evidence_same_source_update
        BEFORE UPDATE OF topic_id,evidence_ref_id ON document_topic_evidence_refs
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_topics t
                JOIN evidence_refs er ON er.id=NEW.evidence_ref_id
                WHERE t.id=NEW.topic_id AND t.source_id=er.source_id
            ) THEN RAISE(ABORT,'document topic evidence must belong to the topic source') END;
        END;
        CREATE TRIGGER topic_element_reference_validate_insert
        BEFORE INSERT ON document_topic_evidence_refs
        WHEN NEW.element_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.evidence_ref_id=NEW.evidence_ref_id
            ) THEN RAISE(ABORT,'topic element must belong to its evidence reference') END;
            SELECT CASE WHEN NEW.review_state='ACCEPTED' AND NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.review_state='ACCEPTED'
            ) THEN RAISE(ABORT,'topic element must be accepted before evidence link') END;
        END;
        CREATE TRIGGER topic_element_reference_validate_update
        BEFORE UPDATE OF element_id,evidence_ref_id,review_state ON document_topic_evidence_refs
        WHEN NEW.element_id IS NOT NULL
        BEGIN
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.evidence_ref_id=NEW.evidence_ref_id
            ) THEN RAISE(ABORT,'topic element must belong to its evidence reference') END;
            SELECT CASE WHEN NEW.review_state='ACCEPTED' AND NOT EXISTS(
                SELECT 1 FROM document_elements de
                WHERE de.id=NEW.element_id AND de.review_state='ACCEPTED'
            ) THEN RAISE(ABORT,'topic element must be accepted before evidence link') END;
        END;
        CREATE TRIGGER topic_ocr_review_guard_insert
        BEFORE INSERT ON document_topic_evidence_refs
        WHEN NEW.review_state='ACCEPTED' AND EXISTS(
            SELECT 1 FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.evidence_ref_id AND length(trim(dp.text_content))=0
              AND NOT EXISTS(
                SELECT 1 FROM document_ocr_pages o
                WHERE o.page_id=dp.id AND o.status='ACCEPTED'
                  AND length(trim(o.text_content))>0
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'OCR page must be accepted before topic evidence link');
        END;
        CREATE TRIGGER topic_ocr_review_guard_update
        BEFORE UPDATE OF review_state,evidence_ref_id ON document_topic_evidence_refs
        WHEN NEW.review_state='ACCEPTED' AND EXISTS(
            SELECT 1 FROM evidence_refs er
            JOIN document_pages dp ON dp.id=er.document_page_id
            WHERE er.id=NEW.evidence_ref_id AND length(trim(dp.text_content))=0
              AND NOT EXISTS(
                SELECT 1 FROM document_ocr_pages o
                WHERE o.page_id=dp.id AND o.status='ACCEPTED'
                  AND length(trim(o.text_content))>0
              )
        )
        BEGIN
            SELECT RAISE(ABORT,'OCR page must be accepted before topic evidence link');
        END;
        CREATE TRIGGER document_element_review_demotion
        AFTER UPDATE OF review_state ON document_elements
        WHEN NEW.review_state <> 'ACCEPTED'
        BEGIN
            UPDATE claim_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
            UPDATE block_evidence_refs SET review_state='NEEDS_REVIEW'
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
            UPDATE document_topic_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
            UPDATE knowledge_unit_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
        END;
        CREATE TRIGGER document_ocr_review_demotion
        AFTER UPDATE OF status ON document_ocr_pages
        WHEN NEW.status <> 'ACCEPTED'
        BEGIN
            UPDATE claim_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
            UPDATE block_evidence_refs SET review_state='NEEDS_REVIEW'
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
            UPDATE document_topic_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
            UPDATE knowledge_unit_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
        END;
        """
    ),
    (
        "0026_knowledge_unit_source_element_guard",
        """
        CREATE TRIGGER knowledge_unit_element_link_source_insert
        BEFORE INSERT ON knowledge_unit_evidence_refs
        WHEN EXISTS(
            SELECT 1 FROM knowledge_units ku
            WHERE ku.id=NEW.knowledge_unit_id AND ku.source_element_id IS NOT NULL
              AND NEW.element_id IS NOT ku.source_element_id
        )
        BEGIN
            SELECT RAISE(ABORT,'knowledge unit citation must match its source element');
        END;
        CREATE TRIGGER knowledge_unit_element_link_source_update
        BEFORE UPDATE OF knowledge_unit_id,element_id ON knowledge_unit_evidence_refs
        WHEN EXISTS(
            SELECT 1 FROM knowledge_units ku
            WHERE ku.id=NEW.knowledge_unit_id AND ku.source_element_id IS NOT NULL
              AND NEW.element_id IS NOT ku.source_element_id
        )
        BEGIN
            SELECT RAISE(ABORT,'knowledge unit citation must match its source element');
        END;
        """
    ),
    (
        "0027_recompute_topic_status_after_evidence_demotion",
        """
        DROP TRIGGER document_element_review_demotion;
        DROP TRIGGER document_ocr_review_demotion;
        CREATE TRIGGER document_element_review_demotion
        AFTER UPDATE OF review_state ON document_elements
        WHEN NEW.review_state <> 'ACCEPTED'
        BEGIN
            UPDATE claim_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
            UPDATE block_evidence_refs SET review_state='NEEDS_REVIEW'
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
            UPDATE document_topic_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
            UPDATE knowledge_unit_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE element_id=NEW.id AND review_state='ACCEPTED';
            UPDATE document_topics SET status=CASE
                WHEN provenance='UNCERTAIN' THEN 'NEEDS_REVIEW'
                WHEN EXISTS(
                    SELECT 1 FROM document_topic_evidence_refs te
                    WHERE te.topic_id=document_topics.id AND te.review_state='ACCEPTED'
                ) THEN 'ACCEPTED'
                ELSE 'DRAFT' END,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id IN (
                SELECT topic_id FROM document_topic_evidence_refs WHERE element_id=NEW.id
            );
        END;
        CREATE TRIGGER document_ocr_review_demotion
        AFTER UPDATE OF status ON document_ocr_pages
        WHEN NEW.status <> 'ACCEPTED'
        BEGIN
            UPDATE claim_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
            UPDATE block_evidence_refs SET review_state='NEEDS_REVIEW'
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
            UPDATE document_topic_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
            UPDATE knowledge_unit_evidence_refs SET review_state='NEEDS_REVIEW',reviewed_at=NULL
            WHERE evidence_ref_id IN (
                SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
            ) AND review_state='ACCEPTED';
            UPDATE document_topics SET status=CASE
                WHEN provenance='UNCERTAIN' THEN 'NEEDS_REVIEW'
                WHEN EXISTS(
                    SELECT 1 FROM document_topic_evidence_refs te
                    WHERE te.topic_id=document_topics.id AND te.review_state='ACCEPTED'
                ) THEN 'ACCEPTED'
                ELSE 'DRAFT' END,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE id IN (
                SELECT topic_id FROM document_topic_evidence_refs
                WHERE evidence_ref_id IN (
                    SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
                )
            );
        END;
        """
    ),
    (
        "0028_reopen_knowledge_units_after_source_demotion",
        """
        CREATE TRIGGER document_element_knowledge_unit_demotion
        AFTER UPDATE OF review_state ON document_elements
        WHEN NEW.review_state <> 'ACCEPTED'
        BEGIN
            UPDATE knowledge_units SET status='NEEDS_REVIEW',
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE status='VALIDATED' AND id IN (
                SELECT knowledge_unit_id FROM knowledge_unit_evidence_refs
                WHERE element_id=NEW.id
            );
        END;
        CREATE TRIGGER document_ocr_knowledge_unit_demotion
        AFTER UPDATE OF status ON document_ocr_pages
        WHEN NEW.status <> 'ACCEPTED'
        BEGIN
            UPDATE knowledge_units SET status='NEEDS_REVIEW',
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
            WHERE status='VALIDATED' AND id IN (
                SELECT knowledge_unit_id FROM knowledge_unit_evidence_refs
                WHERE evidence_ref_id IN (
                    SELECT id FROM evidence_refs WHERE document_page_id=NEW.page_id
                )
            );
        END;
        """
    ),
    (
        "0029_resumable_audio_transcription",
        """
        CREATE TABLE transcription_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
            source_asset_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE RESTRICT,
            input_sha256 TEXT NOT NULL CHECK(length(input_sha256)=64),
            config_sha256 TEXT NOT NULL CHECK(length(config_sha256)=64),
            adapter_name TEXT NOT NULL,
            adapter_version TEXT NOT NULL,
            model_id TEXT NOT NULL,
            language TEXT,
            chunk_seconds INTEGER NOT NULL CHECK(chunk_seconds > 0),
            sample_rate INTEGER NOT NULL CHECK(sample_rate > 0),
            channels INTEGER NOT NULL CHECK(channels > 0),
            sample_width INTEGER NOT NULL CHECK(sample_width > 0),
            duration_ms INTEGER NOT NULL CHECK(duration_ms > 0),
            status TEXT NOT NULL CHECK(status IN ('RUNNING','PARTIAL','COMPLETED')),
            segment_ids_json TEXT CHECK(segment_ids_json IS NULL OR json_valid(segment_ids_json)),
            evidence_ids_json TEXT CHECK(evidence_ids_json IS NULL OR json_valid(evidence_ids_json)),
            evidence_ref_ids_json TEXT CHECK(evidence_ref_ids_json IS NULL OR json_valid(evidence_ref_ids_json)),
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(source_id,source_asset_id,input_sha256,config_sha256)
        );
        CREATE INDEX idx_transcription_runs_source ON transcription_runs(source_id,created_at);
        CREATE TABLE transcription_chunks (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES transcription_runs(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
            audio_sha256 TEXT NOT NULL CHECK(length(audio_sha256)=64),
            start_ms INTEGER NOT NULL CHECK(start_ms >= 0),
            end_ms INTEGER NOT NULL CHECK(end_ms > start_ms),
            status TEXT NOT NULL CHECK(status IN ('RUNNING','COMPLETED')),
            result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id,chunk_index)
        );
        CREATE INDEX idx_transcription_chunks_run ON transcription_chunks(run_id,chunk_index);
        """
    ),
    (
        "0029_local_media_probe",
        """
        CREATE TABLE media_probes (
            id TEXT PRIMARY KEY,
            source_asset_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE RESTRICT,
            asset_sha256 TEXT NOT NULL CHECK(length(asset_sha256)=64),
            probe_fingerprint TEXT NOT NULL CHECK(length(probe_fingerprint)=64),
            tool_name TEXT NOT NULL CHECK(tool_name='ffprobe'),
            tool_version TEXT NOT NULL CHECK(length(trim(tool_version))>0),
            format_name TEXT NOT NULL CHECK(length(trim(format_name))>0),
            duration_ms INTEGER CHECK(duration_ms IS NULL OR duration_ms>0),
            byte_size INTEGER NOT NULL CHECK(byte_size>0),
            metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
            created_at TEXT NOT NULL,
            UNIQUE(source_asset_id,probe_fingerprint)
        );
        CREATE INDEX idx_media_probes_asset_created
            ON media_probes(source_asset_id,created_at);
        CREATE TABLE media_streams (
            probe_id TEXT NOT NULL REFERENCES media_probes(id) ON DELETE CASCADE,
            stream_index INTEGER NOT NULL CHECK(stream_index>=0),
            codec_type TEXT NOT NULL,
            codec_name TEXT,
            duration_ms INTEGER CHECK(duration_ms IS NULL OR duration_ms>0),
            width INTEGER CHECK(width IS NULL OR width>0),
            height INTEGER CHECK(height IS NULL OR height>0),
            sample_rate INTEGER CHECK(sample_rate IS NULL OR sample_rate>0),
            channels INTEGER CHECK(channels IS NULL OR channels>0),
            metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
            PRIMARY KEY(probe_id,stream_index)
        );
        CREATE INDEX idx_media_streams_type ON media_streams(probe_id,codec_type);
        """
    ),
    (
        "0030_audio_derivatives_and_timeline_offsets",
        """
        ALTER TABLE media_streams ADD COLUMN start_ms INTEGER;
        ALTER TABLE transcription_runs ADD COLUMN time_offset_ms INTEGER NOT NULL DEFAULT 0
            CHECK(time_offset_ms>=0);
        CREATE TABLE media_derivatives (
            id TEXT PRIMARY KEY,
            source_asset_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE RESTRICT,
            output_asset_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE RESTRICT,
            source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
            output_sha256 TEXT NOT NULL CHECK(length(output_sha256)=64),
            config_sha256 TEXT NOT NULL CHECK(length(config_sha256)=64),
            operation TEXT NOT NULL CHECK(operation='AUDIO_PCM_WAV'),
            tool_name TEXT NOT NULL CHECK(tool_name='ffmpeg'),
            tool_version TEXT NOT NULL CHECK(length(trim(tool_version))>0),
            stream_index INTEGER NOT NULL CHECK(stream_index>=0),
            source_stream_start_ms INTEGER,
            time_offset_ms INTEGER NOT NULL CHECK(time_offset_ms>=0),
            duration_ms INTEGER NOT NULL CHECK(duration_ms>0),
            sample_rate INTEGER NOT NULL CHECK(sample_rate=16000),
            channels INTEGER NOT NULL CHECK(channels=1),
            sample_width INTEGER NOT NULL CHECK(sample_width=2),
            byte_size INTEGER NOT NULL CHECK(byte_size>0),
            metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
            created_at TEXT NOT NULL,
            UNIQUE(source_asset_id,config_sha256)
        );
        CREATE INDEX idx_media_derivatives_output ON media_derivatives(output_asset_id);
        CREATE TRIGGER media_derivative_source_guard
        BEFORE INSERT ON media_derivatives
        WHEN
            (SELECT source_id FROM source_assets WHERE id=NEW.source_asset_id) IS NULL
            OR
            (SELECT source_id FROM source_assets WHERE id=NEW.source_asset_id) <>
            (SELECT source_id FROM source_assets WHERE id=NEW.output_asset_id)
            OR
            (SELECT role FROM source_assets WHERE id=NEW.output_asset_id) <> 'AUDIO'
        BEGIN
            SELECT RAISE(ABORT,'media derivative assets must share a source and output role must be AUDIO');
        END;
        """
    ),
    (
        "0031_video_frame_extraction",
        """
        CREATE TABLE frame_extractions (
            id TEXT PRIMARY KEY,
            source_asset_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE RESTRICT,
            source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
            config_sha256 TEXT NOT NULL CHECK(length(config_sha256)=64),
            tool_name TEXT NOT NULL CHECK(tool_name='ffmpeg'),
            tool_version TEXT NOT NULL CHECK(length(trim(tool_version))>0),
            video_stream_index INTEGER NOT NULL CHECK(video_stream_index>=0),
            sample_interval_ms INTEGER NOT NULL CHECK(sample_interval_ms>0),
            frame_count INTEGER NOT NULL CHECK(frame_count>0),
            total_bytes INTEGER NOT NULL CHECK(total_bytes>0),
            total_pixels INTEGER NOT NULL CHECK(total_pixels>0),
            metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
            created_at TEXT NOT NULL,
            UNIQUE(source_asset_id,config_sha256)
        );
        CREATE INDEX idx_frame_extractions_source
            ON frame_extractions(source_asset_id,created_at);
        CREATE TABLE video_frames (
            id TEXT PRIMARY KEY,
            extraction_id TEXT NOT NULL REFERENCES frame_extractions(id) ON DELETE RESTRICT,
            source_asset_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE RESTRICT,
            frame_asset_id TEXT NOT NULL REFERENCES source_assets(id) ON DELETE RESTRICT,
            frame_index INTEGER NOT NULL CHECK(frame_index>=0),
            timestamp_ms INTEGER NOT NULL CHECK(timestamp_ms>=0),
            width INTEGER NOT NULL CHECK(width>0),
            height INTEGER NOT NULL CHECK(height>0),
            byte_size INTEGER NOT NULL CHECK(byte_size>0),
            sha256 TEXT NOT NULL CHECK(length(sha256)=64),
            created_at TEXT NOT NULL,
            UNIQUE(extraction_id,frame_index),
            UNIQUE(extraction_id,timestamp_ms)
        );
        CREATE INDEX idx_video_frames_source_time
            ON video_frames(source_asset_id,timestamp_ms);
        CREATE INDEX idx_video_frames_asset ON video_frames(frame_asset_id);
        CREATE TRIGGER frame_extraction_source_guard
        BEFORE INSERT ON frame_extractions
        WHEN NOT EXISTS(
            SELECT 1 FROM source_assets sa
            JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
            WHERE sa.id=NEW.source_asset_id
              AND sa.blob_sha256=NEW.source_sha256
              AND ab.media_type LIKE 'video/%'
        )
        BEGIN
            SELECT RAISE(ABORT,'frame extraction must reference the verified video source asset');
        END;
        CREATE TRIGGER video_frame_source_guard
        BEFORE INSERT ON video_frames
        WHEN
            (SELECT source_id FROM source_assets WHERE id=NEW.source_asset_id) IS NULL
            OR
            (SELECT source_id FROM source_assets WHERE id=NEW.source_asset_id) <>
            (SELECT source_id FROM source_assets WHERE id=NEW.frame_asset_id)
            OR
            (SELECT role FROM source_assets WHERE id=NEW.frame_asset_id) <> 'FRAME'
            OR
            NOT EXISTS(
                SELECT 1 FROM frame_extractions fe
                WHERE fe.id=NEW.extraction_id AND fe.source_asset_id=NEW.source_asset_id
            )
        BEGIN
            SELECT RAISE(ABORT,'video frame asset must belong to its source and extraction');
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
