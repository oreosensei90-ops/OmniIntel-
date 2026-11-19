# Synchronized course reader

The reader opens a course textbook version while preserving each chapter's source identity. Every evidence link resolves to its original source, locator and transcript excerpt or document-page location. Transcript timestamps remain source-local milliseconds.

Clock mapping uses only accepted alignment records. The anchor source defines course time zero. For an accepted pair with the stored convention t_A = t_B + offset_ms, the reader maps the B clock into A by adding the offset. Unreviewed/rejected alignments are ignored. Conflicting paths beyond the recorded sample interval are marked ambiguous and not mapped.

The reader does not synthesize a common timeline when no accepted alignment exists. Document-page evidence remains page-based and is never assigned a fake media timestamp.

Reader sessions store a local version, anchor/current source, source-local position, chapter and block. The database is device-local in this foundation; no cloud sync is implied.

Commands:

```bash
omniintel reader-open ./omniintel.db VERSION_ID --anchor-source-id SOURCE_ID
omniintel reader-save-position ./omniintel.db SESSION_ID VERSION_ID 125000 --anchor-source-id SOURCE_A --current-source-id SOURCE_B
omniintel reader-resume ./omniintel.db SESSION_ID
```


## Page-native document reading

When a course block cites a PDF page, the reader returns the extracted page text and up to 100 positioned document elements (including element type, normalized bounding box, confidence, provenance and review state). These remain page-native locators. They are not converted to media milliseconds, and pending OCR/structure elements remain visibly reviewable rather than being treated as accepted facts. The current reader API returns these records; a graphical page canvas and tap-to-highlight UI remain application-layer work.


## Import safety and completeness

The Web and Android prototypes cap reader JSON imports at 50 MiB. The Web reader additionally bounds the document to 500 chapters, 25,000 blocks, 100 evidence links per block, 40 transcript excerpts per evidence link and 100 positioned document elements per evidence link. The Android reader applies the same structural ceilings and rejects malformed nested records, duplicate/empty source IDs and evidence links to sources outside the export instead of silently dropping malformed content. These are prototype resource guards, not a substitute for a future streaming reader for very large textbooks.


## Native Android prototype playback

The first Android reader prototype can attach one user-selected local audio or video file to an explicitly selected course source. Evidence jump controls are enabled only when the evidence source ID matches that selected source; the reader seeks using the source-local millisecond locator and never applies a course-clock offset to the media player. Android playback currently uses platform MediaPlayer/VideoView, so codec support follows the device platform. Background playback, persistent media grants, playback-service controls, subtitles, Room-backed library state and device-level testing remain future work.
