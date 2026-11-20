"""Explicit provider selection for evidence-grounded study generation."""
from __future__ import annotations
from collections.abc import Callable
from typing import Any

def resolve_study_generator(provider: str) -> Callable[[str, str], dict[str, Any]] | None:
    selected = (provider or "").strip().lower()
    if selected == "openai":
        from .remote_generation import generate_openai_study_json
        return generate_openai_study_json
    if selected == "ollama":
        # None selects the existing fixed 127.0.0.1 Ollama adapter.
        return None
    if selected == "freelm":
        from .freelm_generation import generate_freelm_study_json
        return generate_freelm_study_json
    raise ValueError("Unsupported OMNIINTEL_AI_PROVIDER; choose openai, ollama or freelm. No fallback is performed.")
