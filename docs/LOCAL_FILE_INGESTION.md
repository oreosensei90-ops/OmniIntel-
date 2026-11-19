# Local file source registration

OmniIntel can register a user-selected local file as a source and preserve its original bytes
in the content-addressed asset store.

## CLI

\`\`\`bash
omniintel import-file ./omniintel.db ./omniintel-assets ./lecture.pdf --title "Lecture 01"
\`\`\`

The command prints the source ID, asset ID, SHA-256, detected media type, byte size and modality.
The asset directory is separate from the SQLite database and must be included in backups.

## Initial supported types

- PDF and UTF-8 text: registered as DOCUMENT assets.
- Common detected audio formats: registered as AUDIO assets.
- MP4/WebM: registered as VIDEO assets.
- Common detected image formats: registered as ATTACHMENT assets.

The detector uses content signatures, not filename extensions. ZIP containers are rejected by this
adapter; office archives are not unpacked. A maximum file size is enforced while the asset store
streams bytes to staging.

## Provenance and rights

The source metadata records the local-ingestion method, modality, detected media type, original
filename and rights_status=UNVERIFIED. Importing a file does not establish ownership, permission,
public-domain status or a right to redistribute it. The user remains responsible for confirming
authorization before processing or sharing its contents.

## Deliberate boundaries

This is source registration and byte preservation, not document or media extraction. It does not
parse PDF pages, extract text, OCR images, transcribe audio, decode video, inspect archives, fetch
URLs, execute embedded content or scan for malware. Those are separate pipeline stages and must
have their own limits, evidence models and tests.
