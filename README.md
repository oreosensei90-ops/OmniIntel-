# OmniIntel

**A local-first learning and personal knowledge ecosystem.**

OmniIntel is being engineered to turn authorized learning sources—videos, audio, transcripts, documents and presentations—into detailed, evidence-grounded textbooks and reusable study resources.

The product direction includes native Android and installable web applications, a modular processing engine, offline library/search, structured knowledge, document publishing and personal study tools.

## Current implementation status

This repository is at the beginning of its implementation. The foundation branch introduces the Python engine package, deterministic transcript ingestion, SQLite persistence and migration integrity checks. Android, web, media extraction, AI inference and publishing are planned integrations and must not be mistaken for completed features.

## Engineering principles

- Local-first data ownership; reading and saved-library access should work offline.
- Preserve original source material and provenance.
- Separate source evidence, interpreted knowledge and learning artifacts.
- Treat model output and imported content as untrusted until validated.
- Make long-running jobs resumable and idempotent.
- Never claim a source citation proves a claim without checking relevance.
- External processing requires explicit user approval.
- Keep provider, model and platform integrations replaceable.
- Preserve user-authored notes and history across regeneration.

## Repository map

- `engine/omniintel/` — Python domain and persistence foundation.
- `schemas/` — versioned cross-platform data contracts.
- `tests/` — automated tests.
- `docs/` — architecture, decisions, research and roadmap.
- `apps/` — future Android and web applications.

## Python development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

Core persistence initially uses the Python standard library. Optional publishing dependencies are installed with `python -m pip install -e '.[publishing]'`.

## Rights and source access

Only process media and documents the user is authorized to access and use. Public availability does not automatically grant download, reproduction or redistribution rights. Respect platform terms, copyright and access controls. OmniIntel will not implement DRM or access-control circumvention.

## License

The repository's existing MIT license is retained. Third-party code, model weights, fonts, datasets and native dependencies require separate license review before distribution.
