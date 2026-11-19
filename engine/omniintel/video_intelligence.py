"""Reviewable visual analysis: scene candidates, OCR, descriptions and cross-modal checks.

Heuristics and model outputs are proposals only. No result is automatically accepted as evidence.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .assets import AssetStore
from .database import connect, migrate
from .document_ocr import OCRResult, TesseractOCR, _validate_ocr_result
from .ids import uuid7
from .models import utc_now


@dataclass(frozen=True, slots=True)
class VisualDescription:
    text: str
    model_id: str


@dataclass(frozen=True, slots=True)
class SemanticMatch:
    score: float
    rationale: str


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    verdict: str
    rationale: str


class VisualDescriptionAdapter(Protocol):
    name: str
    version: str
    def describe(self, image_bytes: bytes, *, mime_type: str, timestamp_ms: int) -> VisualDescription: ...


class SemanticAlignmentAdapter(Protocol):
    name: str
    version: str
    model_id: str
    def score(self, image_bytes: bytes, transcript_text: str, *, timestamp_ms: int) -> SemanticMatch: ...


class CrossModalVerifier(Protocol):
    name: str
    version: str
    model_id: str
    def verify(
        self, claim: str, visual_description: str, transcript_text: str | None
    ) -> ClaimVerdict: ...


def normalized_frame_difference(left: bytes, right: bytes, *, size: tuple[int,int]=(64,36)) -> float:
    """Mean absolute grayscale pixel difference normalized to [0,1]."""
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:
        raise RuntimeError("Visual scene analysis requires Pillow: pip install -e '.[vision]'") from exc
    images=[]
    for raw in (left,right):
        image=Image.open(io.BytesIO(raw))
        image.load()
        images.append(image.convert("L").resize(size))
    difference=ImageChops.difference(images[0],images[1])
    score=ImageStat.Stat(difference).mean[0]/255.0
    if not math.isfinite(score):
        raise ValueError("Frame difference calculation returned a non-finite score")
    return min(1.0,max(0.0,score))


def detect_scene_changes(
    database_path: str | Path, asset_dir: str | Path, source_id: str,
    *, threshold: float=0.28, max_comparisons: int=2000,
) -> dict[str,object]:
    if not 0.01 <= threshold <= 1:
        raise ValueError("threshold must be between 0.01 and 1")
    if not 1 <= max_comparisons <= 10000:
        raise ValueError("max_comparisons must be between 1 and 10000")
    store=AssetStore(database_path,asset_dir,max_bytes=64*1024*1024)
    with connect(database_path) as conn:
        migrate(conn)
        rows=conn.execute(
            """SELECT ve.id,ve.timestamp_ms,vf.frame_asset_id
               FROM visual_events ve JOIN video_frames vf ON vf.id=ve.frame_id
               WHERE ve.source_id=? ORDER BY ve.timestamp_ms,ve.id LIMIT ?""",
            (source_id,max_comparisons+1),
        ).fetchall()
    if len(rows)>max_comparisons:
        raise ValueError("Scene analysis exceeds configured comparison limit")
    if len(rows)<2:
        return {"source_id":source_id,"comparisons":0,"candidates":[]}
    candidates=[]
    for previous,current in zip(rows,rows[1:]):
        left=store.resolve_path(previous["frame_asset_id"],verify_hash=True).read_bytes()
        right=store.resolve_path(current["frame_asset_id"],verify_hash=True).read_bytes()
        score=normalized_frame_difference(left,right)
        if score >= threshold:
            candidates.append({
                "previous_event_id":previous["id"],"current_event_id":current["id"],
                "previous_timestamp_ms":previous["timestamp_ms"],
                "current_timestamp_ms":current["timestamp_ms"],"difference_score":score,
            })
    created=0
    with connect(database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for item in candidates:
            existing=conn.execute(
                "SELECT id FROM visual_scene_candidates WHERE previous_event_id=? AND current_event_id=?",
                (item["previous_event_id"],item["current_event_id"]),
            ).fetchone()
            if existing:
                item["id"]=existing["id"]
                continue
            item["id"]=uuid7()
            conn.execute(
                """INSERT INTO visual_scene_candidates
                   (id,source_id,previous_event_id,current_event_id,previous_timestamp_ms,
                    current_timestamp_ms,difference_score,threshold,review_state,created_at)
                   VALUES(?,?,?,?,?,?,?,?, 'NEEDS_REVIEW',?)""",
                (item["id"],source_id,item["previous_event_id"],item["current_event_id"],
                 item["previous_timestamp_ms"],item["current_timestamp_ms"],
                 item["difference_score"],threshold,utc_now()),
            )
            created+=1
    return {"source_id":source_id,"comparisons":len(rows)-1,"created":created,"candidates":candidates}


def ocr_video_frames(
    database_path: str | Path, asset_dir: str | Path, source_id: str,
    *, adapter: object | None=None, max_frames: int=200, timeout_seconds: int=30,
) -> dict[str,object]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Video OCR requires Pillow: pip install -e '.[vision]'") from exc
    recognizer=adapter or TesseractOCR()
    store=AssetStore(database_path,asset_dir,max_bytes=64*1024*1024)
    with connect(database_path) as conn:
        migrate(conn)
        rows=conn.execute(
            """SELECT ve.id,ve.timestamp_ms,vf.frame_asset_id
               FROM visual_events ve JOIN video_frames vf ON vf.id=ve.frame_id
               WHERE ve.source_id=? ORDER BY ve.timestamp_ms LIMIT ?""",
            (source_id,max_frames),
        ).fetchall()
    results=[]
    for row in rows:
        with connect(database_path) as conn:
            old=conn.execute("SELECT id FROM visual_ocr_results WHERE visual_event_id=?",(row["id"],)).fetchone()
        if old:
            results.append({"id":old["id"],"visual_event_id":row["id"],"reused":True})
            continue
        raw=store.resolve_path(row["frame_asset_id"],verify_hash=True).read_bytes()
        image=Image.open(io.BytesIO(raw))
        image.load()
        buffer=io.BytesIO()
        image.convert("RGB").save(buffer,format="PNG",optimize=True)
        recognized=recognizer.recognize_png(buffer.getvalue(),timeout_seconds=timeout_seconds)
        _validate_ocr_result(recognized)
        result_id=uuid7()
        with connect(database_path) as conn:
            conn.execute(
                """INSERT INTO visual_ocr_results
                   (id,source_id,visual_event_id,adapter_name,adapter_version,text_content,
                    words_json,mean_confidence,review_state,created_at)
                   VALUES(?,?,?,?,?,?,?,?, 'NEEDS_REVIEW',?)""",
                (result_id,source_id,row["id"],recognizer.name,recognizer.version,
                 recognized.text,json.dumps([word.__dict__ if hasattr(word,"__dict__") else {
                    "text":word.text,"x0":word.x0,"y0":word.y0,"x1":word.x1,
                    "y1":word.y1,"confidence":word.confidence} for word in recognized.words],
                    ensure_ascii=False,allow_nan=False),recognized.mean_confidence,utc_now()),
            )
        results.append({"id":result_id,"visual_event_id":row["id"],"characters":len(recognized.text),
                        "mean_confidence":recognized.mean_confidence,"review_state":"NEEDS_REVIEW"})
    return {"source_id":source_id,"processed":len(results),"results":results}


def describe_visual_events(
    database_path: str | Path, asset_dir: str | Path, source_id: str,
    adapter: VisualDescriptionAdapter, *, max_frames: int=100,
) -> list[dict[str,object]]:
    if not 1 <= max_frames <= 500:
        raise ValueError("max_frames must be between 1 and 500")
    store=AssetStore(database_path,asset_dir,max_bytes=64*1024*1024)
    with connect(database_path) as conn:
        rows=conn.execute(
            """SELECT ve.id,ve.timestamp_ms,vf.frame_asset_id,ab.media_type
               FROM visual_events ve JOIN video_frames vf ON vf.id=ve.frame_id
               JOIN source_assets sa ON sa.id=vf.frame_asset_id
               JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
               WHERE ve.source_id=? ORDER BY ve.timestamp_ms LIMIT ?""",
            (source_id,max_frames),
        ).fetchall()
    output=[]
    for row in rows:
        image=store.resolve_path(row["frame_asset_id"],verify_hash=True).read_bytes()
        described=adapter.describe(image,mime_type=row["media_type"],timestamp_ms=row["timestamp_ms"])
        if not isinstance(described,VisualDescription) or not described.text.strip() or len(described.text)>20000:
            raise ValueError("Visual description adapter returned invalid output")
        prompt_hash=hashlib.sha256(b"omniintel-visual-description-v1").hexdigest()
        record_id=uuid7()
        with connect(database_path) as conn:
            existing=conn.execute(
                """SELECT id FROM visual_descriptions
                   WHERE visual_event_id=? AND model_id=? AND prompt_sha256=?""",
                (row["id"],described.model_id,prompt_hash),
            ).fetchone()
            if existing:
                output.append({"id":existing["id"],"visual_event_id":row["id"],"reused":True})
                continue
            conn.execute(
                """INSERT INTO visual_descriptions
                   (id,source_id,visual_event_id,adapter_name,adapter_version,model_id,
                    prompt_sha256,description,review_state,created_at)
                   VALUES(?,?,?,?,?,?,?,?, 'NEEDS_REVIEW',?)""",
                (record_id,source_id,row["id"],adapter.name,adapter.version,
                 described.model_id,prompt_hash,described.text.strip(),utc_now()),
            )
        output.append({"id":record_id,"visual_event_id":row["id"],"review_state":"NEEDS_REVIEW"})
    return output


def align_visual_semantics(
    database_path: str | Path, asset_dir: str | Path, source_id: str,
    adapter: SemanticAlignmentAdapter, *, max_pairs: int=500,
) -> list[dict[str,object]]:
    if not 1 <= max_pairs <= 5000:
        raise ValueError("max_pairs must be between 1 and 5000")
    store=AssetStore(database_path,asset_dir,max_bytes=64*1024*1024)
    with connect(database_path) as conn:
        rows=conn.execute(
            """SELECT ve.id,ve.timestamp_ms,vf.frame_asset_id,ts.id AS segment_id,ts.text
               FROM visual_events ve JOIN video_frames vf ON vf.id=ve.frame_id
               JOIN visual_transcript_alignments vta ON vta.visual_event_id=ve.id
               JOIN transcript_segments ts ON ts.id=vta.transcript_segment_id
               WHERE ve.source_id=? ORDER BY ve.timestamp_ms,ts.start_ms LIMIT ?""",
            (source_id,max_pairs),
        ).fetchall()
    output=[]
    for row in rows:
        image=store.resolve_path(row["frame_asset_id"],verify_hash=True).read_bytes()
        match=adapter.score(image,row["text"],timestamp_ms=row["timestamp_ms"])
        if not isinstance(match,SemanticMatch) or not math.isfinite(match.score) or not 0<=match.score<=1:
            raise ValueError("Semantic alignment adapter returned invalid score")
        if not isinstance(match.rationale,str) or len(match.rationale)>5000:
            raise ValueError("Semantic alignment rationale is invalid")
        record_id=uuid7()
        with connect(database_path) as conn:
            existing=conn.execute(
                """SELECT id FROM visual_semantic_alignments
                   WHERE visual_event_id=? AND transcript_segment_id=? AND model_id=?""",
                (row["id"],row["segment_id"],adapter.model_id),
            ).fetchone()
            if existing:
                output.append({"id":existing["id"],"reused":True})
                continue
            conn.execute(
                """INSERT INTO visual_semantic_alignments
                   (id,source_id,visual_event_id,transcript_segment_id,description_id,
                    adapter_name,adapter_version,model_id,score,rationale,review_state,created_at)
                   VALUES(?,?,?,?,NULL,?,?,?,?,?,'NEEDS_REVIEW',?)""",
                (record_id,source_id,row["id"],row["segment_id"],adapter.name,
                 adapter.version,adapter.model_id,match.score,match.rationale,utc_now()),
            )
        output.append({"id":record_id,"visual_event_id":row["id"],
                       "transcript_segment_id":row["segment_id"],"score":match.score,
                       "review_state":"NEEDS_REVIEW"})
    return output


def verify_visual_claim(
    database_path: str | Path, source_id: str, claim_id: str, visual_event_id: str,
    adapter: CrossModalVerifier, *, description_id: str, transcript_segment_id: str | None=None,
) -> str:
    with connect(database_path) as conn:
        claim=conn.execute("SELECT statement FROM claims WHERE id=?",(claim_id,)).fetchone()
        description=conn.execute(
            "SELECT description FROM visual_descriptions WHERE id=? AND source_id=?",
            (description_id,source_id),
        ).fetchone()
        if claim is None or description is None:
            raise ValueError("Claim or source-matched visual description does not exist")
        transcript=None
        if transcript_segment_id:
            segment=conn.execute(
                "SELECT text FROM transcript_segments WHERE id=? AND source_id=?",
                (transcript_segment_id,source_id),
            ).fetchone()
            if segment is None:
                raise ValueError("Transcript segment does not belong to the selected source")
            transcript=segment["text"]
    verdict=adapter.verify(claim["statement"],description["description"],transcript)
    if not isinstance(verdict,ClaimVerdict) or verdict.verdict not in {
        "SUPPORTS","CONTRADICTS","INSUFFICIENT","UNCERTAIN"
    } or not isinstance(verdict.rationale,str) or not verdict.rationale.strip():
        raise ValueError("Cross-modal verifier returned invalid output")
    record_id=uuid7()
    with connect(database_path) as conn:
        conn.execute(
            """INSERT INTO visual_claim_verifications
               (id,source_id,claim_id,visual_event_id,description_id,transcript_segment_id,
                adapter_name,adapter_version,model_id,verdict,rationale,review_state,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,'NEEDS_REVIEW',?)""",
            (record_id,source_id,claim_id,visual_event_id,description_id,
             transcript_segment_id,adapter.name,adapter.version,adapter.model_id,
             verdict.verdict,verdict.rationale[:10000],utc_now()),
        )
    return record_id


def review_visual_record(
    database_path: str | Path, table: str, record_id: str, state: str
) -> str:
    allowed_tables={
        "visual_scene_candidates","visual_ocr_results","visual_descriptions",
        "visual_semantic_alignments","visual_claim_verifications",
    }
    if table not in allowed_tables:
        raise ValueError("Unsupported visual review table")
    if state not in {"ACCEPTED","REJECTED","NEEDS_REVIEW"}:
        raise ValueError("Invalid review state")
    with connect(database_path) as conn:
        cursor=conn.execute(f"UPDATE {table} SET review_state=? WHERE id=?",(state,record_id))
        if cursor.rowcount!=1:
            raise ValueError("Visual record does not exist")
    return state
