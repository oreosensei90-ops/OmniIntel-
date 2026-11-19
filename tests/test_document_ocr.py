from pathlib import Path
import sqlite3

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
from omniintel.document_structure import extract_document_structure, review_document_element
from omniintel.document_knowledge import create_knowledge_candidates_from_document_elements
from omniintel.topics import DocumentTopicEvidenceInput, DocumentTopicInput, TopicStore
from omniintel.textbook import TextbookStore
from omniintel.textbook_audit import TextbookPublicationAuditor


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
    with pytest.raises(sqlite3.IntegrityError,match="OCR page must be accepted"):
        knowledge.review_evidence_reference_link(link,"ACCEPTED")

    assert review_ocr_page(database,page.page_id,"ACCEPTED") == "ACCEPTED"
    assert knowledge.review_evidence_reference_link(link,"ACCEPTED") == "SUPPORTED"

    structure = extract_document_structure(database,assets,imported.asset.id)
    assert len(structure.elements) == 2
    element = structure.elements[0]
    with pytest.raises(ValueError,match="cannot be relabelled"):
        review_document_element(
            database,element.id,"ACCEPTED",provenance="SOURCE"
        )
    review_document_element(
        database,element.id,"ACCEPTED",provenance="DERIVED",
        rationale="Checked against the rendered source page",
    )

    candidates = create_knowledge_candidates_from_document_elements(
        database,imported.source_id
    )
    assert len(candidates.candidate_unit_ids) == 1
    unit_id = candidates.candidate_unit_ids[0]
    bundle = knowledge.get_unit_bundle(unit_id)
    knowledge.review_unit_evidence_reference(
        bundle["evidence_references"][0]["link_id"],"ACCEPTED"
    )
    assert knowledge.review_unit(
        unit_id,status="VALIDATED",provenance="DERIVED"
    ) == "VALIDATED"

    claim_from_element = knowledge.create_claim(ClaimInput(
        "Quantum tunnelling is identified in this source.",
        knowledge_unit_id=unit_id,
    ))
    element_link = knowledge.link_evidence_reference(ClaimEvidenceReferenceInput(
        claim_from_element,extracted.evidence_ref_ids[0],"SUPPORTS",0.95,
        element_id=element.id,
    ))
    assert knowledge.review_evidence_reference_link(
        element_link,"ACCEPTED"
    ) == "SUPPORTED"

    topics = TopicStore(database)
    topic = topics.create_document_topic(
        DocumentTopicInput(imported.source_id,"Quantum tunnelling",0)
    )
    topic_link = topics.link_document_evidence(DocumentTopicEvidenceInput(
        topic,extracted.evidence_ref_ids[0],"INTRODUCES",0.98,
        element_id=element.id,
    ))
    assert topics.review_document_evidence_link(topic_link,"ACCEPTED") == "ACCEPTED"

    version = TextbookStore(database).compose_from_accepted_document_topics(
        imported.source_id,"OCR-grounded textbook"
    )
    assert TextbookPublicationAuditor(database).audit(version).ready

    assert review_ocr_page(database,page.page_id,"NEEDS_REVIEW") == "NEEDS_REVIEW"
    assert knowledge.get_claim_bundle(claim)["claim"]["status"] == "DRAFT"
    assert knowledge.get_claim_bundle(claim_from_element)["claim"]["status"] == "DRAFT"
    assert knowledge.get_unit_bundle(unit_id)["unit"]["status"] == "NEEDS_REVIEW"
    assert not TextbookPublicationAuditor(database).audit(version).ready


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

def test_ocr_adapter_geometry_and_text_budgets_are_enforced(tmp_path: Path) -> None:
    pdf = tmp_path / "bounded-scan.pdf"
    _scan_pdf(pdf)
    database = tmp_path / "bounded.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database,assets,pdf)
    extract_pdf(database,assets,imported.asset.id)

    class InvalidGeometryOCR:
        name = "invalid-geometry"
        version = "1"

        def recognize_png(self, png_bytes: bytes, *, timeout_seconds: int) -> OCRResult:
            return OCRResult(
                "bad box",
                (OCRWord("bad",-0.1,0.1,0.2,0.2,90.0),),
                90.0,
            )

    with pytest.raises(ValueError,match="normalized"):
        ocr_pdf(database,assets,imported.asset.id,adapter=InvalidGeometryOCR())

    class OversizedOCR:
        name = "oversized"
        version = "1"

        def recognize_png(self, png_bytes: bytes, *, timeout_seconds: int) -> OCRResult:
            return OCRResult("x" * 11,(),90.0)

    with pytest.raises(ValueError,match="character limit"):
        ocr_pdf(
            database,assets,imported.asset.id,adapter=OversizedOCR(),
            max_chars_per_page=10,
        )
    assert get_ocr_page(database,extract_pdf(database,assets,imported.asset.id).pages[0].id) is None

def test_tesseract_adapter_uses_bounded_tsv_file_and_normalizes_word_boxes(tmp_path: Path) -> None:
    import io
    import sys

    from PIL import Image
    from omniintel.document_ocr import TesseractOCR

    executable = tmp_path / "tesseract-stub"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import pathlib,sys\n"
        "if sys.argv[1] == '--version':\n"
        " print('tesseract stub 1')\n"
        "else:\n"
        " output=pathlib.Path(sys.argv[2] + '.tsv')\n"
        " output.write_text("
        "'level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext\\n'"
        " '1\\t1\\t0\\t0\\t0\\t0\\t0\\t0\\t1000\\t500\\t-1\\t\\n'"
        " '5\\t1\\t1\\t1\\t1\\t1\\t100\\t50\\t200\\t50\\t96\\tHello\\n'"
        ")\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    adapter = TesseractOCR(str(executable))
    png = io.BytesIO()
    Image.new("RGB",(16,16),"white").save(png,format="PNG")
    result = adapter.recognize_png(png.getvalue(),timeout_seconds=5)
    assert result.text == "Hello"
    assert result.words[0].x0 == pytest.approx(0.1)
    assert result.words[0].y0 == pytest.approx(0.1)
    assert result.words[0].x1 == pytest.approx(0.3)
    assert result.words[0].y1 == pytest.approx(0.2)

