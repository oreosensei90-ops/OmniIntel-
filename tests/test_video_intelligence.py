from __future__ import annotations

import pytest

from omniintel.video_intelligence import normalized_frame_difference


def test_normalized_frame_difference_is_zero_for_identical_images() -> None:
    pytest.importorskip("PIL")
    from PIL import Image
    import io
    buffer=io.BytesIO()
    Image.new("RGB",(64,36),(80,100,120)).save(buffer,format="PNG")
    data=buffer.getvalue()
    assert normalized_frame_difference(data,data)==0


def test_normalized_frame_difference_detects_large_visual_change() -> None:
    pytest.importorskip("PIL")
    from PIL import Image
    import io
    def encoded(color: tuple[int,int,int]) -> bytes:
        buffer=io.BytesIO()
        Image.new("RGB",(64,36),color).save(buffer,format="PNG")
        return buffer.getvalue()
    assert normalized_frame_difference(encoded((0,0,0)),encoded((255,255,255)))==1


def test_normalized_frame_difference_rejects_invalid_image() -> None:
    pytest.importorskip("PIL")
    with pytest.raises(OSError):
        normalized_frame_difference(b"not an image",b"also not an image")
