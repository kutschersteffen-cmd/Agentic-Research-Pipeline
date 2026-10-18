"""Does a candidate homepage belong to the company? Evidence read from the page and its imprint."""

from __future__ import annotations

import functools
import json
import logging
import re
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

import httpx
import tldextract
from bs4 import BeautifulSoup
from pydantic import BaseModel

from arp.discovery.names import clean_name, names_match
from arp.net_safety import UnsafeURLError, ssrf_guard_request_hook
from arp.schemas.common import CompanyRef

logger = logging.getLogger(__name__)

AGGREGATOR_DOMAINS: frozenset[str] = frozenset(
    {
        "wikipedia.org",
        "linkedin.com",
        "bloomberg.com",
        "reuters.com",
        "yahoo.com",
        "marketscreener.com",
        "zonebourse.com",
        "morningstar.com",
        "finanzen.net",
        "onvista.de",
        "ariva.de",
        "crunchbase.com",
        "dnb.com",
        "annualreports.com",
        "responsibilityreports.com",
        "sec.gov",
        "xbrl.org",
        "gleif.org",
        "facebook.com",
        "x.com",
        "twitter.com",
        "youtube.com",
        "glassdoor.com",
    }
)
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 15
_IMPRINT_TEXT = re.compile(r"impressum|imprint|legal notice|mentions légales|legal information", re.IGNORECASE)
_TITLE_SEPARATORS = re.compile(r"[|\-–:]")
_HOMEPAGE_NAME_EVIDENCE = ("name_in_title", "name_in_site_name", "name_in_jsonld")


class SiteCheck(BaseModel):
    verdict: Literal["owned", "unclear", "rejected"]
    evidence: list[str]


@functools.cache
def _tld() -> tldextract.TLDExtract:
    # Bundled suffix snapshot and no disk cache: never fetches the public suffix list.
    return tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def registrable_domain(url: str) -> str:
    """`https://ir.basf.com/x` -> `basf.com`; a bare IP or `localhost` falls back to the host itself."""
    return (_tld()(url).top_domain_under_public_suffix or urlparse(url).hostname or "").lower()


def is_aggregator(url: str) -> bool:
    return registrable_domain(url) in AGGREGATOR_DOMAINS


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    """GET following redirects by hand, so an aggregator hop is never requested; None if one is hit."""
    for _ in range(MAX_REDIRECTS + 1):
        if is_aggregator(url):
            return None
        resp = await client.get(url)
        if not resp.is_redirect:
            return resp
        url = urljoin(str(resp.url), resp.headers["location"])
    return resp


def _jsonld_organizations(soup: BeautifulSoup) -> list[dict]:
    orgs = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            orgs += _organizations(json.loads(script.string or ""))
        except (ValueError, RecursionError):  # malformed or absurdly nested block: skip it
            continue
    return orgs


def _organizations(node: Any) -> list[dict]:
    """Every dict in a JSON-LD tree whose @type is an Organization (or a Corporation/Company subtype)."""
    if isinstance(node, list):
        return [org for item in node for org in _organizations(item)]
    if not isinstance(node, dict):
        return []
    types = node.get("@type")
    types = [types] if isinstance(types, str) else types if isinstance(types, list) else []
    is_org = any(isinstance(t, str) and ("Organization" in t or t.endswith(("Corporation", "Company"))) for t in types)
    return ([node] if is_org else []) + [org for value in node.values() for org in _organizations(value)]


def _identifier_evidence(text: str, company: CompanyRef, where: str) -> list[str]:
    upper = text.upper()
    return [
        f"{kind}_{where}"
        for kind, value in (("lei", company.lei), ("isin", company.isin))
        if value and value.strip().upper() in upper
    ]


