# TokenVault AI

An AI token-optimization gateway. It sits between AI applications and model providers to reduce real token spend while preserving correctness, security, privacy, and API compatibility.

**Status: early foundation (Batch 3).** The backend skeleton, health checks, safe error handling, an offline mock provider, a database for usage accounting, and automated tests exist. There is no chat endpoint, authentication, caching, or optimization yet. No savings have been measured. Nothing here is claimed to be production-ready.

## Honesty rules

- Savings are never claimed unless measured against a documented baseline.
- Every number in the product is labeled: **provider-reported**, **estimated**, **simulated**, or **unavailable**.
- No compliance regime (SOC 2, ISO 27001, GDPR, HIPAA, etc.) is claimed.

## Where to start

1. `docs/SETUP_GUIDE.md` (plain-English GitHub steps)
2. `docs/ARCHITECTURE.md` (what is being built and why)
3. `docs/SECURITY.md` (threat model and known limitations)
4. `docs/DATABASE.md` (usage accounting tables and labels)

## Cost

Local development and all tests use a free, offline **mock provider** and a local SQLite database. No paid API, hosting, database, or monitoring service is needed. GitHub Actions (the automatic test runner in `.github/workflows/ci.yml`) is free for public repositories and has a monthly free allowance for private ones.

## Progress

| Batch | Content | State |
|---|---|---|
| 1 | Architecture, threat model, configuration, setup guide | Done |
| 2 | Backend skeleton: settings, health, errors, request limits, mock provider, tests, early CI | Done |
| 3 | Database foundation, usage accounting, cost estimation, migration, tests | This delivery |

Planned next (order to be confirmed): API-key authentication and tenant isolation at the API, admin authentication and audit log, chat-completions endpoint with a real provider adapter, exact cache, optimization policy engine, frontend dashboard, Docker and full CI, deployment guide and security checklist.

## License

To be decided by the project owner. See `LICENSE` once added.
