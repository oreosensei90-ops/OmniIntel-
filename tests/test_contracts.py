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

def test_claim_and_block_reference_link_contracts():
    common = {
        "id": "0190f2a1-1234-7123-8123-123456789abc",
        "evidence_ref_id": "0190f2a1-1234-7123-8123-123456789abd",
        "relation": "SUPPORTS",
        "review_state": "PENDING",
        "created_at": "2026-11-19T08:00:00Z",
    }
    claim = {
        **common,
        "claim_id": "0190f2a1-1234-7123-8123-123456789abe",
        "relevance_score": 0.94,
        "rationale": "Relevant page citation",
        "reviewed_at": None,
    }
    assert validator_for("claim-evidence-reference.schema.json").is_valid(claim)

    block = {
        **common,
        "block_id": "0190f2a1-1234-7123-8123-123456789abf",
        "rationale": None,
    }
    assert validator_for("block-evidence-reference.schema.json").is_valid(block)
    block["relation"] = "QUALIFIES"
    assert not validator_for("block-evidence-reference.schema.json").is_valid(block)

def test_document_topic_contracts_do_not_require_video_timestamps():
    topic = {
        "id": "0190f2a1-1234-7123-8123-123456789abc",
        "source_id": "0190f2a1-1234-7123-8123-123456789abd",
        "parent_topic_id": None,
        "title": "Conservation laws",
        "description": "Core principles",
        "ordinal": 0,
        "provenance": "EXPLANATION",
        "status": "DRAFT",
        "confidence": 0.9,
        "created_at": "2026-11-19T08:00:00Z",
        "updated_at": "2026-11-19T08:00:00Z",
    }
    assert validator_for("document-topic.schema.json").is_valid(topic)

    link = {
        "id": "0190f2a1-1234-7123-8123-123456789abe",
        "topic_id": topic["id"],
        "evidence_ref_id": "0190f2a1-1234-7123-8123-123456789abf",
        "relation": "INTRODUCES",
        "review_state": "PENDING",
        "relevance_score": None,
        "rationale": None,
        "created_at": "2026-11-19T08:00:00Z",
        "reviewed_at": None,
    }
    assert validator_for("document-topic-evidence-reference.schema.json").is_valid(link)

def test_document_element_and_ocr_contracts_preserve_native_provenance():
    common = {
        "id": "0190f2a1-1234-7123-8123-123456789abc",
        "page_id": "0190f2a1-1234-7123-8123-123456789abd",
        "evidence_ref_id": "0190f2a1-1234-7123-8123-123456789abe",
        "element_type": "EQUATION",
        "ordinal": 0,
        "text_content": "p_initial = p_final",
        "content": {"text": "p_initial = p_final"},
        "bbox": {"x0": 0.1, "y0": 0.2, "x1": 0.8, "y1": 0.3},
        "asset_id": None,
        "confidence": 0.9,
        "provenance": "SOURCE",
        "review_state": "NEEDS_REVIEW",
        "created_at": "2026-11-19T08:00:00Z",
    }
    assert validator_for("document-element.schema.json").is_valid(common)

    ocr = {
        "page_id": common["page_id"],
        "rendered_asset_id": "0190f2a1-1234-7123-8123-123456789abf",
        "engine_name": "test-ocr",
        "engine_version": "1",
        "text_content": "Recognized text",
        "words": [{
            "text": "Recognized",
            "x0": 0.1, "y0": 0.2, "x1": 0.4, "y1": 0.25,
            "confidence": 96.0,
        }],
        "mean_confidence": 96.0,
        "status": "NEEDS_REVIEW",
        "created_at": "2026-11-19T08:00:00Z",
    }
    assert validator_for("document-ocr-page.schema.json").is_valid(ocr)


def test_knowledge_unit_evidence_reference_contract_supports_element_lineage():
    link = {
        "id": "0190f2a1-1234-7123-8123-123456789abc",
        "knowledge_unit_id": "0190f2a1-1234-7123-8123-123456789abd",
        "evidence_ref_id": "0190f2a1-1234-7123-8123-123456789abe",
        "element_id": "0190f2a1-1234-7123-8123-123456789abf",
        "relation": "SOURCE_EXCERPT",
        "review_state": "PENDING",
        "rationale": None,
        "created_at": "2026-11-19T08:00:00Z",
        "reviewed_at": None,
    }
    assert validator_for("knowledge-unit-evidence-reference.schema.json").is_valid(link)



def test_source_alignment_contract_requires_explicit_review_and_sign_convention():
    validator=validator_for("source-clock-alignment.schema.json")
    alignment={
        "id":"0190f2a1-1234-7123-8123-123456789abc",
        "schema_version":1,
        "collection_id":"0190f2a1-1234-7123-8123-123456789abd",
        "source_a_id":"0190f2a1-1234-7123-8123-123456789abe",
        "source_b_id":"0190f2a1-1234-7123-8123-123456789abf",
        "offset_ms":1250,"sample_interval_ms":100,
        "correlation":0.95,"runner_up_correlation":0.2,
        "method":"normalized-cross-correlation","algorithm_version":"1",
        "input_sha256":"a"*64,"rationale":"Shared measured audio envelope",
        "sign_convention":"time_A_ms = time_B_ms + offset_ms",
        "review_state":"NEEDS_REVIEW",
        "created_at":"2026-11-19T08:00:00Z","reviewed_at":None,
    }
    assert validator.is_valid(alignment)
    alignment["review_state"]="AUTO_ACCEPTED"
    assert not validator.is_valid(alignment)


def test_reader_session_and_execution_plan_contracts_preserve_locality():
    reader={
        "id":"0190f2a1-1234-7123-8123-123456789abc","schema_version":1,
        "version_id":"0190f2a1-1234-7123-8123-123456789abd",
        "anchor_source_id":None,"current_source_id":"0190f2a1-1234-7123-8123-123456789abe",
        "position_ms":0,"chapter_id":None,"block_id":None,
        "updated_at":"2026-11-19T08:00:00Z",
    }
    assert validator_for("reader-session.schema.json").is_valid(reader)
    reader["position_ms"]=-1
    assert not validator_for("reader-session.schema.json").is_valid(reader)

    plan={
        "schema_version":1,"read_only":True,"ready_for_execution":True,
        "total_bytes":16,"questions":[],"warnings":[],
        "inputs":[{
            "path":"/private/lesson.pdf","display_name":"lesson.pdf",
            "modality":"DOCUMENT","media_type":"application/pdf","byte_size":16,
            "modified_ns":1,"file_id":2,"action":"EXTRACT_PDF",
            "resource_class":"MEDIUM","network":"none","requires_user_review":False,
        }],
    }
    assert validator_for("execution-plan.schema.json").is_valid(plan)
    plan["inputs"][0]["network"]="internet"
    assert not validator_for("execution-plan.schema.json").is_valid(plan)


def test_quality_benchmark_contract_is_versioned_and_nonempty():
    report={
        "schema_version":1,"case_count":1,
        "aggregates":{"wer":{"mean":0.1,"count":1}},
        "cases":[{"case_id":"lecture-1","metrics":{"wer":0.1}}],
    }
    assert validator_for("quality-benchmark-report.schema.json").is_valid(report)
    report["case_count"]=0
    assert not validator_for("quality-benchmark-report.schema.json").is_valid(report)
