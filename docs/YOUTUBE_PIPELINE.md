# YouTube caption-to-reader pipeline

The YouTube adapter is an explicit, caption-first intake path. When public captions are
unavailable, it can download only the audio stream and pass it through the existing local
FFmpeg/Faster-Whisper pipeline. The web client asks the user to approve that fallback.

## What is implemented

1. Validates a single YouTube video URL (watch, youtu.be, shorts, live and embed forms).
2. Retrieves bounded public metadata using the optional `yt-dlp` adapter.
3. Retrieves public subtitle sidecars first (manual captions and automatic captions),
   preferring the requested language and otherwise trying English and Hindi.
4. If no usable public captions are available, downloads the audio stream only (never the
   video stream), registers it as a source asset, extracts mono 16 kHz PCM WAV with FFmpeg,
   and transcribes checkpointed chunks with Faster-Whisper. The original YouTube URL and
   video metadata remain attached to the source.
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
python -m pip install -e '.[youtube,asr,dev,publishing]'
# FFmpeg and ffprobe must also be installed and available on PATH.
omniintel-youtube ./omniintel.db 'https://www.youtube.com/watch?v=VIDEO_ID' \
  --approve-network --language en --output ./exports/video-reader.json
```

The approval flag is mandatory. It confirms authorization to process the video and permits
metadata/caption requests. The web client separately explains that, if captions are missing,
the audio stream will be downloaded for transcription. Only audio is downloaded; the video
stream is not saved. No cookies, account credentials, private endpoints or DRM circumvention
are used. Follow the platform's current terms and the source owner's rights. Audio fallback
requires an ASR model configured with `OMNIINTEL_ASR_MODEL_PATH`, or an explicit model ID
plus `OMNIINTEL_ASR_ALLOW_MODEL_DOWNLOAD=1`.

## Android queue handoff

The Android app can export its saved YouTube links as OMNIINTEL_YOUTUBE_QUEUE JSON. Transfer that file to a computer with the Python engine installed, then process it sequentially:

~~~bash
python -m pip install -e '.[youtube]'
omniintel-youtube-queue ./omniintel.db ./omniintel-video-queue.json --output-dir ./exports --approve-network --language en
~~~

The command validates the complete queue before processing, rejects duplicate or mismatched video IDs, caps a batch at 200 items, continues after individual video failures, and writes queue-results.json plus one reader JSON file for each success. Network approval applies to every queued video. Import successful reader JSON files into Android individually. This is a deliberate user-mediated transfer; the offline Android app does not fetch YouTube content itself.

## Android offline handoff

Open OmniIntel Android, choose **Import reader JSON**, and select the generated
`video-reader.json`. The app imports normalized chapters, blocks and evidence into
Room. The resulting book is available offline; no web reader service is required.

## No-caption audio fallback

When no public captions are available, the approved YouTube path downloads only the
audio stream with yt-dlp (bounded to 250 MiB), registers the temporary media asset,
extracts mono 16 kHz PCM WAV with FFmpeg, and runs the existing checkpointed
Faster-Whisper transcription engine. The source URI remains the canonical YouTube URL,
and the transcript records `transcript_origin=youtube_audio_asr`. The temporary download
is not retained as a separate user-facing file; the registered source asset and normalized
WAV remain in the engine asset store so provenance and resumable ASR checkpoints work.

For local runs, configure either a local CTranslate2 model directory with
`OMNIINTEL_ASR_MODEL_PATH`, or explicitly permit a named model download by setting
`OMNIINTEL_ASR_MODEL_ID=tiny` and `OMNIINTEL_ASR_ALLOW_MODEL_DOWNLOAD=1`.
Install FFmpeg/ffprobe on PATH. Hosted CI uses the tiny model, CPU int8 and a cache.

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

The caption CLI prints the persistent `source_id`; pass that ID to `omniintel-study-guide` to generate a local AI-assisted draft from the same ingested source.

## Optional local-model learning draft

The command prints the registered `source_id` and writes it to the reader JSON source
object. If Ollama is installed locally, pass that ID to `omniintel-study-guide` as
documented in [AI_STUDY_GUIDE.md](AI_STUDY_GUIDE.md). The generated draft is separate
from caption ingestion and requires its own explicit approval.
