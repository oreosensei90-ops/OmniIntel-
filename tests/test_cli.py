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

def test_document_structure_and_knowledge_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    import json
    from reportlab.pdfgen import canvas

    from omniintel.document_pdf import extract_pdf
    from omniintel.local_files import import_local_file

    pdf = tmp_path / "cli-document.pdf"
    output = canvas.Canvas(str(pdf))
    output.setFont("Helvetica",10)
    output.drawString(72,720,"A conserved quantity remains constant in an isolated system.")
    output.showPage()
    output.save()
    database = tmp_path / "document-cli.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database,assets,pdf,title="CLI document")
    extract_pdf(database,assets,imported.asset.id)

    monkeypatch.setattr(
        "sys.argv",
        ["omniintel","structure-pdf",str(database),str(assets),imported.asset.id],
    )
    main()
    structure = json.loads(capsys.readouterr().out)
    assert structure["elements"] >= 1
    element_id = structure["element_ids"][0]

    monkeypatch.setattr(
        "sys.argv",
        ["omniintel","review-document-element",str(database),element_id,"ACCEPTED"],
    )
    main()
    assert '"review_state": "ACCEPTED"' in capsys.readouterr().out

    monkeypatch.setattr(
        "sys.argv",["omniintel","build-document-knowledge",str(database),imported.source_id]
    )
    main()
    candidates = json.loads(capsys.readouterr().out)
    assert candidates["created_or_reused"] == 1
    assert candidates["candidate_units"]
    unit_id = candidates["candidate_units"][0]
    from omniintel.knowledge_store import KnowledgeStore
    bundle = KnowledgeStore(database).get_unit_bundle(unit_id)
    KnowledgeStore(database).review_unit_evidence_reference(
        bundle["evidence_references"][0]["link_id"],"ACCEPTED"
    )
    monkeypatch.setattr(
        "sys.argv",
        ["omniintel","review-knowledge-unit",str(database),unit_id,"VALIDATED",
         "--provenance","DERIVED"],
    )
    main()
    assert '"status": "VALIDATED"' in capsys.readouterr().out


def test_review_ocr_page_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    from reportlab.pdfgen import canvas

    from omniintel.document_ocr import OCRResult, OCRWord, ocr_pdf
    from omniintel.document_pdf import extract_pdf
    from omniintel.local_files import import_local_file

    class FakeOCR:
        name = "cli-fake"
        version = "1"

        def recognize_png(self, png_bytes: bytes, *, timeout_seconds: int) -> OCRResult:
            return OCRResult(
                "A scanned source statement.",
                (OCRWord("A",0.1,0.1,0.2,0.2,95.0),),
                95.0,
            )

    pdf = tmp_path / "cli-scan.pdf"
    output = canvas.Canvas(str(pdf))
    output.showPage()
    output.save()
    database = tmp_path / "ocr-cli.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database,assets,pdf)
    extract_pdf(database,assets,imported.asset.id)
    result = ocr_pdf(database,assets,imported.asset.id,adapter=FakeOCR())
    page_id = result.pages[0].page_id

    monkeypatch.setattr(
        "sys.argv",["omniintel","review-ocr-page",str(database),page_id,"ACCEPTED"]
    )
    main()
    assert '"status": "ACCEPTED"' in capsys.readouterr().out

