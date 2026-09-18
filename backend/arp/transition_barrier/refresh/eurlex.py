from __future__ import annotations

import logging
import re

import httpx

from arp.net_safety import UnsafeURLError, assert_safe_fetch_target, ssrf_guard_request_hook
from arp.transition_barrier.refresh.eli import EliRef
from arp.transition_barrier.refresh.reconciler import FetchedVersion
from arp.transition_barrier.refresh.router import RoutedSource

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; ARP-TransitionBarrierRefresh/0.1; +https://eur-lex.europa.eu)"

# EUR-Lex marks repealed/expired acts in the document header. These are
# intentionally narrow: a miss yields in_force=None ("unknown"), which the
# reconciler treats as no signal, rather than a false "repealed".
_NOT_IN_FORCE_RE = re.compile(r"\b(no longer in force|repealed|date of end of validity)\b", re.I)
_IN_FORCE_RE = re.compile(r"\bin force\b", re.I)
# The most recent consolidated version link, e.g. /eli/reg/2023/1804/2026-01-08
_CONSOLIDATED_RE = re.compile(r"/eli/[a-z_]+/\d{4}/\d+/(\d{4}-\d{2}-\d{2})")


def _classify(html: str, eli: EliRef) -> tuple[str | None, bool | None, str]:
    """Extract (latest_point_in_time, in_force, quote) from a EUR-Lex page."""
    dates = sorted(set(_CONSOLIDATED_RE.findall(html)))
    latest = dates[-1] if dates else None

    in_force: bool | None = None
    quote = ""
    if (match := _NOT_IN_FORCE_RE.search(html)) is not None:
        in_force = False
        quote = html[max(0, match.start() - 120) : match.end() + 120].strip()
    elif (match := _IN_FORCE_RE.search(html)) is not None:
        in_force = True
        quote = html[max(0, match.start() - 120) : match.end() + 120].strip()
    return latest, in_force, quote


async def fetch_version(routed: RoutedSource, *, client: httpx.AsyncClient) -> FetchedVersion:
    """Establish the current state of one EUR-Lex act.

    Never raises for a fetch problem -- a failure comes back as a
    FetchedVersion with `error` set, so one unreachable source does not abort
    a run over the other fourteen.
    """
    assert routed.eli is not None, "fetch_version requires an automatable source"
    url = routed.source.url or ""
    try:
        assert_safe_fetch_target(url)
        response = await client.get(url)
        response.raise_for_status()
    except UnsafeURLError as exc:
        return FetchedVersion(source_key=routed.source.key, eli=routed.eli, error=f"unsafe URL: {exc}")
    except httpx.HTTPError as exc:
        return FetchedVersion(source_key=routed.source.key, eli=routed.eli, error=str(exc))

    latest, in_force, quote = _classify(response.text, routed.eli)
    return FetchedVersion(
        source_key=routed.source.key,
        eli=routed.eli,
        latest_point_in_time=latest,
        in_force=in_force,
        quote=quote,
    )


def build_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """An SSRF-guarded client. The guard runs as a request hook so it also
    fires on every redirect hop, not just the initial URL.
    """
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=True,
        event_hooks={"request": [ssrf_guard_request_hook]},
    )
