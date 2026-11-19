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
