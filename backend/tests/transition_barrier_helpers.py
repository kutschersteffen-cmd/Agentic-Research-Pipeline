"""Fixture documents D1-D4, the test users, and a helper that enters an analyst fact with an uploaded PDF."""

from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from arp.api.auth import Principal, current_user
from arp.api.main import app

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
