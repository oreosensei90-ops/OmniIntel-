"""Bounded, local-only PDF text extraction with stable page provenance."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .assets import AssetStore
from .database import connect, migrate
from .ids import uuid7
from .models import utc_now

PARSER_NAME = "pypdf"
PARSER_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    id: str
    page_number: int
    text: str
    char_count: int
    content_sha256: str
    status: str


@dataclass(frozen=True, slots=True)
class PDFExtractionResult:
    extraction_id: str
    source_id: str
    asset_id: str
    page_count: int
    extracted_pages: int
    empty_pages: int
    pages: tuple[ExtractedPage, ...]


def _normalize_page_text(value: str) -> str:
    value = value.replace("\x00", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    return value.strip()


def extract_pdf(
    database_path: str | Path,
    asset_dir: str | Path,
    asset_id: str,
    *,
    max_pages: int = 500,
    max_chars_per_page: int = 100_000,
    max_total_chars: int = 5_000_000,
) -> PDFExtractionResult:
    """Extract text from an already-ingested PDF asset; never fetch or execute PDF content.

    Work is bounded by page and character limits. All page records are committed together,
    and rerunning the same parser version replaces its prior page set atomically.
    """
    if min(max_pages, max_chars_per_page, max_total_chars) <= 0:
        raise ValueError("PDF extraction limits must be positive")

    store = AssetStore(database_path, asset_dir)
    path = store.resolve_path(asset_id, verify_hash=True)
    with connect(database_path) as conn:
        migrate(conn)
        asset = conn.execute(
            """SELECT sa.id,sa.source_id,ab.media_type
               FROM source_assets sa JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
               WHERE sa.id=?""",
            (asset_id,),
        ).fetchone()
    if asset is None:
        raise ValueError("PDF source asset does not exist")
    if asset["media_type"] != "application/pdf":
        raise ValueError("Selected source asset is not a PDF")

    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        page_count = len(reader.pages)
        if page_count <= 0:
            raise ValueError("PDF contains no pages")
        if page_count > max_pages:
            raise ValueError(f"PDF page count exceeds configured maximum ({max_pages})")

        extracted: list[tuple[int, str, str, str]] = []
        total_chars = 0
        for index, page in enumerate(reader.pages, start=1):
            text = _normalize_page_text(page.extract_text() or "")
            if len(text) > max_chars_per_page:
                raise ValueError(
                    f"PDF page {index} exceeds configured character limit "
                    f"({max_chars_per_page})"
                )
            total_chars += len(text)
            if total_chars > max_total_chars:
                raise ValueError(
                    f"PDF extracted text exceeds configured total character limit "
                    f"({max_total_chars})"
                )
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            status = "TEXT_EXTRACTED" if text else "EMPTY"
            extracted.append((index, text, digest, status))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Unable to safely extract PDF text: {type(exc).__name__}") from exc

    now = utc_now()
    with connect(database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """SELECT id FROM document_extractions
               WHERE source_asset_id=? AND parser_name=? AND parser_version=?""",
            (asset_id, PARSER_NAME, PARSER_VERSION),
        ).fetchone()
        extraction_id = existing["id"] if existing else uuid7()
        if existing:
            conn.execute("DELETE FROM document_pages WHERE extraction_id=?", (extraction_id,))
            conn.execute(
                """UPDATE document_extractions
                   SET status=?,page_count=?,extracted_at=? WHERE id=?""",
                (
                    "COMPLETED_WITH_EMPTY_PAGES" if any(not item[1] for item in extracted)
                    else "COMPLETED",
                    page_count, now, extraction_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO document_extractions
                   (id,source_asset_id,parser_name,parser_version,status,page_count,extracted_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    extraction_id, asset_id, PARSER_NAME, PARSER_VERSION,
                    "COMPLETED_WITH_EMPTY_PAGES" if any(not item[1] for item in extracted)
                    else "COMPLETED",
                    page_count, now,
                ),
            )
        pages: list[ExtractedPage] = []
        for page_number, text, digest, status in extracted:
            page_id = uuid7()
            conn.execute(
                """INSERT INTO document_pages
                   (id,extraction_id,page_number,text_content,char_count,
                    content_sha256,extraction_status,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (page_id, extraction_id, page_number, text, len(text), digest, status, now),
            )
            pages.append(
                ExtractedPage(page_id, page_number, text, len(text), digest, status)
            )

    empty = sum(page.status == "EMPTY" for page in pages)
    return PDFExtractionResult(
        extraction_id, asset["source_id"], asset_id, page_count,
        page_count - empty, empty, tuple(pages),
    )


def list_extracted_pages(
    database_path: str | Path, extraction_id: str
) -> tuple[ExtractedPage, ...]:
    with connect(database_path) as conn:
        rows = conn.execute(
            """SELECT id,page_number,text_content,char_count,content_sha256,extraction_status
               FROM document_pages WHERE extraction_id=? ORDER BY page_number""",
            (extraction_id,),
        ).fetchall()
    return tuple(
        ExtractedPage(
            row["id"], row["page_number"], row["text_content"], row["char_count"],
            row["content_sha256"], row["extraction_status"],
        )
        for row in rows
    )

def search_document_pages(
    database_path: str | Path, query: str, *, limit: int = 20
) -> list[dict[str, object]]:
    """Search extracted page text using quoted Unicode FTS terms."""
    if not 1 <= limit <= 100:
        raise ValueError("Search limit must be between 1 and 100")
    terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
    if not terms:
        return []
    match_query = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
    with connect(database_path) as conn:
        rows = conn.execute(
            """SELECT s.id AS source_id,s.title,sa.id AS asset_id,
                      dp.id AS page_id,dp.page_number,
                      snippet(document_pages_fts,0,'[',']','…',18) AS excerpt,
                      bm25(document_pages_fts) AS rank
               FROM document_pages_fts
               JOIN document_pages dp ON dp.rowid=document_pages_fts.rowid
               JOIN document_extractions de ON de.id=dp.extraction_id
               JOIN source_assets sa ON sa.id=de.source_asset_id
               JOIN sources s ON s.id=sa.source_id
               WHERE document_pages_fts MATCH ?
               ORDER BY rank,s.title,dp.page_number
               LIMIT ?""",
            (match_query, limit),
        ).fetchall()
    return [dict(row) for row in rows]

