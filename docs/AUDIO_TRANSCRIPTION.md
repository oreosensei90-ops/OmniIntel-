# Local audio transcription

OmniIntel now has a local media-to-transcript path: ffprobe identifies audio streams, FFmpeg creates a normalized content-addressed PCM WAV derivative, and an adapter-driven ASR stage transcribes it with persistent chunk checkpoints. Original media remains immutable; transcript segments become source-linked evidence only after every chunk succeeds.

## Current scope

- Accepts an already-ingested PCM WAV asset, including a normalized derivative created by the local extract-audio stage.
- Verifies the source-asset relationship and content-addressed SHA-256 blob before processing.
- FFmpeg extraction enforces local-only protocols, output-size, timeout, stream selection, normalized PCM format and source timeline checks. ASR enforces duration, channel, sample-rate, sample-width, chunk-duration and chunk-byte limits.
- Writes bounded temporary WAV chunks and processes them sequentially.
- Persists each completed chunk in SQLite, keyed by the run identity and exact chunk SHA-256.
- Run identity includes source bytes, adapter name/version, model ID, adapter settings, language and chunking configuration.
- Re-running an interrupted job reuses only completed chunks whose content hash and time bounds still match.
- Inserts transcript segments and SOURCE evidence atomically after all chunks complete.
- Registers stable timestamp evidence references for every segment.
- Refuses to overwrite an existing source transcript. A different model/configuration requires a new source revision until transcript version management is implemented.
- A no-speech result never creates an empty published transcript.

## Optional local backend

Install the optional dependency:

~~~bash
python -m pip install -e '.[asr]'
~~~

Example:

~~~bash
omniintel import-file ./omniintel.db ./assets ./lecture.mp4
omniintel extract-audio ./omniintel.db ./assets SOURCE_ASSET_ID
omniintel transcribe-wav ./omniintel.db ./assets SOURCE_ID OUTPUT_ASSET_ID --model /path/to/local-ct2-model --device cpu --compute-type int8 --threads 4 --language en
~~~

Use the source and asset IDs returned by import-file and extract-audio. The derivative's stored stream offset is applied automatically; manual offset override is rarely needed. By default the selected model must be an existing local CTranslate2 model directory. Voice activity detection is off by default to preserve quiet speech; pass --vad only when you prefer VAD's speed/segmentation trade-off. To explicitly permit a download, pass a model name and add --allow-model-download. This is a network operation and must be a deliberate user choice. Verify model license and resource requirements.

## Adapter contract

An adapter provides a stable name, version, model ID, configuration fingerprint and a method that accepts one temporary WAV chunk and returns relative millisecond segments. The core validates every segment against its chunk duration. The test suite uses deterministic fake adapters; CI does not download model weights or require a GPU.

## Current limitations

- Audio extraction currently normalizes one selected stream to mono 16 kHz PCM WAV. Embedded subtitle extraction, multi-stream transcription and stereo preservation are not yet implemented.
- No word-level timing, diarization, speaker identity inference, language translation, transcript correction or semantic quality scoring yet.
- The faster-whisper adapter is optional and CPU-int8 by default; VAD filtering is disabled by default because voice-activity detection can drop quiet technical speech in lectures. Use the explicit --vad option only when its speed trade-off is acceptable. The adapter is not claimed to run efficiently on Android.
- Mobile ASR requires a separately implemented native Android adapter and device benchmarks. CoursePilot's sherpa-onnx work is a research reference, not a dependency adopted here.
- Transcript reprocessing/version history is not yet implemented. Existing source history is protected from overwrite. Stream start offsets are stored in the run configuration and applied to source evidence timestamps.
- Transcript presence and timestamp integrity do not establish ASR correctness; quality review remains a later stage.
