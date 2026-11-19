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

## Android queue → local engine

1. Add YouTube URLs in the app and choose **Export processing queue**.
2. Transfer `omniintel-video-queue.json` to a computer running the Python engine.
3. Install the optional adapter with `python -m pip install -e '.[youtube]'`.
4. Run the queue command shown above. Network access is explicit and public captions only.
5. Transfer each `*-reader.json` result back to Android and import it into the offline library.

This is a user-mediated file handoff, not automatic background processing or an in-app network client.

## Annotation backup and restore

Use **Back up notes** to export notes and bookmarks from the Room library to a portable JSON file. **Restore notes** validates the schema, caps the file at 5 MiB and 100,000 records, ignores references to blocks that are not in the local library, and preserves newer local edits when merging. Backups stay under the user's control; no network sync is performed.

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
- The YouTube intake queue exports a portable JSON handoff. On a computer with the local Python engine installed, run `omniintel-youtube-queue ./omniintel.db ./omniintel-video-queue.json --output-dir ./exports --approve-network`. This retrieves public metadata/captions only; it does not download media. Each completed video produces a reader JSON file, and failures are listed in `queue-results.json`.
- Annotation export/backup, background media controls, large-library FTS indexing, native ASR and complete study workflows remain future work.
