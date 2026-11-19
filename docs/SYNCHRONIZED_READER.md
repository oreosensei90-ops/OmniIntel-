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

The first Android reader prototype can attach one user-selected local audio or video file to an explicitly selected course source. Evidence jump controls are enabled only when the evidence source ID matches that selected source; the reader seeks using the source-local millisecond locator and never applies a course-clock offset to the media player. Android playback currently uses platform MediaPlayer/VideoView, so codec support follows the device platform. Playback pauses when the activity leaves the foreground; background playback, persistent media grants, playback-service controls, subtitles, Room-backed library state and device-level testing remain future work. Search spans all chapters and results identify the chapter with an explicit navigation action.


The Web Reader displays an accepted course-clock time and alignment status separately from the source-local citation time. Media seeking always uses the source-local locator and requires the exact source to be attached; the mapped course clock is informational and is never substituted for a media player's local timeline.


## Android reading progress

The native Android prototype stores the last-opened chapter index in Preferences DataStore, keyed by the immutable textbook version ID. Reopening that version restores the saved chapter, clamped to the current chapter range. This is local device state only; it does not yet store a paragraph-level scroll offset, selected text, annotations, bookmarks or cross-device sync. A Room-backed source/library and richer reader-session model remain planned.


Android block notes and bookmarks are stored locally in Preferences DataStore, keyed by textbook version and stable block ID. Notes are limited to 5,000 characters per block and can be cleared by saving an empty note. Bookmark state is independent per block. These are device-local reader conveniences, not yet a full annotation model: there is no paragraph-level anchoring, highlight ranges, export/import of annotations, conflict handling or cross-device sync. Replacing a textbook version does not silently merge notes into a different version.


The Android reader can filter the library view to bookmarked blocks across all chapters and search block text, evidence excerpts, source titles and saved private notes. Search results retain their chapter label and can jump back to the owning chapter. This is a local reader index, not a full-text database or semantic search engine.


## Android library catalog

The Android reader keeps a local Room catalog of imported textbook versions. It stores the version ID, display title, source/chapter counts, original Storage Access Framework document URI, import time and last-opened time. On import it requests a persistable read grant; entries that cannot retain access remain available for the current session but are not added as durable library entries. Users can reopen or remove catalog entries. Removing an entry releases the persisted URI grant; it does not delete the user's original document. Room stores catalog metadata only: the JSON export is still parsed on demand, and chapter/block content, media derivatives and annotation records are not yet normalized into Room. There is no cloud sync or backup yet.
