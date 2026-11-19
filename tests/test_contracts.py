import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


SCHEMA_DIR = Path(__file__).parents[1] / "schemas"


def load_schema(name: str):
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def validator_for(name: str):
    common = load_schema("common.schema.json")
    registry = Registry().with_resource(
        common["$id"], Resource.from_contents(common)
    )
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry)


def test_all_contract_schemas_are_valid():
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_source_contract_accepts_valid_source_and_rejects_unknown_fields():
    validator = validator_for("source.schema.json")
    source = {
        "id": "0190f2a1-1234-7123-8123-123456789abc",
        "schema_version": 1,
        "created_at": "2026-11-19T08:00:00Z",
        "updated_at": "2026-11-19T08:00:00Z",
        "revision": 1,
        "deleted_at": None,
        "source_type": "imported_transcript",
        "title": "Lecture notes",
        "source_uri": None,
        "language": "en",
        "duration_ms": 120000,
        "metadata": {},
    }
    assert validator.is_valid(source)
    source["unexpected"] = True
    assert not validator.is_valid(source)


def test_transcript_contract_rejects_nonpositive_end_timestamp():
    validator = validator_for("transcript-segment.schema.json")
    segment = {
        "id": "0190f2a1-1234-7123-8123-123456789abc",
        "schema_version": 1,
        "created_at": "2026-11-19T08:00:00Z",
        "updated_at": "2026-11-19T08:00:00Z",
        "revision": 1,
        "deleted_at": None,
        "source_id": "0190f2a1-1234-7123-8123-123456789abd",
        "text": "Hello world",
        "start_ms": 500,
        "end_ms": 0,
        "language": "en",
        "speaker_id": None,
        "origin": "caption",
        "confidence": 0.9,
    }
    assert not validator.is_valid(segment)


def test_knowledge_contracts_preserve_provenance_and_review_states():
    unit_validator = validator_for("knowledge-unit.schema.json")
    unit = {
        "id": "0190f2a1-1234-7123-8123-123456789abc",
        "schema_version": 1,
        "created_at": "2026-11-19T08:00:00Z",
        "updated_at": "2026-11-19T08:00:00Z",
        "revision": 1,
        "deleted_at": None,
        "unit_type": "concept",
        "title": "Energy",
        "body": "A physical quantity.",
        "provenance": "EXPLANATION",
        "status": "DRAFT",
    }
    assert unit_validator.is_valid(unit)
    unit["provenance"] = "SOURCE"
    assert not unit_validator.is_valid(unit)

    link_validator = validator_for("claim-evidence.schema.json")
    link = {
        "id": "0190f2a1-1234-7123-8123-123456789abd",
        "claim_id": "0190f2a1-1234-7123-8123-123456789abe",
        "evidence_id": "0190f2a1-1234-7123-8123-123456789abf",
        "relation": "SUPPORTS",
        "review_state": "PENDING",
        "relevance_score": 0.9,
        "rationale": None,
        "created_at": "2026-11-19T08:00:00Z",
        "reviewed_at": None,
    }
    assert link_validator.is_valid(link)
    link["review_state"] = "AUTO_APPROVED"
    assert not link_validator.is_valid(link)

def test_unified_evidence_reference_contract_supports_native_locators():
    validator = validator_for("evidence-reference.schema.json")
    common = {
        "id": "0190f2a1-1234-7123-8123-123456789abc",
        "source_id": "0190f2a1-1234-7123-8123-123456789abd",
        "created_at": "2026-11-19T08:00:00Z",
    }
    transcript = {
        **common,
        "locator_kind": "TRANSCRIPT_INTERVAL",
        "evidence_item_id": "0190f2a1-1234-7123-8123-123456789abe",
        "document_page_id": None,
        "source_asset_id": None,
        "start_ms": 1500,
        "end_ms": 4200,
        "page_number": None,
    }
    assert validator.is_valid(transcript)

    page = {
        **common,
        "locator_kind": "DOCUMENT_PAGE",
        "evidence_item_id": None,
        "document_page_id": "0190f2a1-1234-7123-8123-123456789abf",
        "source_asset_id": "0190f2a1-1234-7123-8123-123456789ab0",
        "start_ms": None,
        "end_ms": None,
        "page_number": 7,
    }
    assert validator.is_valid(page)
    page["start_ms"] = 0
    assert not validator.is_valid(page)

