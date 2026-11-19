# YouTube caption-to-reader pipeline

The first YouTube adapter is an explicit, caption-first intake path. It is deliberately
separate from local-file transcription and does not silently download or process media.

## What is implemented

1. Validates a single YouTube video URL (watch, youtu.be, shorts, live and embed forms).
2. Retrieves bounded public metadata using the optional `yt-dlp` adapter.
3. Retrieves public subtitle sidecars only (manual captions first as supplied by yt-dlp,
   then automatic captions), preferring the requested language and otherwise trying
   English and Hindi.
4. Parses WebVTT into timestamped transcript segments and persists source, transcript,
   evidence and citation references in SQLite.
5. Creates a versioned, source-ordered reader draft. Transcript paragraphs are exact
   extractive text with timestamp evidence links. Review prompts are generated
   deterministically. Repeated capitalized phrases can be surfaced as uncertain glossary
   candidates; definitions are intentionally left for review rather than invented.
6. Writes the existing reader JSON contract, which can be imported into the native
   Android app and retained in its offline Room library.

## Install and run

```bash
python -m pip install -e '.[youtube,dev,publishing]'
omniintel-youtube ./omniintel.db 'https://www.youtube.com/watch?v=VIDEO_ID' \
  --approve-network --language en --output ./exports/video-reader.json
```

The approval flag is mandatory. It confirms that the user is authorized to process the
video's public captions and permits the metadata/caption network requests. No cookies,
account credentials, private endpoints, DRM circumvention, video download or audio
download are used by this adapter. Follow the platform's current terms and the source
owner's rights.

## Android offline handoff

Open OmniIntel Android, choose **Import reader JSON**, and select the generated
`video-reader.json`. The app imports normalized chapters, blocks and evidence into
Room. The resulting book is available offline; no web reader service is required.

## No-caption fallback

Some videos have no public captions or do not expose them in a supported language. The
adapter fails clearly and does not download the media as a fallback. For media the user
owns or is authorized to process, use the existing local-file workflow:

1. Import the local media file with `omniintel import-file`.
2. Probe/extract audio locally with the existing FFmpeg-backed commands.
3. Transcribe a registered PCM WAV with `omniintel transcribe-wav` and an explicitly
   selected local faster-whisper model.
4. Import the resulting transcript into the textbook composition workflow.

Model downloads are disabled by default in the local ASR adapter unless the user
explicitly opts in.

## Honest capability boundary

This milestone is a functional caption ingestion and evidence-linked reader-draft
pipeline, not a generative AI textbook author. It does not invent explanations, factual
summaries, worked solutions or definitions. The generated paragraphs reproduce source
captions, and all glossary candidates remain marked `UNCERTAIN / NEEDS_REVIEW`.
A separately configured and consented knowledge-generation provider is still required
for original explanatory prose, semantic concept extraction and generated study answers.

The CLI output is normalized to the portable Android/Web reader export contract, including
the required source catalog and reader-safe timestamp/page evidence objects. Import it
with **Import reader JSON** in the native app.
