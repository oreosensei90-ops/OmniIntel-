"""Bounded local PDF OCR with injectable adapters and explicit human review.

OCR is an interpretation of source pixels, not source-authored text. Results remain
NEEDS_REVIEW until explicitly accepted. No network access or shell command construction.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pdfplumber

from .assets import AssetStore
from .database import connect, migrate
from .models import utc_now


@dataclass(frozen=True, slots=True)
class OCRWord:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float


@dataclass(frozen=True, slots=True)
class OCRResult:
    text: str
    words: tuple[OCRWord, ...]
    mean_confidence: float | None


class OCRAdapter(Protocol):
    name: str
    version: str

    def recognize_png(self, png_bytes: bytes, *, timeout_seconds: int) -> OCRResult: ...


@dataclass(frozen=True, slots=True)
class OCRPage:
    page_id: str
    page_number: int
    rendered_asset_id: str
    text: str
    mean_confidence: float | None
    status: str
    words: tuple[OCRWord, ...]


@dataclass(frozen=True, slots=True)
class OCRRun:
    source_id: str
    asset_id: str
    pages: tuple[OCRPage, ...]
    skipped_pages: tuple[int, ...]


class TesseractOCR:
    """Optional local Tesseract CLI adapter; executable must be installed by the user."""

    name = "tesseract-tsv"

    def __init__(self, executable: str = "tesseract") -> None:
        resolved = shutil.which(executable)
        if resolved is None:
            raise RuntimeError(
                "Tesseract OCR is not installed or not on PATH; install it locally "
                "or supply another OCRAdapter"
            )
        self.executable = resolved
        try:
            result = subprocess.run(
                [self.executable, "--version"], capture_output=True, text=True,
                timeout=5, check=True, env={"PATH": str(Path(resolved).parent), "LANG": "C"},
            )
            self.version = result.stdout.splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError, IndexError) as exc:
            raise RuntimeError("Unable to identify the local Tesseract executable") from exc

    def recognize_png(self, png_bytes: bytes, *, timeout_seconds: int = 45) -> OCRResult:
        if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("OCR adapter accepts PNG image bytes only")
        with tempfile.TemporaryDirectory(prefix="omniintel-ocr-") as directory:
            image_path = Path(directory) / "page.png"
            image_path.write_bytes(png_bytes)
            output_base = Path(directory) / "recognized"
            try:
                subprocess.run(
                    [self.executable, str(image_path), str(output_base), "tsv", "--psm", "3"],
                    capture_output=True, text=True, timeout=timeout_seconds, check=True,
                    env={"PATH": str(Path(self.executable).parent), "LANG": "C"},
                )
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError("Tesseract exceeded the per-page OCR time limit") from exc
            except subprocess.CalledProcessError as exc:
                raise RuntimeError("Tesseract failed to process a rendered PDF page") from exc
            tsv_path = output_base.with_suffix(".tsv")
            if not tsv_path.is_file() or tsv_path.stat().st_size > 25 * 1024 * 1024:
                raise ValueError("Tesseract TSV output is missing or exceeds 25 MiB")
            tsv_text = tsv_path.read_text(encoding="utf-8",errors="replace")

        words: list[OCRWord] = []
        image_width = image_height = 0
        reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
        rows = list(reader)
        for row in rows:
            if row.get("level") == "1":
                try:
                    image_width = int(row.get("width", 0))
                    image_height = int(row.get("height", 0))
                except ValueError:
                    pass
                continue
            if row.get("level") != "5":
                continue
            token = (row.get("text") or "").strip()
            try:
                confidence = float(row.get("conf", "-1"))
                left, top = int(row["left"]), int(row["top"])
                width, height = int(row["width"]), int(row["height"])
            except (ValueError, KeyError):
                continue
            if token and confidence >= 0:
                words.append(OCRWord(token, left, top, left + width, top + height, confidence))
        if words and (image_width <= 0 or image_height <= 0):
            raise ValueError("Tesseract did not report valid page image dimensions")
        if image_width and image_height:
            words = [
                OCRWord(
                    word.text, word.x0 / image_width, word.y0 / image_height,
                    word.x1 / image_width, word.y1 / image_height, word.confidence,
                )
                for word in words
            ]
        text = " ".join(word.text for word in words)
        confidence = (
            sum(word.confidence for word in words) / len(words) if words else None
        )
        return OCRResult(text, tuple(words), confidence)


def _render_png(page: pdfplumber.page.Page, dpi: int, max_pixels: int) -> bytes:
    width = max(1, int(page.width * dpi / 72))
    height = max(1, int(page.height * dpi / 72))
    if width * height > max_pixels:
        raise ValueError("Rendered PDF page exceeds the configured pixel limit")
    try:
        image = page.to_image(resolution=dpi, antialias=False).original
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        value = buffer.getvalue()
    except Exception as exc:
        raise ValueError(f"Unable to render PDF page safely: {type(exc).__name__}") from exc
    if len(value) > 25 * 1024 * 1024:
        raise ValueError("Rendered PDF page exceeds the configured image byte limit")
    return value


def ocr_pdf(
    database_path: str | Path,
    asset_dir: str | Path,
    asset_id: str,
    *,
    adapter: OCRAdapter | None = None,
    dpi: int = 144,
    max_pages: int = 200,
    max_pixels_per_page: int = 20_000_000,
    max_total_pixels: int = 200_000_000,
    max_chars_per_page: int = 100_000,
    max_total_chars: int = 5_000_000,
    timeout_seconds_per_page: int = 45,
    force: bool = False,
) -> OCRRun:
    """OCR image-only pages from a verified local PDF; never accepts OCR automatically."""
    if not 72 <= dpi <= 300:
        raise ValueError("OCR render DPI must be between 72 and 300")
    if min(
        max_pages,max_pixels_per_page,max_total_pixels,max_chars_per_page,
        max_total_chars,timeout_seconds_per_page,
    ) <= 0:
        raise ValueError("OCR limits must be positive")
    if adapter is None:
        adapter = TesseractOCR()
    store = AssetStore(database_path, asset_dir)
    pdf_path = store.resolve_path(asset_id, verify_hash=True)
    with connect(database_path) as conn:
        migrate(conn)
        asset = conn.execute(
            """SELECT sa.source_id,ab.media_type FROM source_assets sa
               JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256 WHERE sa.id=?""",
            (asset_id,),
        ).fetchone()
        if asset is None or asset["media_type"] != "application/pdf":
            raise ValueError("Selected source asset is not a registered PDF")
        pages = conn.execute(
            """SELECT dp.id,dp.page_number,dp.text_content,dp.extraction_id
               FROM document_pages dp
               JOIN document_extractions de ON de.id=dp.extraction_id
               WHERE de.source_asset_id=? ORDER BY dp.page_number""",
            (asset_id,),
        ).fetchall()
    if not pages:
        raise ValueError("Run extract-pdf before OCR so page provenance exists")
    if len(pages) > max_pages:
        raise ValueError(f"PDF page count exceeds OCR limit ({max_pages})")

    results: list[OCRPage] = []
    skipped: list[int] = []
    total_pixels = 0
    total_chars = 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) != len(pages):
                raise ValueError("PDF page count differs from its stored extraction")
            for row, page in zip(pages, pdf.pages, strict=True):
                if row["text_content"].strip():
                    skipped.append(row["page_number"])
                    continue
                with connect(database_path) as conn:
                    existing = conn.execute(
                        "SELECT status FROM document_ocr_pages WHERE page_id=?",
                        (row["id"],),
                    ).fetchone()
                if existing and not force:
                    skipped.append(row["page_number"])
                    continue
                estimated = int(page.width * dpi / 72) * int(page.height * dpi / 72)
                total_pixels += estimated
                if total_pixels > max_total_pixels:
                    raise ValueError("PDF OCR render exceeds the configured total pixel limit")
                png = _render_png(page, dpi, max_pixels_per_page)
                ocr = adapter.recognize_png(png, timeout_seconds=timeout_seconds_per_page)
                if len(ocr.text) > max_chars_per_page:
                    raise ValueError("OCR page text exceeds the configured character limit")
                total_chars += len(ocr.text)
                if total_chars > max_total_chars:
                    raise ValueError("OCR output exceeds the configured total character limit")
                rendered = store.add_bytes(
                    asset["source_id"], png, role="SLIDE",
                    display_name=f"ocr-page-{row['page_number']:04d}.png",
                )
                status = "NEEDS_REVIEW" if ocr.text.strip() else "EMPTY"
                now = utc_now()
                with connect(database_path) as conn:
                    conn.execute(
                        """INSERT INTO document_ocr_pages
                           (page_id,rendered_asset_id,engine_name,engine_version,text_content,
                            words_json,mean_confidence,status,created_at,reviewed_at)
                           VALUES(?,?,?,?,?,?,?,?,?,NULL)
                           ON CONFLICT(page_id) DO UPDATE SET
                             rendered_asset_id=excluded.rendered_asset_id,
                             engine_name=excluded.engine_name,
                             engine_version=excluded.engine_version,
                             text_content=excluded.text_content,
                             words_json=excluded.words_json,
                             mean_confidence=excluded.mean_confidence,
                             status=excluded.status,created_at=excluded.created_at,
                             reviewed_at=NULL""",
                        (
                            row["id"],rendered.id,adapter.name,adapter.version,ocr.text,
                            json.dumps([word.__dict__ if hasattr(word, "__dict__") else {
                                "text": word.text, "x0": word.x0, "y0": word.y0,
                                "x1": word.x1, "y1": word.y1, "confidence": word.confidence,
                            } for word in ocr.words],ensure_ascii=False),
                            ocr.mean_confidence,status,now,
                        ),
                    )
                results.append(OCRPage(
                    row["id"],row["page_number"],rendered.id,ocr.text,
                    ocr.mean_confidence,status,ocr.words,
                ))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Unable to complete bounded PDF OCR: {type(exc).__name__}") from exc
    return OCRRun(asset["source_id"],asset_id,tuple(results),tuple(skipped))


def review_ocr_page(
    database_path: str | Path, page_id: str, review_state: str
) -> str:
    if review_state not in {"ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
        raise ValueError("OCR review state must be ACCEPTED, REJECTED or NEEDS_REVIEW")
    with connect(database_path) as conn:
        cursor = conn.execute(
            """UPDATE document_ocr_pages SET status=?,reviewed_at=?
               WHERE page_id=? AND status<>'EMPTY'""",
            (review_state,utc_now(),page_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Non-empty OCR page does not exist")
    return review_state


def get_ocr_page(database_path: str | Path, page_id: str) -> dict[str, object] | None:
    with connect(database_path) as conn:
        row = conn.execute(
            """SELECT page_id,rendered_asset_id,engine_name,engine_version,text_content,
                      words_json,mean_confidence,status,created_at,reviewed_at
               FROM document_ocr_pages WHERE page_id=?""",
            (page_id,),
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["words"] = json.loads(result.pop("words_json"))
    return result
