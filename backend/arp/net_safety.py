from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised when a URL is (or resolves to) a fetch target this app
    refuses to reach: a non-http(s) scheme, or a hostname resolving to a
    loopback/private/link-local/reserved address -- the 169.254.169.254
    cloud-metadata address is link-local, so it's covered too. Guards
    every endpoint that fetches a caller-influenced URL (the taxonomy
    source inspector, the discovery crawler/downloader) against SSRF.
    """


def _is_disallowed_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified


def assert_safe_fetch_target(url: httpx.URL | str) -> None:
    """Resolves url's hostname and raises UnsafeURLError if the scheme
    isn't http(s) or any resolved address is loopback/private/link-local/
    reserved. Call this both before the first request to a caller-supplied
    URL and (via ssrf_guard_request_hook) on every redirect hop, since a
    safe initial host can 302 to an unsafe one.
    """
    parsed = urlparse(str(url))
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Unsupported URL scheme: {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError("URL has no hostname")
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host: {hostname}") from exc
    for info in infos:
        ip = info[4][0]
        if _is_disallowed_ip(ip):
            raise UnsafeURLError(f"{hostname} resolves to a disallowed address ({ip})")


async def ssrf_guard_request_hook(request: httpx.Request) -> None:
    """An httpx `event_hooks={"request": [...]}` hook: fires for every
    request the client actually sends, including each hop of a followed
    redirect. Pass this to every httpx.AsyncClient that fetches a URL not
    hardcoded by this app (a taxonomy source, a company website, a
    discovered document link)."""
    assert_safe_fetch_target(request.url)
