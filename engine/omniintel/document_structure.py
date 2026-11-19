"""Deterministic PDF layout extraction into reviewable, page-cited elements."""
from __future__ import annotations

import io
import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber

from .assets import AssetStore
from .database import connect, migrate
from .ids import uuid7
from .models import utc_now

PARSER_NAME = "pdfplumber-layout"
PARSER_VERSION = "1"
_MATH_MARKERS = re.compile(r"[=∑∫√≤≥≠≈→↔Δ±×÷∞∂∇∏^_]")


@dataclass(frozen=True, slots=True)
class DocumentElement:
    id: str
    page_id: str
    evidence_ref_id: str
    page_number: int
    element_type: str
    ordinal: int
    text_content: str
    content: dict[str, Any]
    bbox: tuple[float, float, float, float] | None
    asset_id: str | None
    confidence: float | None
    provenance: str
    review_state: str


@dataclass(frozen=True, slots=True)
class DocumentStructureResult:
    source_id: str
    asset_id: str
    page_count: int
    element_count: int
    counts_by_type: dict[str, int]
    elements: tuple[DocumentElement, ...]


def _clean_text(value: str) -> str:
    return re.sub(r"[ \t]+", " ", value).strip()


def _norm_bbox(
    bbox: tuple[float, float, float, float], width: float, height: float
) -> tuple[float, float, float, float]:
    x0, top, x1, bottom = bbox
    return (
        max(0.0, min(1.0, x0 / width)),
        max(0.0, min(1.0, top / height)),
        max(0.0, min(1.0, x1 / width)),
        max(0.0, min(1.0, bottom / height)),
    )


