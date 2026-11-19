from pathlib import Path

import pytest

from omniintel.local_files import import_local_file

PDF = b"%PDF-1.7\n% minimal test fixture\n"
PNG = b"\x89PNG\r\n\x1a\nfixture"


def test_import_local_pdf_registers_source_and_original_asset(tmp_path: Path) -> None:
    source_file = tmp_path / "lecture.pdf"
    source_file.write_bytes(PDF)
    result = import_local_file(
        tmp_path / "omniintel.db", tmp_path / "assets", source_file
    )
    assert result.modality == "DOCUMENT"
    assert result.asset.media_type == "application/pdf"
    assert result.asset.role == "DOCUMENT"
    assert result.asset.byte_size == len(PDF)
    assert result.asset.sha256
    assert result.title == "lecture"
    with __import__("sqlite3").connect(tmp_path / "omniintel.db") as conn:
        row = conn.execute(
            "SELECT title,metadata_json FROM sources WHERE id=?", (result.source_id,)
        ).fetchone()
    assert row[0] == "lecture"
    assert '"rights_status": "UNVERIFIED"' in row[1]


def test_import_local_image_keeps_original_bytes_and_safe_name(tmp_path: Path) -> None:
    source_file = tmp_path / "slide.png"
    source_file.write_bytes(PNG)
    result = import_local_file(
        tmp_path / "omniintel.db", tmp_path / "assets", source_file,
        title="Slide source",
    )
    assert result.modality == "IMAGE"
    assert result.asset.role == "ATTACHMENT"
    assert result.asset.display_name == "slide.png"


def test_import_local_file_rejects_archive_and_oversized_input(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.zip"
    archive.write_bytes(b"PK\x03\x04" + b"payload")
    with pytest.raises(ValueError, match="does not support"):
        import_local_file(tmp_path / "omniintel.db", tmp_path / "assets", archive)

    pdf = tmp_path / "large.pdf"
    pdf.write_bytes(PDF + b"x" * 20)
    with pytest.raises(ValueError, match="maximum size"):
        import_local_file(
            tmp_path / "other.db", tmp_path / "other-assets", pdf, max_bytes=10
        )


def test_import_local_file_does_not_leave_source_after_asset_failure(tmp_path: Path) -> None:
    source_file = tmp_path / "bad.pdf"
    source_file.write_bytes(b"%PDF-1.7\n")
    db = tmp_path / "omniintel.db"
    # The path is intentionally occupied by a regular file, preventing asset-store setup.
    assets = tmp_path / "assets"
    assets.write_text("not a directory")
    with pytest.raises((FileExistsError, NotADirectoryError, OSError)):
        import_local_file(db, assets, source_file)
    with __import__("sqlite3").connect(db) as conn:
        count = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
    assert count == 0


def test_reserved_source_registration_is_retry_safe(tmp_path: Path) -> None:
    from omniintel.ids import uuid7

    path=tmp_path/"retry.pdf"
    path.write_bytes(PDF)
    db=tmp_path/"retry.db"
    reserved=uuid7()
    first=import_local_file(db,tmp_path/"assets",path,source_id=reserved)
    second=import_local_file(db,tmp_path/"assets",path,source_id=reserved)
    assert first.source_id==second.source_id==reserved
    assert first.asset.id==second.asset.id
