from pathlib import Path

from omniintel.store import OmniIntelStore
from omniintel.models import TranscriptImport, TranscriptSegmentInput
from omniintel.textbook import BlockInput, TextbookStore
from omniintel.textbook_audit import TextbookPublicationAuditor


def _book(tmp_path: Path):
    path = tmp_path / "publication.db"
    imported = OmniIntelStore(path).import_transcript(TranscriptImport(
        title="Foundations",
        segments=(TranscriptSegmentInput("A source statement.", 0, 2_000),),
        duration_ms=2_000,
    ))
    store = TextbookStore(path)
    textbook = store.create_textbook(imported.source_id, "Foundations")
    version = store.create_version(textbook, "Draft")
    chapter = store.add_chapter(version, "Chapter 1", ordinal=0)
    return path, imported, store, version, chapter


def test_publication_gate_accepts_reviewed_explanation_block(tmp_path: Path) -> None:
    path, _, store, version, chapter = _book(tmp_path)
    store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "An explanation."}, "EXPLANATION",
        review_status="ACCEPTED",
    ))
    report = TextbookPublicationAuditor(path).audit(version)
    assert report.ready
    assert report.total_blocks == 1
    assert report.eligible_blocks == 1
    assert report.blocked_blocks == 0


def test_publication_gate_blocks_unreviewed_and_uncertain_blocks(tmp_path: Path) -> None:
    path, _, store, version, chapter = _book(tmp_path)
    store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "Needs review."}, "EXPLANATION",
        review_status="NEEDS_REVIEW",
    ))
    store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "Uncertain."}, "UNCERTAIN",
        review_status="ACCEPTED", ordinal=1,
    ))
    report = TextbookPublicationAuditor(path).audit(version)
    assert not report.ready
    assert report.blocked_blocks == 2
    codes = {finding.code for finding in report.findings}
    assert "BLOCK_NOT_ACCEPTED" in codes
    assert "UNCERTAIN_PROVENANCE" in codes


def test_publication_gate_requires_claim_support_to_be_carried(tmp_path: Path) -> None:
    from omniintel.knowledge import ClaimEvidenceInput, ClaimInput
    from omniintel.knowledge_store import KnowledgeStore

    path, imported, store, version, chapter = _book(tmp_path)
    knowledge = KnowledgeStore(path)
    claim_id = knowledge.create_claim(ClaimInput(
        "A supported claim.", provenance="EXPLANATION"
    ))
    claim_link = knowledge.link_evidence(ClaimEvidenceInput(
        claim_id, imported.evidence_ids[0], "SUPPORTS"
    ))
    assert knowledge.review_evidence_link(claim_link, "ACCEPTED") == "SUPPORTED"
    block = store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "A supported claim."}, "EXPLANATION",
        review_status="ACCEPTED", claim_id=claim_id,
    ))
    report = TextbookPublicationAuditor(path).audit(version)
    assert not report.ready
    assert report.blocked_blocks == 1
    assert any(f.code == "CLAIM_SUPPORT_NOT_CARRIED" for f in report.findings)

    store.link_evidence(block, imported.evidence_ids[0], relation="SUPPORTS",
                        review_state="ACCEPTED")
    report = TextbookPublicationAuditor(path).audit(version)
    assert report.ready
    assert report.eligible_blocks == 1

