"""Shapes for POST /v1/chat/completions.

Only a small, safe subset of the OpenAI chat format is supported. Anything else is
refused with a clear error rather than silently ignored, so the gateway never changes
what the caller asked for.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError
from app.providers.base import ChatMessage, DataOrigin, ProviderRequest, UnsupportedFeatureError

# Known OpenAI parameters that this gateway does not support yet.
KNOWN_UNSUPPORTED_FIELDS = frozenset(
    {
        "audio",
        "frequency_penalty",
        "function_call",
        "functions",
        "logit_bias",
        "logprobs",
        "max_completion_tokens",
        "metadata",
        "modalities",
        "parallel_tool_calls",
        "prediction",
        "presence_penalty",
        "reasoning_effort",
        "response_format",
        "seed",
        "service_tier",
        "stop",
        "store",
        "stream_options",
        "tool_choice",
        "tools",
        "top_logprobs",
        "top_p",
    }
)


class ChatCompletionRequest(BaseModel):
    # extra="allow" lets us detect unsupported or unknown fields and answer clearly.
    model_config = ConfigDict(extra="allow")

    model: str = Field(pattern=r"^[A-Za-z0-9._:/-]{1,200}$")
    messages: list[ChatMessage] = Field(min_length=1, max_length=500)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    stream: bool = False
    n: int = Field(default=1, ge=1, le=128)
    user: str | None = Field(default=None, max_length=256)  # accepted and ignored

    def ensure_supported(self) -> None:
        """Raise a clear error for anything the gateway cannot honor."""
        extras = self.model_extra or {}
        for name in sorted(extras):
            if name in KNOWN_UNSUPPORTED_FIELDS:
                raise UnsupportedFeatureError(
                    f"The parameter '{name}' is not supported by this gateway yet."
                )
        if extras:
            # Names are not echoed back. This also rejects any client-supplied tenant fields.
            raise AppError(422, "invalid_request", "The request contains unknown parameters.")
        if self.stream:
            raise UnsupportedFeatureError("Streaming ('stream': true) is not supported yet.")
        if self.n != 1:
            raise UnsupportedFeatureError("Only n=1 is supported.")

    def to_provider_request(self) -> ProviderRequest:
        return ProviderRequest(
            model=self.model,
            messages=list(self.messages),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )


class ChatCompletionMessage(BaseModel):
    role: Literal["assistant"]
    content: str


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatCompletionMessage
    finish_reason: Literal["stop", "length"]


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class TokenVaultInfo(BaseModel):
    """TokenVault's own labels. These say what the numbers in `usage` really are."""

    request_id: str
    provider: str
    usage_origin: DataOrigin
    cached_prompt_tokens: int
    accounting: Literal["recorded", "failed"]
    cost_status: Literal["estimated", "simulated", "unavailable"] | None
    estimated_cost_nano_usd: int | None
    notice: str | None


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage
    tokenvault: TokenVaultInfo
