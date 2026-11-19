from __future__ import annotations

import pytest

from omniintel.visual_timeline import align_timestamp


def test_timestamp_alignment_prefers_all_overlapping_segments() -> None:
    segments = [
        {"id": "a", "start_ms": 1000, "end_ms": 2000},
        {"id": "b", "start_ms": 1800, "end_ms": 2400},
        {"id": "c", "start_ms": 4000, "end_ms": 5000},
    ]
    result = align_timestamp(1900, segments)
    assert [(item.transcript_segment_id, item.relation, item.delta_ms) for item in result] == [
        ("a", "OVERLAPS", 0), ("b", "OVERLAPS", 0)
    ]


def test_timestamp_alignment_uses_nearest_only_inside_tolerance() -> None:
    segments = [
        {"id": "later", "start_ms": 5000, "end_ms": 6000},
        {"id": "earlier", "start_ms": 1000, "end_ms": 2000},
    ]
    result = align_timestamp(3500, segments, tolerance_ms=2000)
    assert len(result) == 1
    assert result[0].transcript_segment_id == "earlier"
    assert result[0].relation == "NEAREST"
    assert result[0].delta_ms == 1500


def test_timestamp_alignment_does_not_link_far_away_speech() -> None:
    assert align_timestamp(
        100_000, [{"id": "x", "start_ms": 1_000, "end_ms": 2_000}],
        tolerance_ms=5000,
    ) == ()


@pytest.mark.parametrize("timestamp", [-1, 1.5])
def test_timestamp_alignment_rejects_invalid_time(timestamp: float) -> None:
    with pytest.raises(ValueError):
        align_timestamp(timestamp, [])


def test_timestamp_alignment_rejects_invalid_segment_interval() -> None:
    with pytest.raises(ValueError, match="interval"):
        align_timestamp(100, [{"id": "bad", "start_ms": 200, "end_ms": 100}])