def test_publication_gate_accepts_claim_supported_by_pdf_page_reference(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    from omniintel.document_pdf import extract_pdf
    from omniintel.knowledge import ClaimEvidenceReferenceInput, ClaimInput
    from omniintel.knowledge_store import KnowledgeStore
    from omniintel.local_files import import_local_file

    pdf = tmp_path / "source.pdf"
    output = canvas.Canvas(str(pdf))
    output.drawString(72, 720, "The first law describes conservation of energy.")
    output.showPage()
    output.save()
    path = tmp_path / "publication.db"
    assets = tmp_path / "assets"
    imported = import_local_file(path, assets, pdf, title="Physics source")
    extraction = extract_pdf(path, assets, imported.asset.id)

    knowledge = KnowledgeStore(path)
    claim_id = knowledge.create_claim(ClaimInput("Energy is conserved."))
    claim_link = knowledge.link_evidence_reference(
        ClaimEvidenceReferenceInput(
            claim_id, extraction.evidence_ref_ids[0], "SUPPORTS", 0.96
        )
    )
    assert knowledge.review_evidence_reference_link(claim_link, "ACCEPTED") == "SUPPORTED"

    store = TextbookStore(path)
    textbook = store.create_textbook(imported.source_id, "Physics")
    version = store.create_version(textbook, "PDF grounded edition")
    chapter = store.add_chapter(version, "Conservation", ordinal=0)
    block = store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "Energy is conserved."}, "EXPLANATION",
        review_status="ACCEPTED", claim_id=claim_id,
    ))
    store.link_evidence_reference(
        block, extraction.evidence_ref_ids[0],
        relation="SUPPORTS", review_state="ACCEPTED",
    )
    report = TextbookPublicationAuditor(path).audit(version)
    assert report.ready
    assert report.eligible_blocks == 1

