# OmniIntel Android — offline reader

Native Kotlin + Jetpack Compose reader for local OmniIntel synchronized-reader JSON exports. It renders chapters, blocks, provenance, transcript excerpts and PDF page citations. Users can pair an exact course source with a local audio/video file and jump to source-local evidence timestamps; unreviewed cross-source offsets are never applied.

## Import and offline library

1. Export a reader document from the Python engine:

   ```bash
   omniintel reader-open ./omniintel.db VERSION_ID > ./course-reader.json
   ```

2. Transfer the JSON file to Android and select it with the system document picker.

The app stores the imported reader content on-device in Room v3: sources, chapters, blocks and evidence references are normalized into separate tables. The original JSON is limited to 50 MiB and parsed on an IO dispatcher. Once imported, the reader content remains available offline even if the original document provider does not grant persistent access.

## Persistence and migration

- Private per-block notes and bookmarks are stored in Room.
- Paragraph-level reading position is saved as the last visible block per textbook version and restored when reopening.
- Library-wide search covers book and chapter titles, block text, evidence excerpts and private notes.
- Existing DataStore notes, bookmarks and chapter positions are migrated transactionally on first startup. The legacy store is cleared only after the Room migration commits.
- Re-import replaces normalized source content transactionally while preserving annotations and reading progress for matching block IDs.

## Build

With JDK 17 and Android SDK platform/build-tools 35:

```bash
cd apps/android
./gradlew assembleDebug
```

## Privacy and current boundaries

- No INTERNET permission, account, analytics, provider key or remote endpoint.
- Reader import and library search are local-only.
- Media files are explicitly selected by the user and attached to a chosen source; media bytes are not uploaded.
- The YouTube intake queue currently stores validated links only. Video acquisition, transcription and textbook generation are not yet connected to that queue.
- Annotation export/backup, background media controls, large-library FTS indexing, native ASR and complete study workflows remain future work.
