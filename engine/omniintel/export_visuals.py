"""Safe, source-bound resolution helpers for textbook visual assets and citations."""
from __future__ import annotations

import shutil
import os
from pathlib import Path
from typing import Any

from .assets import AssetStore


def resolve_block_assets(
    database_path: str | Path, asset_dir: str | Path | None,
    source_id: str, block: dict[str, Any],
) -> list[tuple[Path,str,str,str]]:
    assets=block.get("assets",[])
    if not assets:
        return []
    if asset_dir is None:
        raise ValueError("This textbook contains linked images; supply asset_dir to embed them")
    store=AssetStore(database_path,asset_dir,max_bytes=250*1024*1024)
    output=[]
    for asset in assets:
        if asset.get("source_id") != source_id:
            raise ValueError("Textbook visual asset belongs to another source")
        media_type=str(asset.get("media_type",""))
        if not media_type.startswith("image/"):
            raise ValueError("Only image assets can be rendered in textbook visual blocks")
        if int(asset.get("byte_size",0)) <= 0 or int(asset["byte_size"]) > 25*1024*1024:
            raise ValueError("Textbook image exceeds the 25 MiB export limit")
        path=store.resolve_path(str(asset["asset_id"]),verify_hash=True)
        if media_type not in {"image/jpeg","image/png"}:
            try:
                from PIL import Image
            except ImportError as exc:
                raise RuntimeError(
                    "GIF/WebP export requires Pillow: pip install -e '.[vision]'"
                ) from exc
            cache=store.storage_dir/".staging"/"export-normalized"
            cache.mkdir(parents=True,exist_ok=True)
            normalized=cache/f"{asset['sha256']}.png"
            if not normalized.is_file():
                temporary=cache/f".{asset['sha256']}.tmp"
                with Image.open(path) as image:
                    image.seek(0)
                    if image.width*image.height>40_000_000:
                        raise ValueError("Decoded textbook image exceeds the 40 MP export limit")
                    image.convert("RGBA").save(temporary,format="PNG",optimize=True)
                if temporary.stat().st_size>25*1024*1024:
                    temporary.unlink(missing_ok=True)
                    raise ValueError("Normalized textbook image exceeds the 25 MiB export limit")
                os.replace(temporary,normalized)
            path=normalized
            media_type="image/png"
        output.append((path,str(asset.get("caption") or ""),media_type,str(asset["sha256"])))
    return output


def evidence_locator_label(evidence: dict[str,Any]) -> str:
    if evidence.get("locator_kind") == "DOCUMENT_PAGE" or evidence.get("page_number") is not None:
        return f"PDF page {int(evidence['page_number'])}"
    if evidence.get("start_ms") is not None:
        start=int(evidence["start_ms"])/1000
        end=evidence.get("end_ms")
        return f"{start:.1f}s" if end is None else f"{start:.1f}–{int(end)/1000:.1f}s"
    return "Source reference"


def copy_markdown_assets(
    assets: list[tuple[Path,str,str,str]], output_path: Path,
) -> list[tuple[str,str]]:
    if not assets:
        return []
    folder=output_path.with_suffix("").name + ".assets"
    destination=output_path.parent/folder
    destination.mkdir(parents=True,exist_ok=True)
    results=[]
    for path,caption,media_type,digest in assets:
        suffix={"image/jpeg":".jpg","image/png":".png","image/gif":".gif",
                "image/webp":".webp"}.get(media_type,".img")
        name=f"{digest}{suffix}"
        target=destination/name
        if not target.exists():
            shutil.copyfile(path,target)
        results.append((f"{folder}/{name}",caption))
    return results
