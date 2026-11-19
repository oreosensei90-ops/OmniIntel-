from pathlib import Path

import pytest

from omniintel.database import MigrationError, connect, migrate
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore


def sample() -> TranscriptImport:
    return TranscriptImport(
        title="Intro to physics",
        source_uri="imported-transcript://physics-01",
        language="en",
        duration_ms=12_000,
        segments=(
            TranscriptSegmentInput("Motion describes change in position.", 0, 3_000),
            TranscriptSegmentInput("Velocity includes direction.", 3_000, 6_000),
        ),
    )


def test_transcript_import_persists_source_segments_and_evidence(tmp_path: Path) -> None:
    store = OmniIntelStore(tmp_path / "omniintel.db")
    result = store.import_transcript(sample())
    rows = store.get_transcript(result.source_id)
    assert len(rows) == 2
    assert rows[0]["start_ms"] == 0
    assert rows[1]["text"] == "Velocity includes direction."
    assert len(result.evidence_ids) == 2


def test_invalid_timestamp_rejected_before_write(tmp_path: Path) -> None:
    store = OmniIntelStore(tmp_path / "omniintel.db")
    bad = TranscriptImport(
        title="Bad", segments=(TranscriptSegmentInput("bad", 9, 2),), duration_ms=10
    )
    with pytest.raises(ValueError):
        store.import_transcript(bad)
    with connect(tmp_path / "omniintel.db") as conn:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 0


def test_duration_overrun_rejected(tmp_path: Path) -> None:
    bad = TranscriptImport(
        title="Overrun", segments=(TranscriptSegmentInput("late", 0, 11),), duration_ms=10
    )
    with pytest.raises(ValueError, match="exceeds source duration"):
        bad.validate()


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as conn:
        migrate(conn)
        migrate(conn)
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(__import__("omniintel.database", fromlist=["MIGRATIONS"]).MIGRATIONS)


def test_applied_migration_cannot_be_changed(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as conn:
        migrate(conn, (("0001", "CREATE TABLE sample(id INTEGER);"),))
        with pytest.raises(MigrationError):
            migrate(conn, (("0001", "CREATE TABLE sample(id TEXT);"),))
