import sqlite3
from pathlib import Path

import pytest

from omniintel.database import MIGRATIONS, MigrationError, connect, migrate
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore
from omniintel.evidence_refs import get_evidence_reference


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
    assert len(result.evidence_ref_ids) == 2
    reference = get_evidence_reference(store.database_path, result.evidence_ref_ids[0])
    assert reference is not None
    assert reference["locator_kind"] == "TRANSCRIPT_INTERVAL"
    assert reference["start_ms"] == 0 and reference["end_ms"] == 3_000
    assert reference["content"] == "Motion describes change in position."


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
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(MIGRATIONS)


def test_applied_migration_cannot_be_changed(tmp_path: Path) -> None:
    with connect(tmp_path / "db.sqlite") as conn:
        migrate(conn, (("0001", "CREATE TABLE sample(id INTEGER);"),))
        with pytest.raises(MigrationError):
            migrate(conn, (("0001", "CREATE TABLE sample(id TEXT);"),))



def test_failed_migration_rolls_back_ddl_and_ledger(tmp_path: Path):
    path = tmp_path / "rollback.db"
    conn = connect(path)
    with pytest.raises(sqlite3.OperationalError):
        migrate(
            conn,
            (("broken_migration", "CREATE TABLE should_rollback(id TEXT); INSERT INTO missing_table VALUES('x');"),),
        )
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='should_rollback'"
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM schema_migrations WHERE name='broken_migration'"
    ).fetchone() is None
    conn.close()
