# AI-assisted study-guide generation

OmniIntel can now create a local-model-assisted learning draft from an already ingested
source. This is an optional generation stage, not part of default ingestion.

## Privacy and approval

- The adapter contacts only `http://127.0.0.1:11434` (loopback Ollama).
- The CLI requires `--approve-local-model` before sending source excerpts to that local process.
- No cloud endpoint, API key, browser session, cookie or remote model provider is configured.
- The model name selects an Ollama model already installed locally; it is not a URL.
- Source excerpts are bounded to at most 40 evidence records and 30,000 characters.
- Text inside excerpts is untrusted data, not instructions to the model.

## Generated material

The model returns a strict JSON structure containing:
- one chapter summary;
- 3–10 concept explanations;
- 0–15 glossary entries;
- 0–5 worked examples, explicitly treated as hypothetical applications;
- 3–10 review questions.

Every item must cite one or more exact evidence IDs from the source context. Unknown IDs,
missing citations, malformed output, unexpected fields and out-of-range content are rejected.
The resulting version is stored in the same SQLite knowledge/textbook system and serialized
using the existing reader tree contract for Android/Web import.

## Review and provenance

Generated blocks are `EXPLANATION` or `DERIVED`, never `SOURCE`. All generated blocks
are `NEEDS_REVIEW`; claim, knowledge-unit and textbook evidence links begin `PENDING`.
The model cannot accept its own citations or publish claims. A human reviewer must check
whether each excerpt actually supports its explanation and then use the existing review
APIs. An allowed citation ID is only a syntactic/source-boundary check, not proof of entailment.

## Install and run

```bash
python -m pip install -e '.[dev]'
# Start Ollama locally and pull a model suitable for structured JSON output.
ollama pull qwen2.5:7b
omniintel-study-guide ./omniintel.db SOURCE_ID \
  --model qwen2.5:7b --approve-local-model \
  --output ./exports/study-guide.json
```

Import `study-guide.json` in OmniIntel Android with **Import reader JSON**. It is saved
into the offline Room library. This command assumes the source and its evidence have
already been ingested by the existing local-caption, local-ASR or document pipeline.

## Current limitations

This is a first provider adapter and draft generator, not an autonomous subject expert.
It does not yet perform semantic entailment verification, contradiction-scope resolution,
expert quality scoring, source coverage measurement, concept graph clustering, or a
multi-provider routing policy. The generated content must be reviewed before publication
or study reliance.

## Reader export compatibility

The output is normalized to the portable reader contract: it includes a source catalog,
anchor source and alignment policy, plus Android/Web-safe transcript excerpts and
page/element locators. Source timestamps remain local; no course clock is invented.

For a YouTube video, run the caption intake first, then reuse its printed source ID:

```bash
omniintel-youtube ./omniintel.db 'https://www.youtube.com/watch?v=VIDEO_ID' \
  --approve-network --language en --output ./exports/video-reader.json
SOURCE_ID="$(python -c "import json; print(json.load(open('./exports/video-reader.json', encoding='utf-8'))['source']['id'])")"
omniintel-study-guide ./omniintel.db "$SOURCE_ID" \
  --model qwen2.5:7b --approve-local-model \
  --output ./exports/ai-study-guide.json
```
