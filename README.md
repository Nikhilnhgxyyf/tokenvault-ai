# TokenVault AI

An AI token-optimization gateway. It sits between AI applications and model providers to reduce real token spend while preserving correctness, security, privacy, and API compatibility.

**Status: early foundation (Batch 1 of 7: design and configuration only).** No gateway code exists yet. No savings have been measured. Nothing here is claimed to be production-ready.

## Honesty rules

- Savings are never claimed unless measured against a documented baseline.
- Every number in the product is labeled: **measured**, **estimated**, **simulated**, or **unavailable**.
- No compliance regime (SOC 2, ISO 27001, GDPR, HIPAA, etc.) is claimed.

## Where to start

1. Read `docs/SETUP_GUIDE.md` (plain-English GitHub steps).
2. Read `docs/ARCHITECTURE.md` (what is being built and why).
3. Read `docs/SECURITY.md` (threat model and known limitations).

## Cost

Local development uses a free, offline **mock provider**. No paid API, hosting, database, or monitoring service is needed. Anything that can cost money is optional and documented in `docs/DEPLOYMENT.md` (Batch 7).

## Build plan

| Batch | Content | State |
|---|---|---|
| 1 | Architecture, threat model, tree, configuration, setup guide | This delivery |
| 2 | Backend foundation, database, auth, tenant isolation | Not started |
| 3 | Provider adapters, chat endpoint, exact cache, token accounting | Not started |
| 4 | Optimization policy engine, feature flags, shadow mode | Not started |
| 5 | Frontend dashboard | Not started |
| 6 | Tests, CI, Docker, mock mode | Not started |
| 7 | Deployment, security checklist, benchmarks, known gaps | Not started |

## License

To be decided by the project owner. See `LICENSE` once added.
