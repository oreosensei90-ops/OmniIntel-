from pathlib import Path

import pytest

from omniintel.cli import main
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore
from omniintel.textbook import BlockInput, TextbookStore


def test_audit_textbook_cli_reports_blocked_version(tmp_path: Path, monkeypatch, capsys) -> None:
    path = tmp_path / "cli.db"
    imported = OmniIntelStore(path).import_transcript(TranscriptImport(
        title="CLI fixture",
        segments=(TranscriptSegmentInput("Evidence.", 0, 1_000),),
        duration_ms=1_000,
    ))
    store = TextbookStore(path)
    textbook_id = store.create_textbook(imported.source_id, "CLI fixture")
    version_id = store.create_version(textbook_id, "Draft")
    chapter_id = store.add_chapter(version_id, "Chapter", ordinal=0)
    store.add_block(chapter_id, BlockInput(
        "PARAGRAPH", {"text": "Pending review."}, "EXPLANATION",
        review_status="NEEDS_REVIEW",
    ))

    monkeypatch.setattr(
        "sys.argv", ["omniintel", "audit-textbook", str(path), version_id]
    )
    with pytest.raises(SystemExit, match="1"):
        main()

    output = capsys.readouterr().out
    assert '"ready": false' in output
    assert "BLOCK_NOT_ACCEPTED" in output
