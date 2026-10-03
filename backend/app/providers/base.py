"""Provider interface shared by the mock provider and (later) real providers.

Every usage number carries an "origin" label so simulated numbers can never be
mistaken for provider-reported ones.
"""

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProviderError(Exception):
    """Base class for provider failures. Messages must be safe to show to callers."""


class UnsupportedFeatureError(ProviderError):
    """The request needs a capability the provider does not have."""


class ProviderUpstreamError(ProviderError):
    """The upstream provider failed. Details are logged server-side, not returned."""


class ProviderNotConfiguredError(ProviderError):
    """No usable provider is configured."""


DataOrigin = Literal["provider_reported", "simulated"]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1, max_length=200)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cached_prompt_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(ge=0)
    origin: DataOrigin


class ProviderResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    content: str
    finish_reason: Literal["stop", "length"]
    usage: TokenUsage


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    streaming: bool
    tool_calls: bool
    structured_output: bool


class Provider(ABC):
    name: str
    capabilities: ProviderCapabilities

    @abstractmethod
    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Return a non-streaming completion or raise a ProviderError."""
      
