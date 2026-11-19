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

def test_search_and_resolve_evidence_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    from omniintel.models import TranscriptImport, TranscriptSegmentInput

    path = tmp_path / "evidence.db"
    imported = OmniIntelStore(path).import_transcript(TranscriptImport(
        title="CLI evidence",
        segments=(TranscriptSegmentInput("Acceleration changes velocity.", 100, 900),),
        duration_ms=1_000,
    ))
    monkeypatch.setattr(
        "sys.argv", ["omniintel", "search-evidence", str(path), "Acceleration velocity"]
    )
    main()
    search = capsys.readouterr().out
    assert imported.evidence_ref_ids[0] in search
    assert "TRANSCRIPT_INTERVAL" in search

    monkeypatch.setattr(
        "sys.argv", ["omniintel", "resolve-evidence", str(path), imported.evidence_ref_ids[0]]
    )
    main()
    resolved = capsys.readouterr().out
    assert '"start_ms": 100' in resolved
    assert '"end_ms": 900' in resolved

