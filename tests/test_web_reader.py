from pathlib import Path


ROOT = Path(__file__).parents[1] / "apps" / "web"


def test_reader_shell_has_strict_local_only_security_policy() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "default-src 'self'" in html
    assert "connect-src 'none'" in html
    assert "script-src 'self'" in html
    assert "https://" not in html


def test_reader_renders_untrusted_imports_without_html_injection_sinks() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "textContent" in app
    assert "createElement" in app
    assert "innerHTML" not in app
    assert "insertAdjacentHTML" not in app
    assert "eval(" not in app
    assert "new Function" not in app


def test_service_worker_only_caches_static_shell_not_user_documents() -> None:
    worker = (ROOT / "service-worker.js").read_text(encoding="utf-8")
    assert 'const SHELL = ["./", "./index.html", "./styles.css", "./app.js", "./manifest.webmanifest"]' in worker
    assert "shellPaths.includes(url.pathname)" in worker
    assert "application/json" not in worker


def test_reader_has_no_remote_provider_or_analytics_dependencies() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "fetch(" not in app
    assert "XMLHttpRequest" not in app
    assert "WebSocket" not in app
    assert "https://" not in html


def test_web_manifest_is_valid_and_standalone() -> None:
    import json

    manifest = json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "OmniIntel Reader"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "./"


def test_reader_stores_personal_notes_in_indexeddb_without_remote_sync() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'indexedDB.open("omniintel-reader-local", 1)' in app
    assert 'createObjectStore("annotations"' in app
    assert 'createObjectStore("bookmarks"' in app
    assert "PERSONAL STUDY NOTES · THIS BROWSER ONLY" in app
    assert "fetch(" not in app


def test_reader_search_spans_chapters_and_matches_transcript_and_pdf_evidence() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "function renderSearchResults()" in app
    assert "state.chapters.forEach" in app
    assert "item.transcript_excerpt" in app
    assert "item.document_page?.text_content" in app
    assert "scrollIntoView" in app


def test_local_media_seeking_is_source_scoped_and_never_applies_unreviewed_offsets() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'state.mediaSourceId !== item.source_id' in app
    assert 'media.currentTime = Number(item.local_start_ms) / 1000' in app
    assert 'media.currentTime = Number(item.local_start_ms) / 1000' in app
    assert '"COURSE CLOCK · "' in app
    assert 'item.alignment_status' in app
    assert 'URL.createObjectURL(file)' in app
    assert 'URL.revokeObjectURL(state.mediaUrl)' in app
    assert 'file.type.startsWith("audio/")' in app
    assert 'file.type.startsWith("video/")' in app


def test_reader_exposes_positioned_pdf_elements_with_review_state() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "item.document_elements" in app
    assert "part.review_state" in app
    assert "part.confidence" in app
    assert "item.document_elements.slice(0, 20)" in app


def test_shared_reader_export_contract_is_versioned_and_source_clock_explicit() -> None:
    import json

    schema_path = Path(__file__).parents[1] / "schemas" / "reader-export.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("/2020-12/schema")
    assert {"version", "sources", "chapters", "alignment_policy"} <= set(schema["required"])
    evidence = schema["properties"]["chapters"]["items"]["properties"]["blocks"]["items"]["properties"]["evidence"]["items"]["properties"]
    assert "local_start_ms" in evidence
    assert "course_time_ms" in evidence
    assert evidence["seek_available"]["type"] == "boolean"


def test_web_reader_uses_source_local_timestamp_fields_for_citations() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "item.local_start_ms ?? item.start_ms" in app
    assert "item.local_end_ms ?? item.end_ms ?? start" in app


def test_web_reader_requires_explicit_source_selection_before_media_attachment() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "Select the exact course source…" in app
    assert 'state.mediaSourceId = null;' in app
    assert '$("#media-file").disabled = !state.mediaSourceId;' in app
    assert "attach only the matching local media file" in app.lower()


def test_web_reader_rejects_malformed_utf8_imports() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'new TextDecoder("utf-8", { fatal: true })' in app
    assert "file.arrayBuffer()" in app


def test_personal_note_keys_include_textbook_version_and_chapter_scope() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "const chapterId = state.chapters[state.index]?.chapter?.id" in app
    assert 'return versionId + ":" + chapterId + ":"' in app


def test_web_reader_bounds_imported_chapter_block_and_evidence_counts() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "data.chapters.length > 500" in app
    assert "totalBlocks > 25000" in app
    assert "block.evidence.length > 100" in app
    assert "item.transcript_excerpt?.length || 0) > 40" in app
    assert "item.document_elements?.length || 0) > 100" in app
    assert "validateReaderPayload(data);" in app
