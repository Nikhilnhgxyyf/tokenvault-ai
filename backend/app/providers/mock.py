"""Offline, deterministic mock provider. Costs nothing and needs no network or keys.

Its token counts are SIMULATED (a simple word count) and are labeled as such.
They must never be presented as provider-reported usage or real savings.
"""

import hashlib
import json
from typing import Literal

from app.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderRequest,
    ProviderResponse,
    ProviderUpstreamError,
    TokenUsage,
)


class MockProvider(Provider):
    name = "mock"
    capabilities = ProviderCapabilities(
        streaming=False,
        tool_calls=False,
        structured_output=False,
    )

    def __init__(self, fail_mode: Literal["none", "error"] = "none") -> None:
        self._fail_mode = fail_mode

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        if self._fail_mode == "error":
            raise ProviderUpstreamError("Simulated upstream failure from the mock provider.")

        canonical = json.dumps(
            {
                "model": request.model,
                "messages": [message.model_dump() for message in request.messages],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        content = f"[mock-response {digest}]"

        prompt_tokens = sum(len(message.content.split()) for message in request.messages)
        completion_tokens = len(content.split())
        return ProviderResponse(
            provider=self.name,
            model=request.model,
            content=content,
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_prompt_tokens=0,
                total_tokens=prompt_tokens + completion_tokens,
                origin="simulated",
            ),
        )
      
