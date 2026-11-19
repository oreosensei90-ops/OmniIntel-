# OmniIntel Web Reader — first offline UI slice

This is a dependency-free, static PWA reader prototype. It opens a **local JSON file** produced by the synchronized reader CLI; it does not connect to a server, upload files, fetch media, or access the OmniIntel database directly.

## Run locally

From the repository root:

```bash
python -m pip install -e .
omniintel reader-open ./omniintel.db VERSION_ID > ./course-reader.json
cd apps/web
python -m http.server 8080
```

Open `http://localhost:8080` and choose `course-reader.json`. The service worker caches only the static reader shell. The selected course JSON remains in memory and is not added to the service-worker cache. Reading position is saved in localStorage; per-block notes and bookmarks use IndexedDB. These are device-local and are not yet exported, synced or merged into the canonical OmniIntel database.

## Included

- Local JSON import with a 50 MiB limit and minimal shape validation.
- Chapter navigation, current-chapter text search, provenance labels and expandable evidence citations.
- Cross-chapter search across block content, transcript excerpts and PDF page text.
- Explicit local audio/video attachment per selected course source; timestamp jumps are enabled only for the exact attached source and never apply unreviewed cross-source offsets.
- Transcript excerpts, PDF page text and positioned document elements with confidence/review state when present in the reader payload.
- Local IndexedDB notes and bookmarks per textbook block.
- Offline active-recall study cards built from existing definition, exercise and flashcard blocks; reveal answers and mark cards known or needing review, with per-browser progress.
- Per-block personal notes and bookmarks stored in IndexedDB on this browser only; no remote sync.
- Responsive desktop/mobile layout and reduced-motion support.
- Offline shell caching; no external fonts, scripts, analytics, APIs or network calls.

## Deliberate limits

This is not the complete web application. It does not yet provide automatic source-file matching, native math/diagram rendering, full-text indexing at large-library scale, export/import of annotations, account/sync, or a server/API. Local media must be selected by the user and paired with the correct course source. Source-specific times are displayed as citations only; no unsupported cross-source seek is invented. The native Android app remains a separate planned application.
