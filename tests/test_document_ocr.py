from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from omniintel.document_ocr import (
    OCRResult,
    OCRWord,
    get_ocr_page,
    ocr_pdf,
    review_ocr_page,
)
from omniintel.document_pdf import extract_pdf
from omniintel.evidence_refs import get_evidence_reference, search_evidence_references
from omniintel.knowledge import ClaimEvidenceReferenceInput, ClaimInput
from omniintel.knowledge_store import KnowledgeStore
from omniintel.local_files import import_local_file


class FakeOCR:
    name = "test-ocr"
    version = "1"

    def recognize_png(self, png_bytes: bytes, *, timeout_seconds: int) -> OCRResult:
        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert timeout_seconds > 0
        words = (
            OCRWord("Quantum",0.10,0.20,0.30,0.25,96.0),
            OCRWord("tunnelling",0.32,0.20,0.62,0.25,94.0),
            OCRWord("permits",0.10,0.28,0.30,0.33,95.0),
            OCRWord("barrier",0.32,0.28,0.54,0.33,93.0),
            OCRWord("transmission.",0.56,0.28,0.90,0.33,92.0),
        )
        return OCRResult(
            "Quantum tunnelling permits barrier transmission.",
            words,
            sum(word.confidence for word in words) / len(words),
        )


def _scan_pdf(path: Path) -> None:
    output = canvas.Canvas(str(path), pagesize=(612,792))
    output.showPage()
    output.save()


def test_ocr_page_is_searchable_but_not_publishable_until_reviewed(tmp_path: Path) -> None:
    pdf = tmp_path / "scan.pdf"
    _scan_pdf(pdf)
    database = tmp_path / "ocr.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database,assets,pdf,title="Scanned physics page")
    extracted = extract_pdf(database,assets,imported.asset.id)
    assert extracted.empty_pages == 1

    run = ocr_pdf(database,assets,imported.asset.id,adapter=FakeOCR())
    assert len(run.pages) == 1
    page = run.pages[0]
    assert page.status == "NEEDS_REVIEW"
    assert page.rendered_asset_id
    stored = get_ocr_page(database,page.page_id)
    assert stored is not None
    assert len(stored["words"]) == 5

    reference = get_evidence_reference(database,extracted.evidence_ref_ids[0])
    assert reference is not None
    assert reference["content"] == page.text
    assert reference["provenance"] == "UNCERTAIN"
    assert reference["ocr_status"] == "NEEDS_REVIEW"
    assert search_evidence_references(database,"Quantum tunnelling barrier")[0]["page_number"] == 1

    knowledge = KnowledgeStore(database)
    claim = knowledge.create_claim(ClaimInput("Quantum tunnelling permits barrier transmission."))
    link = knowledge.link_evidence_reference(ClaimEvidenceReferenceInput(
        claim,extracted.evidence_ref_ids[0],"SUPPORTS",0.95,
    ))
    with pytest.raises(Exception,match="OCR page must be accepted"):
        knowledge.review_evidence_reference_link(link,"ACCEPTED")

    assert review_ocr_page(database,page.page_id,"ACCEPTED") == "ACCEPTED"
    assert knowledge.review_evidence_reference_link(link,"ACCEPTED") == "SUPPORTED"
    assert review_ocr_page(database,page.page_id,"NEEDS_REVIEW") == "NEEDS_REVIEW"
    assert knowledge.get_claim_bundle(claim)["claim"]["status"] == "DRAFT"


def test_ocr_skips_native_text_pages_and_validates_limits(tmp_path: Path) -> None:
    pdf = tmp_path / "native.pdf"
    output = canvas.Canvas(str(pdf))
    output.drawString(72,720,"Native searchable text.")
    output.showPage()
    output.save()
    database = tmp_path / "native.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database,assets,pdf)
    extract_pdf(database,assets,imported.asset.id)
    run = ocr_pdf(database,assets,imported.asset.id,adapter=FakeOCR())
    assert run.pages == ()
    assert run.skipped_pages == (1,)
    with pytest.raises(ValueError,match="DPI"):
        ocr_pdf(database,assets,imported.asset.id,adapter=FakeOCR(),dpi=600)
