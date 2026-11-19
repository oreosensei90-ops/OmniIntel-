# Local audio transcription

OmniIntel now has an adapter-driven local WAV transcription stage with persistent chunk checkpoints. The original audio asset remains immutable; transcript segments become source-linked evidence only after every chunk succeeds.

## Current scope

- Accepts a user-selected, already-ingested, uncompressed PCM WAV asset.
- Verifies the source-asset relationship and the content-addressed SHA-256 blob before processing.
- Enforces audio duration, channel, sample-rate, sample-width, chunk-duration and chunk-byte limits.
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

\`\`\`bash
python -m pip install -e '.[asr]'
\`\`\`

Example:

\`\`\`bash
omniintel import-file ./omniintel.db ./assets ./lecture.wav
omniintel transcribe-wav ./omniintel.db ./assets SOURCE_ID ASSET_ID \\
  --model base --device cpu --compute-type int8 --threads 4 --language en
\`\`\`

Use the source and asset IDs returned by import-file. Model weights are downloaded/managed by faster-whisper/CTranslate2; the OmniIntel core does not silently download models or select an external provider. Choose an already available model and verify its license and resource requirements.

## Adapter contract

An adapter provides a stable name, version, model ID, configuration fingerprint and a method that accepts one temporary WAV chunk and returns relative millisecond segments. The core validates every segment against its chunk duration. The test suite uses deterministic fake adapters; CI does not download model weights or require a GPU.

## Current limitations

- MP3, M4A, FLAC, OGG and video audio extraction are not yet wired to a decoder. Convert through a separately reviewed local decoder stage or use PCM WAV for this initial slice.
- No word-level timing, diarization, speaker identity inference, language translation, transcript correction or semantic quality scoring yet.
- The faster-whisper adapter is optional and CPU-int8 by default; it is not claimed to run efficiently on Android.
- Mobile ASR requires a separately implemented native Android adapter and device benchmarks. CoursePilot's sherpa-onnx work is a research reference, not a dependency adopted here.
- Transcript reprocessing/version history is not yet implemented. Existing source history is protected from overwrite.
- A transcript's presence and timestamp integrity do not establish that ASR text is correct; quality review remains a later stage.

See also the architecture and engineering constitution for provider consent, checkpoint identity, provenance and mobile resource policy.
