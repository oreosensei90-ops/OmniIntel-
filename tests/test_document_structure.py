from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from omniintel.document_pdf import extract_pdf
from omniintel.document_structure import (
    extract_document_structure,
    list_document_elements,
    review_document_element,
    search_document_elements,
)
from omniintel.evidence_refs import search_evidence_references
from omniintel.knowledge import ClaimEvidenceReferenceInput, ClaimInput
from omniintel.knowledge_store import KnowledgeStore
from omniintel.local_files import import_local_file
from omniintel.textbook import TextbookStore
from omniintel.textbook_audit import TextbookPublicationAuditor
from omniintel.topics import DocumentTopicEvidenceInput, DocumentTopicInput, TopicStore


def _make_structured_pdf(path: Path) -> None:
    image_path = path.with_suffix(".png")
    image = Image.new("RGB",(100,60),"white")
    for x in range(10,90):
        image.putpixel((x,30),(0,0,0))
    image.save(image_path)

    output = canvas.Canvas(str(path),pagesize=(612,792))
    output.setFont("Helvetica-Bold",20)
    output.drawString(72,740,"Conservation of Momentum")
    output.setFont("Helvetica",10)
    output.drawString(72,710,"An isolated system conserves its total momentum.")
    output.setFont("Helvetica",12)
    output.drawString(72,675,"p_initial = p_final")
    x0,y0,x1,y1=72,560,360,640
    output.setLineWidth(1)
    for x in (x0,168,264,x1):
        output.line(x,y0,x,y1)
    for y in (y0,600,y1):
        output.line(x0,y,x1,y)
    output.setFont("Helvetica",9)
    output.drawString(80,615,"Object")
    output.drawString(176,615,"Mass")
    output.drawString(272,615,"Velocity")
    output.drawString(80,575,"Cart A")
    output.drawString(176,575,"2 kg")
    output.drawString(272,575,"3 m/s")
    output.drawImage(ImageReader(str(image_path)),400,560,width=100,height=60)
    output.showPage()
    output.save()


def test_document_structure_extracts_elements_and_composes_reviewed_textbook(tmp_path: Path) -> None:
    pdf = tmp_path / "structured.pdf"
    _make_structured_pdf(pdf)
    database = tmp_path / "structure.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database,assets,pdf,title="Momentum lesson")
    extracted = extract_pdf(database,assets,imported.asset.id)
    result = extract_document_structure(database,assets,imported.asset.id)

    kinds = {item.element_type for item in result.elements}
    assert {"HEADING","PARAGRAPH","EQUATION","TABLE","FIGURE"} <= kinds
    assert result.element_count == len(result.elements)
    assert search_document_elements(database,"Conservation Momentum")
    assert search_evidence_references(database,"Velocity mass")[0]["page_number"] == 1

    figure = next(item for item in result.elements if item.element_type == "FIGURE")
    assert figure.asset_id
    assert any(asset.id == figure.asset_id for asset in __import__(
        "omniintel.assets",fromlist=["AssetStore"]
    ).AssetStore(database,assets).list_source_assets(imported.source_id))

    paragraph = next(
        item for item in result.elements
        if item.element_type == "PARAGRAPH" and "isolated system" in item.text_content
    )
    assert review_document_element(database,paragraph.id,"ACCEPTED") == "ACCEPTED"

    knowledge = KnowledgeStore(database)
    claim = knowledge.create_claim(ClaimInput(
        "An isolated system conserves its total momentum."
    ))
    claim_link = knowledge.link_evidence_reference(ClaimEvidenceReferenceInput(
        claim,paragraph.evidence_ref_id,"SUPPORTS",0.99,
        element_id=paragraph.id,
    ))
    assert knowledge.review_evidence_reference_link(claim_link,"ACCEPTED") == "SUPPORTED"

    topics = TopicStore(database)
    topic = topics.create_document_topic(
        DocumentTopicInput(imported.source_id,"Conservation of momentum",0)
    )
    topic_link = topics.link_document_evidence(DocumentTopicEvidenceInput(
        topic,paragraph.evidence_ref_id,"INTRODUCES",0.99,
        element_id=paragraph.id,
    ))
    assert topics.review_document_evidence_link(topic_link,"ACCEPTED") == "ACCEPTED"

    textbooks = TextbookStore(database)
    version = textbooks.compose_from_accepted_document_topics(
        imported.source_id,"Momentum textbook"
    )
    report = TextbookPublicationAuditor(database).audit(version)
    assert report.ready
    block = textbooks.get_version_tree(version)["chapters"][0]["blocks"][0]
    assert block["evidence_references"][0]["element_id"] == paragraph.id
    assert block["evidence_references"][0]["element_type"] == "PARAGRAPH"

    review_document_element(database,paragraph.id,"NEEDS_REVIEW")
    blocked = TextbookPublicationAuditor(database).audit(version)
    assert not blocked.ready
    assert any(item.code == "EVIDENCE_ELEMENT_NOT_ACCEPTED" for item in blocked.findings)


def test_document_structure_requires_existing_page_extraction(tmp_path: Path) -> None:
    pdf = tmp_path / "unextracted.pdf"
    output = canvas.Canvas(str(pdf))
    output.drawString(72,720,"Unextracted")
    output.showPage()
    output.save()
    database = tmp_path / "structure.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database,assets,pdf)
    import pytest
    with pytest.raises(ValueError,match="extract-pdf"):
        extract_document_structure(database,assets,imported.asset.id)
