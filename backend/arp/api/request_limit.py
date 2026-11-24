"""Whole-request size limit (spec server-paths-upload-limits, D3).

A multipart request may be up to `max_request_bytes`, any other request up to `max_body_bytes`.
A declared `Content-Length` above the limit is answered 413 before the body is read; without one, the
413 comes once more bytes than the limit have arrived. Sits inside CORS, before sign-in and routing.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from arp.api.deps import settings_dep


class _TooLarge(Exception):
    pass


class RequestSizeLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Resolved per request, through the app's overrides, so tests and settings changes apply.
        settings = scope["app"].dependency_overrides.get(settings_dep, settings_dep)()
        headers = Headers(scope=scope)
        multipart = headers.get("content-type", "").startswith("multipart/form-data")
        limit = settings.max_request_bytes if multipart else settings.max_body_bytes
        too_large = JSONResponse(
            status_code=413, content={"detail": f"Request is larger than the {limit // 1_000_000} MB limit."}
        )
        length = headers.get("content-length", "")
        if length.isdigit() and int(length) > limit:
            await too_large(scope, receive, send)
            return

        received = 0
        over = False
        started = False

        async def capped_receive() -> Message:
            nonlocal received, over
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    over = True
                    raise _TooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if over:  # whatever the route made of the cut-off body is dropped; the 413 goes instead
                return
            started = True
            await send(message)

        try:
            await self.app(scope, capped_receive, guarded_send)
        except Exception:
            if not over or started:
                raise
        if over and not started:
            await too_large(scope, receive, send)
