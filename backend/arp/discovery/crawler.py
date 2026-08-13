from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from arp.schemas.common import DocType

logger = logging.getLogger(__name__)

# Keyword patterns (checked against link text + href, lowercased) used to
# classify a candidate document link. Order matters: first match wins.
_DOC_TYPE_PATTERNS: list[tuple[DocType, tuple[str, ...]]] = [
    (DocType.ANNUAL_REPORT_10K, ("10-k", "10k", "annual report", "form 10-k")),
    (DocType.PROXY_DEF14A, ("proxy statement", "def 14a", "def14a")),
    (
        DocType.SUSTAINABILITY_REPORT,
        ("sustainability", "esg report", "csr report", "responsibility report", "impact report", "climate report"),
    ),
    (DocType.EARNINGS_TRANSCRIPT, ("earnings call transcript", "transcript", "earnings transcript")),
    (DocType.INVESTOR_PRESENTATION, ("investor presentation", "investor deck", "investor day")),
]

_DOCUMENT_EXTENSIONS = (".pdf",)


class CandidateDocumentLink(BaseModel):
    url: str
    doc_type: DocType
    link_text: str


class HomepageUnreachableError(Exception):
    """The crawl's starting URL itself couldn't be fetched -- distinct from
    a normal empty result (crawled fine, nothing matched, or robots.txt
    disallowed everything). Raised only for the root URL: a broken link
    found later, deeper in the site, is a routine crawl outcome and stays
    silent (logged, skipped), but if the very first page never loads there
    is nothing else this crawl could have found, and that's worth
    surfacing rather than reporting identically to "zero documents"."""


@dataclass
class CrawlConfig:
    user_agent: str
    max_depth: int = 2
    max_pages: int = 40
    request_delay_seconds: float = 1.0
    timeout_seconds: float = 20.0


@dataclass
class _RobotsCache:
    parsers: dict[str, RobotFileParser] = field(default_factory=dict)

    async def allowed(self, client: httpx.AsyncClient, url: str, user_agent: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.parsers:
            rp = RobotFileParser()
            try:
                resp = await client.get(urljoin(origin, "/robots.txt"))
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    rp.parse([])  # no robots.txt => allow
            except httpx.HTTPError:
                rp.parse([])
            self.parsers[origin] = rp
        return self.parsers[origin].can_fetch(user_agent, url)


def classify_link(url: str, link_text: str) -> DocType | None:
    haystack = f"{link_text} {url}".lower()
    for doc_type, keywords in _DOC_TYPE_PATTERNS:
        if any(kw in haystack for kw in keywords):
            return doc_type
    if url.lower().endswith(_DOCUMENT_EXTENSIONS):
        return DocType.OTHER
    return None


def _same_site(url: str, root_netloc: str) -> bool:
    """True if `url`'s host is the root host itself or a subdomain of it
    (e.g. investors.acme.com is same-site as acme.com), never merely
    sharing a TLD."""
    netloc = urlparse(url).netloc.lower()
    root = root_netloc.lower()
    return netloc == root or netloc.endswith("." + root)


async def crawl_for_documents(root_url: str, config: CrawlConfig) -> list[CandidateDocumentLink]:
    """Bounded, same-site, robots.txt-respecting crawl for investor
    disclosure documents.

    This intentionally only follows links on the company's own domain (or
    subdomains) starting from a known homepage/IR URL — it is not a general
    web crawler and never leaves the site it was pointed at.
    """
    root_netloc = urlparse(root_url).netloc
    found: dict[str, CandidateDocumentLink] = {}
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(root_url, 0)]
    robots = _RobotsCache()

    headers = {"User-Agent": config.user_agent}
    async with httpx.AsyncClient(headers=headers, timeout=config.timeout_seconds, follow_redirects=True) as client:
        while queue and len(visited) < config.max_pages:
            url, depth = queue.pop(0)
            if url in visited or depth > config.max_depth:
                continue
            visited.add(url)

            if not await robots.allowed(client, url, config.user_agent):
                logger.info("robots.txt disallows %s, skipping", url)
                continue

            await asyncio.sleep(config.request_delay_seconds)
            is_root = url == root_url
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                if is_root:
                    raise HomepageUnreachableError(f"Could not fetch {url}: {exc}") from exc
                logger.info("Failed to fetch %s: %s", url, exc)
                continue
            if is_root and resp.status_code >= 400:
                raise HomepageUnreachableError(f"{url} returned HTTP {resp.status_code}")
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type:
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = urljoin(url, a["href"]).split("#")[0]
                link_text = a.get_text(strip=True)
                if not _same_site(href, root_netloc):
                    continue
                doc_type = classify_link(href, link_text)
                if doc_type is not None:
                    found.setdefault(href, CandidateDocumentLink(url=href, doc_type=doc_type, link_text=link_text))
                elif depth < config.max_depth and href not in visited:
                    queue.append((href, depth + 1))

    return list(found.values())
