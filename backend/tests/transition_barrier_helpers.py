"""Fixture documents D1-D4, the test users, and a helper that enters an analyst fact with an uploaded PDF."""

from __future__ import annotations

import io
import ipaddress
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from arp.api.auth import Principal, current_user
from arp.api.main import app
from arp.db.models import BarrierSourceDocument
from arp.db.session import transaction
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.verifier_agent import VerifierOutput
from arp.llm.base import LLMUsage
from arp.net_safety import UnsafeURLError
from arp.transition_barrier import fetching

FIXTURES = Path(__file__).parent / "fixtures" / "transition_barrier"
CELL = "/api/transition-barrier/cells/STL-R1/European Union"

A_ANALYST = Principal(user_id="a.analyst", name="a.analyst", role="analyst")
B_ANALYST = Principal(user_id="b.analyst", name="b.analyst", role="analyst")
A_APPROVER = Principal(user_id="a.approver", name="a.approver", role="approver")
B_APPROVER = Principal(user_id="b.approver", name="b.approver", role="approver")

# title, tier, as-of
DOCS = {
    "D1": ("EU ETS Market Report 2026", "primary", "2026-03-31"),
    "D2": ("CBAM Regulation 2023/956", "primary", "2023-05-16"),
    "D3": ("Steel Policy Tracker", "secondary", "2026-06-30"),
    "D4": ("Carbon Weekly", "news", "2026-09-01"),
}
PRICE = "The effective carbon price was USD {}/tCO2."
QUOTES = {
    "D1": {
        4: "The carbon price applies to steel producers.",
        12: PRICE.format(72),
        8: "Renewable LCOE was USD 45/MWh.",
        9: "New-build fossil LCOE was USD 60/MWh.",
        13: "The floor price was USD 30/tCO2.",
        14: PRICE.format(45),
        15: PRICE.format("72.005"),
        16: "The effective carbon price fell to USD 9/tCO2.",
        17: "The effective carbon price was CNY 66.9/tCO2.",
        18: "The effective carbon price was CNY 71.42/tCO2.",
        19: "The effective carbon price was KRW 66.9/tCO2.",
        20: "Steel is covered by the EU ETS.",
    },
    "D2": {3: "The border levy applies from 1 January 2026."},
    "D3": {
        7: "Estimates range from USD 30/tCO2 to USD 65/tCO2.",
        8: "The carbon price applies to steel.",
        9: PRICE.format(9),
        10: "No border levy is in force.",
        11: PRICE.format(40),
        12: "New-build fossil LCOE was USD 60/MWh.",
        13: "A border levy is in force.",
        14: "No carbon pricing scheme covers steel.",
    },
    "D4": {1: PRICE.format(72)},
}


def pdf_with(pages: list[str | None]) -> bytes:
    """A PDF with one page per entry: the text drawn on it, or a blank page for None."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for text in pages:
        if text:
            c.drawString(72, 700, text)
        c.showPage()
    c.save()
    return buf.getvalue()


def fixture_pdf(doc: str) -> bytes:
    """D1, D2, D3 or D4: one quote per stated page from the quotes table, the other pages blank."""
    quotes = QUOTES[doc]
    return pdf_with([quotes.get(n) for n in range(1, max(quotes) + 1)])


def enter_fact(
    client, fact, value, doc, page, *, as_user=B_APPROVER, quote=None, title=None, publisher="Fixture", as_of=None,
    tier=None, pdf=None, unit=None, cell=CELL, filename=None,
):
    """Posts an analyst fact citing `doc` uploaded as its PDF, with the documents table's title, as-of and tier."""
    d_title, d_tier, d_as_of = DOCS[doc]
    app.dependency_overrides[current_user] = lambda: as_user
    form = {
        "fact": fact,
        "value": "Yes" if value is True else "No" if value is False else str(value),
        "quote": quote if quote is not None else QUOTES[doc][page],
        "page": str(page),
        "title": title or d_title,
        "publisher": publisher,
        "as_of": as_of or d_as_of,
        "tier": tier or d_tier,
    }
    if unit:
        form["unit"] = unit
    files = {"file": (filename or f"{doc}.pdf", pdf or fixture_pdf(doc), "application/pdf")}
    return client.post(f"{cell}/facts", data=form, files=files)


