"""Local WAV transcription with content-addressed, resumable chunk checkpoints.

The core has no mandatory ASR dependency. Adapters are explicit and run locally;
the optional faster-whisper adapter is loaded only when selected by the caller.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from .assets import AssetStore
from .database import connect, migrate
from .evidence_refs import register_transcript_references
from .ids import uuid7
from .models import TranscriptSegmentInput, utc_now


@dataclass(frozen=True, slots=True)
class ChunkTranscription:
    language: str | None
    segments: tuple[TranscriptSegmentInput, ...]


@dataclass(frozen=True, slots=True)
class TranscriptionRunResult:
    run_id: str
    source_id: str
    duration_ms: int
    segment_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_ref_ids: tuple[str, ...]
    reused_chunks: int
    processed_chunks: int


class TranscriptionAdapter(Protocol):
    name: str
    version: str
    model_id: str

    def transcribe_chunk(
        self, wav_path: Path, *, language: str | None
    ) -> ChunkTranscription: ...


@dataclass(frozen=True, slots=True)
class FasterWhisperAdapter:
    """Optional local faster-whisper adapter. Install the 'asr' extra to use it."""

    model_id: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = 4
    allow_model_download: bool = False
    name: str = "faster-whisper"
    version: str = "1"
    _model: object | None = field(default=None,init=False,repr=False,compare=False)

    @property
    def configuration(self) -> dict[str, object]:
        return {
            "device":self.device,
            "compute_type":self.compute_type,
            "cpu_threads":self.cpu_threads,
            "allow_model_download":self.allow_model_download,
            "beam_size":5,
            "vad_filter":True,
            "word_timestamps":False,
        }

    def __post_init__(self) -> None:
        if not self.model_id.strip() or not self.device.strip() or not self.compute_type.strip():
            raise ValueError("faster-whisper model, device and compute type must not be empty")
        if self.cpu_threads < 1:
            raise ValueError("cpu_threads must be positive")

    def transcribe_chunk(
        self, wav_path: Path, *, language: str | None
    ) -> ChunkTranscription:
        if not Path(self.model_id).is_dir() and not self.allow_model_download:
            raise RuntimeError(
                "ASR model must be a local CTranslate2 directory; pass explicit allow_model_download=True to permit a model download"
            )
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "faster-whisper is not installed; install OmniIntel with the 'asr' extra"
            ) from error
        if self._model is None:
            object.__setattr__(self,"_model",WhisperModel(
                self.model_id,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
            ))
        segments, info = self._model.transcribe(
            str(wav_path),
            language=language,
            beam_size=5,
            vad_filter=True,
            word_timestamps=False,
        )
        output = []
        for segment in segments:
            text = str(segment.text or "").strip()
            start_ms = max(0, round(float(segment.start) * 1000))
            end_ms = round(float(segment.end) * 1000)
            if text and end_ms > start_ms:
                output.append(
                    TranscriptSegmentInput(
                        text=text,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        language=getattr(info, "language", None) or language,
                    )
                )
        return ChunkTranscription(
            language=getattr(info, "language", None) or language,
            segments=tuple(output),
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_hash(
    adapter: TranscriptionAdapter,
    *,
    language: str | None,
    chunk_seconds: int,
    max_chunk_bytes: int,
) -> str:
    payload = {
        "adapter": adapter.name,
        "adapter_version": adapter.version,
        "model_id": adapter.model_id,
        "adapter_configuration": getattr(adapter,"configuration",{}),
        "language": language,
        "chunk_seconds": chunk_seconds,
        "max_chunk_bytes": max_chunk_bytes,
        "timestamp_unit": "milliseconds",
        "schema_version": 1,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_wav_info(path: Path, *, max_duration_ms: int) -> tuple[int, int, int, int, int]:
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            compression = wav.getcomptype()
    except (OSError, wave.Error, EOFError) as error:
        raise ValueError(f"Audio asset must be a readable PCM WAV file: {error}") from error
    if compression != "NONE":
        raise ValueError("Only uncompressed PCM WAV is supported by this transcription stage")
    if not (1 <= channels <= 8 and sample_width in {1, 2, 3, 4} and 8_000 <= sample_rate <= 192_000):
        raise ValueError("WAV channels, sample width or sample rate are outside supported bounds")
    if frames <= 0:
        raise ValueError("WAV audio contains no frames")
    duration_ms = (frames * 1000) // sample_rate
    if duration_ms <= 0 or duration_ms > max_duration_ms:
        raise ValueError("WAV audio duration exceeds configured limits")
    return channels, sample_width, sample_rate, frames, duration_ms


def _frames_per_chunk(
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    chunk_seconds: int,
    max_chunk_bytes: int,
) -> int:
    frame_bytes=channels*sample_width
    if frame_bytes <= 0 or max_chunk_bytes < frame_bytes:
        raise ValueError("max_chunk_bytes is too small for one audio frame")
    return min(sample_rate*chunk_seconds,max_chunk_bytes//frame_bytes)


def _iter_wav_chunks(
    path: Path,
    work_dir: Path,
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    total_frames: int,
    chunk_seconds: int,
    max_chunk_bytes: int,
):
    frame_bytes = channels * sample_width
    frames_per_chunk = _frames_per_chunk(
        sample_rate=sample_rate,channels=channels,sample_width=sample_width,
        chunk_seconds=chunk_seconds,max_chunk_bytes=max_chunk_bytes,
    )
    with wave.open(str(path), "rb") as source:
        index = 0
        start_frame = 0
        while start_frame < total_frames:
            count = min(frames_per_chunk, total_frames - start_frame)
            data = source.readframes(count)
            expected = count * frame_bytes
            if len(data) != expected:
                raise ValueError("WAV ended before its declared frame count")
            chunk_path = work_dir / f"chunk-{index:06d}.wav"
            with wave.open(str(chunk_path), "wb") as target:
                target.setnchannels(channels)
                target.setsampwidth(sample_width)
                target.setframerate(sample_rate)
                target.writeframes(data)
            start_ms = (start_frame * 1000) // sample_rate
            end_frame = start_frame + count
            end_ms = (end_frame * 1000) // sample_rate
            if end_ms <= start_ms:
                raise ValueError("Audio chunk has no representable duration")
            yield index, chunk_path, start_ms, end_ms, _sha256_file(chunk_path)
            start_frame = end_frame
            index += 1


def _get_or_create_run(
    database_path: str | Path,
    *,
    source_id: str,
    asset_id: str,
    input_sha256: str,
    config_sha256: str,
    adapter: TranscriptionAdapter,
    language: str | None,
    chunk_seconds: int,
    sample_rate: int,
    channels: int,
    sample_width: int,
    duration_ms: int,
) -> dict:
    now = utc_now()
    with connect(database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        asset = conn.execute(
            """SELECT sa.source_id,ab.media_type FROM source_assets sa
               JOIN asset_blobs ab ON ab.sha256=sa.blob_sha256 WHERE sa.id=?""",
            (asset_id,),
        ).fetchone()
        if asset is None or asset["source_id"] != source_id:
            raise ValueError("Audio asset must belong to the selected source")
        if asset["media_type"] != "audio/wav":
            raise ValueError("This transcription adapter currently accepts WAV audio assets only")
        row = conn.execute(
            """SELECT * FROM transcription_runs
               WHERE source_id=? AND source_asset_id=? AND input_sha256=? AND config_sha256=?""",
            (source_id, asset_id, input_sha256, config_sha256),
        ).fetchone()
        if row is not None:
            return dict(row)
        existing = conn.execute(
            "SELECT 1 FROM transcript_segments WHERE source_id=? LIMIT 1", (source_id,)
        ).fetchone()
        if existing is not None:
            raise ValueError(
                "This source already has a transcript; create a new source revision before re-transcribing"
            )
        source = conn.execute(
            "SELECT duration_ms FROM sources WHERE id=?", (source_id,)
        ).fetchone()
        if source is None:
            raise ValueError("Source does not exist")
        if source["duration_ms"] is not None and abs(source["duration_ms"] - duration_ms) > 1_000:
            raise ValueError("WAV duration conflicts with the registered source duration")
        if source["duration_ms"] is None:
            conn.execute("UPDATE sources SET duration_ms=? WHERE id=?", (duration_ms, source_id))
        run_id = uuid7()
        conn.execute(
            """INSERT INTO transcription_runs
               (id,source_id,source_asset_id,input_sha256,config_sha256,
                adapter_name,adapter_version,model_id,language,chunk_seconds,
                sample_rate,channels,sample_width,duration_ms,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'RUNNING',?,?)""",
            (
                run_id,source_id,asset_id,input_sha256,config_sha256,
                adapter.name,adapter.version,adapter.model_id,language,chunk_seconds,
                sample_rate,channels,sample_width,duration_ms,now,now,
            ),
        )
        row = conn.execute("SELECT * FROM transcription_runs WHERE id=?", (run_id,)).fetchone()
        return dict(row)


def _checkpoint_chunk(
    database_path: str | Path,
    *,
    run_id: str,
    index: int,
    audio_sha256: str,
    start_ms: int,
    end_ms: int,
    result: ChunkTranscription | None = None,
) -> ChunkTranscription | None:
    now = utc_now()
    with connect(database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM transcription_chunks WHERE run_id=? AND chunk_index=?",
            (run_id,index),
        ).fetchone()
        if row is not None and (
            row["audio_sha256"] == audio_sha256
            and row["start_ms"] == start_ms
            and row["end_ms"] == end_ms
            and row["status"] == "COMPLETED"
            and row["result_json"]
        ):
            try:
                payload = json.loads(row["result_json"])
                cached = ChunkTranscription(
                    language=payload.get("language"),
                    segments=tuple(TranscriptSegmentInput(**item) for item in payload["segments"]),
                )
                for segment in cached.segments:
                    segment.validate(end_ms - start_ms)
                return cached
            except (KeyError,TypeError,ValueError,json.JSONDecodeError):
                pass
        if row is None:
            conn.execute(
                """INSERT INTO transcription_chunks
                   (id,run_id,chunk_index,audio_sha256,start_ms,end_ms,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,'RUNNING',?,?)""",
                (uuid7(),run_id,index,audio_sha256,start_ms,end_ms,now,now),
            )
        else:
            conn.execute(
                """UPDATE transcription_chunks SET audio_sha256=?,start_ms=?,end_ms=?,
                   status='RUNNING',result_json=NULL,updated_at=?
                   WHERE run_id=? AND chunk_index=?""",
                (audio_sha256,start_ms,end_ms,now,run_id,index),
            )
        if result is not None:
            payload = {
                "language": result.language,
                "segments": [
                    {
                        "text": segment.text,
                        "start_ms": segment.start_ms,
                        "end_ms": segment.end_ms,
                        "language": segment.language,
                        "speaker_id": segment.speaker_id,
                    }
                    for segment in result.segments
                ],
            }
            conn.execute(
                """UPDATE transcription_chunks SET status='COMPLETED',result_json=?,updated_at=?
                   WHERE run_id=? AND chunk_index=? AND audio_sha256=?""",
                (json.dumps(payload,ensure_ascii=False,sort_keys=True),now,run_id,index,audio_sha256),
            )
    return None


def _validate_chunk_result(result: ChunkTranscription, duration_ms: int) -> None:
    if not isinstance(result,ChunkTranscription):
        raise TypeError("Transcription adapter must return ChunkTranscription")
    previous_start = -1
    for segment in result.segments:
        segment.validate(duration_ms)
        if segment.start_ms < previous_start:
            raise ValueError("Transcription adapter segments must be ordered")
        previous_start = segment.start_ms


def _complete_run(
    database_path: str | Path,
    run: dict,
    chunks: list[tuple[int,int,ChunkTranscription]],
) -> tuple[tuple[str,...],tuple[str,...]]:
    segments: list[TranscriptSegmentInput] = []
    for start_ms,_,chunk in chunks:
        for segment in chunk.segments:
            segments.append(
                TranscriptSegmentInput(
                    text=segment.text,
                    start_ms=start_ms + segment.start_ms,
                    end_ms=start_ms + segment.end_ms,
                    language=segment.language or chunk.language or run["language"],
                    speaker_id=segment.speaker_id,
                )
            )
    segments.sort(key=lambda item:(item.start_ms,item.end_ms))
    if not segments:
        raise ValueError("No speech segments were produced; source remains available for another adapter")
    previous_start = -1
    for segment in segments:
        segment.validate(run["duration_ms"])
        if segment.start_ms < previous_start:
            raise ValueError("Combined transcript segments are not ordered")
        previous_start = segment.start_ms

    segment_ids: list[str] = []
    evidence_ids: list[str] = []
    now = utc_now()
    with connect(database_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT segment_ids_json,evidence_ids_json FROM transcription_runs WHERE id=? AND status='COMPLETED'",
            (run["id"],),
        ).fetchone()
        if existing is not None:
            return tuple(json.loads(existing["segment_ids_json"])),tuple(json.loads(existing["evidence_ids_json"]))
        if conn.execute(
            "SELECT 1 FROM transcript_segments WHERE source_id=? LIMIT 1",(run["source_id"],)
        ).fetchone():
            raise ValueError("Source transcript already exists; refusing to overwrite source history")
        for ordinal,segment in enumerate(segments):
            segment_id,evidence_id=uuid7(),uuid7()
            segment_ids.append(segment_id)
            evidence_ids.append(evidence_id)
            conn.execute(
                """INSERT INTO transcript_segments
                   (id,source_id,text,start_ms,end_ms,language,speaker_id,ordinal,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (segment_id,run["source_id"],segment.text,segment.start_ms,segment.end_ms,
                 segment.language,segment.speaker_id,ordinal,now),
            )
            conn.execute(
                """INSERT INTO evidence_items
                   (id,source_id,segment_id,evidence_type,content,start_ms,end_ms,provenance,created_at)
                   VALUES(?,?,?,'transcript',?,?,?,'SOURCE',?)""",
                (evidence_id,run["source_id"],segment_id,segment.text,
                 segment.start_ms,segment.end_ms,now),
            )
        conn.execute(
            """UPDATE transcription_runs SET status='COMPLETED',segment_ids_json=?,
               evidence_ids_json=?,last_error=NULL,completed_at=?,updated_at=? WHERE id=?""",
            (json.dumps(segment_ids),json.dumps(evidence_ids),now,now,run["id"]),
        )
    return tuple(segment_ids),tuple(evidence_ids)


