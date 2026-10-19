from __future__ import annotations

import asyncio
import gzip
import io
import logging
import re
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from lxml import etree
from pydantic import BaseModel

from arp.discovery.site_check import registrable_domain
from arp.net_safety import UnsafeURLError, ssrf_guard_request_hook
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

# Other names for an annual report; demotion words keep interim/summary material out of the 10-K bucket.
_ANNUAL_EXTRA = ("integrated report", "universal registration document", "annual review", "geschäftsbericht",
                 "geschaeftsbericht", "rapport annuel", "informe anual", "jaarverslag", "årsrapport")
_DEMOTION_WORDS = ("quarter", "quarterly", "q1", "q2", "q3", "q4", "half-year", "interim", "factsheet", "fact sheet",
                   "presentation", "transcript", "remuneration", "tax", "summary", "extract")

_DOCUMENT_EXTENSIONS = (".pdf", ".xhtml", ".zip")  # .xhtml/.zip: ESEF reports and report packages

_MAX_SITEMAPS = 3
_MAX_CHILD_SITEMAPS = 5
_MAX_SEEDS = 10
_MAX_SITEMAP_BYTES = 15_000_000
_SEED_HINTS = ("annual-report", "annual_report", "annualreport", "/reports", "reporting", "/investor", "sustainab",
               "integrated-report", "geschaeftsbericht", "nachhaltigkeit")


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
    expected_year: int | None = None


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
            except (httpx.HTTPError, UnsafeURLError):
                rp.parse([])
            self.parsers[origin] = rp
        return self.parsers[origin].can_fetch(user_agent, url)

    async def sitemaps(self, client: httpx.AsyncClient, url: str, user_agent: str) -> list[str]:
        await self.allowed(client, url, user_agent)  # fills the cache
        parsed = urlparse(url)
        return self.parsers[f"{parsed.scheme}://{parsed.netloc}"].site_maps() or []


def _mentions(haystack: str, kw: str) -> bool:
    """Form codes with digits ("10k", "def 14a") must stand alone: "10k" inside an
    id like "umc.cmc.10k6tes..." is not a 10-K. Plain words match anywhere."""
    if not any(ch.isdigit() for ch in kw):
        return kw in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", haystack) is not None


def report_text(url: str, link_text: str) -> str:
    """Link text plus the URL's filename, lowercased."""
    return f"{link_text} {urlparse(url).path.rsplit('/', 1)[-1]}".lower()


def years_in(text: str) -> set[int]:
    return {int(y) for y in re.findall(r"(?<!\d)20\d{2}(?!\d)", text)}


def is_demoted(text: str) -> bool:
    tokens = re.findall(r"[^\W_]+", text.lower())
    padded = " " + " ".join(tokens) + " "
    return any(f" {w.replace('-', ' ')} " in padded for w in _DEMOTION_WORDS)


