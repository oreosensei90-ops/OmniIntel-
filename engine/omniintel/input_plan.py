"""Read-only, plan-first classification of a user-selected local source bundle.

Planning performs bounded metadata/signature reads only. It never imports, copies,
decodes, downloads, transcribes, OCRs, or writes any file.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .assets import detect_media_type

_MAX_FILES = 200
_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_MAX_FILE_BYTES = 1024 * 1024 * 1024
_CAPTION_EXTENSIONS = {".srt": "SUBRIP", ".vtt": "WEBVTT"}
_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}


@dataclass(frozen=True, slots=True)
class PlannedInput:
    path: str
    display_name: str
    modality: str
    media_type: str
    byte_size: int
    action: str
    resource_class: str
    network: str = "none"
    requires_user_review: bool = False


@dataclass(frozen=True, slots=True)
class InputPlan:
    schema_version: int
    read_only: bool
    inputs: tuple[PlannedInput, ...]
    questions: tuple[str, ...]
    warnings: tuple[str, ...]
    total_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "read_only": self.read_only,
            "inputs": [asdict(item) for item in self.inputs],
            "questions": list(self.questions),
            "warnings": list(self.warnings),
            "total_bytes": self.total_bytes,
            "ready_for_execution": not self.questions and bool(self.inputs),
        }


def _classify(path: Path, prefix: bytes) -> tuple[str, str, str, str]:
    suffix = path.suffix.lower()
    if suffix in _CAPTION_EXTENSIONS:
        return "CAPTIONS", "text/vtt" if suffix == ".vtt" else "application/x-subrip", "IMPORT_CAPTIONS", "LOW"
    if suffix in _TEXT_EXTENSIONS and detect_media_type(prefix) == "text/plain":
        return "DOCUMENT", "text/plain", "IMPORT_TEXT", "LOW"
    media_type = detect_media_type(prefix)
    if media_type == "application/pdf":
        return "DOCUMENT", media_type, "EXTRACT_PDF", "MEDIUM"
    if media_type.startswith("video/"):
        return "VIDEO", media_type, "PROBE_EXTRACT_TRANSCRIBE_AND_SAMPLE", "HIGH"
    if media_type.startswith("audio/"):
        return "AUDIO", media_type, "PROBE_EXTRACT_AND_TRANSCRIBE", "HIGH"
    if media_type.startswith("image/"):
        return "IMAGE", media_type, "REGISTER_AND_OPTIONAL_OCR", "MEDIUM"
    raise ValueError(f"Unsupported source file: {path.name}")


def plan_local_inputs(
    paths: list[str | Path] | tuple[str | Path, ...],
    *,
    language: str | None = None,
    max_files: int = _MAX_FILES,
    max_file_bytes: int = _MAX_FILE_BYTES,
    max_total_bytes: int = _MAX_TOTAL_BYTES,
) -> InputPlan:
    """Classify explicit local paths and describe safe next stages without side effects."""
    if not paths:
        raise ValueError("Select at least one local input file")
    if not 1 <= max_files <= _MAX_FILES:
        raise ValueError("max_files must be between 1 and 200")
    if max_file_bytes <= 0 or max_total_bytes <= 0:
        raise ValueError("Input byte limits must be positive")
    if len(paths) > max_files:
        raise ValueError("Selected input count exceeds configured maximum")

    inputs: list[PlannedInput] = []
    warnings: list[str] = []
    total = 0
    speech_inputs = 0
    media_inputs = 0
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.is_file():
            raise FileNotFoundError(path)
        resolved = path.resolve(strict=True)
        if path.is_symlink():
            warnings.append(f"Symbolic link selected; resolved target will be read: {resolved.name}")
        size = resolved.stat().st_size
        if size <= 0:
            raise ValueError(f"Empty input file: {resolved.name}")
        if size > max_file_bytes:
            raise ValueError(f"Input exceeds per-file size limit: {resolved.name}")
        total += size
        if total > max_total_bytes:
            raise ValueError("Selected inputs exceed total size limit")
        with resolved.open("rb") as handle:
            prefix = handle.read(4096)
        modality, media_type, action, resource = _classify(resolved, prefix)
        if modality in {"AUDIO", "VIDEO"}:
            speech_inputs += 1
            media_inputs += 1
        inputs.append(PlannedInput(
            path=str(resolved),
            display_name=resolved.name[:255],
            modality=modality,
            media_type=media_type,
            byte_size=size,
            action=action,
            resource_class=resource,
            requires_user_review=modality in {"IMAGE", "CAPTIONS"},
        ))

    questions: list[str] = []
    if speech_inputs and not language:
        questions.append(
            "Confirm the spoken language(s), including code-switching, before transcription; do not guess."
        )
    if media_inputs > 1:
        questions.append(
            "Confirm whether the selected audio/video files share one recording timeline or need measured alignment."
        )
    if sum(item.modality == "CAPTIONS" for item in inputs) and speech_inputs:
        questions.append(
            "Confirm which media source each caption file belongs to; filenames alone do not establish alignment."
        )
        warnings.append(
            "Captions and media are separate source records; alignment must be validated, not assumed from filenames."
        )
    if any(item.modality == "IMAGE" for item in inputs):
        warnings.append(
            "Image OCR is optional and starts as an unreviewed interpretation; the original image remains authoritative."
        )
    if any(item.modality == "DOCUMENT" for item in inputs):
        warnings.append(
            "Document pages/elements retain page locators; do not convert them into video timestamps."
        )
    if not language and speech_inputs == 0:
        warnings.append("No speech-bearing media was detected; transcription is not planned.")

    return InputPlan(
        schema_version=1,
        read_only=True,
        inputs=tuple(inputs),
        questions=tuple(questions),
        warnings=tuple(warnings),
        total_bytes=total,
    )
