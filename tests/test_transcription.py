from __future__ import annotations

import wave
from pathlib import Path

import pytest

from omniintel.evidence_refs import get_evidence_reference
from omniintel.local_files import import_local_file
from omniintel.models import TranscriptSegmentInput
from omniintel.transcription import (
    ChunkTranscription,
    FasterWhisperAdapter,
    run_wav_transcription,
)


def _make_wav(path: Path, *, seconds: int = 5, sample_rate: int = 16_000) -> None:
    with wave.open(str(path),"wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * seconds * sample_rate)


class FakeAdapter:
    name = "fake-local-asr"
    version = "test-1"
    model_id = "fake-base"

    def __init__(self, *, fail_chunk: int | None = None, model_id: str | None = None):
        self.fail_chunk = fail_chunk
        if model_id:
            self.model_id = model_id
        self.calls: list[int] = []

    @property
    def configuration(self) -> dict[str, object]:
        return {"deterministic": True}

    def transcribe_chunk(self, wav_path: Path, *, language: str | None) -> ChunkTranscription:
        index = int(wav_path.stem.split("-")[-1])
        self.calls.append(index)
        if self.fail_chunk == index:
            raise RuntimeError("simulated interruption")
        with wave.open(str(wav_path),"rb") as wav:
            duration_ms = wav.getnframes() * 1000 // wav.getframerate()
        end_ms = min(800,duration_ms)
        return ChunkTranscription(
            language=language or "en",
            segments=(TranscriptSegmentInput(
                text=f"Recognized chunk {index}",
                start_ms=100,
                end_ms=end_ms,
                language=language or "en",
            ),),
        )


def _import_audio(tmp_path: Path, *, seconds: int = 5):
    pdf = tmp_path / "lecture.wav"
    _make_wav(pdf,seconds=seconds)
    database = tmp_path / "omniintel.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database,assets,pdf,title="Local lecture audio")
    return database,assets,imported


def test_wav_transcription_persists_timed_source_evidence_and_refs(tmp_path: Path) -> None:
    database,assets,imported = _import_audio(tmp_path)
    adapter = FakeAdapter()
    progress: list[tuple[int,int]] = []
    result = run_wav_transcription(
        database,assets,imported.source_id,imported.asset.id,adapter,
        language="en",chunk_seconds=2,progress=lambda done,total: progress.append((done,total)),
    )

    assert result.duration_ms == 5_000
    assert result.processed_chunks == 3
    assert result.reused_chunks == 0
    assert len(result.segment_ids) == len(result.evidence_ids) == len(result.evidence_ref_ids) == 3
    assert progress == [(1,3),(2,3),(3,3)]

    from omniintel.store import OmniIntelStore
    segments = OmniIntelStore(database).get_transcript(imported.source_id)
    assert [row["text"] for row in segments] == [
        "Recognized chunk 0","Recognized chunk 1","Recognized chunk 2"
    ]
    assert [row["start_ms"] for row in segments] == [100,2100,4100]
    assert [row["end_ms"] for row in segments] == [800,2800,4800]

    reference = get_evidence_reference(database,result.evidence_ref_ids[1])
    assert reference is not None
    assert reference["locator_kind"] == "TRANSCRIPT_INTERVAL"
    assert reference["content"] == "Recognized chunk 1"
    assert reference["start_ms"] == 2100


def test_interrupted_transcription_reuses_completed_content_addressed_chunks(tmp_path: Path) -> None:
    database,assets,imported = _import_audio(tmp_path)
    interrupted = FakeAdapter(fail_chunk=1)
    with pytest.raises(RuntimeError,match="simulated interruption"):
        run_wav_transcription(
            database,assets,imported.source_id,imported.asset.id,interrupted,
            language="en",chunk_seconds=2,
        )
    assert interrupted.calls == [0,1]

    from omniintel.database import connect
    with connect(database) as conn:
        run = conn.execute(
            "SELECT id,status FROM transcription_runs WHERE source_id=?",
            (imported.source_id,),
        ).fetchone()
        assert run["status"] == "PARTIAL"
        completed = conn.execute(
            "SELECT count(*) FROM transcription_chunks WHERE run_id=? AND status='COMPLETED'",
            (run["id"],),
        ).fetchone()[0]
        assert completed == 1

    resumed = FakeAdapter()
    result = run_wav_transcription(
        database,assets,imported.source_id,imported.asset.id,resumed,
        language="en",chunk_seconds=2,
    )
    assert result.reused_chunks == 1
    assert result.processed_chunks == 2
    assert resumed.calls == [1,2]
    assert len(result.segment_ids) == 3


def test_completed_transcription_is_idempotent_and_does_not_call_adapter_again(tmp_path: Path) -> None:
    database,assets,imported = _import_audio(tmp_path,seconds=2)
    first_adapter = FakeAdapter()
    first = run_wav_transcription(
        database,assets,imported.source_id,imported.asset.id,first_adapter,
        language="en",chunk_seconds=2,
    )
    second_adapter = FakeAdapter()
    second = run_wav_transcription(
        database,assets,imported.source_id,imported.asset.id,second_adapter,
        language="en",chunk_seconds=2,
    )
    assert second.run_id == first.run_id
    assert second.segment_ids == first.segment_ids
    assert second.evidence_ref_ids == first.evidence_ref_ids
    assert second.processed_chunks == second.reused_chunks == 0
    assert second_adapter.calls == []


def test_different_transcription_configuration_cannot_overwrite_source_history(tmp_path: Path) -> None:
    database,assets,imported = _import_audio(tmp_path,seconds=2)
    run_wav_transcription(
        database,assets,imported.source_id,imported.asset.id,FakeAdapter(),
        language="en",chunk_seconds=2,
    )
    with pytest.raises(ValueError,match="already has a transcript"):
        run_wav_transcription(
            database,assets,imported.source_id,imported.asset.id,
            FakeAdapter(model_id="different-model"),
            language="en",chunk_seconds=2,
        )


def test_wav_transcription_rejects_wrong_asset_owner_and_duration_limit(tmp_path: Path) -> None:
    database,assets,imported = _import_audio(tmp_path,seconds=2)
    from omniintel.store import OmniIntelStore
    other_source = OmniIntelStore(database).create_source(title="Other source")
    with pytest.raises(ValueError,match="belong to the selected source"):
        run_wav_transcription(
            database,assets,other_source,imported.asset.id,FakeAdapter(),
        )
    with pytest.raises(ValueError,match="duration exceeds"):
        run_wav_transcription(
            database,assets,imported.source_id,imported.asset.id,FakeAdapter(),
            max_duration_ms=1_000,
        )


def test_invalid_adapter_segments_are_not_checkpointed_as_complete(tmp_path: Path) -> None:
    database,assets,imported = _import_audio(tmp_path,seconds=2)

    class InvalidAdapter(FakeAdapter):
        def transcribe_chunk(self, wav_path: Path, *, language: str | None) -> ChunkTranscription:
            return ChunkTranscription(
                language="en",
                segments=(TranscriptSegmentInput(
                    text="Outside chunk",start_ms=0,end_ms=99_999,language="en",
                ),),
            )

    with pytest.raises(ValueError,match="exceeds source duration"):
        run_wav_transcription(
            database,assets,imported.source_id,imported.asset.id,InvalidAdapter(),
            language="en",chunk_seconds=2,
        )
    from omniintel.database import connect
    with connect(database) as conn:
        state = conn.execute(
            "SELECT status FROM transcription_chunks",
        ).fetchone()
        assert state["status"] == "RUNNING"
        assert conn.execute(
            "SELECT count(*) FROM transcript_segments WHERE source_id=?",
            (imported.source_id,),
        ).fetchone()[0] == 0


def test_no_speech_does_not_create_an_empty_published_transcript(tmp_path: Path) -> None:
    database,assets,imported = _import_audio(tmp_path,seconds=2)

    class SilenceAdapter(FakeAdapter):
        def transcribe_chunk(self, wav_path: Path, *, language: str | None) -> ChunkTranscription:
            return ChunkTranscription(language="en",segments=())

    with pytest.raises(ValueError,match="No speech segments"):
        run_wav_transcription(
            database,assets,imported.source_id,imported.asset.id,SilenceAdapter(),
            language="en",chunk_seconds=2,
        )
    from omniintel.database import connect
    with connect(database) as conn:
        assert conn.execute(
            "SELECT count(*) FROM transcript_segments WHERE source_id=?",
            (imported.source_id,),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT status FROM transcription_runs WHERE source_id=?",
            (imported.source_id,),
        ).fetchone()["status"] == "PARTIAL"

def test_faster_whisper_requires_local_model_or_explicit_download_consent(tmp_path: Path) -> None:
    from omniintel.transcription import FasterWhisperAdapter

    audio = tmp_path / "chunk.wav"
    _make_wav(audio,seconds=1)
    adapter = FasterWhisperAdapter(model_id="base")
    with pytest.raises(RuntimeError,match="explicit allow_model_download"):
        adapter.transcribe_chunk(audio,language="en")
    assert adapter.configuration["allow_model_download"] is False

def test_faster_whisper_defaults_preserve_quiet_lecture_speech() -> None:
    adapter = FasterWhisperAdapter()
    assert adapter.configuration["vad_filter"] is False
    assert adapter.configuration["beam_size"] == 5
    explicit = FasterWhisperAdapter(vad_filter=True,beam_size=3)
    assert explicit.configuration["vad_filter"] is True
    assert explicit.configuration["beam_size"] == 3
    with pytest.raises(ValueError,match="beam_size"):
        FasterWhisperAdapter(beam_size=0)
    with pytest.raises(RuntimeError,match="local CTranslate2 directory"):
        adapter.transcribe_chunk(Path("unused.wav"),language="en")

def test_transcription_applies_extracted_stream_offset_to_source_timestamps(tmp_path: Path) -> None:
    database,assets,imported = _import_audio(tmp_path,seconds=5)
    result = run_wav_transcription(
        database,assets,imported.source_id,imported.asset.id,FakeAdapter(),
        language="en",chunk_seconds=2,time_offset_ms=250,
    )
    assert result.duration_ms == 5_000
    assert result.time_offset_ms == 250
    from omniintel.store import OmniIntelStore
    segments = OmniIntelStore(database).get_transcript(imported.source_id)
    assert [row["start_ms"] for row in segments] == [350,2350,4350]
    assert [row["end_ms"] for row in segments] == [1050,3050,5050]
    reference = get_evidence_reference(database,result.evidence_ref_ids[1])
    assert reference is not None
    assert reference["start_ms"] == 2350


def test_transcription_rejects_negative_or_out_of_source_timeline_offsets(tmp_path: Path) -> None:
    database,assets,imported = _import_audio(tmp_path,seconds=5)
    with pytest.raises(ValueError,match="non-negative integer"):
        run_wav_transcription(
            database,assets,imported.source_id,imported.asset.id,FakeAdapter(),
            time_offset_ms=-1,
        )
    from omniintel.database import connect
    with connect(database) as conn:
        conn.execute(
            "UPDATE sources SET duration_ms=5000 WHERE id=?",(imported.source_id,)
        )
    with pytest.raises(ValueError,match="extends beyond the registered source timeline"):
        run_wav_transcription(
            database,assets,imported.source_id,imported.asset.id,FakeAdapter(),
            time_offset_ms=2000,
        )

