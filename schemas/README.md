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
- `event-envelope.schema.json`: versioned domain event envelope.
- `knowledge-unit.schema.json`: typed pedagogical knowledge records.
- `claim.schema.json`: atomic claims with provenance and review status.
- `claim-evidence.schema.json`: reviewed claim/evidence relationship records.
- `textbook-block.schema.json`: canonical structured textbook block with provenance and review state.
- `source-clock-alignment.schema.json`: measured, explicitly reviewed cross-source clock offset with a fixed sign convention.
- `reader-session.schema.json`: durable local course-reader position and source anchors.
- `reader-export.schema.json`: portable synchronized-reader payload shared by the Web and Android reader prototypes.
- `execution-plan.schema.json`: read-only local input inventory and network-disabled plan metadata.
- `quality-benchmark-report.schema.json`: versioned deterministic quality metrics and per-case results.

These schemas describe data contracts; they do not imply that all corresponding application features have been implemented.

The local execution plan contains device-local paths and is not a portable sync payload. Reader sessions reference course-version/source IDs and require membership validation by the receiving application. Clock-alignment schemas preserve review state; schema validity never authorizes an alignment. Benchmark schemas validate report structure only, not metric quality or dataset representativeness.
