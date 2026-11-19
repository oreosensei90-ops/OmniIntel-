# Local asset storage

OmniIntel's initial asset repository stores imported local files as immutable, content-addressed
blobs. SQLite stores metadata and source associations; bytes remain outside the database.

## Storage model

- `asset_blobs` is keyed by lowercase SHA-256 and records detected media type, byte size and an
  internally generated relative storage key.
- `source_assets` associates a blob with a source, role and display name.
- Identical content is stored once per asset store and may be associated with multiple sources or
  roles. Re-importing the same blob for the same source and role returns the existing record.
- Storage keys are generated from the content hash. User filenames are metadata only and are
  never used to construct paths.

## Safety properties

- Local file/byte ingestion only; there is no URL fetcher or archive extractor.
- A configurable byte limit is enforced while streaming into a staging file.
- MIME type is inferred from content signatures, not filename extensions. Unknown binary content
  is rejected rather than guessed.
- Files are staged and atomically moved into a hash-derived path.
- Resolved paths are constrained to the configured storage root and can be SHA-256 verified.
- Database foreign keys protect source and blob references; assets are immutable by convention.

## Current limitations

- The initial signature detector covers common image, audio, video, PDF, ZIP and UTF-8 text types;
  it does not deeply validate file structure or sanitize active content.
- ZIP-based office formats are currently identified generically as ZIP. No archive extraction,
  OCR, image decoding, transcoding, thumbnailing or malware scanning is performed.
- IMAGE and DIAGRAM textbook blocks can link source-owned image assets through block_assets;
  database triggers reject cross-source, non-image and role-incompatible attachments.
- Publication audit blocks visual blocks with no linked image asset. This validates metadata links,
  not successful image decoding or semantic relevance.
- Backups must include both the SQLite database and the asset directory. Orphan cleanup and
  deletion/retention policies remain future work.

## Python API

```python
from omniintel.assets import AssetStore

assets = AssetStore("./omniintel.db", "./omniintel-assets")
record = assets.add_file(source_id, "./lecture-slides.pdf", role="DOCUMENT")
path = assets.resolve_path(record.id)  # verifies SHA-256 by default

from omniintel.textbook import TextbookStore

# Attach only after creating an IMAGE or DIAGRAM block.
TextbookStore("./omniintel.db").link_asset(block_id, record.id, caption="Lecture slide")
```
