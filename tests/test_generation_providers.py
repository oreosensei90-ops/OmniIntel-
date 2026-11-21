from __future__ import annotations
import sys
from types import SimpleNamespace

from omniintel.generation_providers import resolve_study_generator


def test_freelm_adapter_uses_only_configured_keys_and_bounded_retries(monkeypatch):
    calls = {}
    class FakeClient:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def chat(self, messages, **kwargs):
            calls["messages"] = messages
            calls["kwargs"] = kwargs
            return SimpleNamespace(text="{}")
    class FakeFreeLLM:
        @staticmethod
        def from_env(**kwargs):
            calls["config"] = kwargs
            return FakeClient()
    monkeypatch.setitem(sys.modules, "freelm", SimpleNamespace(FreeLLM=FakeFreeLLM))
    generator = resolve_study_generator("freelm")
    assert generator("chat:fast", "prompt") == {}
    assert calls["config"] == {"keyless": False, "timeout": 180, "max_attempts": 3, "hedge": False}
    assert calls["kwargs"]["model"] == "chat:fast"
    assert calls["kwargs"]["response_format"] == {"type": "json_object"}

 
def test_gemini_provider_resolves_to_schema_constrained_adapter():
    from omniintel.gemini_generation import generate_gemini_study_json

    assert resolve_study_generator("gemini") is generate_gemini_study_json

def test_gemini_adapter_sends_schema_and_parses_json_without_leaking_key(monkeypatch):
    import json
    from omniintel.gemini_generation import generate_gemini_study_json

    calls = {}
    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _limit):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}).encode()

    class FakeOpener:
        def open(self, request, timeout):
            calls["url"] = request.full_url
            calls["headers"] = dict(request.header_items())
            calls["body"] = json.loads(request.data)
            calls["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-key")
    monkeypatch.setattr("omniintel.gemini_generation.urllib.request.build_opener", lambda *_args: FakeOpener())
    result = generate_gemini_study_json("gemini-2.5-flash", "source evidence")
    assert result == {"ok": True}
    assert "test-secret-key" not in calls["url"]
    assert calls["headers"]["X-goog-api-key"] == "test-secret-key"
    assert calls["timeout"] == 180
    assert calls["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert calls["body"]["generationConfig"]["responseSchema"]["required"]
    assert "additionalProperties" not in str(calls["body"]["generationConfig"]["responseSchema"])
    assert "source evidence" in calls["body"]["contents"][0]["parts"][0]["text"]
