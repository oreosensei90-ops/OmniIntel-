# OmniIntel Provider, Gateway, Agent and Multimodal Audit

Updated: 2026-11-20

## Executive decisions

1. Build a provider-neutral adapter boundary, not a reverse-engineered free-API aggregator.
2. Local inference, self-hosted endpoints, user-key hosted providers and managed hosted providers are distinct privacy/cost routes.
3. No silent local-to-cloud fallback. After a stream emits output, never transparently switch providers.
4. Credentials remain server-side, encrypted if persisted, scoped, revocable and redacted.
5. Computer-use/browser agents require capability-specific approval, isolation, visible actions and a reliable stop control.

## High-value architecture findings

### Verloc
Encrypted provider credentials, hashed application keys, cooldown/recovery, Retry-After handling, bounded analytics, latency/error/token/cost metrics and SSRF protection are useful patterns. Review key rotation, scope separation, cooldown races and SSRF tests before adaptation. Single-instance assumptions may not fit a distributed service.

### Local AI
Ollama `/api/tags` discovery, `/api/ps` loaded-model monitoring, timeouts, keep-alive, generation duration/history and RAM visibility are useful. Do not copy simple key comparisons or unauthenticated health endpoints into public services.

### LocalCodeCli
Explicit model resolution, provider/model identity, separate request pipeline, streaming semantics, structured transport errors, preflight validation and provider cleanup are useful. Resolve its Free Claude Code lineage before reuse.

### Prime Gate
Host validation against DNS rebinding, strict Origin on mutations and double-submit CSRF are generic security concepts. Do not adopt Antigravity-specific OAuth/endpoints. Sampled code exposed raw upstream error text and used a ten-year in-memory session TTL.

### Taskhomie / computer-agent
Granular accessibility, screen-capture, microphone and browser-profile permission concepts are useful. Broad computer/shell/browser control and logging of full instructions/model are risks. No browser cookies or saved credentials may be exposed to agents.

### Free Claude Code projects
Provider adapters, model mapping, rate/concurrency limits, retry/backoff, stream translation, explicit stop and session persistence are useful patterns. These projects do not establish official Anthropic entitlement. Check lineage, Python version and dependencies before selective adaptation.

### 9Router
Multi-provider routing, aliases, format translation, quota tracking, fallback and dashboard are useful. README defaults include a weak example password, fallback API secret, disabled API auth, `0.0.0.0` binding and optional request/response logging. Hardening study only, not a drop-in gateway.

### DuskBot
Agent memory, shared rooms, routines, workspaces and approval prompts are useful product concepts. PolyForm Noncommercial signal blocks commercial code reuse absent permission.

## Batch A — 14 references

| Repository | Disposition |
|---|---|
| utfcmac/local-ai | Local Ollama/model observability ideas; selected source inspected; MIT metadata signal. |
| kunalkcube/verloc | Gateway patterns; selected source inspected; MIT metadata signal; more crypto/SSRF review required. |
| lapoart/Kimi-K3-Code-Free-Desktop | Opaque binary distribution; do not execute. |
| FurqanAhmadKhan/Chatgpt-Reverse-API | Reverse-engineered consumer auth/session/API; reject. |
| alishahryar1/free-claude-code | AGPL-3.0-only; architecture study only. |
| claudeanthropic-free/Claude-Code-Free | Sparse; official entitlement/source depth unverified. |
| ClaudeCodeAnthropic/ClaudeCode-Sonnet-5.5-Free-Desktop | Sparse desktop/binary claim; do not execute. |
| claude-duet-free/Claude-Duet-Free | Collaboration UX lead; shallow review. |
| anthropics-org/Claude-Opus-5.5-Free-Desktop | Unverified affiliation/entitlement; do not execute. |
| irhamkaraman/prime-gate-proxy-antigravity-lik | Generic security concepts only; reject proprietary auth/endpoints and unsafe session defaults. |
| wallquailrespect/claude-ai-ultimate | Sparse/unclear; no integration. |
| suitedaces/computer-agent | Taskhomie agent; Apache-2.0 signal; sandbox/stop/logging review pending. |
| Corporationakht/LocalCodeCli | Router/pipeline patterns; MIT metadata; lineage must be resolved. |
| CombineProsecutor/free-ai-api-proxy | Insufficient source inspection; no integration. |

## Batch B — 24 repositories plus topic index

