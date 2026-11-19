# Local caption ingestion

OmniIntel can import local SubRip (.srt) and WebVTT (.vtt) caption files into the
canonical transcript/evidence store.

## CLI

```bash
omniintel import-captions ./omniintel.db ./lecture.vtt \
  --title "Lecture 01" --language en --source-uri "file:///authorized/lecture.mp4"
```

The command reports the created source ID, segment count, evidence count, duration and detected
caption format. The source ID can then be used by topic mapping and textbook composition.

## Parser behavior

- Reads local UTF-8 caption files only; it does not fetch URLs.
- Accepts SRT comma-millisecond timestamps and WebVTT timestamps/cue settings.
- Preserves cue start/end times in integer milliseconds.
- Decodes HTML entities, removes presentation tags, joins wrapped cue lines and captures a
  WebVTT voice label as the speaker ID.
- Ignores WebVTT NOTE, STYLE and REGION metadata blocks.
- Sorts cues by start/end time and validates them against the supplied or inferred duration.
- Stores the source transcript as transcript evidence with caption-format metadata.

## Boundaries

This is a deterministic text-caption adapter, not a general subtitle parser. It does not parse
ASS/SSA, TTML, embedded media subtitle streams, styling, karaoke timing, positioning, translations,
or speaker diarization beyond a WebVTT voice label. It does not infer missing words or validate
caption semantic accuracy. Malformed cues fail rather than being silently repaired.
