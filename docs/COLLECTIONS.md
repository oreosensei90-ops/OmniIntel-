# Source collections and courses

OmniIntel collections group independent source records without merging their identities, transcripts, evidence references or provenance. A COURSE is the initial use case; PLAYLIST, PROJECT and RESEARCH_SET are also supported.

## CLI

~~~bash
omniintel collection-create ./omniintel.db "Physics 101" --type COURSE --description "Semester 1"
omniintel collection-add-source ./omniintel.db COLLECTION_ID SOURCE_ID --role LEARNING_SOURCE
omniintel collection-add-source ./omniintel.db COLLECTION_ID SLIDE_SOURCE_ID --role SLIDE_DECK
omniintel collection-show ./omniintel.db COLLECTION_ID
~~~

Source membership has a stable ordinal and a role: LEARNING_SOURCE, SLIDE_DECK, CAPTIONS, REFERENCE or NOTES. A source can belong to more than one collection, but it cannot be added twice to the same collection. Ordinals are unique within each collection.

## Important boundary

Collection membership does not prove that two sources share a timeline, that a caption file belongs to a video, or that a slide deck is synchronized with a recording. Those require explicit reviewed alignment records. Claims and textbook blocks must continue to cite their original source-specific evidence references. Multi-source textbook composition, cross-source clock alignment and course-level knowledge graphs are future work.