| Repository | Disposition |
|---|---|
| Zhao73/free-astra | Signed-in Prism/browser-session bridge to undocumented endpoints; reject. |
| liuda30201/AI-Coding | Provider/service catalogue concept; verify each entry and timestamp. |
| Caplet1989/Brokies-AI-Foundry | Modular pipeline lead; deeper module inspection pending. |
| yawumi/free-gpt-api | Third-party free/discounted GPT claim; provider/retention unverified. |
| terzigolu/warp-lite | AGPL terminal UX fork; inspiration only. |
| Joe-Huber/AI-For-Brokies | Discovery lead; limited inspection. |
| technamooz/technamooz-free-Ai | Promotional catalogue; limits unverified. |
| c0m4r/kurczak | Tooling lead; source value not established. |
| oblongfusari/leonardo-ai-free-2026 | External installer/account rotation; avoid. |
| peppery-bearing6441/hailuo-ai-free-2026 | External installer/account rotation; avoid. |
| ripemilitary/kaiber-ai-free-2026 | External installer/account rotation; avoid. |
| quixoticcater/captions-ai-free-2026 | External installer/account rotation; avoid. |
| powersealboil/ai-reverse-proxy-gpt | Proxy/free-access claim; authorization/security unverified. |
| zebbern/no-cost-ai | Free-service catalogue; verify terms/limits individually. |
| velugus9365/ai-reverse-proxy-free-gpt-access | Unverified free-access proxy; do not integrate. |
| obedientthump/otter-ai-free-2026 | External installer/account rotation; avoid. |
| potableteneme/groq-api-free-2026 | Entitlement unverified; use official provider terms only. |
| Mr-Yash-01/VoiceAssistant | Voice UX lead; permissions/privacy review pending. |
| ornatesaddle/fliki-ai-free-2026 | External installer/account rotation; avoid. |
| grokfree/Grokfree | Unofficial access route unverified; no integration. |
| bigsk1/xai-api | Official xAI API and user-owned key only. |
| DuskBotAI/duskbot | Multi-agent/workspace concepts; PolyForm Noncommercial. |
| crazyrob425/BlacklistedAIProxy | GPL-3.0; advertises account pooling/TLS tricks/bypass; do not run. |
| CursorGrok-4-6/Cursor-Grok-4.6-Free | Unverified free-access claim; no integration. |
| Topic: grok-bot-alternative | Discovery index only. |

## Batch C — 3 repositories and 2 products

| Reference | Disposition |
|---|---|
| decolua/9router | MIT; routing/translation/quota/fallback concepts; insecure defaults need hardening. |
| hassanmsthf11/unlimited-claude-AI | MIT; browser/Puter.js chat/artifact UX; not unlimited Anthropic API. |
| codeaashu/free-claude-code | MIT claim; adapters, limits/retries/concurrency and bot UX; Python >=3.14 and lineage review needed. |
| hix.ai/claude | Hosted product with limited free credits and paid agent entitlements; privacy/terms review required. |
| chataibot.pro | Hosted multi-model product; free-plan limits conflicted; Claude listed as paid. |

## Provider contract requirements

- Stable provider/model identity, capability flags and versioned configuration.
- Explicit route class: local, self-hosted, user-key hosted or managed hosted.
- Consent bound to source/job/provider/model and exact data categories transferred.
- Bounded timeout, concurrency, token/output size, retries and cancellation.
- Retry-After, circuit breaker and cooldown; no blind retry of non-idempotent work.
- Stream state machine: retry before first output only when safe; after output, surface failure.
- Structured redacted errors; no raw prompts, keys, cookies or full upstream bodies in logs.
- Authenticated/private health and model discovery.
- No credentials in browser bundles, APKs, URLs, crash reports or telemetry.
- Provider output is untrusted draft content; validate citations against allowed evidence IDs.

## Agent safety contract

- Separate capabilities: selected-file read, media inspection, browser, network, shell, screen, microphone, accessibility and publishing.
- Default deny; approve high-impact capabilities and external side effects.
- Domain/file allowlists; defend against redirect SSRF and private-network pivots.
- Sandboxed processes with CPU/memory/disk/time/output bounds; argv arrays, never shell interpolation.
- No access to browser cookies, password stores or unrelated local files.
- Visible plan, action log, current status and persistent stop/cancel.
- Redacted audit events; do not log raw instructions or transcripts by default.
- Preview separately from publish/send/delete/execute; confirm at side-effect boundary.

## Rejected integration classes

Consumer-session reverse APIs, browser-cookie bridges, account pooling/rotation, quota bypass, TLS fingerprint tricks, opaque executable bundles and unsupported claims of free premium-model access.
