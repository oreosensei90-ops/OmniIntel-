from __future__ import annotations

import pytest

from omniintel.video_intelligence import (
    ClaimVerdict,
    OllamaLocalVisionAdapter,
    SemanticMatch,
    VisualDescription,
)


def test_ollama_adapter_is_loopback_only_and_requires_explicit_model() -> None:
    adapter=OllamaLocalVisionAdapter("local-vision-model",timeout_seconds=45)
    assert adapter.endpoint=="http://127.0.0.1:11434/api/generate"
    assert adapter.model_id=="local-vision-model"
    with pytest.raises(ValueError):
        OllamaLocalVisionAdapter("",timeout_seconds=45)
    with pytest.raises(ValueError):
        OllamaLocalVisionAdapter("model",timeout_seconds=2)


def test_ollama_adapter_validates_visual_description(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter=OllamaLocalVisionAdapter("vision")
    monkeypatch.setattr(adapter,"_generate",lambda prompt,image=None: {"description":"A lecture slide"})
    result=adapter.describe(b"image",mime_type="image/jpeg",timestamp_ms=1200)
    assert result==VisualDescription("A lecture slide","vision")


def test_ollama_adapter_validates_semantic_score(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter=OllamaLocalVisionAdapter("vision")
    monkeypatch.setattr(adapter,"_generate",lambda prompt,image=None: {"score":0.92,"rationale":"The frame shows the formula being discussed."})
    result=adapter.score(b"image","The lecturer explains the formula.",timestamp_ms=2000)
    assert result==SemanticMatch(0.92,"The frame shows the formula being discussed.")
    monkeypatch.setattr(adapter,"_generate",lambda prompt,image=None: {"score":True,"rationale":"bad"})
    with pytest.raises(TypeError):
        adapter.score(b"image","words",timestamp_ms=2000)


def test_ollama_adapter_validates_cross_modal_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter=OllamaLocalVisionAdapter("vision")
    monkeypatch.setattr(adapter,"_generate",lambda prompt,image=None: {"verdict":"INSUFFICIENT","rationale":"The frame does not show enough detail."})
    result=adapter.verify("A formula is displayed.","A classroom scene.",None)
    assert result==ClaimVerdict("INSUFFICIENT","The frame does not show enough detail.")
    monkeypatch.setattr(adapter,"_generate",lambda prompt,image=None: {"verdict":"MAYBE","rationale":"unclear"})
    with pytest.raises(ValueError):
        adapter.verify("claim","description",None)
