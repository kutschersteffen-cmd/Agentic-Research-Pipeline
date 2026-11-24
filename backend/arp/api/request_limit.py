"""Whole-request size limit (spec server-paths-upload-limits, D3).

A multipart request to a route that takes files may be up to `max_request_bytes`; any other request,
including one that only claims to be multipart, up to `max_body_bytes`.
A declared `Content-Length` above the limit is answered 413 before the body is read; without one, the
413 comes once more bytes than the limit have arrived. Sits inside CORS, before sign-in and routing.
"""

from __future__ import annotations

import re

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from arp.api.deps import settings_dep


class _TooLarge(Exception):
    pass


# Routes that read their multipart form by hand (`request.form()`), so OpenAPI does not show it.
HAND_READ_FORMS = [("POST", "/api/signals/runs")]


def _file_routes(app) -> list[tuple[str, re.Pattern[str]]]:
    """(method, path pattern) of every route that takes a multipart body: OpenAPI's, plus HAND_READ_FORMS."""
    routes = [(method, re.compile("^" + re.escape(path) + "$")) for method, path in HAND_READ_FORMS]
    for path, operations in app.openapi()["paths"].items():
        pattern = re.compile("^" + re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(path)) + "$")
        for method, op in operations.items():
            if "multipart/form-data" in op.get("requestBody", {}).get("content", {}):
                routes.append((method.upper(), pattern))
    return routes


class RequestSizeLimit:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._file_routes: list[tuple[str, re.Pattern[str]]] | None = None

    def _takes_files(self, scope: Scope) -> bool:
        if self._file_routes is None:
            self._file_routes = _file_routes(scope["app"])
        return any(m == scope["method"] and p.match(scope["path"]) for m, p in self._file_routes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Resolved per request, through the app's overrides, so tests and settings changes apply.
        settings = scope["app"].dependency_overrides.get(settings_dep, settings_dep)()
        headers = Headers(scope=scope)
        # The larger limit needs both: a multipart body and a route that takes files (else a JSON route
        # could be sent 250 MB just by its Content-Type).
        multipart = headers.get("content-type", "").lower().startswith("multipart/form-data")
        limit = settings.max_request_bytes if multipart and self._takes_files(scope) else settings.max_body_bytes
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
