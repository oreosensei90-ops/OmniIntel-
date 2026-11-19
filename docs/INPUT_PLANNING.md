# Read-only local input planning

The plan-inputs command inspects explicitly selected local files and produces a JSON execution plan. It is a planning stage only: it does not copy/import files, decode media, run OCR/ASR, contact a URL, create a database, or write a manifest.

## Usage

~~~bash
omniintel plan-inputs ./course-folder
omniintel plan-inputs ./course-folder --recursive
omniintel plan-inputs ./lecture.mp4 ./slides.pdf ./captions.vtt --language en,hi
~~~

The planner classifies supported PDF/text, image, audio, video and SRT/WebVTT inputs by bounded content-signature and metadata reads. It reports the next processing stage, coarse resource class, network policy, byte sizes, warnings and unresolved questions. The current limits are 200 selected files, 1 GiB per file and 2 GiB total.

A speech-bearing source without a confirmed language remains blocked for execution. Multiple audio/video files trigger a question about shared versus independent recording clocks. A captions-plus-media bundle is not automatically considered aligned. Image OCR is marked as a reviewable interpretation. PDF pages retain page locators rather than fabricated media timestamps.

## Execution boundary

The command returns ready_for_execution only when no user questions remain. This is not a command executor and does not create jobs yet. A later execution coordinator must:
- Revalidate each path, file size and content hash at execution time (plan/execute TOCTOU boundary).
- Present the exact operations, resources, network behavior and outputs for approval.
- Use argv arrays, never shell interpolation.
- Create idempotent durable jobs/checkpoints only after approval.
- Keep local processing local; no automatic hosted fallback.
- Preserve source-specific provenance and require review for OCR/VLM/semantic alignment.

The plan is a snapshot. Files can change after planning, so its paths and sizes are not trusted execution inputs.
