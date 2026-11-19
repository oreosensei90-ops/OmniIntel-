from pathlib import Path

import pytest

from omniintel.assets import AssetStore
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore
from omniintel.textbook import BlockInput, TextbookStore
from omniintel.textbook_audit import TextbookPublicationAuditor


PNG = b"\x89PNG\r\n\x1a\n" + b"visual-payload"
MP3 = b"ID3" + b"audio-payload"


def _source(db: Path, title: str = "Visual source") -> str:
    return OmniIntelStore(db).import_transcript(TranscriptImport(
        title=title,
        segments=(TranscriptSegmentInput("A source statement.", 0, 1_000),),
    )).source_id


def _image_block(db: Path, source_id: str, block_type: str = "IMAGE"):
    store = TextbookStore(db)
    textbook = store.create_textbook(source_id, "Visual textbook")
    version = store.create_version(textbook, "Draft")
    chapter = store.add_chapter(version, "Visuals", ordinal=0)
    block = store.add_block(chapter, BlockInput(
        block_type, {"alt": "A simple visual"}, "EXPLANATION", review_status="ACCEPTED"
    ))
    return store, version, block


def test_visual_block_requires_linked_image_asset_for_publication(tmp_path: Path) -> None:
    db = tmp_path / "visual.db"
    source = _source(db)
    _, version, _ = _image_block(db, source)
    report = TextbookPublicationAuditor(db).audit(version)
    assert not report.ready
    assert any(item.code == "MISSING_VISUAL_ASSET" for item in report.findings)


def test_visual_asset_link_is_persisted_in_textbook_tree_and_audit(tmp_path: Path) -> None:
    db = tmp_path / "visual.db"
    source = _source(db)
    store, version, block = _image_block(db, source, "DIAGRAM")
    asset_store = AssetStore(db, tmp_path / "assets")
    asset = asset_store.add_bytes(source, PNG, role="DIAGRAM", display_name="diagram.png")
    store.link_asset(block, asset.id, caption="Velocity vector")
    tree = store.get_version_tree(version)
    assert tree is not None
    visual = tree["chapters"][0]["blocks"][0]["assets"][0]
    assert visual["asset_id"] == asset.id
    assert visual["sha256"] == asset.sha256
    assert visual["media_type"] == "image/png"
    assert visual["caption"] == "Velocity vector"
    assert TextbookPublicationAuditor(db).audit(version).ready


def test_visual_asset_link_rejects_cross_source_and_non_image_assets(tmp_path: Path) -> None:
    db = tmp_path / "visual.db"
    source_a = _source(db, "Source A")
    source_b = _source(db, "Source B")
    store, _, block = _image_block(db, source_a)
    assets = AssetStore(db, tmp_path / "assets")
    foreign = assets.add_bytes(source_b, PNG, role="FRAME")
    audio = assets.add_bytes(source_a, MP3, role="AUDIO")
    with pytest.raises(Exception, match="same source"):
        store.link_asset(block, foreign.id)
    with pytest.raises(Exception, match="compatible image"):
        store.link_asset(block, audio.id)


def test_non_visual_block_cannot_receive_asset_link(tmp_path: Path) -> None:
    db = tmp_path / "visual.db"
    source = _source(db)
    store = TextbookStore(db)
    textbook = store.create_textbook(source, "Textbook")
    version = store.create_version(textbook, "Draft")
    chapter = store.add_chapter(version, "Text", ordinal=0)
    block = store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "No visual here."}, "EXPLANATION"
    ))
    asset = AssetStore(db, tmp_path / "assets").add_bytes(source, PNG, role="FRAME")
    with pytest.raises(ValueError, match="only be attached"):
        store.link_asset(block, asset.id)


def test_visual_asset_ordinals_are_unique_per_block(tmp_path: Path) -> None:
    db = tmp_path / "visual.db"
    source = _source(db)
    store, _, block = _image_block(db, source)
    assets = AssetStore(db, tmp_path / "assets")
    first = assets.add_bytes(source, PNG, role="FRAME")
    second = assets.add_bytes(source, PNG + b"2", role="SLIDE")
    store.link_asset(block, first.id, ordinal=0)
    with pytest.raises(Exception, match="UNIQUE"):
        store.link_asset(block, second.id, ordinal=0)
