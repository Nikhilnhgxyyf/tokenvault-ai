# Security and Threat Model

Security is a release requirement. This document describes intended controls, not verified ones. Nothing has been audited or penetration-tested.

## Assets

API keys, provider credentials, tenant usage and cost data, prompts and completions in transit, admin credentials, audit logs.

## Threats and planned mitigations

| Threat | Planned mitigation |
|---|---|
| Stolen or guessed client API key | Long random keys, only a secure hash stored, shown once, revocable, rotation documented |
| Cross-tenant data access | Tenant derived from the authenticated key only; tenant filter in every query and cache key; dedicated isolation tests |
| Cache poisoning / cross-tenant cache leak | Tenant, model, provider config, and canonical request hash in keys; no caching of errors; restricted to deterministic non-tool requests initially |
| SSRF via provider URLs | Upstream hosts come from server config allowlist; callers cannot supply URLs |
| Request smuggling / oversized bodies | Body-size limits, strict validation, standard server stack behind a trusted proxy |
| Abuse and cost exhaustion | Per-key rate limits, concurrency caps, timeouts, bounded retries |
| Secret leakage in logs or errors | No logging of prompts, completions, or auth headers by default; upstream errors sanitized |
| Admin takeover | Separate admin auth, strong password hashing, authorization checks, audit logging of sensitive actions |
| Sensitive data sent to wrong provider | Per-workspace authorized model/provider lists; routing never overrides them |
| Dependency and container vulnerabilities | Pinned versions, automated dependency checks in CI, minimal container images |
| Browser attacks on dashboard | Restrictive CORS, no secrets in frontend code, sanitized rendering |

## Privacy defaults

- Prompts and completions are not logged or stored (`LOG_PROMPTS=false`, `STORE_REQUEST_CONTENT=false`).
- Retention periods are configurable; deletion procedures will be provided.
- Data sent upstream is subject to the upstream provider's own terms.

## Secrets handling

- `.env` is git-ignored; only `.env.example` with placeholders is committed.
- Rotation procedure for the secret key, admin password, API keys, and provider keys will be documented in Batch 7.
- Encryption in transit (TLS) and at rest, and backup practice, will be documented in Batch 7 for each hosting option.

## Known limitations (honest list)

- No code exists yet, so none of the above is implemented as of Batch 1.
- No third-party security review has occurred.
- Free hosting tiers may sleep, lose ephemeral files, and lack production resources.
- Exact-cache correctness depends on provider determinism assumptions that must be tested.
- TokenVault claims no compliance with SOC 2, ISO 27001, GDPR, HIPAA, or any other regime. Having security features does not make a deployment compliant.

## Reporting

Add a private contact address here before any public release.
