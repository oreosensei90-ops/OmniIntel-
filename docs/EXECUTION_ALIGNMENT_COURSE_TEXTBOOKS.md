# Approved execution, cross-source alignment and course textbooks

## Approved execution

PlanExecutor accepts the read-only InputPlan dictionary and a user-approved list of stages. It refuses unresolved planner questions, missing approval, unsupported stage names, network-enabled stages, invalid input indices and inputs whose size or SHA-256 changed since the plan snapshot.

The coordinator validates stage/source modality compatibility and deliberately does not invoke a shell, subprocess or network client. The application injects a local handler for each allowlisted stage (REGISTER_SOURCE, EXTRACT_AUDIO, TRANSCRIBE_LOCAL, EXTRACT_PDF_TEXT, SAMPLE_VIDEO_FRAMES, OCR_LOCAL). A handler must itself enforce format-specific resource limits and revalidate the expected input hash at open/use time. Handlers must be idempotent for the supplied plan/stage/input identity because a crash can occur after a handler's side effect but before its checkpoint is committed. Stage results must be JSON objects. Checkpoints are keyed by plan, stage ordinal/name and input hash. A completed identical plan is reused.

This is a coordinator contract, not a claim that all media handlers have been implemented or that a user interface currently presents the approval dialog. The current coordinator is a single-application execution primitive, not a distributed multi-worker scheduler: the application must serialize concurrent submissions for a given plan. Durable worker leases, heartbeats and automatic recovery of a process killed mid-stage remain pending. Handler idempotency is still mandatory because a crash can occur after a side effect but before its completion checkpoint.

## Cross-source clock alignment

estimate_offset uses normalized cross-correlation over caller-supplied numeric feature envelopes sampled at a common interval. Its sign convention is:

time_in_A_ms = time_in_B_ms + offset_ms

The estimate records best and runner-up correlations. AlignmentStore.propose persists the estimate with an input hash, method/version and rationale. New proposals always start NEEDS_REVIEW. Only a deliberate review action can accept or reject a proposal. Sources must both be members of the same collection.

A constant offset does not model clock drift, variable playback speed, edits, pauses, or different recording segments. Such cases require segmented alignment or a more advanced warp model and must remain unresolved until measured.

## Course textbook model

Course textbooks have their own identity and version tree, rather than pretending that one lecture is the parent source of every chapter. Each chapter can be attributed to a source in the course. Evidence links must resolve to a source in the collection and, when a chapter names a source, to that same source. Each evidence link retains its original evidence-reference identity.

The publication audit blocks unaccepted blocks, uncertain provenance, unreviewed evidence, accepted contradictions, unsupported source/derived/external content and unsupported claims. It does not prove semantic correctness or pedagogical quality. A separate publication-gated course exporter now serializes this tree to Markdown, self-contained HTML, PDF and DOCX. It has its own format-specific limitations and must not be confused with the single-source exporter. The course export path is covered by dedicated tests; native math typesetting and full-fidelity visual asset embedding remain future work.

## CLI clock alignment

The CLI accepts precomputed feature envelopes as JSON with signal_a and signal_b arrays. Both arrays must represent the same feature and sample interval. It recomputes the correlation before storing the proposal. The resulting candidate is still NEEDS_REVIEW; the review command is a separate explicit action. Do not use raw transcript timestamps or filename matching as a substitute for a shared measured feature.


## Synchronized course reader

`SynchronizedReader` resolves each course textbook evidence link back to its original source record. Transcript evidence includes a bounded local transcript excerpt and a source-local seek interval. PDF page evidence retains page locators and is not converted into a fabricated media timestamp.

The reader can optionally map source-local times into an anchor source clock. It uses only alignments explicitly marked ACCEPTED. The stored convention is `time_A = time_B + offset`; offsets are propagated through accepted alignment edges, while conflicting paths are marked ambiguous and left unmapped. Alignment intervals still do not model clock drift or playback-rate changes.

Reader positions are persisted in local SQLite with course-version, anchor source, current source, media position, chapter and block references. Save operations validate that all referenced sources and chapter/block IDs belong to the course version. This is a persistence/API foundation, not yet a graphical reader interface or cross-device sync service.

## Offline quality benchmark metrics

`quality_eval` computes deterministic metrics over caller-supplied, versioned fixtures: transcript WER/CER, timestamp boundary MAE, OCR CER, evidence-ID precision/recall/F1, section coverage and alignment offset absolute error. Reports are stored locally with suite and dataset version. These metrics measure comparison against a supplied reference set; they do not establish semantic correctness, completeness, factual accuracy or teaching quality. Benchmark results must be interpreted with expert review and a representative, licensed golden corpus.
