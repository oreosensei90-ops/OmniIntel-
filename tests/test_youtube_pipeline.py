from __future__ import annotations

import json

import pytest

from omniintel.captions import parse_caption_text
from omniintel.store import OmniIntelStore
from omniintel.youtube_pipeline import (
    compose_transcript_textbook,
    normalize_youtube_url,
    compose_registered_source,
    process_youtube_queue,
)


def test_normalize_youtube_watch_and_short_urls():
    assert normalize_youtube_url("https://youtu.be/AbCdEf12345?t=20") == (
        "https://www.youtube.com/watch?v=AbCdEf12345", "AbCdEf12345"
    )
    assert normalize_youtube_url("https://www.youtube.com/shorts/AbCdEf12345") == (
        "https://www.youtube.com/watch?v=AbCdEf12345", "AbCdEf12345"
    )


@pytest.mark.parametrize("url", [
    "https://youtube.com.evil.example/watch?v=AbCdEf12345",
    "https://evil-youtube.com/watch?v=AbCdEf12345",
    "javascript://youtube.com/watch?v=AbCdEf12345",
    "https://youtube.com/watch?v=bad",
    "https://user:pass@youtube.com/watch?v=AbCdEf12345",
    "https://youtube.com:8443/watch?v=AbCdEf12345",
])
def test_rejects_untrusted_or_invalid_youtube_urls(url):
    with pytest.raises(ValueError):
        normalize_youtube_url(url)


def test_composes_offline_reader_draft_with_source_evidence_and_reviewable_glossary(tmp_path):
    caption = """WEBVTT

00:00:00.000 --> 00:00:03.000
Neural Networks learn patterns from data.

00:00:03.100 --> 00:00:06.000
Neural Networks use layers to transform information.

00:00:06.100 --> 00:00:09.000
A Neural Network can learn complex representations.
"""
    transcript = parse_caption_text(
        caption, title="Neural Networks 101",
        source_uri="https://www.youtube.com/watch?v=AbCdEf12345",
        language="en", duration_ms=9_000,
    )
    result = compose_transcript_textbook(
        tmp_path / "omniintel.db", transcript,
        source_metadata={"video_id": "AbCdEf12345"}, chapter_minutes=10,
    )

    assert result["pipeline"]["status"] == "TRANSCRIPT_DRAFT_READY"
    assert result["sources"][0]["source_id"] == result["source"]["id"]
    assert result["anchor_source_id"] == result["source"]["id"]
    assert result["pipeline"]["ai_generated_explanations"] is False
    assert result["version"]["title"] == "Transcript reader draft"
    content_chapters = [item for item in result["chapters"] if item["blocks"]]
    assert content_chapters
    paragraphs = [
        block for chapter in content_chapters for block in chapter["blocks"]
        if block["block_type"] == "PARAGRAPH"
    ]
    assert paragraphs
    assert "Neural Networks learn patterns from data." in paragraphs[0]["content"]["text"]
    assert len(paragraphs[0]["evidence"]) == 3
    glossary = [item for item in result["chapters"] if item["chapter"]["title"].startswith("Glossary")]
    assert glossary
    definitions = [block for block in glossary[0]["blocks"] if block["block_type"] == "DEFINITION"]
    assert definitions
    assert all(block["provenance"] == "UNCERTAIN" for block in definitions)
    assert all(block["review_status"] == "NEEDS_REVIEW" for block in definitions)


def test_composition_rejects_invalid_chapter_size(tmp_path):
    transcript = parse_caption_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello world",
        title="Test",
    )
    with pytest.raises(ValueError):
        compose_transcript_textbook(tmp_path / "bad.db", transcript, chapter_minutes=0)


def test_composes_existing_local_asr_transcript_without_creating_duplicate_source(tmp_path):
    database = tmp_path / "local-asr.db"
    transcript = parse_caption_text(
        """WEBVTT

00:00:00.000 --> 00:00:02.000
Local audio transcription preserves source timestamps.

00:00:02.100 --> 00:00:04.000
Local audio transcription remains available offline.
""",
        title="Locally transcribed lecture", source_uri="file:///lecture.wav",
        language="en", duration_ms=4_000,
    )
    imported = OmniIntelStore(database).import_transcript(transcript)
    result = compose_registered_source(database, imported.source_id)
    assert result["source"]["id"] == imported.source_id
    assert result["version"]["source_id"] == imported.source_id
    assert result["pipeline"]["transcript_origin"] == "caption"



def test_android_queue_handoff_processes_each_video_and_records_failures(tmp_path, monkeypatch):
    import omniintel.youtube_pipeline as pipeline

    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({
        "schema_version": 1,
        "queue_type": "OMNIINTEL_YOUTUBE_QUEUE",
        "items": [
            {"video_id": "AbCdEf12345", "url": "https://youtu.be/AbCdEf12345"},
            {"video_id": "ZyXwVu98765", "url": "https://youtu.be/ZyXwVu98765"},
        ],
    }), encoding="utf-8")
    calls = []

    def fake_process(database, url, **kwargs):
        calls.append((url, kwargs))
        if "ZyXwVu98765" in url:
            raise RuntimeError("captions unavailable")
        return {
            "source": {"id": "source-one"},
            "pipeline": {"status": "TRANSCRIPT_DRAFT_READY"},
        }

    monkeypatch.setattr(pipeline, "process_youtube_video", fake_process)
    report = process_youtube_queue(
        tmp_path / "engine.db", queue, tmp_path / "exports",
        user_approved_network=True, language="en",
    )
    assert report["total"] == 2
    assert report["completed"] == 1
    assert report["failed"] == 1
    assert len(calls) == 2
    assert (tmp_path / "exports" / "AbCdEf12345-reader.json").is_file()
    results = json.loads((tmp_path / "exports" / "queue-results.json").read_text())
    assert results["items"][1]["status"] == "FAILED"


def test_android_queue_handoff_requires_approval_and_rejects_duplicate_ids(tmp_path):
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps({
        "schema_version": 1,
        "queue_type": "OMNIINTEL_YOUTUBE_QUEUE",
        "items": [
            {"video_id": "AbCdEf12345", "url": "https://youtu.be/AbCdEf12345"},
            {"video_id": "AbCdEf12345", "url": "https://youtube.com/watch?v=AbCdEf12345"},
        ],
    }), encoding="utf-8")
    with pytest.raises(PermissionError):
        process_youtube_queue(
            tmp_path / "engine.db", queue, tmp_path / "out",
            user_approved_network=False,
        )
    with pytest.raises(ValueError, match="duplicate"):
        process_youtube_queue(
            tmp_path / "engine.db", queue, tmp_path / "out",
            user_approved_network=True,
        )
