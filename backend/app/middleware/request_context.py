"""Assigns every request an ID, returns it in X-Request-ID, and logs request metadata.

Only the method, path (without query string), status, and timing are logged.
Bodies and headers are never logged.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")

logger = logging.getLogger("tokenvault.access")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id")
        if incoming is not None and _VALID_REQUEST_ID.fullmatch(incoming):
            request_id = incoming
        else:
            request_id = uuid.uuid4().hex

        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request_completed",
                extra={
                    "fields": {
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status": status_code,
                        "duration_ms": duration_ms,
                    }
                },
            )
            request_id_var.reset(token)
          
