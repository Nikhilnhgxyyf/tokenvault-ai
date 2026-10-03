"""Chooses the provider based on settings."""

from app.core.config import Settings
from app.providers.base import Provider, ProviderNotConfiguredError
from app.providers.mock import MockProvider


def get_provider(settings: Settings) -> Provider:
    if settings.tokenvault_provider_mode == "mock":
        return MockProvider()
    raise ProviderNotConfiguredError("Live provider mode is not available in this version.")
  
