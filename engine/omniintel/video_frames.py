"""Bounded local video-frame sampling with original media timestamps."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .assets import AssetRecord, AssetStore
from .database import connect
from .ids import uuid7
from .media_probe import MediaProbeResult, MediaStreamInfo, probe_local_media
from .models import utc_now

_SCHEMA = "omniintel-video-frames-v1"
_SHOWINFO = re.compile(
    r"\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:([^\s]+)"
)


@dataclass(frozen=True, slots=True)
class VideoFrame:
    id: str
    extraction_id: str
    source_asset_id: str
    frame_asset_id: str
    frame_index: int
    timestamp_ms: int
    width: int
    height: int
    byte_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class FrameExtractionResult:
    id: str
    source_asset_id: str
    source_sha256: str
    tool_version: str
    video_stream_index: int
    sample_interval_ms: int
    frame_count: int
    total_bytes: int
    total_pixels: int
    frames: tuple[VideoFrame, ...]
    reused: bool = False


def _bounded_read(handle: Any, limit: int, label: str) -> bytes:
    handle.seek(0)
    value = handle.read(limit + 1)
    if len(value) > limit:
        raise ValueError(f"ffmpeg {label} exceeded the configured limit")
    return value


def _tool_version(executable: str, timeout_seconds: float) -> str:
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(
        mode="w+b"
    ) as stderr_file:
        try:
            completed = subprocess.run(
                [executable, "-version"],
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=min(timeout_seconds, 10.0),
                check=False,
                shell=False,
                env={"PATH": os.environ.get("PATH", ""), "LANG": "C", "LC_ALL": "C"},
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("ffmpeg version check exceeded its time limit") from error
        output = _bounded_read(stdout_file, 16_384, "version output")
    if completed.returncode != 0:
        raise RuntimeError("Unable to identify the local ffmpeg executable")
    lines = output.decode("utf-8", errors="replace").splitlines()
    version = lines[0].strip()[:256] if lines else ""
    if not version.startswith("ffmpeg version "):
        raise RuntimeError("The selected executable did not identify itself as ffmpeg")
    return version


def _run_ffmpeg(
    executable: str,
    arguments: list[str],
    *,
    timeout_seconds: float,
    max_log_bytes: int,
) -> bytes:
    with tempfile.TemporaryFile(mode="w+b") as stderr_file:
        try:
            completed = subprocess.run(
                [executable, *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                timeout=timeout_seconds,
                check=False,
                shell=False,
                env={"PATH": os.environ.get("PATH", ""), "LANG": "C", "LC_ALL": "C"},
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("Video frame extraction exceeded its time limit") from error
        log = _bounded_read(stderr_file, max_log_bytes, "diagnostic output")
    if completed.returncode != 0:
        detail = log.decode("utf-8", errors="replace").replace("\x00", "")[-1500:]
        raise RuntimeError(f"ffmpeg frame extraction failed with exit code {completed.returncode}: {detail}")
    return log


def _parse_showinfo(log: bytes, *, max_frames: int) -> tuple[int, ...]:
    text = log.decode("utf-8", errors="replace")
    timestamps: list[int] = []
    for match in _SHOWINFO.finditer(text):
        frame_number = int(match.group(1))
        if frame_number != len(timestamps):
            raise ValueError("ffmpeg showinfo frame sequence is not contiguous")
        try:
            seconds = Decimal(match.group(3))
        except InvalidOperation as error:
            raise ValueError("ffmpeg returned an invalid frame timestamp") from error
        if not seconds.is_finite():
            raise ValueError("ffmpeg returned a non-finite frame timestamp")
        timestamp_ms = int((seconds * 1000).to_integral_value())
        if timestamp_ms < 0:
            raise ValueError("Video frame timestamp is negative")
        if timestamps and timestamp_ms <= timestamps[-1]:
            raise ValueError("Video frame timestamps must be strictly increasing")
        timestamps.append(timestamp_ms)
        if len(timestamps) > max_frames:
            raise ValueError("ffmpeg emitted more frames than the configured limit")
    if not timestamps:
        raise ValueError("ffmpeg did not report any sampled frame timestamps")
    return tuple(timestamps)


def _jpeg_dimensions(path: Path, *, max_header_bytes: int = 1_048_576) -> tuple[int, int]:
    with path.open("rb") as handle:
        data = handle.read(max_header_bytes)
    if len(data) < 4 or data[:3] != b"\xff\xd8\xff":
        raise ValueError("Extracted frame is not a JPEG image")
    offset = 2
    start_of_frame = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            raise ValueError("JPEG frame header contains an invalid segment length")
        if marker in start_of_frame:
            if segment_length < 8:
                raise ValueError("JPEG frame dimensions are truncated")
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            if width <= 0 or height <= 0:
                raise ValueError("JPEG frame dimensions are invalid")
            return width, height
        offset += segment_length
    raise ValueError("JPEG frame dimensions were not found in the bounded header")


def _fingerprint(
    source_sha256: str,
    tool_version: str,
    video_stream_index: int,
    sample_interval_ms: int,
    max_frames: int,
    max_frame_bytes: int,
    max_total_bytes: int,
    max_frame_pixels: int,
    max_total_pixels: int,
    max_width: int,
    max_height: int,
) -> str:
    payload = json.dumps(
        {
            "schema": _SCHEMA,
            "source_sha256": source_sha256,
            "tool_version": tool_version,
            "video_stream_index": video_stream_index,
            "sample_interval_ms": sample_interval_ms,
            "max_frames": max_frames,
            "max_frame_bytes": max_frame_bytes,
            "max_total_bytes": max_total_bytes,
            "max_frame_pixels": max_frame_pixels,
            "max_total_pixels": max_total_pixels,
            "max_width": max_width,
            "max_height": max_height,
            "jpeg_quality": 4,
            "timestamp_source": "ffmpeg-showinfo-pts-time-copyts",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_result(
    database_path: str | Path,
    asset_dir: str | Path,
    extraction_id: str,
    *,
    reused: bool,
) -> FrameExtractionResult:
    with connect(database_path) as conn:
        extraction = conn.execute(
            "SELECT * FROM frame_extractions WHERE id=?",
            (extraction_id,),
        ).fetchone()
        if extraction is None:
            raise ValueError("Frame extraction record does not exist")
        rows = conn.execute(
            "SELECT * FROM video_frames WHERE extraction_id=? ORDER BY frame_index",
            (extraction_id,),
        ).fetchall()
    store = AssetStore(database_path, asset_dir, max_bytes=64 * 1024 * 1024)
    frames: list[VideoFrame] = []
    for row in rows:
        asset = store.get_asset(row["frame_asset_id"])
        if asset.sha256 != row["sha256"] or asset.byte_size != row["byte_size"]:
            raise RuntimeError("Frame asset metadata does not match its extraction record")
        store.resolve_path(asset.id, verify_hash=True)
        frames.append(
            VideoFrame(
                id=row["id"],
                extraction_id=row["extraction_id"],
                source_asset_id=row["source_asset_id"],
                frame_asset_id=row["frame_asset_id"],
                frame_index=row["frame_index"],
                timestamp_ms=row["timestamp_ms"],
                width=row["width"],
                height=row["height"],
                byte_size=row["byte_size"],
                sha256=row["sha256"],
            )
        )
    if len(frames) != extraction["frame_count"]:
        raise RuntimeError("Frame extraction record count does not match stored frames")
    return FrameExtractionResult(
        id=extraction["id"],
        source_asset_id=extraction["source_asset_id"],
        source_sha256=extraction["source_sha256"],
        tool_version=extraction["tool_version"],
        video_stream_index=extraction["video_stream_index"],
        sample_interval_ms=extraction["sample_interval_ms"],
        frame_count=extraction["frame_count"],
        total_bytes=extraction["total_bytes"],
        total_pixels=extraction["total_pixels"],
        frames=tuple(frames),
        reused=reused,
    )


def extract_video_frames(
    database_path: str | Path,
    asset_dir: str | Path,
    source_asset_id: str,
    *,
    video_stream_index: int | None = None,
    min_interval_ms: int = 5_000,
    max_frames: int = 500,
    max_frame_bytes: int = 2 * 1024 * 1024,
    max_total_bytes: int = 256 * 1024 * 1024,
    max_frame_pixels: int = 20_000_000,
    max_total_pixels: int = 100_000_000,
    max_width: int = 1280,
    max_height: int = 720,
    timeout_seconds: float = 600.0,
) -> FrameExtractionResult:
    """Extract bounded, timestamped JPEG samples from a registered local video asset."""
    if not 0 < timeout_seconds <= 1800:
        raise ValueError("timeout_seconds must be greater than zero and at most 1800")
    if not 1_000 <= min_interval_ms <= 60_000:
        raise ValueError("min_interval_ms must be between 1000 and 60000")
    if not 1 <= max_frames <= 2_000:
        raise ValueError("max_frames must be between 1 and 2000")
    if not 1_024 <= max_frame_bytes <= 64 * 1024 * 1024:
        raise ValueError("max_frame_bytes must be between 1 KiB and 64 MiB")
    if not max_frame_bytes <= max_total_bytes <= 1024 * 1024 * 1024:
        raise ValueError("max_total_bytes must be between max_frame_bytes and 1 GiB")
    if not 1 <= max_frame_pixels <= 100_000_000:
        raise ValueError("max_frame_pixels must be between 1 and 100 million")
    if not max_frame_pixels <= max_total_pixels <= 1_000_000_000:
        raise ValueError("max_total_pixels must be between max_frame_pixels and 1 billion")
    if not 16 <= max_width <= 8192 or not 16 <= max_height <= 8192:
        raise ValueError("Maximum frame dimensions must be between 16 and 8192")
    if max_width * max_height > max_frame_pixels:
        raise ValueError("Maximum frame dimensions exceed the per-frame pixel budget")

    store = AssetStore(database_path, asset_dir, max_bytes=max_frame_bytes)
    source_asset = store.get_asset(source_asset_id)
    if not source_asset.media_type.startswith("video/"):
        raise ValueError("Frame extraction requires a registered video asset")
    input_path = store.resolve_path(source_asset_id, verify_hash=True)
    probe: MediaProbeResult = probe_local_media(database_path, asset_dir, source_asset_id)
    video_streams = [stream for stream in probe.streams if stream.codec_type == "video"]
    if not video_streams:
        raise ValueError("Source media has no video stream")
    if video_stream_index is None:
        selected: MediaStreamInfo = video_streams[0]
    else:
        selected = next(
            (stream for stream in video_streams if stream.stream_index == video_stream_index),
            None,
        )
        if selected is None:
            raise ValueError("Selected stream index is not a video stream")
    if selected.start_ms is not None and selected.start_ms < 0:
        raise ValueError("Negative video stream start times require explicit timeline review")
    if probe.duration_ms is None:
        raise ValueError("Video duration is required for bounded frame sampling")
    source_pixels = (
        selected.width * selected.height
        if selected.width is not None and selected.height is not None
        else max_width * max_height
    )
    pixels_per_frame_bound = min(source_pixels,max_width * max_height)
    frames_by_pixel_budget = max_total_pixels // pixels_per_frame_bound
    frames_by_byte_budget = max_total_bytes // max_frame_bytes
    effective_max_frames = min(max_frames,frames_by_pixel_budget,frames_by_byte_budget)
    if effective_max_frames < 1:
        raise ValueError("Total pixel budget cannot hold one sampled frame")
    sample_interval_ms = max(
        min_interval_ms,math.ceil(probe.duration_ms / effective_max_frames)
    )
    sample_interval_seconds = sample_interval_ms / 1000
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("ffmpeg was not found; install FFmpeg tools to extract local frames")
    tool_version = _tool_version(executable, timeout_seconds)
    config_sha256 = _fingerprint(
        source_asset.sha256,tool_version,selected.stream_index,sample_interval_ms,
        max_frames,max_frame_bytes,max_total_bytes,max_frame_pixels,max_total_pixels,
        max_width,max_height,
    )
    with connect(database_path) as conn:
        existing = conn.execute(
            "SELECT id FROM frame_extractions WHERE source_asset_id=? AND config_sha256=?",
            (source_asset_id,config_sha256),
        ).fetchone()
    if existing is not None:
        return _load_result(database_path,asset_dir,existing["id"],reused=True)

    staging_root = store.storage_dir / ".staging"
    with tempfile.TemporaryDirectory(prefix="omniintel-frames-",dir=staging_root) as directory:
        staging = Path(directory)
        frame_pattern = str(staging / "frame_%06d.jpg")
        filter_graph = (
            f"fps=1/{sample_interval_seconds:.3f},"
            f"scale=w='min({max_width},iw)':h='min({max_height},ih)':"
            "force_original_aspect_ratio=decrease:force_divisible_by=2,showinfo"
        )
        arguments = [
            "-hide_banner","-nostdin","-loglevel","info",
            "-protocol_whitelist","file,pipe","-max_alloc","67108864",
            "-copyts","-i",str(input_path),
            "-map",f"0:{selected.stream_index}",
            "-an","-sn","-dn","-map_metadata","-1","-map_chapters","-1",
            "-vf",filter_graph,
            "-frames:v",str(effective_max_frames),"-fps_mode","passthrough",
            "-q:v","4","-threads","1","-filter_threads","1",
            "-f","image2","-fs",str(max_total_bytes),frame_pattern,
        ]
        log = _run_ffmpeg(
            executable,arguments,timeout_seconds=timeout_seconds,max_log_bytes=4_000_000,
        )
        frame_paths = sorted(staging.glob("frame_*.jpg"))
        timestamps = _parse_showinfo(log,max_frames=effective_max_frames)
        if len(frame_paths) != len(timestamps):
            raise ValueError("Extracted frame files do not match ffmpeg timestamp records")
        if not frame_paths:
            raise ValueError("ffmpeg did not extract any video frames")

        prepared: list[tuple[Path,int,int,int,int]] = []
        total_bytes = 0
        total_pixels = 0
        previous_timestamp = -1
        stream_end_ms = (
            selected.start_ms + selected.duration_ms
            if selected.start_ms is not None and selected.duration_ms is not None
            else None
        )
        for index,(frame_path,timestamp_ms) in enumerate(zip(frame_paths,timestamps,strict=True)):
            if timestamp_ms <= previous_timestamp:
                raise ValueError("Frame timestamps must be strictly increasing")
            if selected.start_ms is not None and timestamp_ms < selected.start_ms - 100:
                raise ValueError("Frame timestamp precedes the selected video stream")
            if stream_end_ms is not None and timestamp_ms > stream_end_ms + 1_000:
                raise ValueError("Frame timestamp exceeds the selected video stream duration")
            if timestamp_ms > probe.duration_ms + 1_000:
                raise ValueError("Frame timestamp exceeds the source media duration")
            byte_size = frame_path.stat().st_size
            if byte_size <= 0 or byte_size > max_frame_bytes:
                raise ValueError("Extracted frame exceeds the per-frame byte limit")
            width,height = _jpeg_dimensions(frame_path)
            pixels = width * height
            if pixels > max_frame_pixels:
                raise ValueError("Extracted frame exceeds the per-frame pixel limit")
            total_bytes += byte_size
            total_pixels += pixels
            if total_bytes > max_total_bytes:
                raise ValueError("Extracted frames exceed the total byte limit")
            if total_pixels > max_total_pixels:
                raise ValueError("Extracted frames exceed the total pixel limit")
            prepared.append((frame_path,timestamp_ms,width,height,byte_size))
            previous_timestamp = timestamp_ms

        frame_assets: list[AssetRecord] = []
        for index,(frame_path,timestamp_ms,width,height,byte_size) in enumerate(prepared):
            frame_assets.append(
                store.add_file(
                    source_asset.source_id,frame_path,role="FRAME",
                    display_name=f"frame-{timestamp_ms:012d}ms.jpg",
                )
            )
        extraction_id = uuid7()
        created_at = utc_now()
        metadata = {
            "schema":_SCHEMA,
            "timestamp_source":"ffmpeg-showinfo-pts-time-copyts",
            "filter":filter_graph,
            "max_width":max_width,
            "max_height":max_height,
            "effective_max_frames":effective_max_frames,
            "jpeg_quality":4,
            "selected_stream_start_ms":selected.start_ms,
        }
        reused = False
        with connect(database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id FROM frame_extractions WHERE source_asset_id=? AND config_sha256=?",
                (source_asset_id,config_sha256),
            ).fetchone()
            if existing is not None:
                extraction_id = existing["id"]
                reused = True
            else:
                conn.execute(
                    """INSERT INTO frame_extractions
                       (id,source_asset_id,source_sha256,config_sha256,tool_name,tool_version,
                        video_stream_index,sample_interval_ms,frame_count,total_bytes,total_pixels,
                        metadata_json,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        extraction_id,source_asset_id,source_asset.sha256,config_sha256,
                        "ffmpeg",tool_version,selected.stream_index,sample_interval_ms,
                        len(prepared),total_bytes,total_pixels,
                        json.dumps(metadata,ensure_ascii=False,sort_keys=True),created_at,
                    ),
                )
                for index,((frame_path,timestamp_ms,width,height,byte_size),asset) in enumerate(
                    zip(prepared,frame_assets,strict=True)
                ):
                    conn.execute(
                        """INSERT INTO video_frames
                           (id,extraction_id,source_asset_id,frame_asset_id,frame_index,
                            timestamp_ms,width,height,byte_size,sha256,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            uuid7(),extraction_id,source_asset_id,asset.id,index,
                            timestamp_ms,width,height,byte_size,asset.sha256,created_at,
                        ),
                    )
    return _load_result(database_path,asset_dir,extraction_id,reused=reused)


def frame_extraction_dict(result: FrameExtractionResult) -> dict[str, Any]:
    return asdict(result)
