# Offline quality benchmarks

OmniIntel's benchmark evaluator is deterministic and offline. It does not call a model or provider. Fixtures are human-curated JSON arrays; retain dataset version, license/consent and annotation provenance outside or alongside the fixture.

Example case:

```json
[
  {
    "case_id": "lecture-en-001",
    "transcript_reference": "The reference transcript",
    "transcript_hypothesis": "The system transcript",
    "reference_segments": [[0, 1200], [1300, 2500]],
    "hypothesis_segments": [[20, 1210], [1320, 2480]],
    "ocr_reference": "F = ma",
    "ocr_hypothesis": "F = m a",
    "expected_evidence_ids": ["ev-1", "ev-2"],
    "actual_evidence_ids": ["ev-1"],
    "expected_section_ids": ["intro", "proof", "example"],
    "actual_section_ids": ["intro", "example"],
    "expected_offset_ms": 1200,
    "alignment_offset_ms": 1250
  }
]
```

Metrics include normalized WER/CER, OCR CER, positional timestamp-boundary MAE plus unmatched-segment counts, evidence-ID precision/recall/F1, section-ID coverage and alignment absolute offset error. Empty references and empty sets have explicitly deterministic conventions; review those conventions before comparing suites.

Run and persist a report:

```bash
omniintel quality-evaluate ./omniintel.db lecture-golden golden-v1 ./fixtures/lecture-cases.json
omniintel quality-list ./omniintel.db --suite lecture-golden
```

These are metric primitives, not a claim of semantic quality. Evidence-ID matching does not judge whether evidence actually supports a claim. The corpus must be independently annotated and stratified across languages, accents, STEM notation, OCR quality, media types and recording conditions. Add semantic evidence precision/recall and expert pedagogical review as separate human-evaluated tracks; never collapse them into a single opaque score.
