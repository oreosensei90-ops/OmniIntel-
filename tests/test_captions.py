from pathlib import Path

import pytest

from omniintel.captions import import_caption_file, parse_caption_text
from omniintel.store import OmniIntelStore


def test_parse_srt_cues_and_import_as_source_evidence(tmp_path: Path) -> None:
    content = """1
00:00:01,250 --> 00:00:02,500
Hello &amp; welcome.

2
00:00:02,500 --> 00:00:04,000
Second line
continues here.
"""
    parsed = parse_caption_text(content, title="Lecture", language="en")
    assert parsed.duration_ms == 4_000
    assert parsed.metadata["caption_format"] == "srt"
    assert parsed.segments[0].text == "Hello & welcome."
    assert parsed.segments[0].start_ms == 1_250
    assert parsed.segments[1].text == "Second line continues here."

    result = OmniIntelStore(tmp_path / "captions.db").import_transcript(parsed)
    rows = OmniIntelStore(tmp_path / "captions.db").get_transcript(result.source_id)
    assert len(rows) == 2
    assert rows[0]["language"] == "en"


def test_parse_webvtt_cue_settings_and_voice_tags() -> None:
    content = """WEBVTT

NOTE generated for testing

cue-1
00:00:01.5 --> 00:00:03.000 align:start
<v Instructor>Hello <b>class</b>.</v>

00:00:03.000 --> 00:00:04.250
Next cue.
"""
    parsed = parse_caption_text(content, title="Web lecture")
    assert parsed.metadata["caption_format"] == "webvtt"
    assert parsed.segments[0].start_ms == 1_500
    assert parsed.segments[0].speaker_id == "Instructor"
    assert parsed.segments[0].text == "Hello class."


def test_caption_parser_rejects_bad_timestamps_and_empty_cues() -> None:
    with pytest.raises(ValueError, match="component out of range"):
        parse_caption_text("00:99:00,000 --> 00:99:01,000\nBad", title="Bad")
    with pytest.raises(ValueError, match="no usable text cues"):
        parse_caption_text("1\n00:00:00,000 --> 00:00:01,000\n   ", title="Empty")


def test_caption_duration_must_cover_all_cues() -> None:
    with pytest.raises(ValueError, match="exceeds source duration"):
        parse_caption_text(
            "1\n00:00:01,000 --> 00:00:02,000\nLate",
            title="Short", duration_ms=1_500,
        )


def test_import_caption_file_uses_filename_and_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "sample.srt"
    path.write_text("\ufeff1\n00:00:00,000 --> 00:00:01,000\nनमस्ते", encoding="utf-8")
    parsed = import_caption_file(path, language="hi")
    assert parsed.title == "sample"
    assert parsed.segments[0].text == "नमस्ते"