def _homepage_evidence(soup: BeautifulSoup, company: CompanyRef) -> list[str]:
    evidence = []
    title = soup.title.get_text(strip=True) if soup.title else ""
    if title and any(names_match(part, company.name) for part in [title, *_TITLE_SEPARATORS.split(title)]):
        evidence.append("name_in_title")
    site_name = soup.find("meta", property="og:site_name")
    if site_name and names_match(site_name.get("content", ""), company.name):
        evidence.append("name_in_site_name")
    orgs = _jsonld_organizations(soup)
    if any(names_match(str(org.get(key, "")), company.name) for org in orgs for key in ("name", "legalName")):
        evidence.append("name_in_jsonld")
    lei_codes = " ".join(str(org.get("leiCode", "")) for org in orgs)
    evidence += _identifier_evidence(f"{soup.get_text(' ')} {lei_codes}", company, "on_page")
    return evidence


def _imprint_url(soup: BeautifulSoup, page_url: str) -> str | None:
    site = registrable_domain(page_url)
    for a in soup.find_all("a", href=True):
        if not _IMPRINT_TEXT.search(a.get_text(" ", strip=True)):
            continue
        try:
            href = urljoin(page_url, a["href"]).split("#")[0]
            if registrable_domain(href) == site:
                return href
        except ValueError:  # malformed href, e.g. "http://[bad"
            continue
    return None


def _imprint_evidence(html: str, company: CompanyRef) -> list[str]:
    text = BeautifulSoup(html, "lxml").get_text(" ")
    name = clean_name(company.name)
    # Containment, not fuzzy match: an imprint is a whole page, the name is one line of it.
    evidence = ["name_on_imprint"] if name and f" {name} " in f" {clean_name(text)} " else []
    return evidence + _identifier_evidence(text, company, "on_imprint")


def _verdict(evidence: list[str], identifier_source: bool) -> Literal["owned", "unclear", "rejected"]:
    if any(code.startswith(("lei_", "isin_")) for code in evidence):
        return "owned"
    if "name_on_imprint" in evidence and any(code in evidence for code in _HOMEPAGE_NAME_EVIDENCE):
        return "owned"
    # A URL Wikidata gave by identifier only needs the page to agree on the name.
    if identifier_source and any(code in evidence for code in (*_HOMEPAGE_NAME_EVIDENCE, "name_on_imprint")):
        return "owned"
    return "unclear" if evidence else "rejected"


async def check_homepage(
    url: str,
    company: CompanyRef,
    user_agent: str,
    *,
    identifier_source: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SiteCheck:
    fetch_failed = SiteCheck(verdict="unclear", evidence=["fetch_failed"])
    blocklisted = SiteCheck(verdict="rejected", evidence=["blocklisted_domain"])
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
        event_hooks={"request": [ssrf_guard_request_hook]},
        transport=transport,
    ) as client:
        try:
            resp = await _get(client, url)
        except (httpx.HTTPError, httpx.InvalidURL, UnsafeURLError, ValueError) as exc:  # ValueError: bad Location
            logger.info("Site check fetch failed for %s: %s", url, exc)
            return fetch_failed
        if resp is None:
            return blocklisted
        if resp.is_redirect or resp.status_code >= 400 or "text/html" not in resp.headers.get("content-type", ""):
            return fetch_failed

        final_url = str(resp.url)
        soup = BeautifulSoup(resp.text, "lxml")
        evidence = _homepage_evidence(soup, company)
        imprint_url = _imprint_url(soup, final_url)
        if imprint_url:
            try:
                imprint = await _get(client, imprint_url)
            except (httpx.HTTPError, httpx.InvalidURL, UnsafeURLError, ValueError) as exc:
                logger.info("Site check fetch failed for %s: %s", imprint_url, exc)
                imprint = None
            if imprint is not None and not imprint.is_redirect and imprint.status_code < 400:
                evidence += _imprint_evidence(imprint.text, company)

    evidence = list(dict.fromkeys(evidence))
    verdict = _verdict(evidence, identifier_source)
    if identifier_source and verdict == "owned":
        evidence.append("identifier_source")
    return SiteCheck(verdict=verdict, evidence=evidence)
