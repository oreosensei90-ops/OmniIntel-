# OmniIntel Web — online video-to-notes + offline reader

The Web client connects to a separately deployed OmniIntel API for consent-gated online video-to-notes processing. It also remains an offline reader for previously generated reader JSON exports.

## Online video → AI notes

1. Deploy the OmniIntel API and worker using the root README and `docs/ONLINE_VIDEO_TO_NOTES.md`.
2. Serve this directory over HTTPS (or localhost for development).
3. In **Video → Notes**, enter a YouTube video URL, the API origin and the server-issued bearer token.
4. Explicitly approve public metadata/caption retrieval and sending the transcript to the server-configured AI provider.
5. The client submits a background job, displays its progress, and opens the resulting AI-assisted reader export automatically.

The API token is stored only in session storage for the current tab. The API origin is stored locally. The OpenAI key is server-side only and is never embedded in the Web app. CORS must be configured on the server for the exact Web origin.

## Supported source processing

The current hosted source adapter retrieves bounded public YouTube metadata and public caption sidecars. It does not download video/audio, use cookies, access private captions, or bypass DRM/access controls. If public captions are unavailable, the job fails with an explicit error. User-authorized media upload and hosted ASR fallback are not yet connected to this API.

AI output is a structured, timestamp/evidence-linked study-guide draft. Evidence IDs are constrained to the supplied transcript records, but that does not prove semantic entailment or factual correctness. Generated blocks and links require human review.

## Offline reader

- Open a local reader JSON export.
- Navigate chapters and search across the textbook.
- Inspect source evidence, transcript excerpts and PDF page citations.
- Attach an exact local audio/video source for timestamp seeking.
- Save per-block notes and bookmarks in IndexedDB.
- Study existing definitions, exercises and flashcards with local active recall.
- Back up and restore notes, bookmarks, study ratings and reading positions.

Offline reading, notes, bookmarks and study progress do not require an API connection.

## Security

- Remote processing requires HTTPS, a configured API origin, bearer authentication and explicit consent.
- The Web client never accepts a user-entered provider endpoint or API key.
- The API server must use a long random bearer token, exact CORS allowlist, TLS reverse proxy, persistent storage and operational protections.
- User-provided reader exports remain untrusted and are rendered with text-only DOM APIs.
