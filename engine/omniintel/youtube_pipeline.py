"""Consent-gated YouTube caption intake and evidence-preserving textbook composition.

This adapter retrieves public captions only. It never downloads video/audio, bypasses
DRM, uses cookies, or contacts an LLM. Local audio transcription remains a separate,
explicitly selected workflow using the existing WAV/ASR pipeline.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .captions import parse_caption_text
from .database import connect
from .models import TranscriptImport, TranscriptSegmentInput
from .store import OmniIntelStore
from .textbook import BlockInput, TextbookStore
from .reader_export import to_reader_export

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}


def normalize_youtube_url(raw: str) -> tuple[str, str]:
    """Return canonical watch URL and video ID; reject lookalike hosts and URL credentials."""
    if not isinstance(raw, str) or len(raw) > 2048:
        raise ValueError("YouTube URL must be a string no longer than 2048 characters")
    parsed = urlparse(raw.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _ALLOWED_HOSTS:
        raise ValueError("Only youtube.com and youtu.be video URLs are supported")
    if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        raise ValueError("YouTube URL must not contain credentials or a non-standard port")
    if parsed.fragment:
        # Fragments do not identify a different video and are not forwarded.
        pass
    video_id = None
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [None])[0]
    else:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed"}:
            video_id = parts[1]
    if not video_id or not _VIDEO_ID.fullmatch(video_id):
        raise ValueError("URL does not contain a valid YouTube video ID")
    return f"https://www.youtube.com/watch?v={video_id}", video_id


def _yt_dlp():
    try:
        import yt_dlp
    except ImportError as error:
        raise RuntimeError("Install the optional YouTube adapter: pip install -e '.[youtube]'") from error
    return yt_dlp


def inspect_video(url: str) -> dict:
    """Fetch bounded public metadata without downloading media."""
    canonical, video_id = normalize_youtube_url(url)
    yt_dlp = _yt_dlp()
    options = {"quiet": True, "no_warnings": True, "skip_download": True,
               "noplaylist": True, "extract_flat": False}
    with yt_dlp.YoutubeDL(options) as client:
        info = client.extract_info(canonical, download=False)
    if not isinstance(info, dict) or info.get("_type") == "playlist":
        raise ValueError("A single video is required; playlists are not accepted")
    duration = info.get("duration")
    if duration is not None and (not isinstance(duration, (int, float)) or duration <= 0 or duration > 12 * 60 * 60):
        raise ValueError("Video duration is outside the supported 12-hour limit")
    return {
        "video_id": video_id,
        "url": canonical,
        "title": str(info.get("title") or f"YouTube video {video_id}")[:500],
        "uploader": str(info.get("uploader") or info.get("channel") or "")[:300],
        "duration_ms": round(duration * 1000) if duration else None,
        "language": info.get("language"),
        "description": str(info.get("description") or "")[:4000],
        "availability": str(info.get("availability") or "unknown"),
    }


def fetch_public_captions(url: str, *, language: str | None = None) -> tuple[str, str]:
    """Download caption sidecars only; never fetch the video/audio stream."""
    canonical, _ = normalize_youtube_url(url)
    yt_dlp = _yt_dlp()
    languages = [language] if language else ["en", "en.*", "hi", "hi.*"]
    with tempfile.TemporaryDirectory(prefix="omniintel-captions-") as directory:
        options = {
            "quiet": True, "no_warnings": True, "skip_download": True,
            "noplaylist": True, "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": languages, "subtitlesformat": "vtt/best",
            "outtmpl": str(Path(directory) / "caption.%(ext)s"),
            "overwrites": True,
        }
        with yt_dlp.YoutubeDL(options) as client:
            client.download([canonical])
        files = sorted(Path(directory).glob("*.vtt"))
        if not files:
            raise RuntimeError(
                "No public captions were available in the selected languages. "
                "No video/audio was downloaded. Import an audio file you own or are authorized "
                "to process, then use the existing local WAV transcription workflow."
            )
        chosen = files[0]
        return chosen.read_text(encoding="utf-8-sig"), chosen.stem.rsplit(".", 1)[-1]


def _chapter_groups(segments, chapter_ms: int):
    groups = []
    current = []
    start = None
    for segment in segments:
        if current and (segment.start_ms - start >= chapter_ms):
            groups.append(current)
            current = []
            start = None
        if start is None:
            start = segment.start_ms
        current.append(segment)
    if current:
        groups.append(current)
    return groups


def compose_transcript_textbook(
    database_path: str | Path,
    transcript: TranscriptImport,
    *,
    source_metadata: dict | None = None,
    chapter_minutes: int = 10,
) -> dict:
    """Persist a transcript and build a source-faithful, timestamp-cited reader draft.

    This is deliberately extractive: paragraphs reproduce transcript text. Questions
    are review prompts, not model-generated claims. Unstated definitions are not invented.
    """
    if not 1 <= chapter_minutes <= 30:
        raise ValueError("chapter_minutes must be between 1 and 30")
    transcript.validate()
    imported = OmniIntelStore(database_path).import_transcript(transcript)
    store = TextbookStore(database_path)
    textbook_id = store.create_textbook(imported.source_id, transcript.title)
    version_id = store.create_version(textbook_id, "Transcript reader draft", composition_mode="SOURCE_ORDER")
    evidence_by_segment = {id(segment): evidence_id for segment, evidence_id in zip(transcript.segments, imported.evidence_ids, strict=True)}
    groups = _chapter_groups(transcript.segments, chapter_minutes * 60_000)
    for chapter_index, group in enumerate(groups):
        first, last = group[0], group[-1]
        start_label = f"{first.start_ms // 60000:02d}:{(first.start_ms // 1000) % 60:02d}"
        end_label = f"{last.end_ms // 60000:02d}:{(last.end_ms // 1000) % 60:02d}"
        chapter_id = store.add_chapter(
            version_id, f"Chapter {chapter_index + 1} · {start_label}–{end_label}",
            ordinal=chapter_index, summary=f"Source transcript coverage: {start_label} to {end_label}.",
            source_start_ms=first.start_ms, source_end_ms=last.end_ms,
        )
        store.add_block(chapter_id, BlockInput(
            "HEADING", {"text": f"Transcript · {start_label}–{end_label}"},
            "SOURCE", "ACCEPTED", ordinal=0,
        ))
        for paragraph_index in range(0, len(group), 8):
            passage = group[paragraph_index:paragraph_index + 8]
            text = " ".join(segment.text.strip() for segment in passage)
            block_id = store.add_block(chapter_id, BlockInput(
                "PARAGRAPH", {"text": text, "start_ms": passage[0].start_ms,
                              "end_ms": passage[-1].end_ms},
                "SOURCE", "ACCEPTED", ordinal=paragraph_index + 1,
            ))
            for segment in passage:
                evidence_id = evidence_by_segment[id(segment)]
                store.link_evidence(block_id, evidence_id, relation="SUPPORTS", review_state="ACCEPTED")
            store.add_block(chapter_id, BlockInput(
                "EXERCISE",
                {"prompt": "Explain the main idea of this passage in your own words. "
                           "Use the timestamped source evidence above to support your answer.",
                 "answer_guidance": "Learner response; not generated from an external model."},
                "EXPLANATION", "NEEDS_REVIEW", ordinal=paragraph_index + 2,
            ))
    # Surface repeated proper-name/technical phrases as reviewable glossary candidates;
    # never invent definitions that the source did not state.
    term_counts: dict[str, int] = {}
    for segment in transcript.segments:
        for term in re.findall(r"\b[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*){0,2}\b", segment.text):
            normalized = term.strip()
            if len(normalized) > 2 and normalized.lower() not in {"the", "this", "that", "when", "what", "how"}:
                term_counts[normalized] = term_counts.get(normalized, 0) + 1
    candidates = [term for term, count in sorted(term_counts.items(), key=lambda item: (-item[1], item[0].casefold())) if count >= 2][:40]
    if candidates and groups:
        glossary_chapter = store.add_chapter(
            version_id, "Glossary · review candidates", ordinal=len(groups),
            summary="Repeated capitalized terms surfaced from the transcript; definitions require human review.",
        )
        store.add_block(glossary_chapter, BlockInput(
            "HEADING", {"text": "Glossary candidates"}, "EXPLANATION", "NEEDS_REVIEW", ordinal=0,
        ))
        for ordinal, term in enumerate(candidates, start=1):
            store.add_block(glossary_chapter, BlockInput(
                "DEFINITION", {"term": term, "definition": "Definition not explicitly established by this automated pass. Add and verify a source-grounded definition.", "candidate_frequency": term_counts[term]},
                "UNCERTAIN", "NEEDS_REVIEW", ordinal=ordinal,
            ))
    tree = store.get_version_tree(version_id)
    if tree is None:
        raise RuntimeError("Textbook draft could not be read after composition")
    tree["source"] = {
        "id": imported.source_id, "title": transcript.title,
        "source_uri": transcript.source_uri, "language": transcript.language,
        "duration_ms": transcript.duration_ms, "metadata": source_metadata or {},
    }
    tree["pipeline"] = {
        "status": "TRANSCRIPT_DRAFT_READY",
        "transcript_origin": transcript.metadata.get("transcript_origin", "caption"),
        "composition": "EXTRACTIVE_SOURCE_GROUNDED",
        "ai_generated_explanations": False,
        "review_required": True,
    }
    return to_reader_export(database_path, tree, imported.source_id)


def process_youtube_video(
    database_path: str | Path,
    url: str,
    *,
    user_approved_network: bool,
    language: str | None = None,
    chapter_minutes: int = 10,
) -> dict:
    """Run metadata → public captions → transcript/evidence → textbook draft."""
    if user_approved_network is not True:
        raise PermissionError("Explicit approval is required before contacting YouTube")
    metadata = inspect_video(url)
    caption_text, caption_language = fetch_public_captions(metadata["url"], language=language)
    transcript = parse_caption_text(
        caption_text, title=metadata["title"], source_uri=metadata["url"],
        language=language or caption_language, duration_ms=metadata["duration_ms"],
    )
    return compose_transcript_textbook(
        database_path, transcript, source_metadata=metadata, chapter_minutes=chapter_minutes,
    )


def compose_registered_source(
    database_path: str | Path,
    source_id: str,
    *,
    chapter_minutes: int = 10,
) -> dict:
    """Compose a reader from an already-ingested caption or local-ASR source.

    This is the handoff from the existing local WAV/faster-whisper pipeline:
    source and transcript records remain the same; no duplicate source is created.
    """
    if not 1 <= chapter_minutes <= 30:
        raise ValueError("chapter_minutes must be between 1 and 30")
    with connect(database_path) as conn:
        source = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        rows = conn.execute(
            """SELECT t.text,t.start_ms,t.end_ms,t.language,t.speaker_id,e.id AS evidence_id
               FROM transcript_segments t
               JOIN evidence_items e ON e.segment_id=t.id AND e.source_id=t.source_id
               WHERE t.source_id=? ORDER BY t.ordinal,e.created_at,e.id""",
            (source_id,),
        ).fetchall()
    if source is None:
        raise ValueError("Source does not exist")
    if not rows:
        raise ValueError("Source has no transcript; import captions or complete local ASR first")
    transcript = TranscriptImport(
        title=source["title"],
        source_uri=source["source_uri"],
        language=source["language"],
        duration_ms=source["duration_ms"],
        segments=tuple(TranscriptSegmentInput(
            row["text"], row["start_ms"], row["end_ms"], row["language"], row["speaker_id"]
        ) for row in rows),
        metadata=json.loads(source["metadata_json"] or "{}"),
    )
    transcript.validate()
    evidence_ids = [row["evidence_id"] for row in rows]
    store = TextbookStore(database_path)
    textbook_id = store.create_textbook(source_id, transcript.title)
    version_id = store.create_version(textbook_id, "Transcript reader draft", composition_mode="SOURCE_ORDER")
    groups = _chapter_groups(transcript.segments, chapter_minutes * 60_000)
    evidence_by_segment = {
        id(segment): evidence_id
        for segment, evidence_id in zip(transcript.segments, evidence_ids, strict=True)
    }
    for chapter_index, group in enumerate(groups):
        first, last = group[0], group[-1]
        start_label = f"{first.start_ms // 60000:02d}:{(first.start_ms // 1000) % 60:02d}"
        end_label = f"{last.end_ms // 60000:02d}:{(last.end_ms // 1000) % 60:02d}"
        chapter_id = store.add_chapter(
            version_id, f"Chapter {chapter_index + 1} · {start_label}–{end_label}",
            ordinal=chapter_index, summary=f"Source transcript coverage: {start_label} to {end_label}.",
            source_start_ms=first.start_ms, source_end_ms=last.end_ms,
        )
        store.add_block(chapter_id, BlockInput(
            "HEADING", {"text": f"Transcript · {start_label}–{end_label}"},
            "SOURCE", "ACCEPTED", ordinal=0,
        ))
        for paragraph_index in range(0, len(group), 8):
            passage = group[paragraph_index:paragraph_index + 8]
            block_id = store.add_block(chapter_id, BlockInput(
                "PARAGRAPH",
                {"text": " ".join(segment.text.strip() for segment in passage),
                 "start_ms": passage[0].start_ms, "end_ms": passage[-1].end_ms},
                "SOURCE", "ACCEPTED", ordinal=paragraph_index + 1,
            ))
            for segment in passage:
                store.link_evidence(
                    block_id, evidence_by_segment[id(segment)],
                    relation="SUPPORTS", review_state="ACCEPTED",
                )
            store.add_block(chapter_id, BlockInput(
                "EXERCISE",
                {"prompt": "Explain the main idea of this passage in your own words. "
                           "Use the timestamped source evidence above to support your answer.",
                 "answer_guidance": "Learner response; not generated from an external model."},
                "EXPLANATION", "NEEDS_REVIEW", ordinal=paragraph_index + 2,
            ))
    term_counts: dict[str, int] = {}
    for segment in transcript.segments:
        for term in re.findall(r"\b[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*){0,2}\b", segment.text):
            if len(term) > 2 and term.lower() not in {"the", "this", "that", "when", "what", "how"}:
                term_counts[term] = term_counts.get(term, 0) + 1
    candidates = [term for term, count in sorted(
        term_counts.items(), key=lambda item: (-item[1], item[0].casefold())
    ) if count >= 2][:40]
    if candidates:
        glossary_chapter = store.add_chapter(
            version_id, "Glossary · review candidates", ordinal=len(groups),
            summary="Repeated capitalized terms surfaced from the transcript; definitions require human review.",
        )
        store.add_block(glossary_chapter, BlockInput(
            "HEADING", {"text": "Glossary candidates"}, "EXPLANATION", "NEEDS_REVIEW", ordinal=0,
        ))
        for ordinal, term in enumerate(candidates, start=1):
            store.add_block(glossary_chapter, BlockInput(
                "DEFINITION",
                {"term": term, "definition": "Definition not explicitly established by this automated pass. Add and verify a source-grounded definition.", "candidate_frequency": term_counts[term]},
                "UNCERTAIN", "NEEDS_REVIEW", ordinal=ordinal,
            ))
    tree = store.get_version_tree(version_id)
    if tree is None:
        raise RuntimeError("Textbook draft could not be read after composition")
    tree["source"] = {
        "id": source_id, "title": transcript.title, "source_uri": transcript.source_uri,
        "language": transcript.language, "duration_ms": transcript.duration_ms,
        "metadata": transcript.metadata,
    }
    tree["pipeline"] = {
        "status": "TRANSCRIPT_DRAFT_READY", "transcript_origin": transcript.metadata.get("transcript_origin", "unknown"),
        "composition": "EXTRACTIVE_SOURCE_GROUNDED", "ai_generated_explanations": False,
        "review_required": True,
    }
    return to_reader_export(database_path, tree, source_id)


def compose_source_main() -> None:
    parser = argparse.ArgumentParser(prog="omniintel-compose-source")
    parser.add_argument("database", type=Path)
    parser.add_argument("source_id")
    parser.add_argument("--chapter-minutes", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tree = compose_registered_source(args.database, args.source_id, chapter_minutes=args.chapter_minutes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": tree["pipeline"]["status"], "title": tree["version"]["title"],
                      "source_id": tree["source"]["id"],
                      "chapters": len(tree["chapters"]), "output": str(args.output)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="omniintel-youtube")
    parser.add_argument("database", type=Path)
    parser.add_argument("url")
    parser.add_argument("--approve-network", action="store_true",
                        help="Confirm that you are authorized to process this video's public captions")
    parser.add_argument("--language", default=None, help="Caption language code, e.g. en or hi")
    parser.add_argument("--chapter-minutes", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True, help="Reader JSON file to import into OmniIntel Android")
    args = parser.parse_args()
    tree = process_youtube_video(
        args.database, args.url, user_approved_network=args.approve_network,
        language=args.language, chapter_minutes=args.chapter_minutes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": tree["pipeline"]["status"], "title": tree["version"]["title"],
                      "chapters": len(tree["chapters"]), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
