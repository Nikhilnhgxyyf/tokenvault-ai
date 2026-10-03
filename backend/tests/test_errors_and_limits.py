from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.providers.base import (
    ProviderNotConfiguredError,
    ProviderUpstreamError,
    UnsupportedFeatureError,
)


class Item(BaseModel):
    count: int


async def echo(request: Request) -> dict[str, int]:
    body = await request.body()
    return {"size": len(body)}


async def validate(item: Item) -> dict[str, int]:
    return {"count": item.count}


async def boom() -> None:
    raise RuntimeError("secret-internal-detail")


async def unsupported() -> None:
    raise UnsupportedFeatureError("Streaming is not supported by this provider.")


async def upstream() -> None:
    raise ProviderUpstreamError("raw-upstream-detail-should-not-leak")


async def not_configured() -> None:
    raise ProviderNotConfiguredError("internal-config-detail-should-not-leak")


def make_client(build_app: Callable[..., FastAPI], **overrides: object) -> TestClient:
    app = build_app(**overrides)
    app.add_api_route("/_test/echo", echo, methods=["POST"])
    app.add_api_route("/_test/validate", validate, methods=["POST"])
    app.add_api_route("/_test/boom", boom, methods=["GET"])
    app.add_api_route("/_test/unsupported", unsupported, methods=["GET"])
    app.add_api_route("/_test/upstream", upstream, methods=["GET"])
    app.add_api_route("/_test/not-configured", not_configured, methods=["GET"])
    return TestClient(app, raise_server_exceptions=False)


def test_body_at_the_limit_is_accepted(build_app: Callable[..., FastAPI]) -> None:
    client = make_client(build_app, max_request_body_bytes=1024)
    response = client.post("/_test/echo", content=b"x" * 1024)
    assert response.status_code == 200
    assert response.json() == {"size": 1024}


def test_oversized_body_with_content_length_is_rejected(build_app: Callable[..., FastAPI]) -> None:
    client = make_client(build_app, max_request_body_bytes=1024)
    response = client.post("/_test/echo", content=b"x" * 2048)
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "request_too_large"
    assert error["request_id"] == response.headers["x-request-id"]


def test_oversized_chunked_body_is_rejected(build_app: Callable[..., FastAPI]) -> None:
    client = make_client(build_app, max_request_body_bytes=1024)

    def chunks():
        for _ in range(5):
            yield b"x" * 1024

    response = client.post("/_test/echo", content=chunks())
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_validation_error_does_not_echo_submitted_values(
    build_app: Callable[..., FastAPI],
) -> None:
    client = make_client(build_app)
    response = client.post("/_test/validate", json={"count": "SECRET-VALUE-123"})
    assert response.status_code == 422
    assert "SECRET-VALUE-123" not in response.text
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert len(error["details"]) >= 1


def test_unexpected_exception_returns_generic_500(build_app: Callable[..., FastAPI]) -> None:
    client = make_client(build_app)
    response = client.get("/_test/boom")
    assert response.status_code == 500
    assert "secret-internal-detail" not in response.text
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["request_id"] == response.headers["x-request-id"]


def test_unsupported_feature_maps_to_400(build_app: Callable[..., FastAPI]) -> None:
    client = make_client(build_app)
    response = client.get("/_test/unsupported")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "unsupported_feature"
    assert error["message"] == "Streaming is not supported by this provider."


def test_upstream_error_maps_to_502_without_details(build_app: Callable[..., FastAPI]) -> None:
    client = make_client(build_app)
    response = client.get("/_test/upstream")
    assert response.status_code == 502
    assert "raw-upstream-detail-should-not-leak" not in response.text
    assert response.json()["error"]["code"] == "upstream_error"


def test_not_configured_maps_to_503_without_details(build_app: Callable[..., FastAPI]) -> None:
    client = make_client(build_app)
    response = client.get("/_test/not-configured")
    assert response.status_code == 503
    assert "internal-config-detail-should-not-leak" not in response.text
    assert response.json()["error"]["code"] == "provider_not_configured"
  