def _inside_bbox(word: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    center_x = (float(word["x0"]) + float(word["x1"])) / 2
    center_y = (float(word["top"]) + float(word["bottom"])) / 2
    return x0 <= center_x <= x1 and top <= center_y <= bottom


def _group_lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        top = float(word["top"])
        target = next(
            (line for line in reversed(lines)
             if abs(statistics.mean(float(item["top"]) for item in line) - top) <= 3.5),
            None,
        )
        if target is None:
            lines.append([word])
        else:
            target.append(word)
    for line in lines:
        line.sort(key=lambda item: float(item["x0"]))
    return lines


def _native_specs(page: pdfplumber.page.Page) -> list[dict[str, Any]]:
    words = page.extract_words(
        extra_attrs=["fontname", "size"], keep_blank_chars=False, use_text_flow=False
    )
    if not words:
        return []
    font_sizes = [
        float(word.get("size", 0)) for word in words
        if isinstance(word.get("size"), (int, float)) and float(word["size"]) > 0
    ]
    median_size = statistics.median(font_sizes) if font_sizes else 10.0
    specs: list[dict[str, Any]] = []
    table_boxes: list[tuple[float, float, float, float]] = []

    try:
        tables = page.find_tables()
    except Exception:
        tables = []
    for table in tables:
        try:
            rows = table.extract()
            normalized_rows = [
                [_clean_text(cell or "") for cell in row] for row in rows if row
            ]
            if len(normalized_rows) < 2 or max(map(len, normalized_rows), default=0) < 2:
                continue
            bbox = tuple(float(value) for value in table.bbox)
            table_boxes.append(bbox)
            specs.append({
                "type": "TABLE",
                "text": "\n".join(" | ".join(row) for row in normalized_rows),
                "content": {"rows": normalized_rows, "layout_method": "pdfplumber-table"},
                "bbox": bbox,
                "confidence": 0.8,
                "provenance": "SOURCE",
            })
        except Exception:
            continue

    remaining = [
        word for word in words
        if not any(_inside_bbox(word, bbox) for bbox in table_boxes)
    ]
    lines = _group_lines(remaining)
    line_records: list[dict[str, Any]] = []
    for line in lines:
        text = _clean_text(" ".join(str(word["text"]) for word in line))
        if not text:
            continue
        top = min(float(word["top"]) for word in line)
        bottom = max(float(word["bottom"]) for word in line)
        left = min(float(word["x0"]) for word in line)
        right = max(float(word["x1"]) for word in line)
        size = statistics.median(
            [float(word.get("size", median_size)) for word in line]
        )
        fonts = " ".join(str(word.get("fontname", "")).lower() for word in line)
        line_records.append({
            "text": text, "top": top, "bottom": bottom, "x0": left, "x1": right,
            "size": size, "bold": "bold" in fonts or "black" in fonts,
        })

    paragraphs: list[list[dict[str, Any]]] = []
    for line in line_records:
        if not paragraphs:
            paragraphs.append([line])
            continue
        previous = paragraphs[-1][-1]
        gap = line["top"] - previous["bottom"]
        if gap > max(8.0, median_size * 1.6) or line["bold"] or line["size"] >= median_size * 1.25:
            paragraphs.append([line])
        else:
            paragraphs[-1].append(line)

    for paragraph in paragraphs:
        text = "\n".join(item["text"] for item in paragraph).strip()
        if not text:
            continue
        bbox = (
            min(item["x0"] for item in paragraph),
            min(item["top"] for item in paragraph),
            max(item["x1"] for item in paragraph),
            max(item["bottom"] for item in paragraph),
        )
        first = paragraph[0]
        is_heading = (
            (first["size"] >= median_size * 1.25 or first["bold"])
            and len(text) <= 180 and len(paragraph) <= 3
        )
        if _MATH_MARKERS.search(text) and len(text) <= 300:
            element_type = "EQUATION"
        elif is_heading:
            element_type = "HEADING"
        elif text.startswith(("•", "▪", "◦", "-", "–")):
            element_type = "LIST_ITEM"
        else:
            element_type = "PARAGRAPH"
        specs.append({
            "type": element_type,
            "text": text,
            "content": {"text": text, "font_size_pt": first["size"],
                        "layout_method": "pdfplumber-positioned-text"},
            "bbox": bbox,
            "confidence": 0.9,
            "provenance": "SOURCE",
        })

    for image in page.images:
        try:
            bbox = (
                float(image["x0"]), float(image["top"]),
                float(image["x1"]), float(image["bottom"]),
            )
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            specs.append({
                "type": "FIGURE", "text": "",
                "content": {"description": "Embedded image region detected on source page",
                            "layout_method": "pdfplumber-image-object"},
                "bbox": bbox, "confidence": 0.85, "provenance": "SOURCE",
            })
        except (KeyError, TypeError, ValueError):
            continue
    specs.sort(key=lambda item: (
        item["bbox"][1] if item.get("bbox") else 0,
        item["bbox"][0] if item.get("bbox") else 0,
        item["type"],
    ))
    return specs


def _ocr_specs(
    page_row: dict[str, Any], page_width: float, page_height: float,
    database_path: str | Path,
) -> list[dict[str, Any]]:
    with connect(database_path) as conn:
        row = conn.execute(
            """SELECT words_json,mean_confidence,status FROM document_ocr_pages
               WHERE page_id=?""",
            (page_row["id"],),
        ).fetchone()
    if row is None:
        return []
    words = json.loads(row["words_json"])
    if not words:
        return []
    converted = []
    for word in words:
        converted.append({
            "text": word["text"],
            "x0": float(word["x0"]) * page_width,
            "x1": float(word["x1"]) * page_width,
            "top": float(word["y0"]) * page_height,
            "bottom": float(word["y1"]) * page_height,
            "confidence": float(word["confidence"]),
        })
    lines = _group_lines(converted)
    specs = []
    for line in lines:
        text = _clean_text(" ".join(word["text"] for word in line))
        if not text:
            continue
        bbox = (
            min(word["x0"] for word in line), min(word["top"] for word in line),
            max(word["x1"] for word in line), max(word["bottom"] for word in line),
        )
        confidence = statistics.mean(word["confidence"] for word in line) / 100
        specs.append({
            "type": "PARAGRAPH", "text": text,
            "content": {"text": text, "layout_method": "reviewable-ocr-word-boxes",
                        "ocr_status": row["status"]},
            "bbox": bbox, "confidence": confidence,
            "provenance": "UNCERTAIN",
        })
    return specs


def extract_document_structure(
    database_path: str | Path,
    asset_dir: str | Path,
    asset_id: str,
    *,
    max_pages: int = 500,
    max_elements: int = 20_000,
    max_chars_per_element: int = 100_000,
    extract_figure_assets: bool = True,
) -> DocumentStructureResult:
    """Extract positioned text, tables, equations and figure regions from a local PDF."""
    if min(max_pages, max_elements, max_chars_per_element) <= 0:
        raise ValueError("Document structure limits must be positive")
    store = AssetStore(database_path, asset_dir)
    path = store.resolve_path(asset_id, verify_hash=True)
    with connect(database_path) as conn:
        migrate(conn)
        asset = conn.execute(
            """SELECT sa.source_id,ab.media_type FROM source_assets sa
               JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256 WHERE sa.id=?""",
            (asset_id,),
        ).fetchone()
        page_rows = conn.execute(
            """SELECT dp.id,dp.page_number,dp.text_content,er.id AS evidence_ref_id
               FROM document_pages dp
               JOIN document_extractions de ON de.id=dp.extraction_id
               JOIN evidence_refs er ON er.document_page_id=dp.id
               WHERE de.source_asset_id=? ORDER BY dp.page_number""",
            (asset_id,),
        ).fetchall()
    if asset is None or asset["media_type"] != "application/pdf":
        raise ValueError("Selected source asset is not a registered PDF")
    if not page_rows:
        raise ValueError("Run extract-pdf before document structure extraction")
    if len(page_rows) > max_pages:
        raise ValueError(f"PDF page count exceeds structure limit ({max_pages})")

    output: list[DocumentElement] = []
    try:
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) != len(page_rows):
                raise ValueError("PDF page count differs from stored extraction")
            for row, page in zip(page_rows, pdf.pages, strict=True):
                specs = _native_specs(page)
                if not specs and not row["text_content"].strip():
                    specs = _ocr_specs(dict(row), page.width, page.height, database_path)
                for spec in specs:
                    if len(spec["text"]) > max_chars_per_element:
                        raise ValueError("Document element exceeds configured character limit")
                    if len(output) >= max_elements:
                        raise ValueError("Document structure exceeds configured element limit")
                    asset_id_for_element = None
                    bbox = spec.get("bbox")
                    if spec["type"] == "FIGURE" and bbox and extract_figure_assets:
                        try:
                            image = page.crop(bbox).to_image(resolution=120, antialias=False).original
                            buffer = io.BytesIO()
                            image.save(buffer, format="PNG", optimize=True)
                            visual = store.add_bytes(
                                asset["source_id"],buffer.getvalue(),role="DIAGRAM",
                                display_name=f"figure-p{row['page_number']:04d}.png",
                            )
                            asset_id_for_element = visual.id
                        except Exception:
                            asset_id_for_element = None
                    normalized = _norm_bbox(bbox,page.width,page.height) if bbox else None
                    element_id = uuid7()
                    confidence = spec.get("confidence")
                    review_state = "NEEDS_REVIEW"
                    now = utc_now()
                    with connect(database_path) as conn:
                        conn.execute(
                            """INSERT INTO document_elements
                               (id,page_id,evidence_ref_id,parser_name,parser_version,
                                element_type,ordinal,text_content,content_json,
                                x0,y0,x1,y1,asset_id,confidence,provenance,
                                review_state,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) 
                               ON CONFLICT(page_id,parser_name,parser_version,ordinal)
                               DO UPDATE SET
                                 element_type=excluded.element_type,
                                 text_content=excluded.text_content,
                                 content_json=excluded.content_json,
                                 x0=excluded.x0,y0=excluded.y0,x1=excluded.x1,y1=excluded.y1,
                                 asset_id=COALESCE(excluded.asset_id,document_elements.asset_id),
                                 confidence=excluded.confidence,provenance=excluded.provenance,
                                 review_state='NEEDS_REVIEW',reviewed_at=NULL,
                                 review_rationale=NULL""",
                            (
                                element_id,row["id"],row["evidence_ref_id"],PARSER_NAME,
                                PARSER_VERSION,spec["type"],len([
                                    item for item in output
                                    if item.page_id == row["id"]
                                ]),spec["text"],
                                json.dumps(spec["content"],ensure_ascii=False,allow_nan=False),
                                *(normalized or (None,None,None,None)),asset_id_for_element,
                                confidence,spec["provenance"],review_state,now,
                            ),
                        )
                        stored = conn.execute(
                            """SELECT id FROM document_elements
                               WHERE page_id=? AND parser_name=? AND parser_version=? AND ordinal=?""",
                            (row["id"],PARSER_NAME,PARSER_VERSION,len([
                                item for item in output if item.page_id == row["id"]
                            ])),
                        ).fetchone()
                    output.append(DocumentElement(
                        stored["id"],row["id"],row["evidence_ref_id"],row["page_number"],
                        spec["type"],len([item for item in output if item.page_id == row["id"]]),
                        spec["text"],spec["content"],normalized,asset_id_for_element,
                        confidence,spec["provenance"],review_state,
                    ))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"Unable to extract document structure safely: {type(exc).__name__}"
        ) from exc

    counts: dict[str, int] = {}
    for element in output:
        counts[element.element_type] = counts.get(element.element_type, 0) + 1
    return DocumentStructureResult(
        asset["source_id"],asset_id,len(page_rows),len(output),counts,tuple(output)
    )


