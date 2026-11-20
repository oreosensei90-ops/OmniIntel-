from pathlib import Path


ROOT = Path(__file__).parents[1] / "apps" / "web"


def test_reader_shell_allows_configured_api_connections() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "default-src 'self'" in html
    assert "connect-src 'self' https:" in html
    assert "script-src 'self'" in html
    assert "api-base-url" in html


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


def test_online_client_uses_only_user_configured_api_and_never_embeds_provider_keys() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "fetch(base + path" in app
    assert "apiBase()" in app
    assert 'sessionStorage.setItem("omniintel-api-token", token)' in app
    assert "/v1/youtube/jobs" in app
    assert "OMNIINTEL_OPENAI_API_KEY" not in app
    assert "https://" not in app


def test_web_manifest_is_valid_and_standalone() -> None:
    import json

    manifest = json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "OmniIntel Reader"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "./"


def test_reader_stores_personal_notes_in_indexeddb_without_remote_sync() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'indexedDB.open("omniintel-reader-local", 3)' in app
    assert 'createObjectStore("annotations"' in app
    assert 'createObjectStore("bookmarks"' in app
    assert "PERSONAL STUDY NOTES · THIS BROWSER ONLY" in app
    assert "fetch(base + path" in app
    assert "createObjectStore(\"readerBooks\"" in app


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
    assert schema["properties"]["version"]["properties"]["id"]["maxLength"] == 128
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



def test_video_to_notes_requires_network_and_keeps_ai_optional() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="approve-network"' in html
    assert 'id="approve-ai"' in html
    assert "approve_network: true" in app
    assert 'approve_ai: $("#approve-ai").checked' in app
    assert 'id="approve-ai" type="checkbox" required' not in html
    assert "renderBook(reader" in app
    assert 'sessionStorage.setItem("omniintel-api-token", token)' in app


def test_online_reader_saves_generated_books_for_local_reopening() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'db.transaction("readerBooks", "readwrite")' in app
    assert "async function restoreLatestReaderBook()" in app
    assert "restoreLatestReaderBook();" in app


def test_web_supports_authorized_media_upload_for_no_caption_transcription_fallback() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="online-media-form"' in html
    assert 'id="approve-upload" type="checkbox" required' in html
    assert 'id="approve-upload-ai" type="checkbox"' in html
    assert 'approve_ai: $("#approve-upload-ai").checked' in app
    assert 'new URL(job.result_url).protocol !== "https:"' in app
    assert 'accept="audio/*,video/*"' in html
    assert '"/v1/media/jobs"' in app
    assert "filename: file.name" in app
    assert "fetch(created.upload_url" in app
    assert "created.upload_complete_url" in app
    assert "250 * 1024 * 1024" in app


def test_cloudflare_job_schema_tracks_upload_completion_gate() -> None:
    root = Path(__file__).parents[1]
    migrations = root / "infra" / "cloudflare" / "worker" / "migrations"
    schema = (migrations / "0001_jobs.sql").read_text(encoding="utf-8")
    upload_gate = (migrations / "0002_upload_gate.sql").read_text(encoding="utf-8")
    worker = (
        root / "infra" / "cloudflare" / "worker" / "src" / "index.ts"
    ).read_text(encoding="utf-8")
    assert "input_uploaded INTEGER NOT NULL DEFAULT 1" in upload_gate
    assert "input_uploaded" not in schema
    assert "input_uploaded = 1" in worker
    assert "input_uploaded=0" in worker


def test_media_download_url_requires_https_in_both_web_flows() -> None:
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    assert app.count('new URL(job.result_url).protocol !== "https:"') == 2
    assert '!new URL(job.result_url).protocol === "https:"' not in app
