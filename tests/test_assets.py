from pathlib import Path

import pytest

from omniintel.assets import AssetStore
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore


PNG = b"\\x89PNG\\r\\n\\x1a\\n" + b"test-image-payload"


def _source(path: Path) -> str:
    return OmniIntelStore(path).import_transcript(TranscriptImport(
        title="Asset source",
        segments=(TranscriptSegmentInput("A source segment.", 0, 1_000),),
    )).source_id


def test_asset_store_hashes_deduplicates_and_resolves_content(tmp_path: Path) -> None:
    db = tmp_path / "omniintel.db"
    source = _source(db)
    store = AssetStore(db, tmp_path / "assets")
    first = store.add_bytes(source, PNG, role="FRAME", display_name="../../frame.png")
    second = store.add_bytes(source, PNG, role="FRAME", display_name="other.png")
    assert first.id == second.id
    assert first.sha256 == second.sha256
    assert first.media_type == "image/png"
    assert first.display_name == "frame.png"
    resolved = store.resolve_path(first.id)
    assert resolved.read_bytes() == PNG
    assert len(store.list_source_assets(source)) == 1


def test_same_blob_can_have_distinct_roles_and_sources(tmp_path: Path) -> None:
    db = tmp_path / "omniintel.db"
    source_a = _source(db)
    source_b = _source(db)
    store = AssetStore(db, tmp_path / "assets")
    a = store.add_bytes(source_a, PNG, role="FRAME")
    b = store.add_bytes(source_a, PNG, role="SLIDE")
    c = store.add_bytes(source_b, PNG, role="FRAME")
    assert len({a.id, b.id, c.id}) == 3
    assert a.sha256 == b.sha256 == c.sha256
    assert len(list((tmp_path / "assets").glob("*/*/*"))) == 1


def test_asset_store_rejects_unknown_empty_and_oversized_content(tmp_path: Path) -> None:
    db = tmp_path / "omniintel.db"
    source = _source(db)
    store = AssetStore(db, tmp_path / "assets", max_bytes=32)
    with pytest.raises(ValueError, match="unrecognized"):
        store.add_bytes(source, b"\\x00\\x01\\x02", role="ATTACHMENT")
    with pytest.raises(ValueError, match="Empty"):
        store.add_bytes(source, b"")
    with pytest.raises(ValueError, match="maximum size"):
        store.add_bytes(source, PNG + b"x" * 100)


def test_asset_store_rejects_unknown_source_and_unsafe_role(tmp_path: Path) -> None:
    db = tmp_path / "omniintel.db"
    store = AssetStore(db, tmp_path / "assets")
    with pytest.raises(ValueError, match="Source does not exist"):
        store.add_bytes("missing", PNG)
    source = _source(db)
    with pytest.raises(ValueError, match="Unsupported asset role"):
        store.add_bytes(source, PNG, role="EXECUTABLE")


def test_asset_store_detects_post_ingest_corruption(tmp_path: Path) -> None:
    db = tmp_path / "omniintel.db"
    source = _source(db)
    store = AssetStore(db, tmp_path / "assets")
    asset = store.add_bytes(source, PNG, role="THUMBNAIL")
    path = store.resolve_path(asset.id)
    path.write_bytes(b"corrupted")
    with pytest.raises(RuntimeError, match="size does not match"):
        store.resolve_path(asset.id)
