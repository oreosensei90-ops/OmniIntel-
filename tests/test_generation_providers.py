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