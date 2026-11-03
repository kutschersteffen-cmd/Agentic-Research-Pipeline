from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from arp.discovery.site_finder import WebSearchClient
from arp.llm.base import LLMClient
from arp.research.authority_taxonomy.library import LibraryEntry, SourceType, load_library, save_library
from arp.research.taxonomy_sources.discovery import _AUTHORITY_QUERY_TEMPLATES, _run_queries
from arp.research.taxonomy_sources.fetch import fetch_source_text
from arp.schemas.taxonomy_sources import SourceCandidateType

logger = logging.getLogger(__name__)

_EXTRA_TEMPLATES = ["{theme} bill of materials", "{theme} engineering cost study", "{theme} technology report"]
_MAX_FETCH_CHARS = 400_000
_SUMMARY_WORDS = 80

_GUIDANCE_SYSTEM = """\
Turn the user's guidance about which sources to use into a list of allowed \
web host suffixes (e.g. "EU Taxonomy only" -> ["europa.eu"]). Return an \
empty list if the guidance does not restrict sources."""

_CANDIDATE_SYSTEM = f"""\
You assess a candidate source for defining a macro investment theme's \
business-activity taxonomy. Give a summary of at most {_SUMMARY_WORDS} words, a \
one-sentence reason it is (or is not) a useful authority, its source_type, \
and the sub-areas of the theme it covers."""


class Candidate(BaseModel):
    url: str
    title: str
    source_type: SourceType
    summary: str
    reason: str
    fetchable: bool
    covers: list[str]
    from_library: bool


class _GuidanceDraft(BaseModel):
    allowed_hosts: list[str]


class _CandidateDraft(BaseModel):
    summary: str
    reason: str
    source_type: SourceType
    covers: list[str]


def _truncate(text: str) -> str:
    return " ".join(text.split()[:_SUMMARY_WORDS])


async def discover_candidates(
    theme_name: str,
    theme_key: str | None,
    guidance: str,
    *,
    search_client: WebSearchClient,
    llm: LLMClient,
    user_agent: str,
    use_library: bool = True,
    library_root: Path | None = None,
) -> list[Candidate]:
    allowed: list[str] = []
    if guidance.strip():
        draft, _ = await llm.complete_structured(system=_GUIDANCE_SYSTEM, prompt=guidance, output_model=_GuidanceDraft)
        # models sometimes return "https://x" or "*.x"; keep the bare host suffix
        allowed = [h.lower().split("://")[-1].split("/")[0].removeprefix("*.") for h in draft.allowed_hosts]

    def keep(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return not allowed or any(host == h or host.endswith("." + h) for h in allowed)

    candidates: list[Candidate] = []
    seen: set[str] = set()
    if use_library and theme_key:
        for e in load_library(theme_key, library_root):
            if e.status == "approved" and e.url not in seen and keep(e.url):
                seen.add(e.url)
                candidates.append(Candidate(**e.model_dump(exclude={"checked_on", "status", "summary"}), summary=_truncate(e.summary), reason="Approved library entry.", from_library=True))

    web = await _run_queries(
        theme_name, _AUTHORITY_QUERY_TEMPLATES + _EXTRA_TEMPLATES, SourceCandidateType.AUTHORITY, search_client, per_query=4
    )
    for r in web:
        if r.url in seen or not keep(r.url):
            continue
        seen.add(r.url)
        try:
            text = await fetch_source_text(r.url, user_agent, max_chars=_MAX_FETCH_CHARS)
        except Exception:  # noqa: BLE001 - one bad source shouldn't abort discovery
            logger.warning("Fetch failed for %s", r.url, exc_info=True)
            text = None
        body = text if text else f"(not fetchable; search snippet only)\n{r.snippet}"
        prompt = f"Theme: {theme_name}\nTitle: {r.name}\nURL: {r.url}\n\n{body}"
        try:
            draft, _ = await llm.complete_structured(system=_CANDIDATE_SYSTEM, prompt=prompt, output_model=_CandidateDraft)
        except Exception:  # noqa: BLE001 - skip this candidate, keep the rest
            logger.warning("Candidate assessment failed for %s; skipping", r.url, exc_info=True)
            continue
        candidates.append(
            Candidate(
                url=r.url,
                title=r.name,
                source_type=draft.source_type,
                summary=_truncate(draft.summary if text else (r.snippet or "")),
                reason=draft.reason,
                fetchable=bool(text),
                covers=draft.covers,
                from_library=False,
            )
        )
    return candidates


async def propose(
    theme_key: str, *, search_client: WebSearchClient, llm: LLMClient, user_agent: str, root: Path | None = None
) -> int:
    """Appends discovered sources not yet in the library as `proposed`; returns how many were added."""
    entries = load_library(theme_key, root)
    known = {e.url for e in entries}
    found = await discover_candidates(
        theme_key.replace("_", " "), theme_key, "", search_client=search_client, llm=llm, user_agent=user_agent, use_library=False
    )
    new = [
        LibraryEntry(**c.model_dump(include=set(LibraryEntry.model_fields) - {"checked_on", "status"}), status="proposed")
        for c in found
        if c.url not in known
    ]
    save_library(theme_key, entries + new, root)
    return len(new)
