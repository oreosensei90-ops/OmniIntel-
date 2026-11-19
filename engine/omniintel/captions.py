"""Deterministic SRT/WebVTT caption parsing into transcript domain records."""
from __future__ import annotations

import html
import re
from pathlib import Path

from .models import TranscriptImport, TranscriptSegmentInput

_TIMESTAMP = re.compile(
    r"^(?:(?P<hours>\\d{1,2}):)?(?P<minutes>\\d{2}):"
    r"(?P<seconds>\\d{2})[,.](?P<millis>\\d{1,3})$"
)
_TAGS = re.compile(r"<[^>]*>")
_SPEAKER = re.compile(r"^<v(?:\\s+([^>]+))?>(.*)$", re.IGNORECASE | re.DOTALL)


def _timestamp_ms(value: str) -> int:
    match = _TIMESTAMP.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"Invalid caption timestamp: {value!r}")
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    millis = int(match.group("millis").ljust(3, "0"))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Caption timestamp component out of range: {value!r}")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_caption_text(
    text: str,
    *,
    title: str,
    source_uri: str | None = None,
    language: str | None = None,
    duration_ms: int | None = None,
) -> TranscriptImport:
    """Parse local SRT or WebVTT text; does not fetch URLs or execute markup."""
    if not isinstance(text, str):
        raise TypeError("Caption input must be text")
    normalized = text.lstrip("\\ufeff").replace("\\r\\n", "\\n").replace("\\r", "\\n")
    lines = normalized.split("\\n")
    is_vtt = bool(lines and lines[0].strip().startswith("WEBVTT"))
    if not is_vtt and not any("-->" in line for line in lines):
        raise ValueError("Input is neither recognizable WebVTT nor SubRip captions")

    segments: list[TranscriptSegmentInput] = []
    index = 1 if is_vtt else 0
    while index < len(lines):
        line = lines[index].strip()
        if not line or line.startswith(("NOTE", "STYLE", "REGION")):
            index += 1
            while index < len(lines) and lines[index].strip():
                index += 1
            continue
        if "-->" not in line:
            # Cue identifiers are permitted immediately before a timing line.
            if index + 1 < len(lines) and "-->" in lines[index + 1]:
                index += 1
                line = lines[index].strip()
            else:
                index += 1
                continue

        timing = line.split("-->", 1)
        start_token = timing[0].strip()
        end_token = timing[1].strip().split()[0]
        start_ms = _timestamp_ms(start_token)
        end_ms = _timestamp_ms(end_token)
        if end_ms <= start_ms:
            raise ValueError("Caption cue end must be later than its start")
        index += 1
        cue_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            cue_lines.append(lines[index].strip())
            index += 1
        cue_text = " ".join(cue_lines)
        speaker_id = None
        speaker_match = _SPEAKER.match(cue_text)
        if speaker_match:
            speaker_id = speaker_match.group(1)
            cue_text = speaker_match.group(2)
        cue_text = html.unescape(_TAGS.sub("", cue_text))
        cue_text = re.sub(r"\\s+", " ", cue_text).strip()
        if cue_text:
            segments.append(TranscriptSegmentInput(
                cue_text, start_ms, end_ms, language=language, speaker_id=speaker_id
            ))

    if not segments:
        raise ValueError("Caption file contains no usable text cues")
    segments.sort(key=lambda item: (item.start_ms, item.end_ms))
    inferred_duration = max(item.end_ms for item in segments)
    result = TranscriptImport(
        title=title,
        source_uri=source_uri,
        language=language,
        duration_ms=duration_ms or inferred_duration,
        segments=tuple(segments),
        metadata={"transcript_origin": "caption", "caption_format": "webvtt" if is_vtt else "srt"},
    )
    result.validate()
    return result


def import_caption_file(
    file_path: str | Path,
    *,
    title: str | None = None,
    source_uri: str | None = None,
    language: str | None = None,
    duration_ms: int | None = None,
) -> TranscriptImport:
    path = Path(file_path)
    text = path.read_text(encoding="utf-8-sig")
    return parse_caption_text(
        text,
        title=title or path.stem,
        source_uri=source_uri,
        language=language,
        duration_ms=duration_ms,
    )
