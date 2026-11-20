# OmniIntel Web — online video-to-notes + offline reader

The Web client connects to a separately deployed OmniIntel API for consent-gated online video-to-notes processing. It also remains an offline reader for previously generated reader JSON exports.

## Online video → AI notes

1. Deploy the OmniIntel API and worker using the root README and `docs/ONLINE_VIDEO_TO_NOTES.md`.
2. Serve this directory over HTTPS (or localhost for development).
3. In **Video → Notes**, enter a YouTube video URL, the API origin and the server-issued bearer token.
4. Explicitly approve public metadata/caption retrieval and sending the transcript to the server-configured AI provider.
5. The client submits a background job, displays its progress, and opens the resulting AI-assisted reader export automatically.

The API token is stored only in session storage for the current tab. The API origin is stored locally. The provider key stays on the local processing machine and is never embedded in the Web app. The current client contract targets the Cloudflare Worker + D1 + private Backblaze B2 architecture. Configure exact-origin CORS on both the Worker and B2 bucket. Media uploads use a short-lived presigned B2 URL; completed reader JSON is fetched from a short-lived result URL.

## Supported source processing

The current hosted source adapter retrieves bounded public YouTube metadata and public caption sidecars. It does not download video/audio, use cookies, access private captions, or bypass DRM/access controls. If public captions are unavailable, upload an audio/video file you are authorized to process (up to 250 MiB). The worker requires FFmpeg, ffprobe and a preinstalled local faster-whisper model configured through `OMNIINTEL_ASR_MODEL_PATH`.

AI output is a structured, timestamp/evidence-linked study-guide draft. Evidence IDs are constrained to the supplied transcript records, but that does not prove semantic entailment or factual correctness. Generated blocks and links require human review.

## Offline reader

- Open a local reader JSON export.
- Navigate chapters and search across the textbook.
- Inspect source evidence, transcript excerpts and PDF page citations.
- Attach an exact local audio/video source for timestamp seeking.
- Save generated/imported reader books, per-block notes and bookmarks in IndexedDB, then reopen the most recent book automatically.
- Study existing definitions, exercises and flashcards with local active recall.
- Back up and restore notes, bookmarks, study ratings and reading positions.

Offline reading, notes, bookmarks and study progress do not require an API connection.

## Security

- Remote processing requires HTTPS, a configured API origin, bearer authentication and explicit consent.
- The Web client never accepts a user-entered provider endpoint or API key.
- The API server must use a long random bearer token, exact CORS allowlist, TLS reverse proxy, persistent storage and operational protections.
- User-provided reader exports remain untrusted and are rendered with text-only DOM APIs.
