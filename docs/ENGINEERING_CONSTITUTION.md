# OmniIntel Engineering Constitution

## Product invariants

1. **Evidence before exposition.** Educational claims should map to source evidence or be clearly labelled as explanation, derivation, external material or uncertainty.
2. **Three data layers.** Source records are immutable evidence; knowledge records are versioned interpretations; learning artifacts are independently versioned presentations and study materials.
3. **Local ownership.** Core reading, saved-library access, search and study content must not require a hosted account.
4. **Explicit data movement.** External inference or processing must be visible, policy-checked and approved by the user.
5. **Honest completeness.** Missing captions, failed extraction, uncertain OCR and incomplete sections must be disclosed. Partial work is never silently labelled complete.
6. **Recoverability.** Persistent jobs use checkpoints, idempotency and bounded retries. Committed user data is not discarded on failure.
7. **Versioned evolution.** Contracts and database migrations are versioned. Historical migrations are immutable and checksummed.
8. **Replaceable integrations.** Models, providers, media tools and platform adapters are behind stable interfaces.
9. **User content is not disposable.** Notes, annotations, corrections, bookmarks and study history survive regeneration and upgrades.
10. **Measured claims.** A feature is complete only when implemented and tested. An interface or adapter alone is not a working integration.

## Trust boundaries

Imported media, captions, transcripts, OCR, documents, provider responses and model outputs are untrusted. They must not be treated as application instructions or allowed to access secrets, private files or privileged operations.

## Engineering workflow

- Make small, reviewable commits on a non-main branch.
- Add tests with each domain capability.
- Run formatting, static checks and tests before claiming success.
- Preserve the existing repository history and MIT license.
- Verify dependency and model licenses independently.
- Never commit credentials, private keys, user media or model weights without verified redistribution rights.
