# Gateway API

Status: first version. It only works with the offline **mock provider**. Nothing here has been used with real providers or real traffic.

## POST /v1/chat/completions

A small, safe subset of the OpenAI chat format.

**Authentication:** send `Authorization: Bearer tv_...`. Your tenant is determined by the key alone. A tenant ID sent in a header is ignored, and one sent in the body is rejected.

**Request (JSON, `Content-Type: application/json`):**

| Field | Rules |
|---|---|
| `model` | Required. Letters, digits and `. _ : / -`, up to 200 characters. |
| `messages` | Required. 1 to 500 items. `role` is `system`, `user` or `assistant`; `content` is a string. |
| `temperature` | Optional, 0 to 2. |
| `max_tokens` | Optional, 1 to 1,000,000. |
| `stream` | Optional. Only `false` is supported. |
| `n` | Optional. Only `1` is supported. |
| `user` | Optional. Accepted and ignored. |

Known OpenAI fields that are not supported yet (for example `tools`, `response_format`, `top_p`, `stop`, `seed`) are refused with a clear error, never silently ignored. Unknown fields are refused too.

**Response:** an OpenAI-style `chat.completion` object plus a `tokenvault` block:

| `tokenvault` field | Meaning |
|---|---|
| `usage_origin` | `simulated` (mock provider) or `provider_reported`. |
| `accounting` | `recorded` if the usage was saved. `failed` if it could not be saved. |
| `cost_status` | `estimated`, `simulated`, `unavailable`, or `null` when accounting failed. `unavailable` means no price is configured, so no cost is shown. |
| `estimated_cost_nano_usd` | Estimated cost in billionths of a US dollar, or `null`. Never a billed amount. |
| `notice` | Plain-language warning, for example that the numbers are simulated. |

The same labels are sent as headers `X-TokenVault-Usage-Origin` and `X-TokenVault-Accounting`.

With the mock provider, `usage` token counts are a simple word count and are **not real usage**.

## Errors

Every error uses the same shape: `{"error": {"message", "type", "code", "request_id"}}`.

| Status | `code` | When |
|---|---|---|
| 400 | `unsupported_feature` | A valid OpenAI feature this gateway does not support yet. |
| 401 | `invalid_api_key` | Missing, malformed, unknown or revoked key (all look the same on purpose). |
| 403 | `tenant_disabled` | The key's tenant is disabled. |
| 413 | `request_too_large` | Body larger than `MAX_REQUEST_BODY_BYTES`. |
| 415 | `unsupported_media_type` | Not `application/json`. |
| 422 | `invalid_request` | Bad or unknown fields, or invalid JSON. Submitted values are never echoed back. |
| 502 | `upstream_error` | The provider failed. Details are not exposed. |
| 503 | `auth_unavailable` | The key could not be checked (database problem). Not a "wrong key" answer. |
| 503 | `provider_not_configured` | No provider is available. |
| 504 | `upstream_timeout` | The provider took longer than `UPSTREAM_TIMEOUT_SECONDS`. |

## Usage accounting

After a successful provider call, one usage event is saved for the key's tenant. If saving fails, the answer is still returned (the provider call already happened) but `accounting` is `failed`, a server-side log entry records the request ID and token counts (never the prompt or reply), and that request is **not** in usage reports. Requests that fail before a provider answers (errors, timeouts) are not recorded.

## API keys

Keys look like `tv_` followed by 43 random characters. Only a SHA-256 hash is stored; the key itself is shown once at creation and can never be recovered. Keys can be revoked.

## Known limits

- There is no HTTP route to create or revoke keys yet; that needs admin authentication, which is not built. Keys are created by code (and tests) only.
- No streaming, tools, structured output, retries, rate limits, concurrency limits, caching, or model authorization yet.
- No real provider is connected.
- Prices must be entered by an operator; none are built in.
- 