def run_wav_transcription(
    database_path: str | Path,
    asset_dir: str | Path,
    source_id: str,
    asset_id: str,
    adapter: TranscriptionAdapter,
    *,
    language: str | None = None,
    chunk_seconds: int = 120,
    max_chunk_bytes: int = 16 * 1024 * 1024,
    max_duration_ms: int = 12 * 60 * 60 * 1000,
    progress: Callable[[int,int],None] | None = None,
) -> TranscriptionRunResult:
    """Transcribe a user-selected PCM WAV, persisting each completed chunk.

    A rerun with the same source bytes, adapter identity and settings reuses
    completed chunks. The original asset is never modified. This first adapter
    accepts WAV only; compressed audio/video decoding is a separate stage.
    """
    if not 1 <= chunk_seconds <= 600:
        raise ValueError("chunk_seconds must be between 1 and 600")
    if max_chunk_bytes < 64 * 1024 or max_chunk_bytes > 64 * 1024 * 1024:
        raise ValueError("max_chunk_bytes must be between 64 KiB and 64 MiB")
    if max_duration_ms <= 0:
        raise ValueError("max_duration_ms must be positive")
    asset_store=AssetStore(database_path,asset_dir)
    audio_path=asset_store.resolve_path(asset_id)
    input_sha256=_sha256_file(audio_path)
    channels,sample_width,sample_rate,total_frames,duration_ms=_read_wav_info(
        audio_path,max_duration_ms=max_duration_ms
    )
    config_sha256=_config_hash(
        adapter,language=language,chunk_seconds=chunk_seconds,max_chunk_bytes=max_chunk_bytes
    )
    run=_get_or_create_run(
        database_path,source_id=source_id,asset_id=asset_id,input_sha256=input_sha256,
        config_sha256=config_sha256,adapter=adapter,language=language,
        chunk_seconds=chunk_seconds,sample_rate=sample_rate,channels=channels,
        sample_width=sample_width,duration_ms=duration_ms,
    )
    if run["status"] == "COMPLETED":
        segment_ids=tuple(json.loads(run["segment_ids_json"] or "[]"))
        evidence_ids=tuple(json.loads(run["evidence_ids_json"] or "[]"))
        reference_ids=register_transcript_references(database_path,evidence_ids)
        with connect(database_path) as conn:
            conn.execute(
                "UPDATE transcription_runs SET evidence_ref_ids_json=?,updated_at=? WHERE id=?",
                (json.dumps(reference_ids),utc_now(),run["id"]),
            )
        return TranscriptionRunResult(
            run["id"],source_id,duration_ms,segment_ids,evidence_ids,reference_ids,0,0
        )

    with connect(database_path) as conn:
        conn.execute(
            "UPDATE transcription_runs SET status='RUNNING',last_error=NULL,updated_at=? WHERE id=?",
            (utc_now(),run["id"]),
        )
    processed=0
    reused=0
    combined: list[tuple[int,int,ChunkTranscription]]=[]
    frames_per_chunk=_frames_per_chunk(
        sample_rate=sample_rate,channels=channels,sample_width=sample_width,
        chunk_seconds=chunk_seconds,max_chunk_bytes=max_chunk_bytes,
    )
    total_chunks=(total_frames+frames_per_chunk-1)//frames_per_chunk
    try:
        with tempfile.TemporaryDirectory(prefix="omniintel-asr-") as directory:
            work_dir=Path(directory)
            for index,chunk_path,start_ms,end_ms,chunk_sha in _iter_wav_chunks(
                audio_path,work_dir,sample_rate=sample_rate,channels=channels,
                sample_width=sample_width,total_frames=total_frames,
                chunk_seconds=chunk_seconds,max_chunk_bytes=max_chunk_bytes,
            ):
                cached=_checkpoint_chunk(
                    database_path,run_id=run["id"],index=index,audio_sha256=chunk_sha,
                    start_ms=start_ms,end_ms=end_ms,
                )
                if cached is not None:
                    result=cached
                    reused+=1
                else:
                    chunk_duration=end_ms-start_ms
                    result=adapter.transcribe_chunk(chunk_path,language=language)
                    _validate_chunk_result(result,chunk_duration)
                    _checkpoint_chunk(
                        database_path,run_id=run["id"],index=index,audio_sha256=chunk_sha,
                        start_ms=start_ms,end_ms=end_ms,result=result,
                    )
                    processed+=1
                combined.append((start_ms,end_ms,result))
                if progress:
                    progress(index+1,max(1,total_chunks))
        segment_ids,evidence_ids=_complete_run(database_path,run,combined)
        reference_ids=register_transcript_references(database_path,evidence_ids)
        with connect(database_path) as conn:
            conn.execute(
                "UPDATE transcription_runs SET evidence_ref_ids_json=?,updated_at=? WHERE id=?",
                (json.dumps(reference_ids),utc_now(),run["id"]),
            )
        return TranscriptionRunResult(
            run["id"],source_id,duration_ms,segment_ids,evidence_ids,reference_ids,reused,processed
        )
    except Exception as error:
        with connect(database_path) as conn:
            conn.execute(
                "UPDATE transcription_runs SET status='PARTIAL',last_error=?,updated_at=? WHERE id=? AND status<>'COMPLETED'",
                (str(error)[:2000],utc_now(),run["id"]),
            )
        raise
