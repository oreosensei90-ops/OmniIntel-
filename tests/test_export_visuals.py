from __future__ import annotations

import base64
from pathlib import Path

import pytest

from omniintel.assets import AssetStore
from omniintel.export_visuals import evidence_locator_label
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore
from omniintel.textbook import BlockInput, TextbookStore

PNG=base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ9sAAAAASUVORK5CYII="
)


def _image_book(tmp_path: Path) -> tuple[Path,Path,str]:
    database=tmp_path/"book.db"
    asset_dir=tmp_path/"assets"
    source=OmniIntelStore(database).import_transcript(TranscriptImport(
        title="Visual source",
        segments=(TranscriptSegmentInput("A visual source.",0,1000),),
        duration_ms=1000,
    ))
    asset=AssetStore(database,asset_dir).add_bytes(
        source.source_id,PNG,role="DIAGRAM",display_name="pixel.png",
    )
    store=TextbookStore(database)
    book=store.create_textbook(source.source_id,"Visual book")
    version=store.create_version(book,"Edition 1")
    chapter=store.add_chapter(version,"Figures",ordinal=0)
    block=store.add_block(chapter,BlockInput(
        "IMAGE",{"alt":"A tiny test image"},"EXPLANATION",review_status="ACCEPTED",
    ))
    store.link_asset(block,asset.id,caption="Pixel sample")
    return database,asset_dir,version


def test_evidence_locator_labels_document_pages_without_fake_timestamps() -> None:
    assert evidence_locator_label({"locator_kind":"DOCUMENT_PAGE","page_number":7})=="PDF page 7"
    assert evidence_locator_label({"locator_kind":"TRANSCRIPT_INTERVAL","start_ms":1250,"end_ms":2500})=="1.2–2.5s"


def test_pdf_export_embeds_linked_visual_asset(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    from omniintel.pdf_export import TextbookPDFExporter
    database,asset_dir,version=_image_book(tmp_path)
    output=TextbookPDFExporter(database).export(
        version,tmp_path/"book.pdf",asset_dir=asset_dir,
    )
    assert b"/Subtype /Image" in output.read_bytes()


def test_docx_export_embeds_linked_visual_asset(tmp_path: Path) -> None:
    docx=pytest.importorskip("docx")
    from omniintel.docx_export import TextbookDOCXExporter
    database,asset_dir,version=_image_book(tmp_path)
    output=TextbookDOCXExporter(database).export(
        version,tmp_path/"book.docx",asset_dir=asset_dir,
    )
    assert len(docx.Document(output).inline_shapes)==1


def test_html_export_embeds_linked_visual_asset_as_data_uri(tmp_path: Path) -> None:
    from omniintel.html_export import TextbookHTMLExporter
    database,asset_dir,version=_image_book(tmp_path)
    output=TextbookHTMLExporter(database).export(
        version,tmp_path/"book.html",asset_dir=asset_dir,
    )
    html=output.read_text(encoding="utf-8")
    assert "data:image/png;base64," in html
    assert "Pixel sample" in html


def test_markdown_export_copies_linked_visual_asset(tmp_path: Path) -> None:
    from omniintel.markdown_export import TextbookMarkdownExporter
    database,asset_dir,version=_image_book(tmp_path)
    output=TextbookMarkdownExporter(database).export(
        version,tmp_path/"book.md",asset_dir=asset_dir,
    )
    markdown=output.read_text(encoding="utf-8")
    assert "![Pixel sample](book.assets/" in markdown
    assert list((tmp_path/"book.assets").glob("*.png"))


def test_image_export_requires_asset_store_directory(tmp_path: Path) -> None:
    from omniintel.html_export import TextbookHTMLExporter
    database,_asset_dir,version=_image_book(tmp_path)
    with pytest.raises(ValueError,match="supply asset_dir"):
        TextbookHTMLExporter(database).export(version,tmp_path/"book.html")


def test_all_exporters_render_pdf_page_citations(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader

    from omniintel.document_pdf import extract_pdf
    from omniintel.local_files import import_local_file
    from omniintel.docx_export import TextbookDOCXExporter
    from omniintel.html_export import TextbookHTMLExporter
    from omniintel.markdown_export import TextbookMarkdownExporter
    from omniintel.pdf_export import TextbookPDFExporter

    source_pdf=tmp_path/"source.pdf"
    page=canvas.Canvas(str(source_pdf))
    page.drawString(72,720,"A page-cited source statement.")
    page.showPage()
    page.save()
    database=tmp_path/"citations.db"
    asset_dir=tmp_path/"source-assets"
    imported=import_local_file(database,asset_dir,source_pdf,title="Page source")
    extraction=extract_pdf(database,asset_dir,imported.asset.id)
    reference=extraction.evidence_ref_ids[0]
    store=TextbookStore(database)
    textbook=store.create_textbook(imported.source_id,"Page-cited textbook")
    version=store.create_version(textbook,"Edition 1")
    chapter=store.add_chapter(version,"Chapter",ordinal=0)
    block=store.add_block(chapter,BlockInput(
        "PARAGRAPH",{"text":"A grounded explanation."},"EXPLANATION",
        review_status="ACCEPTED",
    ))
    store.link_evidence_reference(
        block,reference,relation="SUPPORTS",review_state="ACCEPTED",
    )

    pdf=TextbookPDFExporter(database).export(version,tmp_path/"out.pdf",asset_dir=asset_dir)
    docx_path=TextbookDOCXExporter(database).export(version,tmp_path/"out.docx",asset_dir=asset_dir)
    html=TextbookHTMLExporter(database).export(version,tmp_path/"out.html",asset_dir=asset_dir)
    markdown=TextbookMarkdownExporter(database).export(version,tmp_path/"out.md",asset_dir=asset_dir)

    assert "PDF page 1" in "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages)
    import docx as docx_module
    docx_text="\n".join(p.text for p in docx_module.Document(docx_path).paragraphs)
    assert "PDF page 1" in docx_text
    assert "PDF page 1" in html.read_text(encoding="utf-8")
    assert "PDF page 1" in markdown.read_text(encoding="utf-8")