def test_document_topic_composition_builds_page_cited_textbook(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    from omniintel.document_pdf import extract_pdf
    from omniintel.knowledge import ClaimEvidenceReferenceInput, ClaimInput
    from omniintel.knowledge_store import KnowledgeStore
    from omniintel.local_files import import_local_file
    from omniintel.topics import DocumentTopicEvidenceInput, DocumentTopicInput, TopicStore

    pdf = tmp_path / "lesson.pdf"
    output = canvas.Canvas(str(pdf))
    output.drawString(72, 720, "An isolated system conserves momentum.")
    output.showPage()
    output.save()
    database = tmp_path / "document-book.db"
    assets = tmp_path / "assets"
    imported = import_local_file(database, assets, pdf, title="Momentum lesson")
    extraction = extract_pdf(database, assets, imported.asset.id)
    reference_id = extraction.evidence_ref_ids[0]

    topics = TopicStore(database)
    topic_id = topics.create_document_topic(
        DocumentTopicInput(imported.source_id, "Conservation of momentum", 0)
    )
    topic_link = topics.link_document_evidence(
        DocumentTopicEvidenceInput(topic_id, reference_id, "INTRODUCES", 0.99)
    )
    assert topics.review_document_evidence_link(topic_link, "ACCEPTED") == "ACCEPTED"

    knowledge = KnowledgeStore(database)
    claim_id = knowledge.create_claim(ClaimInput("An isolated system conserves momentum."))
    claim_link = knowledge.link_evidence_reference(
        ClaimEvidenceReferenceInput(claim_id, reference_id, "SUPPORTS", 0.99)
    )
    assert knowledge.review_evidence_reference_link(claim_link, "ACCEPTED") == "SUPPORTED"

    store = TextbookStore(database)
    version_id = store.compose_from_accepted_document_topics(
        imported.source_id, "Momentum textbook"
    )
    report = TextbookPublicationAuditor(database).audit(version_id)
    assert report.ready
    tree = store.get_version_tree(version_id)
    block = tree["chapters"][0]["blocks"][0]
    assert block["claim_id"] == claim_id
    assert block["evidence_references"][0]["evidence_ref_id"] == reference_id
    assert block["evidence_references"][0]["page_number"] == 1



def test_accepted_visual_contradiction_blocks_textbook_publication(tmp_path: Path) -> None:
    import json

    from omniintel.assets import AssetStore
    from omniintel.database import connect
    from omniintel.ids import uuid7
    from omniintel.knowledge import ClaimEvidenceReferenceInput, ClaimInput
    from omniintel.knowledge_store import KnowledgeStore
    from omniintel.models import utc_now
    from omniintel.video_intelligence import review_visual_record
    from omniintel.visual_timeline import review_visual_event

    path, imported, store, version, chapter = _book(tmp_path)
    knowledge = KnowledgeStore(path)
    claim_id = knowledge.create_claim(ClaimInput("The diagram shows an increasing trend."))
    link = knowledge.link_evidence_reference(
        ClaimEvidenceReferenceInput(claim_id, imported.evidence_ref_ids[0], "SUPPORTS", 0.99)
    )
    assert knowledge.review_evidence_reference_link(link, "ACCEPTED") == "SUPPORTED"
    block = store.add_block(chapter, BlockInput(
        "PARAGRAPH", {"text": "The diagram shows an increasing trend."}, "EXPLANATION",
        review_status="ACCEPTED", claim_id=claim_id,
    ))
    store.link_evidence_reference(
        block, imported.evidence_ref_ids[0], relation="SUPPORTS", review_state="ACCEPTED",
    )

    asset_dir = tmp_path / "assets"
    assets = AssetStore(path, asset_dir)
    video = assets.add_bytes(
        imported.source_id, b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64,
        role="VIDEO", display_name="source.mp4",
    )
    frame_png = (
        b"\x89PNG\r\n\x1a\n" +
        __import__("base64").b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ9sAAAAASUVORK5CYII="
        )
    )
    frame = assets.add_bytes(
        imported.source_id, frame_png, role="FRAME", display_name="frame.png",
    )
    extraction_id, frame_id, event_id = uuid7(), uuid7(), uuid7()
    now = utc_now()
    with connect(path) as conn:
        conn.execute(
            """INSERT INTO frame_extractions
               (id,source_asset_id,source_sha256,config_sha256,tool_name,tool_version,
                video_stream_index,sample_interval_ms,frame_count,total_bytes,total_pixels,
                metadata_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (extraction_id,video.id,video.sha256,"a"*64,"ffmpeg","test",0,1000,1,
             frame.byte_size,1,json.dumps({}),now),
        )
        conn.execute(
            """INSERT INTO video_frames
               (id,extraction_id,source_asset_id,frame_asset_id,frame_index,timestamp_ms,
                width,height,byte_size,sha256,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (frame_id,extraction_id,video.id,frame.id,0,0,1,1,frame.byte_size,frame.sha256,now),
        )
        conn.execute(
            """INSERT INTO visual_events
               (id,source_id,source_asset_id,frame_id,timestamp_ms,event_kind,review_state,created_at)
               VALUES(?,?,?,?,?,'FRAME_SAMPLE','NEEDS_REVIEW',?)""",
            (event_id,imported.source_id,video.id,frame_id,0,now),
        )
    assert review_visual_event(path,event_id,"ACCEPTED") == "ACCEPTED"

    description_id = uuid7()
    with connect(path) as conn:
        conn.execute(
            """INSERT INTO visual_descriptions
               (id,source_id,visual_event_id,adapter_name,adapter_version,model_id,
                prompt_sha256,description,review_state,created_at)
               VALUES(?,?,?,?,?,?,?,?, 'NEEDS_REVIEW',?)""",
            (description_id,imported.source_id,event_id,"test","1","test-model","b"*64,
             "A downward sloping graph.",now),
        )
    assert review_visual_record(path,"visual_descriptions",description_id,"ACCEPTED") == "ACCEPTED"

    verification_id = uuid7()
    with connect(path) as conn:
        conn.execute(
            """INSERT INTO visual_claim_verifications
               (id,source_id,claim_id,visual_event_id,description_id,transcript_segment_id,
                adapter_name,adapter_version,model_id,verdict,rationale,review_state,created_at)
               VALUES(?,?,?,?,?,NULL,?,?,?,'CONTRADICTS',?,'NEEDS_REVIEW',?)""",
            (verification_id,imported.source_id,claim_id,event_id,description_id,
             "test","1","test-model","The graph direction contradicts the claim.",now),
        )
    assert review_visual_record(
        path,"visual_claim_verifications",verification_id,"ACCEPTED"
    ) == "ACCEPTED"
    report = TextbookPublicationAuditor(path).audit(version)
    assert not report.ready
    assert any(item.code == "CLAIM_VISUALLY_CONTRADICTED" for item in report.findings)
