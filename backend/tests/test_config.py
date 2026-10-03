import pytest
from pydantic import ValidationError

from app.core.config import Settings

_ENV_NAMES = (
    "TOKENVAULT_ENV",
    "LOG_LEVEL",
    "TOKENVAULT_PROVIDER_MODE",
    "TOKENVAULT_SECRET_KEY",
    "MAX_REQUEST_BODY_BYTES",
    "CORS_ALLOWED_ORIGINS",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_safe_and_free() -> None:
    settings = Settings(_env_file=None)
    assert settings.tokenvault_env == "local"
    assert settings.tokenvault_provider_mode == "mock"
    assert settings.log_level == "INFO"
    assert settings.max_request_body_bytes == 1_048_576
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.docs_enabled is True


def test_log_level_is_case_insensitive() -> None:
    assert Settings(_env_file=None, log_level="debug").log_level == "DEBUG"


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level="loud")


def test_tiny_body_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_request_body_bytes=10)


def test_wildcard_cors_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_allowed_origins="*")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_allowed_origins="http://a.example, *")


def test_multiple_cors_origins_are_parsed() -> None:
    settings = Settings(_env_file=None, cors_allowed_origins="http://a.example, http://b.example")
    assert settings.cors_origins == ["http://a.example", "http://b.example"]


def test_production_rejects_placeholder_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, tokenvault_env="production")


def test_production_rejects_short_secret_without_leaking_it() -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(
            _env_file=None,
            tokenvault_env="production",
            tokenvault_secret_key="short-secret-xyz",
        )
    assert "short-secret-xyz" not in str(caught.value)


def test_production_accepts_long_secret() -> None:
    settings = Settings(_env_file=None, tokenvault_env="production", tokenvault_secret_key="a" * 40)
    assert settings.tokenvault_env == "production"
    assert settings.docs_enabled is False


def test_secret_is_hidden_in_repr() -> None:
    settings = Settings(_env_file=None, tokenvault_secret_key="x" * 40)
    assert "x" * 40 not in repr(settings)
  
