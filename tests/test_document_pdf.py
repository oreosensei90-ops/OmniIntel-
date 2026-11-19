from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from omniintel.assets import AssetStore
from omniintel.database import connect
from omniintel.document_pdf import extract_pdf, list_extracted_pages
from omniintel.local_files import import_local_file


def make_pdf(path: Path, pages: list[str]) -> None:
    output = canvas.Canvas(str(path))
    for text in pages:
        output.drawString(72, 720, text)
        output.showPage()
    output.save()


def ingest_pdf(tmp_path: Path, pages: list[str]) -> tuple[Path, Path, str]:
    pdf = tmp_path / "source.pdf"
    make_pdf(pdf, pages)
    database = tmp_path / "omniintel.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database, assets, pdf)
    return database, assets, imported.asset.id


def test_extract_pdf_preserves_page_numbers_and_hashes(tmp_path: Path) -> None:
    database, assets, asset_id = ingest_pdf(tmp_path, ["First page text", "Second page text"])
    result = extract_pdf(database, assets, asset_id)
    assert result.page_count == 2
    assert result.extracted_pages == 2
    assert result.empty_pages == 0
    assert [page.page_number for page in result.pages] == [1, 2]
    assert "First page text" in result.pages[0].text
    assert "Second page text" in result.pages[1].text
    assert all(len(page.content_sha256) == 64 for page in result.pages)
    assert list_extracted_pages(database, result.extraction_id) == result.pages


def test_extract_pdf_rerun_is_idempotent_for_parser_version(tmp_path: Path) -> None:
    database, assets, asset_id = ingest_pdf(tmp_path, ["Stable content"])
    first = extract_pdf(database, assets, asset_id)
    second = extract_pdf(database, assets, asset_id)
    assert first.extraction_id == second.extraction_id
    assert first.pages[0].id != second.pages[0].id
    assert list_extracted_pages(database, second.extraction_id) == second.pages
    with connect(database) as conn:
        count = conn.execute(
            "SELECT count(*) FROM document_extractions WHERE source_asset_id=?",
            (asset_id,),
        ).fetchone()[0]
    assert count == 1


def test_extract_pdf_enforces_page_and_character_limits(tmp_path: Path) -> None:
    database, assets, asset_id = ingest_pdf(tmp_path, ["Page one", "Page two"])
    with pytest.raises(ValueError, match="page count"):
        extract_pdf(database, assets, asset_id, max_pages=1)
    with pytest.raises(ValueError, match="character limit"):
        extract_pdf(database, assets, asset_id, max_chars_per_page=3)


def test_extract_pdf_rejects_non_pdf_asset(tmp_path: Path) -> None:
    text_file = tmp_path / "notes.txt"
    text_file.write_text("not a PDF", encoding="utf-8")
    imported = import_local_file(
        tmp_path / "omniintel.db", tmp_path / "assets", text_file
    )
    with pytest.raises(ValueError, match="not a PDF"):
        extract_pdf(tmp_path / "omniintel.db", tmp_path / "assets", imported.asset.id)


def test_extract_pdf_rejects_encrypted_pdf(tmp_path: Path) -> None:
    database, assets, asset_id = ingest_pdf(tmp_path, ["Secret page"])
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(AssetStore(database, assets).resolve_path(asset_id)))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt("secret")
    encrypted_path = tmp_path / "encrypted.pdf"
    with encrypted_path.open("wb") as handle:
        writer.write(handle)
    source = import_local_file(database, assets, encrypted_path)
    with pytest.raises(ValueError, match="Encrypted"):
        extract_pdf(database, assets, source.asset.id)
