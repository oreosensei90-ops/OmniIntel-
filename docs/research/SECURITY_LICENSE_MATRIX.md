# OmniIntel Security and License Matrix

Updated: 2026-11-20

## Reuse decision vocabulary

- **Potentially compatible:** MIT/Apache signal; still check exact file notices, dependency/model licenses, security and attribution.
- **Conditional:** GPL/AGPL or PolyForm Noncommercial; no reuse until legal compatibility and distribution/commercial-use position is decided.
- **Unclear:** missing, NOASSERTION, README-only or conflicting license; treat as unlicensed for reuse until verified.
- **Reject integration:** reverse-engineered sessions, undocumented private endpoints, account pooling/rotation, quota circumvention, opaque binaries or unsafe credential handling.

## Known license signals

| Reference | Signal | Decision |
|---|---|---|
| drpwchen/lecture-to-notes; thewh1teagle/vibe; Enyu-Liu/video-to-notes-skill; Allen0497/video-to-notes; amroeser/lecture-notes-app; davertor/take-notes; risonsimon/interactive-deep-notes | MIT | Potentially compatible; exact-file/dependency review required; no code copied. |
| HHousen/lecture2notes | AGPL-3.0 | Architecture study only absent compatibility decision. |
| CoursePilot; Course Navigator; Video Study Pipeline; Scribly; LearnQuest | MIT | High-value reference; no code copied. |
| LearnNote | Apache-2.0 | High-value reference; no code copied. |
| alishahryar1/free-claude-code | AGPL-3.0-only | No code reuse absent decision. |
| terzigolu/warp-lite | AGPL family | UX inspiration only. |
| suitedaces/computer-agent | Apache-2.0 signal | Permission concepts; deeper security review pending. |
| Corporationakht/LocalCodeCli | MIT metadata | Resolve source lineage before reuse. |
| crazyrob425/BlacklistedAIProxy | GPL-3.0 | Reject integration; unsafe access patterns. |
| DuskBotAI/duskbot | PolyForm Noncommercial | No commercial code reuse absent permission. |
| decolua/9router | MIT | Potentially compatible, but insecure defaults require hardening. |
| hassanmsthf11/unlimited-claude-AI | MIT | Potentially compatible; Puter service terms separate. |
| codeaashu/free-claude-code | MIT claimed | Verify LICENSE, lineage and dependencies; Python version mismatch. |
| Other repositories | Missing/ambiguous/README-only/unknown unless explicitly verified in original register | No code reuse until verified. |

## Threat model and controls

### Provider credentials and sessions
- Store secrets in a secret manager or encrypted server-side store; never in client code or source control.
- Hash application API tokens; compare in constant time; rate-limit auth; use short, revocable sessions.
- Separate tenant/user keys, administrator credentials and provider credentials.
- Never accept browser cookies, OAuth refresh tokens or session exports from unofficial access projects.
- Redact authorization headers, query tokens, prompt content and upstream response bodies.

### SSRF and network
- Validate scheme, host, resolved IP and redirect destination on every hop.
- Deny loopback, link-local, private, multicast and metadata-service IPs for untrusted targets; revalidate DNS to mitigate rebinding.
- Restrict upstream hosts to provider allowlists where possible.
- Enforce byte limits, timeouts and content-type checks.
- Do not allow user endpoints or agent tools to pivot into local services or cloud metadata.

### Agent/computer use
- Treat shell, browser, screen, microphone and accessibility as separate capabilities.
- Default deny; least privilege, per-action approvals, visible history and immediate cancellation.
- Never expose browser cookie jars or saved passwords.
- Sandbox execution; argv arrays, no shell interpolation, resource quotas and filesystem/network allowlists.
- Confirm before publishing, sending, deleting or executing side effects.

### Content and model output
- Transcripts, captions, OCR, web pages and model output are untrusted data, not instructions.
- Preserve source hashes/evidence IDs; validate model citations against the job's allowed evidence set.
- Escape/sanitize rendered HTML and active content; enforce CSP and safe URL policies.
- Distinguish source facts, inference, hypotheses and unsupported content.
- External transfer consent must be source/job/provider-bound.

### Rights and licensing
Repository license, dependency license, model weights, datasets, API terms and media rights are separate checks. No public video URL grants download or redistribution rights.

## Mandatory pre-adoption checklist

1. Verify canonical upstream and exact commit.
2. Verify LICENSE file and file-level notices.
3. Inspect dependencies, install scripts, postinstall hooks and binaries.
4. Scan secrets, credential exfiltration, telemetry and prompt logging.
5. Review network calls, redirects, SSRF, DNS rebinding and auth.
6. Build/test in isolated Linux; do not execute opaque binaries.
7. Review model/dataset/API/media terms separately.
8. Record exact copied files, modifications, attribution and notices.
9. Add SBOM and dependency/license scan.
10. Obtain explicit approval before adding dependencies or enabling external transfer.
