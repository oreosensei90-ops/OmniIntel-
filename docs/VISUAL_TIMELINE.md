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
