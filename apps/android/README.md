# OmniIntel Android — first native reader slice

A native Kotlin + Jetpack Compose reader for local OmniIntel synchronized-reader JSON exports. It renders chapters, blocks, provenance, transcript excerpts and PDF page citations.

## Create a reader export

From a machine with the OmniIntel Python engine installed:

```bash
omniintel reader-open ./omniintel.db VERSION_ID > ./course-reader.json
```

Transfer that JSON file to the Android device, then open it from the system document picker.

## Build

With JDK 17, Android SDK platform/build-tools 35, and Gradle 8.9:

```bash
gradle assembleDebug
```

## Privacy and limits

- No INTERNET permission, account, analytics, provider key or remote endpoint.
- The user explicitly selects a JSON document using Android's Storage Access Framework.
- Import is capped at 50 MiB and parsing runs on an IO dispatcher.
- This is an initial native UI slice. Persistent Room library, media playback, annotations/bookmarks, offline indexing, full textbook typography and study workflows remain future work.
