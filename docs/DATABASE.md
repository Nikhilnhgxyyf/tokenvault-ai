# Database and Usage Accounting

Status: foundation only. Nothing here has been run against real provider traffic.

## Where data lives

- Local default: a SQLite file named `tokenvault.db` (address set by `DATABASE_URL`). It is free and needs no setup. The `.gitignore` keeps `*.db` files out of GitHub.
- PostgreSQL is planned for production but is **not supported yet**. The app refuses any other database address for now.
- Free hosting may lose files. Do not treat a local SQLite file as durable production storage.

## Tables

| Table | Purpose |
|---|---|
| `tenants` | The isolation boundary. Every tenant-owned row has a `tenant_id`. |
| `model_prices` | Versioned prices, **entered by an operator** with a stated source. The code never invents prices. |
| `usage_events` | One row per model call: request ID, provider, model, token counts, labels, estimated cost. |

## Labels (never mixed)

`usage_origin`
- `provider_reported`: numbers returned by a provider.
- `simulated`: numbers from the offline mock provider (a simple word count).

`cost_status`
- `estimated`: provider-reported tokens multiplied by a configured price.
- `simulated`: simulated tokens multiplied by a configured price.
- `unavailable`: no price was configured, so **no cost is stored** (it is not recorded as zero).

Not stored yet: measured billing or invoice data, cache-hit savings, net savings. No savings are calculated in this version.

## Units (no floating point)

- Prices: micro-USD per 1,000,000 tokens. Example: $0.15 per million tokens is stored as `150000`.
- Costs: nano-USD (1e-9 USD). Cost = tokens x price / 1000, rounded half up.
- `prompt_tokens` includes cached tokens. If no cached-input price is configured, cached tokens are charged at the normal input price, so the estimate is never understated.

## Safety rules enforced by the database itself

Token counts cannot be negative, cached tokens cannot exceed prompt tokens, labels must be from the allowed lists, a cost must be present exactly when the status is not `unavailable`, and every usage event must belong to a real tenant. Reports always filter by tenant and are grouped by label.

## Creating tables

- **Local development (`TOKENVAULT_ENV=local`)**: missing tables are created automatically at startup. Set `DATABASE_AUTO_CREATE=false` to turn this off.
- **Everywhere else**: tables are never created automatically. They must be created with the Alembic migration in `backend/migrations`. A beginner-friendly way to run it will be provided with the Docker and deployment batches.

## Known limits

- Request IDs may be supplied by clients, so they are indexed but not unique.
- Workspaces, API keys and admin users do not exist yet.
- Prices are global, not per tenant.
- Only automated tests run in GitHub verify migrations; none have been run against PostgreSQL.
- 
