# OmniIntel Android — video-to-notes and offline reader

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

## Online video → notes

On the library screen, paste a supported YouTube URL, enter the HTTPS OmniIntel API address and server-issued bearer token, and approve both public metadata/caption retrieval and external AI processing. The app submits a durable job, polls its status, downloads the generated reader JSON and imports it directly into Room. The API token remains in the current app session; only the API origin is saved locally. The app uses the Cloudflare Worker API contract and downloads completed reader JSON from its short-lived B2 result URL. The server must be deployed and configured with its worker, YouTube adapter and AI provider. Videos without retrievable public captions can use the authorized media-upload fallback from the same screen. Choose an audio/video file (up to 250 MiB), approve uploading it to your server and approve AI processing. The media is uploaded directly to the private Backblaze bucket through a short-lived URL; the local processing agent downloads it, then removes its temporary copy after processing. The agent needs FFmpeg, ffprobe and a preinstalled local faster-whisper model directory. No DRM or access-control bypass is performed.

Online processing requires Android INTERNET permission. Local reading, annotations, playback and backups continue to work offline.

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

- The app uses the network only when the user explicitly submits a video to a configured OmniIntel API. No analytics or provider API key is embedded in the APK.
- Reader import and library search are local-only.
- Media files are explicitly selected by the user and uploaded only after explicit consent to the private B2 bucket; a short-lived presigned URL is used, and media is not exposed publicly.
- The YouTube intake queue exports a portable JSON handoff. On a computer with the local Python engine installed, run `omniintel-youtube-queue ./omniintel.db ./omniintel-video-queue.json --output-dir ./exports --approve-network`. This retrieves public metadata/captions only; it does not download media. Each completed video produces a reader JSON file, and failures are listed in `queue-results.json`.
- Annotation export/backup, background media controls, large-library FTS indexing, native ASR and complete study workflows remain future work.
