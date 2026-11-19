"""Bounded, local-only FFmpeg audio normalization into immutable WAV derivatives."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from shutil import which as find_executable

from .assets import AssetRecord, AssetStore
from .database import connect
from .ids import uuid7
from .media_probe import MediaProbeResult, probe_local_media
from .models import utc_now


@dataclass(frozen=True, slots=True)
class AudioDerivativeResult:
    id: str
    source_asset_id: str
    output_asset: AssetRecord
    stream_index: int
    source_stream_start_ms: int | None
    time_offset_ms: int
    duration_ms: int
    tool_version: str
    reused: bool = False


def _run_tool(
    executable: str,
    arguments: list[str],
    *,
    timeout_seconds: float,
    max_stdout_bytes: int = 16_384,
    max_stderr_bytes: int = 8_192,
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
                [executable,*arguments],
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout_seconds,
                check=False,
                shell=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("FFmpeg exceeded the configured time limit") from error
        stdout_file.seek(0)
        stdout=stdout_file.read(max_stdout_bytes+1)
        stderr_file.seek(0)
        stderr=stderr_file.read(max_stderr_bytes+1)
    if len(stdout)>max_stdout_bytes or len(stderr)>max_stderr_bytes:
        raise ValueError("FFmpeg diagnostic output exceeded its configured limit")
    if completed.returncode != 0:
        detail=stderr.decode("utf-8",errors="replace").replace("\x00","")[:1000]
        raise RuntimeError(f"FFmpeg failed with exit code {completed.returncode}: {detail}")
    return stdout,stderr


def _ffmpeg_version(executable: str, timeout_seconds: float) -> str:
    output,_=_run_tool(
        executable,["-version"],timeout_seconds=min(timeout_seconds,10.0),
        max_stdout_bytes=16_384,
    )
    first=output.decode("utf-8",errors="replace").splitlines()
    version=first[0].strip()[:256] if first else ""
    if not version.startswith("ffmpeg version "):
        raise RuntimeError("The selected executable did not identify itself as FFmpeg")
    return version


def _wav_properties(path: Path) -> tuple[int,int,int,int]:
    try:
        with wave.open(str(path),"rb") as wav:
            channels=wav.getnchannels()
            sample_width=wav.getsampwidth()
            sample_rate=wav.getframerate()
            frames=wav.getnframes()
            compression=wav.getcomptype()
    except (OSError,wave.Error,EOFError) as error:
        raise ValueError(f"FFmpeg did not produce a valid WAV file: {error}") from error
    if (compression!="NONE" or channels!=1 or sample_width!=2 or sample_rate!=16_000 or frames<=0):
        raise ValueError("FFmpeg output is not mono 16 kHz signed PCM WAV")
    return channels,sample_width,sample_rate,(frames*1000)//sample_rate


def _derivative_fingerprint(
    source_sha256: str,
    *,
    stream_index: int,
    tool_version: str,
    max_output_bytes: int,
    max_duration_ms: int,
) -> str:
    payload={
        "source_sha256":source_sha256,
        "operation":"AUDIO_PCM_WAV",
        "tool":"ffmpeg",
        "tool_version":tool_version,
        "stream_index":stream_index,
        "sample_rate":16_000,
        "channels":1,
        "sample_width":2,
        "max_output_bytes":max_output_bytes,
        "max_duration_ms":max_duration_ms,
        "schema_version":1,
    }
    return hashlib.sha256(
        json.dumps(payload,sort_keys=True,separators=(",",":")).encode("utf-8")
    ).hexdigest()


def _load_existing(
    database_path: str | Path,
    asset_store: AssetStore,
    row: dict,
) -> AudioDerivativeResult:
    output=asset_store.get_asset(row["output_asset_id"])
    if output.source_id != asset_store.get_asset(row["source_asset_id"]).source_id:
        raise RuntimeError("Stored audio derivative crossed a source boundary")
    asset_store.resolve_path(output.id,verify_hash=True)
    return AudioDerivativeResult(
        id=row["id"],
        source_asset_id=row["source_asset_id"],
        output_asset=output,
        stream_index=row["stream_index"],
        source_stream_start_ms=row["source_stream_start_ms"],
        time_offset_ms=row["time_offset_ms"],
        duration_ms=row["duration_ms"],
        tool_version=row["tool_version"],
        reused=True,
    )


def extract_audio_to_wav(
    database_path: str | Path,
    asset_dir: str | Path,
    source_asset_id: str,
    *,
    stream_index: int | None = None,
    timeout_seconds: float = 600.0,
    max_output_bytes: int = 250 * 1024 * 1024,
    max_duration_ms: int = 12 * 60 * 60 * 1000,
) -> AudioDerivativeResult:
    """Extract one audio stream to bounded 16 kHz mono PCM WAV, without network access."""
    if not 0 < timeout_seconds <= 3_600:
        raise ValueError("timeout_seconds must be greater than zero and at most 3600")
    if not 64 * 1024 <= max_output_bytes <= 2 * 1024 * 1024 * 1024:
        raise ValueError("max_output_bytes must be between 64 KiB and 2 GiB")
    if not 1_000 <= max_duration_ms <= 12 * 60 * 60 * 1000:
        raise ValueError("max_duration_ms must be between 1 second and 12 hours")
    if stream_index is not None and (type(stream_index) is not int or stream_index < 0):
        raise ValueError("stream_index must be a non-negative integer")

    asset_store=AssetStore(database_path,asset_dir,max_bytes=max_output_bytes)
    source_asset=asset_store.get_asset(source_asset_id)
    if not (source_asset.media_type.startswith("audio/") or source_asset.media_type.startswith("video/")):
        raise ValueError("Only registered audio and video assets can produce audio derivatives")
    input_path=asset_store.resolve_path(source_asset_id,verify_hash=True)
    probe: MediaProbeResult=probe_local_media(database_path,asset_dir,source_asset_id)
    audio_streams=[stream for stream in probe.streams if stream.codec_type=="audio"]
    if stream_index is None:
        selected=audio_streams[0] if audio_streams else None
    else:
        selected=next((stream for stream in audio_streams if stream.stream_index==stream_index),None)
    if selected is None:
        raise ValueError("The requested media asset has no matching audio stream")
    offset_ms=max(0,selected.start_ms or 0)
    expected_duration=selected.duration_ms
    if expected_duration is None and probe.duration_ms is not None:
        expected_duration=max(0,probe.duration_ms-offset_ms)
    if expected_duration is None or expected_duration<=0:
        raise ValueError("The selected audio stream has no reliable duration metadata")
    if expected_duration>max_duration_ms or offset_ms+expected_duration>max_duration_ms+max_duration_ms:
        raise ValueError("The selected audio stream exceeds the configured duration limit")

    executable=find_executable("ffmpeg")
    if not executable:
        raise RuntimeError("ffmpeg was not found; install FFmpeg tools to extract local audio")
    version=_ffmpeg_version(executable,timeout_seconds)
    fingerprint=_derivative_fingerprint(
        source_asset.sha256,stream_index=selected.stream_index,tool_version=version,
        max_output_bytes=max_output_bytes,max_duration_ms=max_duration_ms,
    )
    with connect(database_path) as conn:
        existing=conn.execute(
            "SELECT * FROM media_derivatives WHERE source_asset_id=? AND config_sha256=?",
            (source_asset_id,fingerprint),
        ).fetchone()
    if existing is not None:
        return _load_existing(database_path,asset_store,dict(existing))

    with tempfile.TemporaryDirectory(prefix="omniintel-audio-") as directory:
        output_path=Path(directory)/"audio-16k-mono.wav"
        arguments=[
            "-nostdin","-hide_banner","-loglevel","error",
            "-protocol_whitelist","file,pipe",
            "-max_alloc","67108864",
            "-i",str(input_path),
            "-map",f"0:{selected.stream_index}",
            "-vn","-sn","-dn",
            "-map_metadata","-1","-map_chapters","-1",
            "-threads","1",
            "-ac","1","-ar","16000","-c:a","pcm_s16le",
            "-f","wav","-fs",str(max_output_bytes),
            "-y",str(output_path),
        ]
        _run_tool(
            executable,arguments,timeout_seconds=timeout_seconds,
            max_stdout_bytes=1024,max_stderr_bytes=8192,
        )
        if not output_path.is_file():
            raise RuntimeError("FFmpeg completed without producing an audio file")
        output_size=output_path.stat().st_size
        if output_size<=44 or output_size>=max_output_bytes:
            raise ValueError("Extracted audio is empty or reached the configured output-size cap")
        channels,sample_width,sample_rate,duration_ms=_wav_properties(output_path)
        tolerance=max(1_500,int(expected_duration*0.02))
        if abs(duration_ms-expected_duration)>tolerance:
            raise ValueError(
                "Extracted WAV duration does not match the selected source audio stream; "
                "the output may be truncated or the source timestamps may be inconsistent"
            )
        if duration_ms>max_duration_ms:
            raise ValueError("Extracted audio exceeds the configured duration limit")
        output_asset=asset_store.add_file(
            source_asset.source_id,output_path,role="AUDIO",
            display_name=f"{Path(source_asset.display_name).stem}.audio-16k.wav",
        )

    now=utc_now()
    derivative_id=uuid7()
    metadata={
        "input_media_type":source_asset.media_type,
        "output_media_type":output_asset.media_type,
        "normalization":"mono-16000hz-s16le",
        "protocols":"file,pipe",
    }
    with connect(database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing=conn.execute(
            "SELECT * FROM media_derivatives WHERE source_asset_id=? AND config_sha256=?",
            (source_asset_id,fingerprint),
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO media_derivatives
                   (id,source_asset_id,output_asset_id,source_sha256,output_sha256,
                    config_sha256,operation,tool_name,tool_version,stream_index,
                    source_stream_start_ms,time_offset_ms,duration_ms,sample_rate,
                    channels,sample_width,byte_size,metadata_json,created_at)
                   VALUES(?,?,?,?,?,?,'AUDIO_PCM_WAV','ffmpeg',?,?,?,?,?,16000,1,2,?,?,?)""",
                (
                    derivative_id,source_asset_id,output_asset.id,source_asset.sha256,
                    output_asset.sha256,fingerprint,version,selected.stream_index,
                    selected.start_ms,offset_ms,duration_ms,output_asset.byte_size,
                    json.dumps(metadata,ensure_ascii=False,sort_keys=True),now,
                ),
            )
        else:
            derivative_id=existing["id"]
            output_asset=asset_store.get_asset(existing["output_asset_id"])
            offset_ms=existing["time_offset_ms"]
            duration_ms=existing["duration_ms"]
    if existing is not None:
        asset_store.resolve_path(output_asset.id,verify_hash=True)
    return AudioDerivativeResult(
        id=derivative_id,
        source_asset_id=source_asset_id,
        output_asset=output_asset,
        stream_index=selected.stream_index,
        source_stream_start_ms=selected.start_ms,
        time_offset_ms=offset_ms,
        duration_ms=duration_ms,
        tool_version=version,
        reused=existing is not None,
    )
