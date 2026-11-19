# OmniIntel Architecture — Initial Foundation

## Target architecture

OmniIntel is a modular monorepo with native Android and web clients, shared versioned contracts, and a replaceable processing engine. Each platform owns its local database and files; contracts and import/export formats are shared rather than sharing a live SQLite database.

```text
Android (Compose / Room / WorkManager)      Web (React / TypeScript / IndexedDB)
                    \                         /
                     Shared domain + event contracts
                                  |
              Source -> Evidence -> Knowledge -> Learning artifacts
                                  |
          Processing engine / persistent jobs / asset manager
                                  |
        SQLite + FTS / local files / optional approved AI adapters
```

## Three canonical layers

- **Source:** source identity, immutable original assets, transcript segments, visual events and evidence.
- **Knowledge:** topics, concepts, claims, relationships, evidence mappings, provenance and uncertainty.
- **Learning:** textbooks, chapter blocks, annotations, flashcards, assessments and study history.

Do not collapse these layers into one summary field.

## Initial Python slice

The first implementation slice establishes stable identifiers, typed transcript inputs, SQLite persistence, immutable migration checksums and deterministic transcript import. It deliberately does not claim to perform speech recognition, visual understanding or AI reasoning.

## Planned processing flow

1. Inspect and validate an authorized source.
2. Acquire permitted captions/transcript or process user-provided media.
3. Preserve original evidence and timestamps.
4. Extract visual evidence where applicable.
5. Reconstruct topics, concepts and claims.
6. Validate references, coverage, provenance and uncertainty.
7. Compose versioned textbook blocks.
8. Render and validate exports.
9. Publish into the offline library and derive study materials.

## Persistence rules

- SQLite is the initial metadata and relational store; binary assets live outside the database.
- Enable foreign keys on every connection.
- Use short transactions; never hold a transaction open during inference or media processing.
- Configure WAL during database initialization where supported.
- Migrations are numbered, immutable and checksum-verified.
- Full-text indexes are derived and rebuildable from canonical records.

## AI boundary

AI providers are optional adapters. Deterministic core operations must remain available without a model. External processing is disabled unless the user explicitly authorizes it.
