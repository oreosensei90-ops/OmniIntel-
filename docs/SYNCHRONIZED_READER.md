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