def is_pdf(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def classify_link(url: str, link_text: str, expected_year: int | None = None) -> DocType | None:
    haystack = f"{link_text} {url}".lower()
    text = report_text(url, link_text)
    for doc_type, keywords in _DOC_TYPE_PATTERNS:
        if any(_mentions(haystack, kw) for kw in keywords):
            return doc_type
        if doc_type == DocType.ANNUAL_REPORT_10K and any(p in haystack for p in _ANNUAL_EXTRA) and not is_demoted(text):
            return doc_type
    if (expected_year and is_pdf(url) and "report" in text and not is_demoted(text)
            and years_in(text) & {expected_year - 1, expected_year}):
        return DocType.ANNUAL_REPORT_10K
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


async def _fetch_sitemap(client: httpx.AsyncClient, url: str, robots: _RobotsCache, config: CrawlConfig, sleep) -> bytes | None:
    if not await robots.allowed(client, url, config.user_agent):
        return None
    await sleep(config.request_delay_seconds)
    try:
        async with client.stream("GET", url) as resp:
            length = resp.headers.get("content-length", "")
            if resp.status_code != 200 or (length.isdigit() and int(length) > _MAX_SITEMAP_BYTES):
                return None
            chunks, size = [], 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size > _MAX_SITEMAP_BYTES:
                    return None
        data = b"".join(chunks)
        if urlparse(url).path.lower().endswith(".gz"):
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read(_MAX_SITEMAP_BYTES + 1)
            if len(data) > _MAX_SITEMAP_BYTES:
                return None
        return data
    except (httpx.HTTPError, UnsafeURLError, OSError, EOFError, zlib.error) as exc:
        logger.info("Failed to fetch sitemap %s: %s", url, exc)
        return None


def _parse_sitemap(data: bytes | None) -> tuple[bool, list[str]]:
    """(is_index, <loc> values); matched by local name so a missing namespace or padded text still reads."""
    if data is None:
        return False, []
    try:
        root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return False, []
    locs = [e.text.strip() for e in root.iter() if isinstance(e.tag, str) and etree.QName(e).localname == "loc" and e.text]
    return etree.QName(root).localname == "sitemapindex", [loc for loc in locs if loc]


async def _sitemap_seeds(client: httpx.AsyncClient, robots: _RobotsCache, root_url: str, config: CrawlConfig, sleep) -> list[str]:
    """Report-looking same-site pages listed in the site's sitemaps (robots.txt `Sitemap:` lines, else /sitemap.xml)."""
    parsed = urlparse(root_url)
    domain = registrable_domain(root_url)
    tops = (await robots.sitemaps(client, root_url, config.user_agent))[:_MAX_SITEMAPS] or [f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"]
    pages: list[str] = []
    children: list[str] = []
    for url in (u for u in tops if registrable_domain(u) == domain):
        is_index, locs = _parse_sitemap(await _fetch_sitemap(client, url, robots, config, sleep))
        (children if is_index else pages).extend(locs)
    # stable sort: an `en` path token first, listed order otherwise
    children = [u for u in children if registrable_domain(u) == domain]
    children.sort(key=lambda u: "en" not in re.split(r"[^a-z0-9]+", urlparse(u).path.lower()))
    for url in children[:_MAX_CHILD_SITEMAPS]:
        is_index, locs = _parse_sitemap(await _fetch_sitemap(client, url, robots, config, sleep))
        if not is_index:
            pages.extend(locs)
    seeds = [u for u in dict.fromkeys(pages)
             if _same_site(u, parsed.netloc) and not is_pdf(u) and any(h in urlparse(u).path.lower() for h in _SEED_HINTS)]
    seeds.sort(key=lambda u: len(urlparse(u).path))
    return seeds[:_MAX_SEEDS]


async def crawl_for_documents(
    root_url: str, config: CrawlConfig, *, transport: httpx.AsyncBaseTransport | None = None, sleep=asyncio.sleep
) -> list[CandidateDocumentLink]:
    """Bounded, same-site, robots.txt-respecting crawl for investor
    disclosure documents.

    This intentionally only follows links on the company's own domain (or
    subdomains) starting from a known homepage/IR URL — it is not a general
    web crawler. Only its pages stay on the site; an off-site annual or
    sustainability report PDF is recorded as a candidate but never crawled.
    """
    root_netloc = urlparse(root_url).netloc
    found: dict[str, CandidateDocumentLink] = {}
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(root_url, 0)]
    robots = _RobotsCache()

    # root_url comes from a company's website field (client-supplied CSV) or
    # a best-effort web search fallback, and every link found while crawling
    # is on the same site by construction -- so every outgoing request (the
    # root fetch, robots.txt, every followed link, every redirect hop) needs
    # the same SSRF check as any other caller-influenced fetch target. Wired
    # as a request hook (rather than a one-off pre-check) so it also catches
    # a same-site host that DNS-rebinds to a private address mid-crawl, and
    # so a fake client swapped in for tests never triggers a real DNS call.
    headers = {"User-Agent": config.user_agent}
    async with httpx.AsyncClient(
        headers=headers,
        timeout=config.timeout_seconds,
        follow_redirects=True,
        event_hooks={"request": [ssrf_guard_request_hook]},
        transport=transport,
    ) as client:
        try:
            seeds = await _sitemap_seeds(client, robots, root_url, config, sleep)
        except Exception:  # seeding is best effort: whatever goes wrong in a sitemap, the crawl still runs
            logger.exception("Sitemap seeding failed for %s", root_url)
            seeds = []
        queue += [(seed, 1) for seed in seeds if seed != root_url]
        while queue and len(visited) < config.max_pages:
            url, depth = queue.pop(0)
            if url in visited or depth > config.max_depth:
                continue
            visited.add(url)

            if not await robots.allowed(client, url, config.user_agent):
                logger.info("robots.txt disallows %s, skipping", url)
                continue

            await sleep(config.request_delay_seconds)
            is_root = url == root_url
            try:
                resp = await client.get(url)
            except (httpx.HTTPError, UnsafeURLError) as exc:
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
                doc_type = classify_link(href, link_text, config.expected_year)
                if not _same_site(href, root_netloc):
                    if is_pdf(href) and doc_type in (DocType.ANNUAL_REPORT_10K, DocType.SUSTAINABILITY_REPORT):
                        found.setdefault(href, CandidateDocumentLink(url=href, doc_type=doc_type, link_text=link_text))
                    continue
                if doc_type is not None:
                    found.setdefault(href, CandidateDocumentLink(url=href, doc_type=doc_type, link_text=link_text))
                elif depth < config.max_depth and href not in visited:
                    queue.append((href, depth + 1))

    return list(found.values())
