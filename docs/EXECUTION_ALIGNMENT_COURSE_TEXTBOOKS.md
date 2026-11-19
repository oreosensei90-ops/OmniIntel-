# Approved execution, cross-source alignment and course textbooks

## Approved execution

PlanExecutor accepts the read-only InputPlan dictionary and a user-approved list of stages. It refuses unresolved planner questions, missing approval, unsupported stage names, network-enabled stages, invalid input indices and inputs whose size or SHA-256 changed since the plan snapshot.

The coordinator deliberately does not invoke a shell, subprocess or network client. The application injects a local handler for each allowlisted stage (REGISTER_SOURCE, EXTRACT_AUDIO, TRANSCRIBE_LOCAL, EXTRACT_PDF_TEXT, SAMPLE_VIDEO_FRAMES, OCR_LOCAL). A handler must itself enforce format-specific resource limits and revalidate the expected input hash at open/use time. Stage results must be JSON objects. Checkpoints are keyed by plan, stage ordinal/name and input hash. A completed identical plan is reused.

This is a coordinator contract, not a claim that all media handlers have been implemented or that a user interface currently presents the approval dialog.

## Cross-source clock alignment

estimate_offset uses normalized cross-correlation over caller-supplied numeric feature envelopes sampled at a common interval. Its sign convention is:

time_in_A_ms = time_in_B_ms + offset_ms

The estimate records best and runner-up correlations. AlignmentStore.propose persists the estimate with an input hash, method/version and rationale. New proposals always start NEEDS_REVIEW. Only a deliberate review action can accept or reject a proposal. Sources must both be members of the same collection.

A constant offset does not model clock drift, variable playback speed, edits, pauses, or different recording segments. Such cases require segmented alignment or a more advanced warp model and must remain unresolved until measured.

## Course textbook model

Course textbooks have their own identity and version tree, rather than pretending that one lecture is the parent source of every chapter. Each chapter can be attributed to a source in the course. Evidence links must resolve to a source in the collection and, when a chapter names a source, to that same source. Each evidence link retains its original evidence-reference identity.

The publication audit blocks unaccepted blocks, uncertain provenance, unreviewed evidence, accepted contradictions, unsupported source/derived/external content and unsupported claims. It does not prove semantic correctness or pedagogical quality. Existing single-source PDF/DOCX/HTML/Markdown exporters are not yet wired to this new course-textbook tree; do not imply course-level export is available until a serializer/exporter is implemented and tested.

## CLI clock alignment

The CLI accepts precomputed feature envelopes as JSON with signal_a and signal_b arrays. Both arrays must represent the same feature and sample interval. It recomputes the correlation before storing the proposal. The resulting candidate is still NEEDS_REVIEW; the review command is a separate explicit action. Do not use raw transcript timestamps or filename matching as a substitute for a shared measured feature.
