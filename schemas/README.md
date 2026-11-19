# OmniIntel Shared Contracts

JSON Schema Draft 2020-12 is the initial canonical wire-contract format for Python, TypeScript and Kotlin.

## Rules

- Contract schema version is independent of entity revision.
- IDs are UUIDv7 strings; media time is integer milliseconds.
- Timestamps are RFC 3339 date-time strings, normalized to UTC by producers.
- Unknown source data remains unknown; do not replace null with invented values.
- Imported/model-generated payloads are untrusted until schema and domain validation pass.
- Schema changes are versioned. Do not silently mutate a published contract.
- Cross-record invariants (source ownership, timestamp bounds, graph cycles and evidence relevance) require application-level validation; JSON Schema cannot prove them.
- Keep contract fixtures and validation tests for Python, web and Android clients.

## Initial contracts

- `common.schema.json`: shared UUID and entity envelope definitions.
- `source.schema.json`: source metadata and type.
- `transcript-segment.schema.json`: timestamped transcript segment.
- `evidence.schema.json`: typed source evidence and provenance.
- `job.schema.json`: cross-platform job state representation.
- `event-envelope.schema.json`: versioned domain event envelope.\n- `knowledge-unit.schema.json`: typed pedagogical knowledge records.\n- `claim.schema.json`: atomic claims with provenance and review status.\n- `claim-evidence.schema.json`: reviewed claim/evidence relationship records.

These schemas describe data contracts; they do not imply that all corresponding application features have been implemented.
