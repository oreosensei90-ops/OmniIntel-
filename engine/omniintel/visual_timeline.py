"""Reviewable timestamp links between sampled video frames and transcript segments.

These records are alignment candidates, not scene understanding or semantic claims.
All candidates start in NEEDS_REVIEW and remain source-bound.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now


@dataclass(frozen=True, slots=True)
class AlignmentCandidate:
    transcript_segment_id: str
    relation: str
    delta_ms: int


@dataclass(frozen=True, slots=True)
class VisualTimelineResult:
    source_id: str
    events_created: int
    alignments_created: int
    reused_events: int


def align_timestamp(
    timestamp_ms: int,
    segments: list[dict[str, object]],
    *,
    tolerance_ms: int = 10_000,
) -> tuple[AlignmentCandidate, ...]:
    """Return overlapping transcript segments, or one nearest candidate within tolerance."""
    if not isinstance(timestamp_ms, int) or timestamp_ms < 0:
        raise ValueError("timestamp_ms must be a non-negative integer")
    if not 0 <= tolerance_ms <= 120_000:
        raise ValueError("tolerance_ms must be between 0 and 120000")
    overlapping: list[AlignmentCandidate] = []
    nearest: tuple[int, str] | None = None
    for segment in segments:
        segment_id = str(segment["id"])
        start_ms = int(segment["start_ms"])
        end_ms = int(segment["end_ms"])
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("transcript segment interval is invalid")
        if start_ms <= timestamp_ms <= end_ms:
            overlapping.append(AlignmentCandidate(segment_id, "OVERLAPS", 0))
            continue
        distance = start_ms - timestamp_ms if timestamp_ms < start_ms else timestamp_ms - end_ms
        if nearest is None or distance < nearest[0]:
            nearest = (distance, segment_id)
    if overlapping:
        return tuple(overlapping)
    if nearest is None or nearest[0] > tolerance_ms:
        return ()
    return (AlignmentCandidate(nearest[1], "NEAREST", nearest[0]),)


def build_visual_timeline(
    database_path: str | Path,
    extraction_id: str,
    *,
    tolerance_ms: int = 10_000,
) -> VisualTimelineResult:
    """Persist frame samples and conservative transcript alignment candidates."""
    if not 0 <= tolerance_ms <= 120_000:
        raise ValueError("tolerance_ms must be between 0 and 120000")
    created = reused = linked = 0
    with connect(database_path) as conn:
        migrate(conn)
        extraction = conn.execute(
            """SELECT fe.source_asset_id,sa.source_id
               FROM frame_extractions fe
               JOIN source_assets sa ON sa.id=fe.source_asset_id
               WHERE fe.id=?""",
            (extraction_id,),
        ).fetchone()
        if extraction is None:
            raise ValueError("Frame extraction does not exist")
        source_id = extraction["source_id"]
        frames = conn.execute(
            """SELECT id,timestamp_ms FROM video_frames
               WHERE extraction_id=? ORDER BY timestamp_ms""",
            (extraction_id,),
        ).fetchall()
        if not frames:
            raise ValueError("Frame extraction contains no frames")
        segments = [
            dict(row) for row in conn.execute(
                """SELECT id,start_ms,end_ms FROM transcript_segments
                   WHERE source_id=? ORDER BY start_ms,end_ms,id""",
                (source_id,),
            ).fetchall()
        ]
        conn.execute("BEGIN IMMEDIATE")
        for frame in frames:
            event = conn.execute(
                "SELECT id FROM visual_events WHERE frame_id=?", (frame["id"],)
            ).fetchone()
            if event is None:
                event_id = uuid7()
                conn.execute(
                    """INSERT INTO visual_events
                       (id,source_id,source_asset_id,frame_id,timestamp_ms,event_kind,
                        review_state,created_at)
                       VALUES(?,?,?,?,?,'FRAME_SAMPLE','NEEDS_REVIEW',?)""",
                    (event_id,source_id,extraction["source_asset_id"],
                     frame["id"],frame["timestamp_ms"],utc_now()),
                )
                created += 1
            else:
                event_id = event["id"]
                reused += 1
            for candidate in align_timestamp(
                frame["timestamp_ms"],segments,tolerance_ms=tolerance_ms
            ):
                exists = conn.execute(
                    """SELECT 1 FROM visual_transcript_alignments
                       WHERE visual_event_id=? AND transcript_segment_id=?""",
                    (event_id,candidate.transcript_segment_id),
                ).fetchone()
                if exists:
                    continue
                conn.execute(
                    """INSERT INTO visual_transcript_alignments
                       (id,source_id,visual_event_id,transcript_segment_id,relation,
                        delta_ms,review_state,created_at)
                       VALUES(?,?,?,?,?,?, 'NEEDS_REVIEW',?)""",
                    (uuid7(),source_id,event_id,candidate.transcript_segment_id,
                     candidate.relation,candidate.delta_ms,utc_now()),
                )
                linked += 1
    return VisualTimelineResult(source_id,created,linked,reused)


def list_visual_timeline(
    database_path: str | Path, source_id: str
) -> list[dict[str, object]]:
    with connect(database_path) as conn:
        rows = conn.execute(
            """SELECT ve.id AS visual_event_id,ve.timestamp_ms,ve.review_state,
                      vf.frame_asset_id,vf.frame_index,
                      vta.id AS alignment_id,vta.transcript_segment_id,
                      ts.start_ms AS transcript_start_ms,ts.end_ms AS transcript_end_ms,
                      ts.text AS transcript_text,vta.relation,vta.delta_ms,
                      vta.review_state AS alignment_review_state
               FROM visual_events ve
               JOIN video_frames vf ON vf.id=ve.frame_id
               LEFT JOIN visual_transcript_alignments vta ON vta.visual_event_id=ve.id
               LEFT JOIN transcript_segments ts ON ts.id=vta.transcript_segment_id
               WHERE ve.source_id=?
               ORDER BY ve.timestamp_ms,vta.delta_ms""",
            (source_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def review_visual_event(
    database_path: str | Path, event_id: str, state: str
) -> str:
    if state not in {"ACCEPTED", "REJECTED", "NEEDS_REVIEW"}:
        raise ValueError("Invalid visual event review state")
    with connect(database_path) as conn:
        migrate(conn)
        cursor = conn.execute(
            "UPDATE visual_events SET review_state=? WHERE id=?",
            (state,event_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Visual event does not exist")
    return state
