import json
import logging
import re
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter, request_id_var


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str)


def test_ready_in_mock_mode(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["provider_mode"] == "mock"
    assert body["provider"] == "mock"


def test_ready_is_503_when_live_mode_is_unavailable(build_app: Callable[..., FastAPI]) -> None:
    app = build_app(tokenvault_provider_mode="live")
    with TestClient(app, raise_server_exceptions=False) as live_client:
        response = live_client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["provider_mode"] == "live"
    assert body["provider"] is None


def test_request_id_is_generated(client: TestClient) -> None:
    response = client.get("/health")
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_valid_incoming_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc12345-test"})
    assert response.headers["x-request-id"] == "abc12345-test"


def test_invalid_incoming_request_id_is_replaced(client: TestClient) -> None:
    sent = "bad id with spaces"
    response = client.get("/health", headers={"X-Request-ID": sent})
    returned = response.headers["x-request-id"]
    assert returned != sent
    assert re.fullmatch(r"[0-9a-f]{32}", returned)


def test_interactive_docs_are_disabled_outside_local(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_unknown_path_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/no-such-path")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["x-request-id"]


def test_wrong_method_uses_error_envelope(client: TestClient) -> None:
    response = client.post("/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert "allow" in response.headers


def test_allowed_cors_origin_is_accepted(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_unlisted_cors_origin_is_not_accepted(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_json_formatter_outputs_valid_json_with_request_id() -> None:
    token = request_id_var.set("req-12345678")
    try:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        record.fields = {"status": 200}
        parsed = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"
    assert parsed["request_id"] == "req-12345678"
    assert parsed["fields"]["status"] == 200
  
