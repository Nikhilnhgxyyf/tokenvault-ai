"""Rejects request bodies larger than the configured limit.

Checks the declared Content-Length first, then counts bytes as they arrive so that
chunked uploads (no Content-Length) are limited too.
"""

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_payload


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        state = scope.get("state")
        request_id = state.get("request_id") if isinstance(state, dict) else None
        response = JSONResponse(
            status_code=status_code,
            content=error_payload(
                message=message,
                error_type="invalid_request_error",
                code=code,
                request_id=request_id,
            ),
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError:
                declared_size = -1
            if declared_size < 0:
                await self._reject(
                    scope, receive, send, 400, "invalid_content_length", "Invalid Content-Length."
                )
                return
            if declared_size > self.max_bytes:
                await self._reject(
                    scope,
                    receive,
                    send,
                    413,
                    "request_too_large",
                    "Request body exceeds the maximum allowed size.",
                )
                return

        received = 0
        exceeded = False
        response_started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started, rejected
            if exceeded:
                # The app is reacting to our simulated disconnect. Replace whatever
                # it tries to send with a clean 413 (if nothing was sent yet).
                if not response_started and not rejected:
                    rejected = True
                    await self._reject(
                        scope,
                        receive,
                        send,
                        413,
                        "request_too_large",
                        "Request body exceeds the maximum allowed size.",
                    )
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            # When we cut an upload short, the app may fail with a "client disconnected"
            # error. That is our 413 situation, not a server error. Any other failure
            # is re-raised untouched.
            if not exceeded:
                raise

        if exceeded and not response_started and not rejected:
            rejected = True
            await self._reject(
                scope,
                receive,
                send,
                413,
                "request_too_large",
                "Request body exceeds the maximum allowed size.",
            )
            
