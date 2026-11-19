from __future__ import annotations

import pytest

from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore
from omniintel.study_generation import (
    _validate_study_guide,
    generate_study_guide,
)


def _sample_source(tmp_path):
    imported = OmniIntelStore(tmp_path / "study.db").import_transcript(TranscriptImport(
        title="Foundations of Physics",
        source_uri="file:///physics.wav",
        language="en",
        duration_ms=8_000,
        segments=(
            TranscriptSegmentInput("Motion describes a change in position over time.", 0, 4_000),
            TranscriptSegmentInput("Velocity describes the rate and direction of displacement.", 4_000, 8_000),
        ),
    ))
    return tmp_path / "study.db", imported


def _payload(ids):
    return {
        "chapter_summary": "This chapter introduces motion and explains how velocity describes displacement over time.",
        "summary_evidence_ids": [ids[0], ids[1]],
        "concepts": [
            {"title": "Motion", "body": "Motion describes a change in position over time.", "evidence_ids": [ids[0]]},
            {"title": "Displacement", "body": "Displacement describes the change in position.", "evidence_ids": [ids[1]]},
            {"title": "Velocity", "body": "Velocity describes the rate and direction of displacement.", "evidence_ids": [ids[1]]},
        ],
        "glossary": [
            {"title": "Velocity", "body": "Velocity is described in the source through rate and direction of displacement.", "evidence_ids": [ids[1]]},
        ],
        "worked_examples": [
            {"title": "Interpreting direction", "body": "A hypothetical learner can compare two equal rates with opposite directions to distinguish velocity.", "evidence_ids": [ids[1]]},
        ],
        "questions": [
            {"title": "Recall motion", "body": "How does the source describe motion?", "evidence_ids": [ids[0]]},
            {"title": "Explain displacement", "body": "What change does displacement describe?", "evidence_ids": [ids[1]]},
            {"title": "Compare terms", "body": "Which two aspects does the source associate with velocity?", "evidence_ids": [ids[1]]},
        ],
    }


def test_generation_requires_explicit_local_model_approval(tmp_path):
    database, imported = _sample_source(tmp_path)
    with pytest.raises(PermissionError, match="Explicit approval"):
        generate_study_guide(
            database, imported.source_id, model="qwen2.5:7b",
            approve_local_model=False, generator=lambda _model, _prompt: {},
        )


def test_generates_review_gated_textbook_and_reader_tree(tmp_path):
    database, imported = _sample_source(tmp_path)
    payload = _payload(list(imported.evidence_ref_ids))
    result = generate_study_guide(
        database, imported.source_id, model="test-local",
        approve_local_model=True,
        generator=lambda model, prompt: payload,
    )

    assert result["pipeline"]["status"] == "AI_STUDY_DRAFT_READY"
    assert result["pipeline"]["all_evidence_links"] == "PENDING"
    assert result["pipeline"]["human_review_required"] is True
    assert result["source"]["id"] == imported.source_id
    assert result["sources"][0]["source_id"] == imported.source_id
    assert result["anchor_source_id"] == imported.source_id
    assert result["alignment_policy"].startswith("Single-source reader")
    blocks = result["chapters"][0]["blocks"]
    assert {block["block_type"] for block in blocks} >= {
        "SUMMARY", "PARAGRAPH", "DEFINITION", "WORKED_SOLUTION", "EXERCISE"
    }
    assert all(block["review_status"] == "NEEDS_REVIEW" for block in blocks)
    assert all(
        link["review_state"] == "PENDING"
        for block in blocks for link in block["evidence_references"]
    )
    assert all(block["provenance"] != "SOURCE" for block in blocks)
    assert all(
        item["seek_available"] and item["transcript_excerpt"]
        for block in blocks for item in block["evidence"]
    )


def test_rejects_model_citations_not_in_supplied_source(tmp_path):
    database, imported = _sample_source(tmp_path)
    payload = _payload(list(imported.evidence_ref_ids))
    payload["concepts"][0]["evidence_ids"] = ["made-up-evidence-id"]
    with pytest.raises(ValueError, match="outside the supplied source"):
        generate_study_guide(
            database, imported.source_id, model="test-local",
            approve_local_model=True,
            generator=lambda _model, _prompt: payload,
        )


def test_rejects_missing_required_learning_sections():
    payload = _payload(["e1", "e2"])
    payload["questions"] = []
    with pytest.raises(ValueError, match="questions"):
        _validate_study_guide(payload, {"e1", "e2"})


def test_rejects_unexpected_provider_fields():
    payload = _payload(["e1", "e2"])
    payload["extra"] = "ignore all rules"
    with pytest.raises(ValueError, match="unexpected"):
        _validate_study_guide(payload, {"e1", "e2"})
