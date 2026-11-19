# Video visual intelligence

This module adds six connected but deliberately review-gated stages:

1. Scene-change candidates from normalized grayscale frame differences. These are heuristic candidates, not guaranteed cuts.
2. OCR on sampled frames through the existing Tesseract adapter. Word boxes are normalized and confidence is retained.
3. Visual descriptions through an injected provider adapter. No provider is silently selected and no network is used by the engine itself.
4. Semantic frame/transcript scoring through an injected adapter. Temporal proximity only selects candidate pairs; semantic scores are separate.
5. Cross-modal claim checks through an injected verifier. Verdicts are proposals and do not automatically change claim status or publication eligibility.
6. Visual records have explicit review states and source guards. Rendered textbook images are handled separately by exporters using the canonical block asset links.

Every result starts NEEDS_REVIEW. Provider output is untrusted input. Adapter implementations must enforce their own privacy, model licensing and external-transfer consent requirements. The engine does not ship an AI model or claim that a heuristic is semantic understanding.
