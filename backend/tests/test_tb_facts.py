from __future__ import annotations

import shutil
from datetime import date

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import current_user
from arp.api.main import app
from arp.config import get_settings
from arp.transition_barrier import dataset, store
from arp.transition_barrier.facts import pdf_pages
from arp.transition_barrier.rule_book import load_rule_book
from tests.transition_barrier_helpers import (
    A_ANALYST,
    CELL,
    FIXTURES,
    QUOTES,
    enter_fact,
    fixture_pdf,
    pdf_with,
)

pytestmark = pytest.mark.usefixtures("pg")
TODAY = date(2026, 10, 20)
D1_TITLE, D3_TITLE = "EU ETS Market Report 2026", "Steel Policy Tracker"


@pytest.fixture
def fixture_dir(tmp_path, monkeypatch, pg):
    target = tmp_path / "transition_barrier"
    shutil.copytree(FIXTURES, target)
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(target))
    get_settings.cache_clear()
    dataset.reset_caches()
    yield target
    app.dependency_overrides.pop(current_user, None)
    get_settings.cache_clear()
    dataset.reset_caches()


@pytest.fixture
def client(fixture_dir):
    return TestClient(app)


def values():
    rules = load_rule_book(dataset.data_dir())[0].criteria["STL-R1"]
    return store.cell_values("STL-R1", "European Union", rules, dataset.load_criteria()[0].primary_sources, TODAY)


