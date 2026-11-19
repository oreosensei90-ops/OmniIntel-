"""Safe registration of user-selected local files as OmniIntel sources."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .assets import AssetRecord, AssetStore, detect_media_type
from .store import OmniIntelStore
from .models import utc_now


@dataclass(frozen=True, slots=True)
class LocalFileImportResult:
    source_id: str
    asset: AssetRecord
    modality: str
    title: str


def _classify(media_type: str) -> tuple[str, str]:
    if media_type == "application/pdf" or media_type == "text/plain":
        return "DOCUMENT", "DOCUMENT"
    if media_type.startswith("video/"):
        return "VIDEO", "VIDEO"
    if media_type.startswith("audio/"):
        return "AUDIO", "AUDIO"
    if media_type.startswith("image/"):
        return "IMAGE", "ATTACHMENT"
    raise ValueError(f"Local import does not support detected media type: {media_type}")


def import_local_file(
    database_path: str | Path,
    storage_dir: str | Path,
    file_path: str | Path,
    *,
    title: str | None = None,
    max_bytes: int = 250 * 1024 * 1024,
    expected_sha256: str | None = None,
) -> LocalFileImportResult:
    """Register one explicitly selected local file; never fetch URLs or unpack archives.

    This records the original bytes and provenance metadata. It does not extract text,
    transcribe audio, decode video, OCR images, or assert that the user has reuse rights.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size <= 0:
        raise ValueError("Local source file is empty")
    if path.stat().st_size > max_bytes:
        raise ValueError("Local source file exceeds configured maximum size")
    with path.open("rb") as handle:
        media_type = detect_media_type(handle.read(4096))
    modality, role = _classify(media_type)
    source_title = (title or path.stem).strip()
    if not source_title:
        raise ValueError("Source title must not be empty")

    store = OmniIntelStore(database_path)
    source_id = store.create_source(
        title=source_title,
        metadata={
            "ingestion_method": "local_file",
            "modality": modality,
            "media_type": media_type,
            "original_filename": path.name[:255],
            "rights_status": "UNVERIFIED",
            "imported_at": utc_now(),
        },
    )
    try:
        asset = AssetStore(
            database_path, storage_dir, max_bytes=max_bytes
        ).add_file(
            source_id,path,role=role,display_name=path.name,
            expected_sha256=expected_sha256,
        )
    except Exception:
        store.delete_empty_source(source_id)
        raise
    return LocalFileImportResult(source_id, asset, modality, source_title)
