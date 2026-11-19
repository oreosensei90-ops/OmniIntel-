"""Local content-addressed asset storage for source media and documents."""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from .database import connect, migrate
from .ids import uuid7
from .models import utc_now

AssetRole = Literal[
    "THUMBNAIL", "FRAME", "SLIDE", "AUDIO", "VIDEO",
    "DOCUMENT", "DIAGRAM", "ATTACHMENT",
]
_ALLOWED_ROLES = {
    "THUMBNAIL", "FRAME", "SLIDE", "AUDIO", "VIDEO",
    "DOCUMENT", "DIAGRAM", "ATTACHMENT",
}


@dataclass(frozen=True, slots=True)
class AssetRecord:
    id: str
    source_id: str
    sha256: str
    media_type: str
    byte_size: int
    storage_key: str
    role: str
    display_name: str
    created_at: str


def detect_media_type(prefix: bytes) -> str:
    """Identify supported common formats from content signatures, never filename suffixes."""
    if prefix.startswith(b"%PDF-"):
        return "application/pdf"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return "image/webp"
    if len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        return "video/mp4"
    if prefix.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    if prefix.startswith(b"ID3") or (
        len(prefix) >= 2 and prefix[0] == 0xFF and prefix[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE":
        return "audio/wav"
    if prefix.startswith(b"OggS"):
        return "audio/ogg"
    if prefix.startswith(b"fLaC"):
        return "audio/flac"
    if prefix.startswith(b"PK\x03\x04"):
        return "application/zip"
    if prefix and b"\x00" not in prefix:
        try:
            prefix.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return "text/plain"
    raise ValueError("Unsupported or unrecognized asset content type")


class AssetStore:
    """Store immutable blobs by SHA-256 and associate them with source records.

    Storage keys are generated internally. User-provided filenames are metadata only and
    can never influence filesystem paths. No URL fetching or archive extraction is performed.
    """

    def __init__(
        self,
        database_path: str | Path,
        storage_dir: str | Path,
        *,
        max_bytes: int = 250 * 1024 * 1024,
    ):
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.database_path = Path(database_path)
        self.storage_dir = Path(storage_dir).resolve()
        self.max_bytes = max_bytes
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        (self.storage_dir / ".staging").mkdir(exist_ok=True)
        with connect(self.database_path) as conn:
            migrate(conn)

    @staticmethod
    def _display_name(value: str) -> str:
        normalized = value.replace("\\", "/").split("/")[-1]
        normalized = "".join(
            char for char in normalized
            if char >= " " and char != "\x7f"
        ).strip()
        if normalized in {"", ".", ".."}:
            normalized = "asset"
        return normalized[:255]

    def add_bytes(
        self,
        source_id: str,
        data: bytes,
        *,
        role: AssetRole = "ATTACHMENT",
        display_name: str = "asset",
    ) -> AssetRecord:
        if not isinstance(data, bytes):
            raise TypeError("Asset data must be bytes")
        return self._ingest(
            source_id, io.BytesIO(data), role=role, display_name=display_name
        )

    def add_file(
        self,
        source_id: str,
        file_path: str | Path,
        *,
        role: AssetRole = "ATTACHMENT",
        display_name: str | None = None,
        expected_sha256: str | None = None,
    ) -> AssetRecord:
        path = Path(file_path)
        with path.open("rb") as handle:
            return self._ingest(
                source_id, handle, role=role,
                display_name=display_name or path.name,
                expected_sha256=expected_sha256,
            )

    def _ingest(
        self,
        source_id: str,
        stream: BinaryIO,
        *,
        role: str,
        display_name: str,
        expected_sha256: str | None = None,
    ) -> AssetRecord:
        if role not in _ALLOWED_ROLES:
            raise ValueError("Unsupported asset role")
        safe_name = self._display_name(display_name)
        with connect(self.database_path) as conn:
            if conn.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone() is None:
                raise ValueError("Source does not exist")

        digest = hashlib.sha256()
        total = 0
        prefix = bytearray()
        staging_dir = self.storage_dir / ".staging"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=staging_dir, prefix="asset-", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise ValueError("Asset exceeds configured maximum size")
                    if len(prefix) < 4096:
                        prefix.extend(chunk[:4096 - len(prefix)])
                    digest.update(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())

            if total == 0:
                raise ValueError("Empty assets are not supported")
            media_type = detect_media_type(bytes(prefix))
            sha256 = digest.hexdigest()
            if expected_sha256 is not None and sha256 != expected_sha256:
                raise ValueError("Asset content changed after execution-plan approval")
            storage_key = f"{sha256[:2]}/{sha256[2:4]}/{sha256}"
            target = self.storage_dir / storage_key
            target.parent.mkdir(parents=True, exist_ok=True)
            resolved_parent = target.parent.resolve()
            if not resolved_parent.is_relative_to(self.storage_dir):
                raise RuntimeError("Asset storage path escaped the configured directory")

            if target.exists():
                existing_hash = hashlib.sha256()
                with target.open("rb") as existing:
                    for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                        existing_hash.update(chunk)
                if existing_hash.hexdigest() != sha256:
                    raise RuntimeError("Existing content-addressed asset failed integrity check")
                temporary_path.unlink(missing_ok=True)
                temporary_path = None
            else:
                os.replace(temporary_path, target)
                temporary_path = None

            now = utc_now()
            asset_id = uuid7()
            with connect(self.database_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                blob = conn.execute(
                    "SELECT media_type,byte_size,storage_key FROM asset_blobs WHERE sha256=?",
                    (sha256,),
                ).fetchone()
                if blob is None:
                    conn.execute(
                        """INSERT INTO asset_blobs
                           (sha256,media_type,byte_size,storage_key,created_at)
                           VALUES(?,?,?,?,?)""",
                        (sha256, media_type, total, storage_key, now),
                    )
                elif (
                    blob["media_type"] != media_type
                    or blob["byte_size"] != total
                    or blob["storage_key"] != storage_key
                ):
                    raise RuntimeError("Asset blob metadata conflicts with its content hash")

                existing = conn.execute(
                    """SELECT sa.id,sa.source_id,sa.blob_sha256,sa.role,sa.display_name,
                              sa.created_at,ab.media_type,ab.byte_size,ab.storage_key
                       FROM source_assets sa JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
                       WHERE sa.source_id=? AND sa.blob_sha256=? AND sa.role=?""",
                    (source_id, sha256, role),
                ).fetchone()
                if existing is not None:
                    return AssetRecord(
                        id=existing["id"], source_id=existing["source_id"],
                        sha256=existing["blob_sha256"], media_type=existing["media_type"],
                        byte_size=existing["byte_size"], storage_key=existing["storage_key"],
                        role=existing["role"], display_name=existing["display_name"],
                        created_at=existing["created_at"],
                    )
                conn.execute(
                    """INSERT INTO source_assets
                       (id,source_id,blob_sha256,role,display_name,created_at)
                       VALUES(?,?,?,?,?,?)""",
                    (asset_id, source_id, sha256, role, safe_name, now),
                )
            return AssetRecord(
                id=asset_id, source_id=source_id, sha256=sha256,
                media_type=media_type, byte_size=total, storage_key=storage_key,
                role=role, display_name=safe_name, created_at=now,
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def list_source_assets(self, source_id: str) -> list[AssetRecord]:
        with connect(self.database_path) as conn:
            rows = conn.execute(
                """SELECT sa.id,sa.source_id,sa.blob_sha256,ab.media_type,ab.byte_size,
                          ab.storage_key,sa.role,sa.display_name,sa.created_at
                   FROM source_assets sa JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
                   WHERE sa.source_id=? ORDER BY sa.created_at,sa.id""",
                (source_id,),
            ).fetchall()
        return [
            AssetRecord(
                id=row["id"], source_id=row["source_id"], sha256=row["blob_sha256"],
                media_type=row["media_type"], byte_size=row["byte_size"],
                storage_key=row["storage_key"], role=row["role"],
                display_name=row["display_name"], created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_asset(self, asset_id: str) -> AssetRecord:
        """Resolve an asset record without trusting caller-supplied storage paths."""
        with connect(self.database_path) as conn:
            row = conn.execute(
                """SELECT sa.id,sa.source_id,sa.blob_sha256,ab.media_type,ab.byte_size,
                          ab.storage_key,sa.role,sa.display_name,sa.created_at
                   FROM source_assets sa JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
                   WHERE sa.id=?""",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Asset does not exist")
        return AssetRecord(
            id=row["id"],source_id=row["source_id"],sha256=row["blob_sha256"],
            media_type=row["media_type"],byte_size=row["byte_size"],
            storage_key=row["storage_key"],role=row["role"],
            display_name=row["display_name"],created_at=row["created_at"],
        )

    def resolve_path(self, asset_id: str, *, verify_hash: bool = True) -> Path:
        with connect(self.database_path) as conn:
            row = conn.execute(
                """SELECT ab.sha256,ab.storage_key,ab.byte_size
                   FROM source_assets sa JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256
                   WHERE sa.id=?""",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Asset does not exist")
        key = Path(row["storage_key"])
        if key.is_absolute() or ".." in key.parts:
            raise RuntimeError("Stored asset key is unsafe")
        path = (self.storage_dir / key).resolve()
        if not path.is_relative_to(self.storage_dir) or not path.is_file():
            raise FileNotFoundError("Asset blob is missing or outside the asset store")
        if path.stat().st_size != row["byte_size"]:
            raise RuntimeError("Asset blob size does not match its metadata")
        if verify_hash:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != row["sha256"]:
                raise RuntimeError("Asset blob failed SHA-256 integrity verification")
        return path