def enter(client, fact, value, doc, page, **kw):
    r = enter_fact(client, fact, value, doc, page, as_user=A_ANALYST, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def register(client, fact, value, key, page, quote):
    """A fact citing a registered source, without a document."""
    app.dependency_overrides[current_user] = lambda: A_ANALYST
    form = {"fact": fact, "value": str(value), "quote": quote, "page": str(page), "source_key": key}
    r = client.post(f"{CELL}/facts", data=form)
    assert r.status_code == 201, r.text
    return r.json()


def refused(r, status, message):
    assert (r.status_code, r.json()["detail"]) == (status, message)


def test_ac46(client):
    app.dependency_overrides[current_user] = lambda: A_ANALYST
    form = {"fact": "price", "value": "72", "unit": "USD/tCO2", "quote": "about USD 70", "page": "12", "source_key": "eu_ets_report"}
    refused(client.post(f"{CELL}/facts", data=form), 422, "Number not in quote.")


def test_ac47(client):
    other = pdf_with(["Nothing to see here."] * 12)
    r = enter_fact(client, "price", 72, "D1", 12, as_user=A_ANALYST, quote="USD 72/tCO2", title="Extra report", pdf=other,
                   as_of="2026-05-01")
    refused(r, 422, "Quote not found in the uploaded document.")


def test_ac48(client):
    r = enter_fact(client, "price", 72, "D4", 1, as_user=A_ANALYST, quote="USD 72/tCO2")
    refused(r, 422, "News cannot ground a fact.")


def test_ac145(client):
    r = enter_fact(client, "price", 72, "D1", 12, as_user=A_ANALYST, quote="about USD 70", publisher="", tier="news")
    refused(r, 422, "An uploaded document needs a title, publisher, as-of date and tier.")


def test_ac49(client):
    out = enter(client, "price", 72, "D1", 12)
    assert (out["page"], out["machine_checked"]) == (12, True)
    [v] = values()
    assert (v.value, v.unit, v.document, v.page, v.confidence, v.machine_checked, v.entered_by) == (
        72.0, "USD/tCO2", D1_TITLE, 12, "high", True, "a.analyst",
    )
    assert v.id == str(out["id"]) and v.document_id is not None


def test_found_page_replaces_stated_page(client):
    assert enter(client, "price", 72, "D1", 5, quote=QUOTES["D1"][12])["page"] == 12


def test_no_document_is_low_and_unchecked(client):
    register(client, "applies", "Yes", "eu_ets_report", 4, QUOTES["D1"][4])
    [v] = values()
    assert (v.value, v.document, v.confidence, v.machine_checked, v.entered_by, v.document_id) == (
        True, D1_TITLE, "low", False, "a.analyst", None,
    )


def test_ac50_empty_reason(client):
    a = enter(client, "price", 72, "D1", 12)
    enter(client, "price", 30, "D3", 7)
    for reason in ("", "  "):
        r = client.post(f"{CELL}/choices", json={"fact": "price", "value_id": a["id"], "reason": reason})
        refused(r, 422, "A reason is required.")


def test_unit_refused(client):
    r = enter_fact(client, "price", 66.9, "D1", 19, as_user=A_ANALYST, quote=QUOTES["D1"][19], unit="KRW/tCO2")
    refused(r, 422, "Unit not convertible: KRW/tCO2")


def test_pdf_only(client):
    app.dependency_overrides[current_user] = lambda: A_ANALYST
    form = {"fact": "price", "value": "72", "quote": QUOTES["D1"][12], "title": "T", "publisher": "P", "as_of": "2026-03-31", "tier": "primary"}
    r = client.post(f"{CELL}/facts", data=form, files={"file": ("x.txt", b"hello", "text/plain")})
    refused(r, 422, "Upload a PDF document.")


def test_too_large(client, monkeypatch):
    monkeypatch.setenv("ARP_MAX_UPLOAD_BYTES", "100")
    get_settings.cache_clear()
    assert enter_fact(client, "price", 72, "D1", 12, as_user=A_ANALYST).status_code == 413


def test_scanned_pdf_gives_quote_not_found(client):
    import io

    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawImage(ImageReader(Image.new("RGB", (200, 50), "white")), 72, 700)
    c.showPage()
    c.save()
    r = enter_fact(client, "price", 72, "D1", 12, as_user=A_ANALYST, pdf=buf.getvalue())
    refused(r, 422, "Quote not found in the uploaded document.")


def test_bad_value_unknown_fact_and_cell(client):
    r = enter_fact(client, "price", "lots", "D1", 12, as_user=A_ANALYST)
    refused(r, 422, "Value must be a number.")
    refused(enter_fact(client, "levy", "maybe", "D2", 3, as_user=A_ANALYST), 422, "Value must be Yes or No.")
    refused(enter_fact(client, "nope", 1, "D1", 12, as_user=A_ANALYST), 422, "Unknown fact nope")
    refused(enter_fact(client, "price", 72, "D1", 12, as_user=A_ANALYST, cell="/api/transition-barrier/cells/XXX/European Union"),
            404, "Unknown cell XXX / European Union")
    refused(enter_fact(client, "price", 72, "D1", 12, as_user=A_ANALYST, cell="/api/transition-barrier/cells/STL-R1/Mars"),
            404, "Unknown cell STL-R1 / Mars")


def test_same_source_replaces(client):
    enter(client, "price", 72, "D1", 12)
    enter(client, "price", 45, "D1", 14)
    [v] = values()
    assert (v.value, v.page) == (45.0, 14)
    assert len(store.cell_facts("STL-R1", "European Union")) == 2  # both stay in the history


def test_document_is_served(client):
    pdf = fixture_pdf("D1")
    out = enter(client, "price", 72, "D1", 12, pdf=pdf)
    doc_id = values()[0].document_id
    r = client.get(f"/api/transition-barrier/documents/{doc_id}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content == pdf and out["id"]
    assert client.get("/api/transition-barrier/documents/999").status_code == 404


def test_choice_holds_until_new_value(client):
    d1 = enter(client, "price", 72, "D1", 12)
    enter(client, "price", 30, "D3", 7)
    assert len(values()) == 2
    r = client.post(f"{CELL}/choices", json={"fact": "price", "value_id": d1["id"], "reason": "newer data"})
    assert r.status_code == 201
    assert [(v.document, v.value) for v in values()] == [(D1_TITLE, 72.0)]
    assert [(v.document, v.value) for v in values()] == [(D1_TITLE, 72.0)]  # holds on later derivations
    enter(client, "price", 40, "D3", 11)
    assert [(v.document, v.value) for v in values()] == [(D1_TITLE, 72.0), (D3_TITLE, 40.0)]


def test_choice_needs_a_current_value(client):
    d1 = enter(client, "price", 72, "D1", 12)
    refused(client.post(f"{CELL}/choices", json={"fact": "price", "value_id": "999", "reason": "x"}), 422, "Unknown value 999")
    refused(client.post(f"{CELL}/choices", json={"fact": "nope", "value_id": d1["id"], "reason": "x"}), 422, "Unknown fact nope")


def test_value_order(client):
    enter(client, "price", 30, "D3", 7)  # uploads, entered D3 first
    enter(client, "price", 72, "D1", 12)
    register(client, "price", 30, "steel_policy_tracker", 7, QUOTES["D3"][7])  # registered, entered D3 first
    register(client, "price", 72, "eu_ets_report", 12, QUOTES["D1"][12])
    assert [(v.document, v.document_id is None) for v in values()] == [
        (D1_TITLE, True), (D3_TITLE, True), (D3_TITLE, False), (D1_TITLE, False),
    ]


@pytest.mark.parametrize("doc", ["D1", "D2", "D3"])
def test_committed_pdfs_have_their_quotes(doc):
    pages = pdf_pages((FIXTURES / f"{doc}.pdf").read_bytes())
    assert len(pages) == max(QUOTES[doc])
    for page, quote in QUOTES[doc].items():
        assert quote in pages[page - 1]
    assert all(not text.strip() for n, text in enumerate(pages, 1) if n not in QUOTES[doc])
