from __future__ import annotations
import json
from omniintel.cloud_worker_bridge import _validate_reader
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.store import OmniIntelStore
from omniintel.study_generation import generate_study_guide


def test_transcript_to_evidence_reader_round_trip(tmp_path):
    database = tmp_path / "pipeline.db"
    imported = OmniIntelStore(database).import_transcript(TranscriptImport(
        title="Controlled test lecture", source_uri="file:///controlled-lecture.txt",
        language="en", duration_ms=8000,
        segments=(
            TranscriptSegmentInput("Motion describes a change in position over time.", 0, 4000),
            TranscriptSegmentInput("Velocity describes the rate and direction of displacement.", 4000, 8000),
        ),
    ))
    evidence = list(imported.evidence_ref_ids)
    payload = {
        "chapter_summary": "This controlled chapter introduces motion and explains velocity as rate and direction of displacement.",
        "summary_evidence_ids": evidence,
        "concepts": [
            {"title": "Motion", "body": "Motion describes a change in position over time.", "evidence_ids": [evidence[0]]},
            {"title": "Displacement", "body": "Displacement describes a change in position.", "evidence_ids": [evidence[1]]},
            {"title": "Velocity", "body": "Velocity describes rate and direction of displacement.", "evidence_ids": [evidence[1]]},
        ],
        "glossary": [], "worked_examples": [],
        "questions": [
            {"title": "Motion recall", "body": "How does the source describe motion?", "evidence_ids": [evidence[0]]},
            {"title": "Velocity recall", "body": "Which two aspects describe velocity?", "evidence_ids": [evidence[1]]},
            {"title": "Displacement recall", "body": "What change does displacement describe?", "evidence_ids": [evidence[1]]},
        ],
    }
    reader = generate_study_guide(
        database, imported.source_id, model="test-fixture", approve_local_model=True,
        generator=lambda _model, _prompt: payload,
    )
    serialized = json.loads(json.dumps(reader, ensure_ascii=False))
    _validate_reader(serialized)
    assert serialized["source"]["id"] == imported.source_id
    assert serialized["pipeline"]["human_review_required"] is True
    assert any(block["evidence"] for chapter in serialized["chapters"] for block in chapter["blocks"])
