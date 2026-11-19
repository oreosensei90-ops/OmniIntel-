"""Bounded local FFmpeg audio extraction with source-time provenance."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .assets import AssetRecord, AssetStore
from .database import connect
from .ids import uuid7
from .media_probe import MediaProbeResult, probe_local_media
from .models import utc_now

_OPERATION = "AUDIO_PCM_WAV"
_SAMPLE_RATE = 16_000
_CHANNELS = 1
_SAMPLE_WIDTH = 2
_SCHEMA = "omniintel-audio-pcm-wav-v1"


@dataclass(frozen=True, slots=True)
class AudioExtractionResult:
    id: str
    source_asset_id: str
    output_asset_id: str
    source_sha256: str
    output_sha256: str
    stream_index: int
    source_stream_start_ms: int | None
    time_offset_ms: int
    duration_ms: int
    byte_size: int
    sample_rate: int
    channels: int
    sample_width: int
    tool_name: str
    tool_version: str
    reused: bool = False


def _run_version(executable: str, *, timeout_seconds: float) -> str:
    environment = {"PATH": os.environ.get("PATH", ""), "LANG": "C", "LC_ALL": "C"}
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
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("ffmpeg version check exceeded its time limit") from error
        stdout_file.seek(0)
        output = stdout_file.read(16_385)
    if completed.returncode != 0 or len(output) > 16_384:
        raise RuntimeError("Unable to identify the local ffmpeg executable")
    first_line = output.decode("utf-8", errors="replace").splitlines()
    version = first_line[0].strip()[:256] if first_line else ""
    if not version.startswith("ffmpeg version "):
        raise RuntimeError("The selected executable did not identify itself as ffmpeg")
    return version


def _run_ffmpeg(
    executable: str,
    arguments: list[str],
    *,
    timeout_seconds: float,
) -> None:
    environment = {"PATH": os.environ.get("PATH", ""), "LANG": "C", "LC_ALL": "C"}
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
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("ffmpeg audio extraction exceeded its time limit") from error
        stderr_file.seek(0)
        detail = stderr_file.read(8193)
    if len(detail) > 8192:
        raise ValueError("ffmpeg diagnostic output exceeded its configured limit")
    if completed.returncode != 0:
        message = detail.decode("utf-8", errors="replace").replace("\x00", "")[:1000]
        raise RuntimeError(f"ffmpeg failed with exit code {completed.returncode}: {message}")


def _config_fingerprint(
    source_sha256: str,
    tool_version: str,
    stream_index: int,
    max_output_bytes: int,
) -> str:
    payload = json.dumps(
        {
            "schema": _SCHEMA,
            "operation": _OPERATION,
            "source_sha256": source_sha256,
            "tool_version": tool_version,
            "stream_index": stream_index,
            "sample_rate": _SAMPLE_RATE,
            "channels": _CHANNELS,
            "sample_width": _SAMPLE_WIDTH,
            "max_output_bytes": max_output_bytes,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_pcm_wav(path: Path) -> tuple[int, int]:
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getcomptype() != "NONE":
                raise ValueError("ffmpeg output is not uncompressed PCM WAV")
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            if (channels, sample_width, sample_rate) != (
                _CHANNELS,
                _SAMPLE_WIDTH,
                _SAMPLE_RATE,
            ):
                raise ValueError("ffmpeg output does not match the normalized PCM format")
            if frames <= 0:
                raise ValueError("ffmpeg produced an empty WAV")
            pcm = wav.readframes(frames)
            if len(pcm) != frames * channels * sample_width:
                raise ValueError("ffmpeg produced a truncated PCM WAV")
            duration_ms = frames * 1000 // sample_rate
            if duration_ms <= 0:
                raise ValueError("ffmpeg output duration is too short")
            return duration_ms, frames
    except (OSError, wave.Error, EOFError) as error:
        raise ValueError(f"ffmpeg output is not a readable WAV file: {error}") from error


def _load_result(
    database_path: str | Path,
    asset_dir: str | Path,
    derivative_id: str,
    *,
    reused: bool,
) -> AudioExtractionResult:
    with connect(database_path) as conn:
        row = conn.execute(
            "SELECT * FROM media_derivatives WHERE id=? AND operation=?",
            (derivative_id, _OPERATION),
        ).fetchone()
    if row is None:
        raise ValueError("Audio derivative record does not exist")
    store = AssetStore(database_path, asset_dir, max_bytes=max(row["byte_size"], 64 * 1024))
    output_asset = store.get_asset(row["output_asset_id"])
    if output_asset.sha256 != row["output_sha256"] or output_asset.byte_size != row["byte_size"]:
        raise RuntimeError("Derived audio asset metadata does not match its extraction record")
    store.resolve_path(output_asset.id, verify_hash=True)
    return AudioExtractionResult(
        id=row["id"],
        source_asset_id=row["source_asset_id"],
        output_asset_id=row["output_asset_id"],
        source_sha256=row["source_sha256"],
        output_sha256=row["output_sha256"],
        stream_index=row["stream_index"],
        source_stream_start_ms=row["source_stream_start_ms"],
        time_offset_ms=row["time_offset_ms"],
        duration_ms=row["duration_ms"],
        byte_size=row["byte_size"],
        sample_rate=row["sample_rate"],
        channels=row["channels"],
        sample_width=row["sample_width"],
        tool_name=row["tool_name"],
        tool_version=row["tool_version"],
        reused=reused,
    )


def extract_audio(
    database_path: str | Path,
    asset_dir: str | Path,
    source_asset_id: str,
    *,
    stream_index: int | None = None,
    timeout_seconds: float = 600.0,
    max_output_bytes: int = 512 * 1024 * 1024,
) -> AudioExtractionResult:
    """Extract one local audio stream to mono 16 kHz signed 16-bit PCM WAV."""
    if not 0 < timeout_seconds <= 1800:
        raise ValueError("timeout_seconds must be greater than zero and at most 1800")
    if not 64 * 1024 <= max_output_bytes <= 2 * 1024 * 1024 * 1024:
        raise ValueError("max_output_bytes must be between 64 KiB and 2 GiB")
    store = AssetStore(database_path, asset_dir, max_bytes=max_output_bytes)
    source_asset = store.get_asset(source_asset_id)
    if not (
        source_asset.media_type.startswith("video/")
        or source_asset.media_type.startswith("audio/")
    ):
        raise ValueError("Audio extraction requires a registered audio or video asset")
    input_path = store.resolve_path(source_asset_id, verify_hash=True)
    probe: MediaProbeResult = probe_local_media(
        database_path, asset_dir, source_asset_id,
    )
    audio_streams = [stream for stream in probe.streams if stream.codec_type == "audio"]
    if not audio_streams:
        raise ValueError("Source media has no audio stream")
    if stream_index is None:
        selected = audio_streams[0]
    else:
        selected = next(
            (stream for stream in audio_streams if stream.stream_index == stream_index),
            None,
        )
        if selected is None:
            raise ValueError("Selected stream index is not an audio stream")
    source_stream_start_ms = selected.start_ms
    if source_stream_start_ms is not None and source_stream_start_ms < 0:
        raise ValueError("Negative audio stream start times require explicit timeline review")
    time_offset_ms = source_stream_start_ms or 0

    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("ffmpeg was not found; install FFmpeg tools to extract local audio")
    tool_version = _run_version(executable, timeout_seconds=timeout_seconds)
    config_sha256 = _config_fingerprint(
        source_asset.sha256, tool_version, selected.stream_index, max_output_bytes,
    )
    with connect(database_path) as conn:
        existing = conn.execute(
            "SELECT id FROM media_derivatives WHERE source_asset_id=? AND config_sha256=?",
            (source_asset_id, config_sha256),
        ).fetchone()
    if existing is not None:
        return _load_result(database_path, asset_dir, existing["id"], reused=True)

    staging_root = store.storage_dir / ".staging"
    with tempfile.TemporaryDirectory(prefix="omniintel-audio-", dir=staging_root) as directory:
        output_path = Path(directory) / "audio-16k-mono.wav"
        arguments = [
            "-hide_banner",
            "-nostdin",
            "-v", "error",
            "-protocol_whitelist", "file,pipe",
            "-max_alloc", "67108864",
            "-i", str(input_path),
            "-map", f"0:{selected.stream_index}",
            "-vn", "-sn", "-dn",
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-af", "asetpts=PTS-STARTPTS",
            "-ac", str(_CHANNELS),
            "-ar", str(_SAMPLE_RATE),
            "-c:a", "pcm_s16le",
            "-threads", "1",
            "-filter_threads", "1",
            "-f", "wav",
            "-fs", str(max_output_bytes),
            str(output_path),
        ]
        _run_ffmpeg(executable, arguments, timeout_seconds=timeout_seconds)
        if not output_path.is_file():
            raise RuntimeError("ffmpeg completed without producing an audio file")
        byte_size = output_path.stat().st_size
        if byte_size <= 44 or byte_size >= max_output_bytes:
            raise ValueError("Extracted audio is empty or reached the configured output-size limit")
        duration_ms, _ = _read_pcm_wav(output_path)
        if selected.duration_ms is not None and abs(duration_ms - selected.duration_ms) > 5_000:
            raise ValueError("Extracted audio duration does not match the selected stream")
        with connect(database_path) as conn:
            source = conn.execute(
                "SELECT duration_ms FROM sources WHERE id=?",
                (source_asset.source_id,),
            ).fetchone()
        source_duration_ms = source["duration_ms"] if source else None
        if source_duration_ms is not None and time_offset_ms + duration_ms > source_duration_ms + 1_000:
            raise ValueError("Extracted audio extends beyond the registered source timeline")
        output_asset: AssetRecord = store.add_file(
            source_asset.source_id,
            output_path,
            role="AUDIO",
            display_name="audio-16k-mono.wav",
        )
        output_sha256 = output_asset.sha256
        derivative_id = uuid7()
        created_at = utc_now()
        metadata = {
            "schema": _SCHEMA,
            "source_media_type": source_asset.media_type,
            "source_stream_codec": selected.codec_name,
            "source_stream_start_ms": source_stream_start_ms,
            "normalization": "mono-16000hz-s16le",
            "duration_tolerance_ms": 5000,
        }
        reused = False
        with connect(database_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id FROM media_derivatives WHERE source_asset_id=? AND config_sha256=?",
                (source_asset_id, config_sha256),
            ).fetchone()
            if existing is not None:
                derivative_id = existing["id"]
                reused = True
            else:
                conn.execute(
                    """INSERT INTO media_derivatives
                       (id,source_asset_id,output_asset_id,source_sha256,output_sha256,
                        config_sha256,operation,tool_name,tool_version,stream_index,
                        source_stream_start_ms,time_offset_ms,duration_ms,sample_rate,
                        channels,sample_width,byte_size,metadata_json,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        derivative_id,source_asset_id,output_asset.id,source_asset.sha256,
                        output_sha256,config_sha256,_OPERATION,"ffmpeg",tool_version,
                        selected.stream_index,source_stream_start_ms,time_offset_ms,
                        duration_ms,_SAMPLE_RATE,_CHANNELS,_SAMPLE_WIDTH,byte_size,
                        json.dumps(metadata,ensure_ascii=False,sort_keys=True),created_at,
                    ),
                )
    return _load_result(database_path, asset_dir, derivative_id, reused=reused)


def audio_extraction_dict(result: AudioExtractionResult) -> dict[str, Any]:
    return asdict(result)