def derive(client, cells=(("STL-R1", "European Union"),)):
    """`POST /derive` for the cells (code, region); returns the id of the finished run."""
    r = client.post("/api/transition-barrier/derive", json={"cells": [{"code": c, "region": g} for c, g in cells]})
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


D_URLS = {
    "D1": "https://climate.ec.europa.eu/eu-ets-market-report-2026.pdf",
    "D2": "https://eur-lex.europa.eu/eli/reg/2023/956/oj",
    "D3": "https://example.org/steel-policy-tracker",
}


def fetch_stub(monkeypatch, served: dict[str, tuple[bytes, str, str | None]] | None = None) -> list[str]:
    """Serves URLs to `fetching` from memory: url -> (body, content type, Last-Modified as an ISO date).
    D1-D3 are served as their fixture PDFs unless `served` replaces them. Returns the list of requested URLs."""
    pages = {
        D_URLS[d]: (fixture_pdf(d), "application/pdf", DOCS[d][2]) for d in D_URLS
    } | (served or {})
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) not in pages:
            return httpx.Response(404)
        body, content_type, modified = pages[str(request.url)]
        headers = {"content-type": content_type}
        if modified:
            headers["last-modified"] = format_datetime(datetime.combine(date.fromisoformat(modified), datetime.min.time(), UTC), usegmt=True)
        return httpx.Response(200, content=body, headers=headers)

    def assert_safe(url) -> None:  # no DNS: only an IP literal can be refused
        host = urlparse(str(url)).hostname or ""
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise UnsafeURLError(f"{host} is a disallowed address")

    monkeypatch.setattr(fetching, "build_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True))
    monkeypatch.setattr(fetching, "assert_safe", assert_safe)
    monkeypatch.setattr(fetching, "fetch_sources", getattr(fetching.fetch_sources, "real", fetching.fetch_sources))  # conftest's stand-in
    return requested


_BLOCK = re.compile(r"^\[doc_id=(\S+) \| passage_id=(\S+)[^\]\n]*\]\n(.*?)(?=\n\n---\n\n|\Z)", re.S | re.M)


def _stored_title(doc_id: str) -> str:
    with transaction() as s:
        return s.get(BarrierSourceDocument, int(doc_id.removeprefix("tbsrc_"))).title


class FactStub:
    """The extraction stub: answers keyed by (fact id, document title), a missing key meaning not found.
    The prompt shows only `doc_id`, so `title_of` resolves it (default: the stored barrier source document)."""

    def __init__(self, answers: dict[tuple[str, str], PeriodValue | None], title_of: Callable[[str], str] = _stored_title):
        self.answers, self.title_of = answers, title_of
        self.calls: list[str] = []

    async def complete_structured(self, *, system, prompt, output_model, images=None, **_):
        self.calls.append(output_model.__name__)
        usage = LLMUsage(provider="fake")
        if output_model is VerifierOutput:
            return VerifierOutput(agrees=True, confidence=1.0, notes=""), usage
        assert issubclass(output_model, ExtractionDraft), output_model  # the per-field typed draft subclasses it
        fact = re.search(r"^Field: (.+)$", prompt, re.M)[1]
        blocks = _BLOCK.findall(prompt)
        answer = self.answers.get((fact, self.title_of(blocks[0][0]))) if blocks else None
        if answer is None:
            return ExtractionDraft(confidence=1.0), usage
        cites = []
        for c in answer.citations:  # the passage that holds the quote, else the first shown
            doc_id, passage_id, _ = next((b for b in blocks if c.quote in b[2]), blocks[0])
            cites.append(c.model_copy(update={"doc_id": doc_id, "passage_id": passage_id}))
        return ExtractionDraft(values=[answer.model_copy(update={"citations": cites})], confidence=1.0), usage
