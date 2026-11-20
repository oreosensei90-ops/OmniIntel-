# Visual timeline and transcript alignment

The local frame sampler produces timestamped frame assets. This module converts those samples into
source-bound FRAME_SAMPLE visual events and proposes transcript alignment candidates.

## Alignment rules

- Every frame sample becomes a visual event with its original media timestamp.
- Every transcript segment overlapping the frame timestamp is included.
- If no segment overlaps, only the single nearest segment within the configured tolerance is proposed.
- Events and alignments begin as NEEDS_REVIEW; the heuristic does not claim semantic relevance.
- Database triggers prevent cross-source frame or transcript links.
- Re-running the operation is idempotent for existing frame events and event/segment pairs.

## CLI

~~~bash
omniintel build-visual-timeline DATABASE FRAME_EXTRACTION_ID --tolerance-ms 10000
omniintel visual-timeline DATABASE SOURCE_ID
omniintel review-visual-event DATABASE EVENT_ID ACCEPTED
~~~

This is temporal grounding only. Scene-change detection, OCR on video frames, slide classification,
visual descriptions, semantic transcript/frame matching and cross-modal claim verification remain
separate future stages. A frame timestamp does not prove that its nearby speech describes the frame.


## Uploaded-media worker integration

The uploaded-media worker can run this stage only when the job payload carries
`approve_visual: true`. The web upload form exposes this as a separate consent checkbox;
it is independent of approval for external AI generation. Audio-only uploads are marked
not applicable. For video uploads, the worker extracts timestamped JPEG samples with
bounded defaults (15-second minimum interval, at most 120 requested frames, 128 MiB
total image bytes and 60 million total pixels), then persists FRAME_SAMPLE events and
temporal transcript candidates.

The reader export includes a compact `visual_timeline` summary: event timestamps,
frame indices, review states and proposed transcript intervals. It does not embed frame
bytes or expose filesystem paths. Frame assets remain in the local asset store. All
events and alignments remain NEEDS_REVIEW; this worker stage does not invoke OCR, a
vision model, semantic matching or automatic evidence acceptance. YouTube jobs do not
currently run visual sampling through this path.
