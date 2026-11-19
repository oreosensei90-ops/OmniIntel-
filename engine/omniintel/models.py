"""Typed domain inputs for the first transcript-ingestion slice."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class TranscriptSegmentInput:
    text: str
    start_ms: int
    end_ms: int
    language: str | None = None
    speaker_id: str | None = None

    def validate(self, duration_ms: int | None = None) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Transcript segment text must not be empty")
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("Transcript timestamps must satisfy 0 <= start_ms < end_ms")
        if duration_ms is not None and self.end_ms > duration_ms:
            raise ValueError("Transcript segment exceeds source duration")


@dataclass(frozen=True, slots=True)
class TranscriptImport:
    title: str
    segments: tuple[TranscriptSegmentInput, ...]
    source_uri: str | None = None
    language: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("Source title must not be empty")
        if not self.segments:
            raise ValueError("At least one transcript segment is required")
        if self.duration_ms is not None and self.duration_ms <= 0:
            raise ValueError("Source duration must be positive")
        previous_start = -1
        for segment in self.segments:
            segment.validate(self.duration_ms)
            if segment.start_ms < previous_start:
                raise ValueError("Transcript segments must be ordered by start timestamp")
            previous_start = segment.start_ms


@dataclass(frozen=True, slots=True)
class ImportResult:
    source_id: str
    segment_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_ref_ids: tuple[str, ...] = ()
