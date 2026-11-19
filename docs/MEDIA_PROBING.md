# Local media probing

OmniIntel can inspect a user-selected local audio/video asset with the external FFmpeg ffprobe executable. This is a metadata stage only: it does not decode or transcode the media, extract audio, extract frames, download subtitles, or contact a remote service.

## Workflow

1. Register a local file with the existing import-file command. The original bytes are preserved in the content-addressed asset store and the source rights status remains UNVERIFIED.
2. Run probe-media with the returned asset ID.
3. The engine verifies the original asset size and SHA-256 before invoking ffprobe.
4. The probe records the container name, duration, byte size, selected stream metadata and the ffprobe version.
5. If the source duration was not previously known, the validated media duration is written to the source record. Existing duration metadata is not overwritten.
6. Repeating the same probe with the same asset, ffprobe version and configured limits reuses the existing result.

Example:

```bash
omniintel import-file ./omniintel.db ./omniintel-assets ./lecture.mp4
omniintel probe-media ./omniintel.db ./omniintel-assets ASSET_ID
```

The command accepts optional limits:

- --timeout: maximum ffprobe runtime in seconds (default 30, maximum 300).
- --max-streams: maximum stream count (default 32, maximum 64).
- --max-output-bytes: maximum JSON output read into memory (default 1,000,000, maximum 4,000,000).

## Security and resource boundaries

- Only an already registered local asset ID is accepted; no URL or arbitrary input path is accepted by the probe API.
- The asset store resolves the path internally and verifies its content hash.
- The subprocess uses an argument array, never a shell command.
- The process receives a minimal environment and no stdin.
- FFmpeg protocols are restricted to file and pipe; this stage does not enable network protocols.
- ffprobe execution has a timeout, stream-count cap, allocation cap, bounded probe/analyze sizes and bounded captured output.
- Parsed stream indexes, dimensions, sample rates, channel counts, strings and duration values are range-checked before persistence.
- Probe results are immutable and keyed by asset hash, tool version, probe schema and configured limits. A changed binary or configuration creates a new record rather than silently rewriting old metadata.

## Dependency and licensing

Install FFmpeg tools so ffprobe is available on PATH. OmniIntel does not bundle the executable. FFmpeg build configurations can be LGPL or GPL depending on enabled components; any future distribution or bundling decision must review the exact binary build and its notices. The metadata adapter itself has no Python runtime dependency on an FFmpeg binding.

## Current limitations

- This stage does not verify the source's copyright or platform download permissions.
- It does not inspect embedded subtitles, chapters, attachments, metadata tags or thumbnails.
- It does not extract or normalize audio, detect speech, transcribe, sample video frames or create frame evidence references.
- A successful metadata probe does not prove that the media fully decodes or is free of malformed-stream behavior.
- ffprobe is an external native parser and is not a hostile-media sandbox. Keep it updated and run it with least privilege.

Bounded local audio extraction and timestamp-preserving resumable transcription are now implemented as separate stages; see docs/AUDIO_EXTRACTION.md and docs/AUDIO_TRANSCRIPTION.md. The next media stages are frame/slide evidence extraction and transcript-to-visual grounding.
