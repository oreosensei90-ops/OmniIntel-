# Local audio extraction

OmniIntel can extract one selected audio stream from a registered local audio/video asset into a normalized PCM WAV derivative for the resumable transcription stage.

## Workflow

1. Register the user-selected media file with import-file.
2. Run probe-media to inspect the local container and stream map.
3. Run extract-audio. By default it selects the first audio stream; use --stream-index to select a different ffprobe stream index.
4. The output is registered as a content-addressed AUDIO asset belonging to the same source. The original video/audio asset remains unchanged.
5. The extraction record stores the source and output hashes, stream index, FFmpeg version, normalized format, duration and source-timeline offset.
6. Pass the returned output_asset_id and time_offset_ms to transcribe-wav.

Example:

~~~bash
omniintel import-file ./omniintel.db ./omniintel-assets ./lecture.mp4
omniintel probe-media ./omniintel.db ./omniintel-assets SOURCE_ASSET_ID
omniintel extract-audio ./omniintel.db ./omniintel-assets SOURCE_ASSET_ID
omniintel transcribe-wav ./omniintel.db ./omniintel-assets SOURCE_ID OUTPUT_ASSET_ID --model /path/to/local-ct2-model --time-offset-ms 250 --language en
~~~

The WAV output is 16,000 Hz, mono, signed 16-bit PCM. The source stream start timestamp is retained separately; FFmpeg resets the extracted audio's internal timestamps to zero, and the transcription stage adds the stored offset to every segment and evidence reference. Negative stream start times are rejected pending explicit timeline review rather than silently clamped.

## Limits and safety

- Only a registered source asset ID is accepted. No URL, playlist or arbitrary filesystem path is accepted by this stage.
- The source asset is SHA-256 verified before ffprobe and FFmpeg are invoked.
- ffprobe and FFmpeg are executed as argument arrays without a shell, with stdin disabled and a minimal environment.
- Input protocols are restricted to file and pipe; no remote network protocol is enabled.
- FFmpeg runtime, output byte size, stream selection, allocation and output format are bounded.
- The generated WAV is checked for exact channel count, sample rate, sample width, PCM encoding, non-empty frames, complete frame data and duration consistency.
- The derived asset and its provenance record are idempotent for the same source bytes, stream, FFmpeg version and configuration.
- The derivative table enforces that input and output assets belong to the same source and that the output role is AUDIO.
- The extractor processes one stream sequentially and does not change the original media.

## Dependency and licensing

Install FFmpeg tools so both ffprobe and ffmpeg are available on PATH. OmniIntel does not bundle these executables. Review the exact FFmpeg build configuration and its LGPL/GPL notices before any future bundling or distribution.

## Current limitations

- The current output is mono 16 kHz PCM. Stereo separation and multi-channel preservation are not implemented.
- Only one selected audio stream is extracted per run.
- Embedded subtitle streams are not extracted by this command; caption ingestion remains a separate local SRT/WebVTT path.
- This stage does not perform speech recognition, diarization, translation, frame extraction or semantic quality review.
- ffmpeg is an external native media parser/decoder, not a hostile-media sandbox. Keep it updated and run with least privilege.