def list_document_elements(
    database_path: str | Path, page_id: str | None = None
) -> tuple[dict[str, Any], ...]:
    with connect(database_path) as conn:
        rows = conn.execute(
            """SELECT de.*,dp.page_number FROM document_elements de
               JOIN document_pages dp ON dp.id=de.page_id
               WHERE (? IS NULL OR de.page_id=?)
               ORDER BY dp.page_number,de.ordinal""",
            (page_id,page_id),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["content"] = json.loads(item.pop("content_json"))
        result.append(item)
    return tuple(result)


def review_document_element(
    database_path: str | Path,
    element_id: str,
    review_state: str,
    *,
    rationale: str | None = None,
) -> str:
    if review_state not in {"ACCEPTED","REJECTED","NEEDS_REVIEW"}:
        raise ValueError("Element review state must be ACCEPTED, REJECTED or NEEDS_REVIEW")
    with connect(database_path) as conn:
        cursor = conn.execute(
            """UPDATE document_elements
               SET review_state=?,review_rationale=?,reviewed_at=?
               WHERE id=?""",
            (review_state,rationale,utc_now(),element_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Document element does not exist")
    return review_state


def search_document_elements(
    database_path: str | Path, query: str, *, limit: int = 50
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 200:
        raise ValueError("Search limit must be between 1 and 200")
    terms = re.findall(r"[\w]+",query,flags=re.UNICODE)
    if not terms:
        return []
    match = " AND ".join(f'"{term}"' for term in terms)
    with connect(database_path) as conn:
        rows = conn.execute(
            """SELECT f.element_id,f.page_id,f.evidence_ref_id,f.element_type,
                      snippet(document_elements_fts,4,'[',']','…',24) AS excerpt,
                      de.review_state,dp.page_number
               FROM document_elements_fts f
               JOIN document_elements de ON de.id=f.element_id
               JOIN document_pages dp ON dp.id=f.page_id
               WHERE document_elements_fts MATCH ?
               ORDER BY bm25(document_elements_fts),dp.page_number,de.ordinal
               LIMIT ?""",
            (match,limit),
        ).fetchall()
    return [dict(row) for row in rows]
