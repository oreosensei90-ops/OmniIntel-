"""Local-only ffprobe adapter for registered video/audio assets.

No URLs, shell interpolation, subtitle downloads, decoding or transcoding are performed here.
The adapter records bounded container/stream metadata and preserves the original asset.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .assets import AssetStore
from .database import connect
from .ids import uuid7
from .models import utc_now

_TOOL_NAME = "ffprobe"
_PROBE_SCHEMA = "omniintel-media-probe-v1"
_SHOW_ENTRIES = (
    "format=format_name,duration,size,bit_rate:"
    "stream=index,codec_type,codec_name,profile,width,height,sample_rate,"
    "channels,channel_layout,avg_frame_rate,r_frame_rate,start_time,duration"
)


@dataclass(frozen=True, slots=True)
class MediaStreamInfo:
    stream_index: int
    codec_type: str
    codec_name: str | None
    duration_ms: int | None
    start_ms: int | None
    width: int | None
    height: int | None
    sample_rate: int | None
    channels: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MediaProbeResult:
    id: str
    source_asset_id: str
    asset_sha256: str
    tool_name: str
    tool_version: str
    format_name: str
    duration_ms: int | None
    byte_size: int
    metadata: dict[str, Any]
    streams: tuple[MediaStreamInfo, ...]
    reused: bool = False


def _read_limited(handle: Any, limit: int, label: str) -> bytes:
    handle.seek(0)
    data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"ffprobe {label} exceeded the configured output limit")
    return data


def _run_bounded(
    executable: str,
    arguments: list[str],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> tuple[bytes, bytes]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C",
        "LC_ALL": "C",
    }
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(
        mode="w+b"
    ) as stderr_file:
        try:
            completed = subprocess.run(
                [executable, *arguments],
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout_seconds,
                check=False,
                shell=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("ffprobe exceeded its time limit") from error
        stdout = _read_limited(stdout_file, max_output_bytes, "stdout")
        stderr = _read_limited(stderr_file, 8192, "stderr")
    if completed.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").replace("\x00", "")[:1000]
        raise RuntimeError(f"ffprobe failed with exit code {completed.returncode}: {detail}")
    return stdout, stderr


def _tool_version(executable: str, timeout_seconds: float) -> str:
    output, _ = _run_bounded(
        executable,
        ["-version"],
        timeout_seconds=min(timeout_seconds, 10.0),
        max_output_bytes=16_384,
    )
    first_line = output.decode("utf-8", errors="replace").splitlines()
    version = first_line[0].strip()[:256] if first_line else ""
    if not version.startswith("ffprobe version "):
        raise RuntimeError("The selected executable did not identify itself as ffprobe")
    return version


def _duration_ms(value: Any) -> int | None:
    if value is None or (isinstance(value, str) and value in {"", "N/A"}):
        return None
    try:
        seconds = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not seconds.is_finite() or seconds <= 0:
        return None
    milliseconds = int((seconds * 1000).to_integral_value())
    if milliseconds <= 0 or milliseconds > 2**63 - 1:
        raise ValueError("Media duration is outside the supported range")
    return milliseconds



def _timestamp_ms(value: Any) -> int | None:
    if value is None or (isinstance(value, str) and value in {"", "N/A"}):
        return None
    try:
        seconds = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not seconds.is_finite():
        return None
    milliseconds = int((seconds * 1000).to_integral_value())
    if abs(milliseconds) > 2**63 - 1:
        raise ValueError("Media stream start time is outside the supported range")
    return milliseconds


def _timestamp_ms(value: Any) -> int | None:
    if value is None or (isinstance(value,str) and value in {"","N/A"}):
        return None
    try:
        seconds=Decimal(str(value))
    except (InvalidOperation,ValueError):
        return None
    if not seconds.is_finite():
        return None
    milliseconds=int((seconds*1000).to_integral_value())
    if abs(milliseconds)>2**63-1:
        raise ValueError("Media stream start time is outside the supported range")
    return milliseconds


def _optional_int(value: Any, *, maximum: int) -> int | None:
    if value is None or (isinstance(value,str) and value in {"", "N/A"}):
        return None
    if isinstance(value, bool):
        raise TypeError("ffprobe returned a boolean where an integer was expected")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("ffprobe returned an invalid integer field") from error
    if number <= 0 or number > maximum:
        raise ValueError("ffprobe integer field is outside the supported range")
    return number



def _optional_nonnegative_int(value: Any, *, maximum: int) -> int | None:
    if value is None or (isinstance(value, str) and value in {"", "N/A"}):
        return None
    if isinstance(value, bool):
        raise TypeError("ffprobe returned a boolean where an integer was expected")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("ffprobe returned an invalid integer field") from error
    if number < 0 or number > maximum:
        raise ValueError("ffprobe integer field is outside the supported range")
    return number or None


def _bounded_text(value: Any, *, maximum: int = 128) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("ffprobe returned a non-text metadata field")
    cleaned = "".join(character for character in value if character >= " " and character != "\x7f")
    cleaned = cleaned.strip()
    return cleaned[:maximum] or None


def _parse_probe(
    payload: bytes,
    *,
    max_streams: int,
) -> tuple[str, int | None, dict[str, Any], tuple[MediaStreamInfo, ...]]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("ffprobe returned invalid JSON") from error
    if not isinstance(document, dict):
        raise TypeError("ffprobe output must be a JSON object")
    format_info = document.get("format")
    if not isinstance(format_info, dict):
        raise TypeError("ffprobe did not return container format metadata")
    format_name = _bounded_text(format_info.get("format_name"), maximum=255)
    if not format_name:
        raise ValueError("ffprobe did not identify the container format")
    raw_streams = document.get("streams")
    if not isinstance(raw_streams, list) or not raw_streams:
        raise ValueError("Media contains no inspectable streams")
    if len(raw_streams) > max_streams:
        raise ValueError("Media exceeds the configured stream-count limit")

    streams: list[MediaStreamInfo] = []
    seen_indices: set[int] = set()
    for raw in raw_streams:
        if not isinstance(raw, dict):
            raise TypeError("ffprobe returned a malformed stream record")
        index = raw.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index in seen_indices:
            raise TypeError("ffprobe returned an invalid or duplicate stream index")
        seen_indices.add(index)
        codec_type = _bounded_text(raw.get("codec_type"), maximum=32)
        if not codec_type:
            raise ValueError("ffprobe stream is missing codec_type")
        metadata = {
            key: value
            for key in ("profile", "channel_layout", "avg_frame_rate", "r_frame_rate")
            if (value := _bounded_text(raw.get(key), maximum=128)) is not None
        }
        streams.append(
            MediaStreamInfo(
                stream_index=index,
                codec_type=codec_type,
                codec_name=_bounded_text(raw.get("codec_name"), maximum=128),
                duration_ms=_duration_ms(raw.get("duration")),
                start_ms=_timestamp_ms(raw.get("start_time")),
                width=_optional_int(raw.get("width"), maximum=32_768),
                height=_optional_int(raw.get("height"), maximum=32_768),
                sample_rate=_optional_int(raw.get("sample_rate"), maximum=768_000),
                channels=_optional_int(raw.get("channels"), maximum=64),
                metadata=metadata,
            )
        )
    if not any(stream.codec_type in {"video", "audio"} for stream in streams):
        raise ValueError("Media contains no audio or video stream")
    duration_ms = _duration_ms(format_info.get("duration"))
    if duration_ms is None:
        durations = [stream.duration_ms for stream in streams if stream.duration_ms]
        duration_ms = max(durations) if durations else None
    metadata = {
        "container_bit_rate": _optional_nonnegative_int(format_info.get("bit_rate"), maximum=2**63 - 1),
        "container_reported_size": _optional_nonnegative_int(format_info.get("size"), maximum=2**63 - 1),
        "probe_schema": _PROBE_SCHEMA,
    }
    return format_name, duration_ms, metadata, tuple(sorted(streams, key=lambda item: item.stream_index))


def _fingerprint(asset_sha256: str, tool_version: str, max_streams: int, max_output_bytes: int) -> str:
    payload = json.dumps(
        {
            "asset_sha256": asset_sha256,
            "tool_name": _TOOL_NAME,
            "tool_version": tool_version,
            "probe_schema": _PROBE_SCHEMA,
            "show_entries": _SHOW_ENTRIES,
            "max_streams": max_streams,
            "max_output_bytes": max_output_bytes,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_result(database_path: str | Path, probe_id: str, *, reused: bool) -> MediaProbeResult:
    with connect(database_path) as conn:
        row = conn.execute(
            "SELECT * FROM media_probes WHERE id=?",
            (probe_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Media probe record does not exist")
        stream_rows = conn.execute(
            "SELECT * FROM media_streams WHERE probe_id=? ORDER BY stream_index",
            (probe_id,),
        ).fetchall()
    streams = tuple(
        MediaStreamInfo(
            stream_index=item["stream_index"],
            codec_type=item["codec_type"],
            codec_name=item["codec_name"],
            duration_ms=item["duration_ms"],
            start_ms=item["start_ms"],
            width=item["width"],
            height=item["height"],
            sample_rate=item["sample_rate"],
            channels=item["channels"],
            metadata=json.loads(item["metadata_json"]),
        )
        for item in stream_rows
    )
    return MediaProbeResult(
        id=row["id"],
        source_asset_id=row["source_asset_id"],
        asset_sha256=row["asset_sha256"],
        tool_name=row["tool_name"],
        tool_version=row["tool_version"],
        format_name=row["format_name"],
        duration_ms=row["duration_ms"],
        byte_size=row["byte_size"],
        metadata=json.loads(row["metadata_json"]),
        streams=streams,
        reused=reused,
    )


def probe_local_media(
    database_path: str | Path,
    asset_dir: str | Path,
    asset_id: str,
    *,
    timeout_seconds: float = 30.0,
    max_streams: int = 32,
    max_output_bytes: int = 1_000_000,
) -> MediaProbeResult:
    """Probe one registered local media asset without fetching or decoding its contents."""
    if not 0 < timeout_seconds <= 300:
        raise ValueError("timeout_seconds must be greater than zero and at most 300")
    if not 1 <= max_streams <= 64:
        raise ValueError("max_streams must be between 1 and 64")
    if not 1024 <= max_output_bytes <= 4_000_000:
        raise ValueError("max_output_bytes must be between 1024 and 4000000")

    store = AssetStore(database_path, asset_dir)
    asset = store.get_asset(asset_id)
    if not (asset.media_type.startswith("video/") or asset.media_type.startswith("audio/")):
        raise ValueError("Only registered audio and video assets can be probed")
    media_path = store.resolve_path(asset_id, verify_hash=True)
    executable = shutil.which("ffprobe")
    if not executable:
        raise RuntimeError("ffprobe was not found; install FFmpeg tools to inspect local media")
    version = _tool_version(executable, timeout_seconds)
    fingerprint = _fingerprint(asset.sha256, version, max_streams, max_output_bytes)
    with connect(database_path) as conn:
        existing = conn.execute(
            "SELECT id FROM media_probes WHERE source_asset_id=? AND probe_fingerprint=?",
            (asset_id, fingerprint),
        ).fetchone()
    if existing is not None:
        return _load_result(database_path, existing["id"], reused=True)

    arguments = [
        "-v", "error",
        "-protocol_whitelist", "file,pipe",
        "-max_alloc", "67108864",
        "-max_streams", str(max_streams),
        "-probesize", "10000000",
        "-analyzeduration", "10000000",
        "-show_entries", _SHOW_ENTRIES,
        "-of", "json",
        str(media_path),
    ]
    payload, _ = _run_bounded(
        executable,
        arguments,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )
    format_name, duration_ms, metadata, streams = _parse_probe(
        payload,
        max_streams=max_streams,
    )
    probe_id = uuid7()
    created_at = utc_now()
    reused = False
    with connect(database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT id FROM media_probes WHERE source_asset_id=? AND probe_fingerprint=?",
            (asset_id, fingerprint),
        ).fetchone()
        if existing is not None:
            probe_id = existing["id"]
            reused = True
        else:
            conn.execute(
                """INSERT INTO media_probes
                   (id,source_asset_id,asset_sha256,probe_fingerprint,tool_name,tool_version,
                    format_name,duration_ms,byte_size,metadata_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    probe_id, asset_id, asset.sha256, fingerprint, _TOOL_NAME, version,
                    format_name, duration_ms, asset.byte_size,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            for stream in streams:
                conn.execute(
                    """INSERT INTO media_streams
                       (probe_id,stream_index,codec_type,codec_name,duration_ms,start_ms,width,height,
                        sample_rate,channels,metadata_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        probe_id, stream.stream_index, stream.codec_type, stream.codec_name,
                        stream.duration_ms, stream.start_ms, stream.width, stream.height, stream.sample_rate,
                        stream.channels,
                        json.dumps(stream.metadata, ensure_ascii=False, sort_keys=True),
                    ),
                )
            if duration_ms is not None:
                conn.execute(
                    """UPDATE sources SET duration_ms=?
                       WHERE id=(SELECT source_id FROM source_assets WHERE id=?)
                         AND duration_ms IS NULL""",
                    (duration_ms, asset_id),
                )
    return _load_result(database_path, probe_id, reused=reused)


def media_probe_dict(result: MediaProbeResult) -> dict[str, Any]:
    return asdict(result)
