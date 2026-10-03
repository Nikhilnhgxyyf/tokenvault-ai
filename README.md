# TokenVault AI

An AI token-optimization gateway. It sits between AI applications and model providers to reduce real token spend while preserving correctness, security, privacy, and API compatibility.

**Status: early foundation (Batch 2A of the build plan).** The backend skeleton, health checks, safe error handling, and an offline mock provider exist. There is no chat endpoint, database, authentication, or optimization yet. No savings have been measured. Nothing here is claimed to be production-ready.

## Honesty rules

- Savings are never claimed unless measured against a documented baseline.
- Every number in the product is labeled: **measured**, **estimated**, **simulated**, or **unavailable**.
- No compliance regime (SOC 2, ISO 27001, GDPR, HIPAA, etc.) is claimed.

## Where to start

1. Read `docs/SETUP_GUIDE.md` (plain-English GitHub steps).
2. Read `docs/ARCHITECTURE.md` (what is being built and why).
3. Read `docs/SECURITY.md` (threat model and known limitations).

## Cost

Local development and all tests use a free, offline **mock provider**. No paid API, hosting, database, or monitoring service is needed. GitHub Actions (the automatic test runner in `.github/workflows/ci.yml`) is free for public repositories and has a monthly free allowance for private ones.

## Build plan

| Batch | Content | State |
|---|---|---|
| 1 | Architecture, threat model, configuration, setup guide | Done |
| 2A | Backend skeleton: settings, health, errors, request limits, mock provider, tests, early CI | This delivery |
| 2B | Database models, migrations, API-key auth, tenant isolation, admin auth, audit log | Not started |
| 3 | Chat-completions endpoint, OpenAI-compatible adapter, exact cache, token accounting | Not started |
| 4 | Optimization policy engine, feature flags, shadow mode | Not started |
| 5 | Frontend dashboard | Not started |
| 6 | Full tests, Docker, full CI, local mock mode guide | Not started |
| 7 | Deployment, security checklist, benchmarks, known gaps | Not started |

## License

To be decided by the project owner. See `LICENSE` once added.
