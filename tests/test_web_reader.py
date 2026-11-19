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
