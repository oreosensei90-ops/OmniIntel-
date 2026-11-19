from __future__ import annotations

import pytest

from omniintel.reader_export import _normalize_evidence


def test_normalizes_transcript_evidence_for_reader_seek():
    result = _normalize_evidence({
        "start_ms": 1250,
        "end_ms": 4250,
        "content": "A transcript excerpt.",
        "relation": "SUPPORTS",
        "review_state": "PENDING",
    }, "source-1")

    assert result["source_id"] == "source-1"
    assert result["locator_kind"] == "TRANSCRIPT_INTERVAL"
    assert result["local_start_ms"] == 1250
    assert result["local_end_ms"] == 4250
    assert result["seek_available"] is True
    assert result["transcript_excerpt"] == [{
        "text": "A transcript excerpt.", "start_ms": 1250, "end_ms": 4250,
    }]


def test_normalizes_document_page_and_reviewed_element():
    result = _normalize_evidence({
        "source_id": "document-1",
        "locator_kind": "DOCUMENT_PAGE",
        "page_number": 7,
        "content": "Page text",
        "element_id": "element-1",
        "element_type": "EQUATION",
        "element_text": "E = mc^2",
        "element_review_state": "ACCEPTED",
        "review_state": "ACCEPTED",
    }, "fallback-source")

    assert result["source_id"] == "document-1"
    assert result["locator_kind"] == "DOCUMENT_PAGE"
    assert result["document_page"] == {"page_number": 7, "text_content": "Page text"}
    assert result["document_elements"] == [{
        "id": "element-1",
        "element_type": "EQUATION",
        "text_content": "E = mc^2",
        "review_state": "ACCEPTED",
    }]
    assert result["seek_available"] is False


def test_rejects_evidence_without_a_supported_locator():
    with pytest.raises(ValueError, match="no supported source locator"):
        _normalize_evidence({"content": "Unlocated text"}, "source-1")
