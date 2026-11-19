import sqlite3
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from omniintel.assets import AssetStore
from omniintel.database import connect
from omniintel.document_pdf import extract_pdf, list_extracted_pages
from omniintel.evidence_refs import get_evidence_reference, search_evidence_references
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
    assert len(result.evidence_ref_ids) == 2
    reference = get_evidence_reference(database, result.evidence_ref_ids[1])
    assert reference is not None
    assert reference["locator_kind"] == "DOCUMENT_PAGE"
    assert reference["page_number"] == 2
    assert reference["start_ms"] is None and reference["end_ms"] is None
    assert reference["content"] == result.pages[1].text
    assert reference["source_asset_id"] == asset_id
    assert search_evidence_references(database, "Second page text")[0]["page_number"] == 2


def test_extract_pdf_rerun_is_idempotent_for_parser_version(tmp_path: Path) -> None:
    database, assets, asset_id = ingest_pdf(tmp_path, ["Stable content"])
    first = extract_pdf(database, assets, asset_id)
    second = extract_pdf(database, assets, asset_id)
    assert first.extraction_id == second.extraction_id
    assert first.pages[0].id == second.pages[0].id
    assert first.evidence_ref_ids == second.evidence_ref_ids
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

def test_search_document_pages_returns_page_level_source_provenance(
    tmp_path: Path,
) -> None:
    database, assets, asset_id = ingest_pdf(
        tmp_path, ["Quantum entanglement connects distant measurements", "Classical mechanics"]
    )
    extraction = extract_pdf(database, assets, asset_id)
    from omniintel.document_pdf import search_document_pages

    results = search_document_pages(database, "quantum (entanglement)")
    assert len(results) == 1
    assert results[0]["source_id"] == extraction.source_id
    assert results[0]["asset_id"] == asset_id
    assert results[0]["page_id"] == extraction.pages[0].id
    assert results[0]["page_number"] == 1
    assert "Quantum" in results[0]["excerpt"]


def test_document_page_search_index_tracks_page_deletion(tmp_path: Path) -> None:
    database, assets, asset_id = ingest_pdf(tmp_path, ["Unique searchable phrase"])
    extraction = extract_pdf(database, assets, asset_id)
    from omniintel.document_pdf import search_document_pages

    assert search_document_pages(database, "Unique searchable")
    with connect(database) as conn:
        conn.execute("DELETE FROM document_pages WHERE id=?", (extraction.pages[0].id,))
    assert search_document_pages(database, "Unique searchable") == []


def test_document_page_search_handles_empty_and_invalid_limits(tmp_path: Path) -> None:
    database, _, _ = ingest_pdf(tmp_path, ["Any page"])
    from omniintel.document_pdf import search_document_pages

    assert search_document_pages(database, "   ") == []
    with pytest.raises(ValueError, match="between 1 and 100"):
        search_document_pages(database, "page", limit=101)



def test_evidence_reference_rejects_cross_source_page_locator(tmp_path: Path) -> None:
    database, assets, asset_id = ingest_pdf(tmp_path, ["Source A page"])
    result = extract_pdf(database, assets, asset_id)
    other = import_local_file(
        database, assets, tmp_path / "source.pdf", title="Second source"
    )
    with connect(database) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="document page reference"):
            conn.execute(
                """INSERT INTO evidence_refs
                   (id,source_id,locator_kind,document_page_id,source_asset_id,page_number,created_at)
                   VALUES('bad-reference',?,'DOCUMENT_PAGE',?,?,1,'2026-01-01T00:00:00Z')""",
                (other.source_id,result.pages[0].id,asset_id),
            )
