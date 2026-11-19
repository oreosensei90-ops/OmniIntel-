"""Reviewable visual analysis: scene candidates, OCR, descriptions and cross-modal checks.

Heuristics and model outputs are proposals only. No result is automatically accepted as evidence.
"""
from __future__ import annotations

import hashlib
import io
from itertools import pairwise
import json
import math
import base64
import http.client
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .assets import AssetStore
from .database import connect, migrate
from .document_ocr import TesseractOCR, _validate_ocr_result
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



class OllamaLocalVisionAdapter:
    """Opt-in local Ollama vision adapter; connects only to loopback, never a hosted endpoint."""

    name = "ollama-local-vision"

    def __init__(self, model_id: str, *, timeout_seconds: int = 120):
        if not model_id or len(model_id)>200 or any(ord(ch)<32 for ch in model_id):
            raise ValueError("A valid local Ollama model identifier is required")
        if not 5 <= timeout_seconds <= 600:
            raise ValueError("timeout_seconds must be between 5 and 600")
        self.model_id=model_id
        self.version="ollama-local-api-v1"
        self.timeout_seconds=timeout_seconds
        self.endpoint="http://127.0.0.1:11434/api/generate"

    def _generate(self, prompt: str, image_bytes: bytes | None = None) -> dict[str,object]:
        payload={"model":self.model_id,"prompt":prompt,"stream":False,"format":"json",
                 "options":{"temperature":0}}
        if image_bytes is not None:
            if len(image_bytes)>20*1024*1024:
                raise ValueError("Vision input exceeds 20 MiB")
            payload["images"]=[base64.b64encode(image_bytes).decode("ascii")]
        connection=http.client.HTTPConnection(
            "127.0.0.1",11434,timeout=self.timeout_seconds,
        )
        try:
            connection.request(
                "POST","/api/generate",body=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type":"application/json"},
            )
            response=connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f"Local Ollama returned HTTP {response.status}")
            raw=response.read(2*1024*1024+1)
        except (TimeoutError,OSError,http.client.HTTPException) as exc:
            raise RuntimeError("Local Ollama vision service is unavailable") from exc
        finally:
            connection.close()
        if len(raw)>2*1024*1024:
            raise ValueError("Local model response exceeds 2 MiB")
        envelope=json.loads(raw.decode("utf-8"))
        content=envelope.get("response")
        if not isinstance(content,str) or len(content)>100_000:
            raise ValueError("Local model returned an invalid response envelope")
        result=json.loads(content)
        if not isinstance(result,dict):
            raise TypeError("Local model response must be a JSON object")
        return result

    def describe(self,image_bytes: bytes,*,mime_type: str,timestamp_ms: int) -> VisualDescription:
        result=self._generate(
            "Describe only visible content in this video frame. Do not infer hidden context. "
            "Return JSON with one string field description. Include readable on-screen text "
            "only when legible. Media timestamp: "+str(timestamp_ms)+" ms.",
            image_bytes,
        )
        text=result.get("description")
        if not isinstance(text,str) or not text.strip():
            raise ValueError("Local vision model did not return a description")
        return VisualDescription(text.strip(),self.model_id)

    def score(self,image_bytes: bytes,transcript_text: str,*,timestamp_ms: int) -> SemanticMatch:
        result=self._generate(
            "Assess whether the visible content in this frame is semantically relevant to the "
            "provided spoken transcript segment. Temporal closeness is not evidence. Return JSON "
            "with numeric score from 0 to 1 and concise rationale. Transcript: "
            + transcript_text[:12000] + " Timestamp: "+str(timestamp_ms)+" ms.",
            image_bytes,
        )
        score=result.get("score")
        rationale=result.get("rationale")
        if isinstance(score,bool) or not isinstance(score,(int,float)) or not isinstance(rationale,str):
            raise TypeError("Local semantic model returned invalid score/rationale")
        return SemanticMatch(float(score),rationale[:5000])

    def verify(
        self,claim: str,visual_description: str,transcript_text: str|None
    ) -> ClaimVerdict:
        result=self._generate(
            "Evaluate whether the claim is supported by the supplied visual description and "
            "optional transcript. Do not assume either source is complete. Choose SUPPORTS only "
            "when directly supported, CONTRADICTS only for a direct conflict, INSUFFICIENT when "
            "evidence does not decide, or UNCERTAIN when ambiguous. Return JSON verdict and "
            "rationale. Claim: "+claim[:12000]+" Visual description: "+visual_description[:12000]
            +" Transcript: "+(transcript_text or "[not supplied]")[:12000]
        )
        verdict=result.get("verdict")
        rationale=result.get("rationale")
        if verdict not in {"SUPPORTS","CONTRADICTS","INSUFFICIENT","UNCERTAIN"} or not isinstance(rationale,str):
            raise ValueError("Local cross-modal verifier returned an invalid verdict or rationale")
        return ClaimVerdict(verdict,rationale[:10000])

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
    for previous,current in pairwise(rows):
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
    if not 1 <= max_frames <= 2000:
        raise ValueError("max_frames must be between 1 and 2000")
    if not 1 <= timeout_seconds <= 180:
        raise ValueError("timeout_seconds must be between 1 and 180")
    recognizer=adapter or TesseractOCR()
    store=AssetStore(database_path,asset_dir,max_bytes=64*1024*1024)
    with connect(database_path) as conn:
        migrate(conn)
        rows=conn.execute(
            """SELECT ve.id,ve.timestamp_ms,vf.frame_asset_id
               FROM visual_events ve JOIN video_frames vf ON vf.id=ve.frame_id
               WHERE ve.source_id=? AND ve.review_state='ACCEPTED'
               ORDER BY ve.timestamp_ms LIMIT ?""",
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
               WHERE ve.source_id=? AND ve.review_state='ACCEPTED'
               ORDER BY ve.timestamp_ms LIMIT ?""",
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
               WHERE ve.source_id=? AND ve.review_state='ACCEPTED'
                 AND vta.review_state='ACCEPTED'
               ORDER BY ve.timestamp_ms,ts.start_ms LIMIT ?""",
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
        linked=conn.execute(
            """SELECT 1 FROM claim_evidence_refs cer
               JOIN evidence_refs er ON er.id=cer.evidence_ref_id
               WHERE cer.claim_id=? AND er.source_id=? LIMIT 1""",
            (claim_id,source_id),
        ).fetchone()
        event=conn.execute(
            "SELECT review_state FROM visual_events WHERE id=? AND source_id=?",
            (visual_event_id,source_id),
        ).fetchone()
        accepted_description=conn.execute(
            "SELECT review_state FROM visual_descriptions WHERE id=? AND source_id=?",
            (description_id,source_id),
        ).fetchone()
        if (claim is None or description is None or linked is None or event is None
                or event["review_state"] != "ACCEPTED"
                or accepted_description is None
                or accepted_description["review_state"] != "ACCEPTED"):
            raise ValueError("Claim, frame, description and source evidence must be accepted and source-matched")
        transcript=None
        if transcript_segment_id:
            segment=conn.execute(
                "SELECT text FROM transcript_segments WHERE id=? AND source_id=?",
                (transcript_segment_id,source_id),
            ).fetchone()
            temporal=conn.execute(
                """SELECT review_state FROM visual_transcript_alignments
                   WHERE visual_event_id=? AND transcript_segment_id=?""",
                (visual_event_id,transcript_segment_id),
            ).fetchone()
            if segment is None or temporal is None or temporal["review_state"] != "ACCEPTED":
                raise ValueError("Transcript segment must have an accepted temporal link to this frame")
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
        "visual_transcript_alignments","visual_scene_candidates","visual_ocr_results",
        "visual_descriptions","visual_semantic_alignments","visual_claim_verifications",
    }
    if table not in allowed_tables:
        raise ValueError("Unsupported visual review table")
    if state not in {"ACCEPTED","REJECTED","NEEDS_REVIEW"}:
        raise ValueError("Invalid review state")
    with connect(database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row=conn.execute(f"SELECT * FROM {table} WHERE id=?",(record_id,)).fetchone()
        if row is None:
            raise ValueError("Visual record does not exist")
        if state == "ACCEPTED":
            if table == "visual_transcript_alignments":
                event=conn.execute(
                    "SELECT review_state FROM visual_events WHERE id=?",
                    (row["visual_event_id"],),
                ).fetchone()
                if event is None or event["review_state"] != "ACCEPTED":
                    raise ValueError("Accept the visual frame event before accepting temporal alignment")
            elif table == "visual_scene_candidates":
                accepted=conn.execute(
                    """SELECT count(*) FROM visual_events
                       WHERE id IN (?,?) AND review_state='ACCEPTED'""",
                    (row["previous_event_id"],row["current_event_id"]),
                ).fetchone()[0]
                if accepted != 2:
                    raise ValueError("Both frame events must be accepted before accepting a scene cut")
            elif table in {"visual_ocr_results","visual_descriptions"}:
                event=conn.execute(
                    "SELECT review_state FROM visual_events WHERE id=?",
                    (row["visual_event_id"],),
                ).fetchone()
                if event is None or event["review_state"] != "ACCEPTED":
                    raise ValueError("The visual event must be accepted before accepting its interpretation")
            elif table == "visual_semantic_alignments":
                event=conn.execute(
                    "SELECT review_state FROM visual_events WHERE id=?",
                    (row["visual_event_id"],),
                ).fetchone()
                temporal=conn.execute(
                    """SELECT review_state FROM visual_transcript_alignments
                       WHERE visual_event_id=? AND transcript_segment_id=?""",
                    (row["visual_event_id"],row["transcript_segment_id"]),
                ).fetchone()
                if event is None or event["review_state"] != "ACCEPTED" or temporal is None or temporal["review_state"] != "ACCEPTED":
                    raise ValueError("Accept the frame and temporal alignment before semantic alignment")
            elif table == "visual_claim_verifications":
                event=conn.execute(
                    "SELECT review_state FROM visual_events WHERE id=?",
                    (row["visual_event_id"],),
                ).fetchone()
                description=conn.execute(
                    "SELECT review_state FROM visual_descriptions WHERE id=?",
                    (row["description_id"],),
                ).fetchone() if row["description_id"] else None
                if event is None or event["review_state"] != "ACCEPTED" or description is None or description["review_state"] != "ACCEPTED":
                    raise ValueError("Accept the visual event and description before accepting claim verification")
                if row["transcript_segment_id"]:
                    temporal=conn.execute(
                        """SELECT review_state FROM visual_transcript_alignments
                           WHERE visual_event_id=? AND transcript_segment_id=?""",
                        (row["visual_event_id"],row["transcript_segment_id"]),
                    ).fetchone()
                    if temporal is None or temporal["review_state"] != "ACCEPTED":
                        raise ValueError("Accept the temporal transcript alignment before cross-modal verification")
        conn.execute(f"UPDATE {table} SET review_state=? WHERE id=?",(state,record_id))
    return state
