import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.providers.base import (
    ChatMessage,
    ProviderNotConfiguredError,
    ProviderRequest,
    ProviderUpstreamError,
)
from app.providers.mock import MockProvider
from app.providers.registry import get_provider


def make_request(content: str = "hello world", model: str = "mock-model") -> ProviderRequest:
    return ProviderRequest(model=model, messages=[ChatMessage(role="user", content=content)])


async def test_same_input_gives_same_output() -> None:
    provider = MockProvider()
    first = await provider.complete(make_request())
    second = await provider.complete(make_request())
    assert first == second


async def test_different_input_gives_different_output() -> None:
    provider = MockProvider()
    first = await provider.complete(make_request("hello world"))
    second = await provider.complete(make_request("something else"))
    assert first.content != second.content


async def test_usage_is_labeled_simulated_and_adds_up() -> None:
    response = await MockProvider().complete(make_request("hello world"))
    usage = response.usage
    assert usage.origin == "simulated"
    assert usage.prompt_tokens == 2
    assert usage.cached_prompt_tokens == 0
    assert usage.total_tokens == usage.prompt_tokens + usage.completion_tokens
    assert response.provider == "mock"
    assert response.model == "mock-model"
    assert response.finish_reason == "stop"


def test_mock_provider_declares_no_advanced_capabilities() -> None:
    capabilities = MockProvider().capabilities
    assert capabilities.streaming is False
    assert capabilities.tool_calls is False
    assert capabilities.structured_output is False


async def test_failure_mode_raises_upstream_error() -> None:
    with pytest.raises(ProviderUpstreamError):
        await MockProvider(fail_mode="error").complete(make_request())


def test_request_without_messages_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProviderRequest(model="mock-model", messages=[])


def test_registry_returns_mock_provider_by_default() -> None:
    settings = Settings(_env_file=None, tokenvault_env="test", tokenvault_provider_mode="mock")
    assert get_provider(settings).name == "mock"


def test_registry_refuses_live_mode_for_now() -> None:
    settings = Settings(_env_file=None, tokenvault_env="test", tokenvault_provider_mode="live")
    with pytest.raises(ProviderNotConfiguredError):
        get_provider(settings)
      
