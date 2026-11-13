"""Data rule 2, one review list (AC-53, AC-54): a conflict, a found document and a value item sit in the one
Review Queue, each with its kind, and the keyboard steps through them (Tape Reader is the queue's J / K keys).

The runs are seeded straight into the stack's store (no model call), so this runs on CI's key-less stack."""

import os
from uuid import uuid4

import pytest

from arp.config import Settings
from arp.schemas.common import JobStatus, RunManifest
from arp.storage.run_store import RunStore

URL = os.environ.get("ARP_E2E_URL")
DSN = os.environ.get("ARP_POSTGRES_DSN", "postgresql+psycopg://arp:arp@localhost:5432/arp_test")  # e2e_stack.sh's default
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]


@pytest.fixture
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=Settings().chromium_path)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(15_000)
        page.console_errors = []
        page.on("console", lambda m: m.type == "error" and page.console_errors.append(m.text))
        yield page
        browser.close()


def _field(value):
    return {"field_id": "capex", "field_name": "Green capex", "value": value, "citations": [], "confidence": 0.5,
            "grounded": True, "conflicting_sources": False, "value_state": "found", "route": "review",
            "period_end": "2025-12-31"}


@pytest.fixture
def three_kinds():
    """One open item of each kind, each in its own run; returns {kind label: run id}."""
    store = RunStore(DSN, Settings().runs_dir)
    tag = uuid4().hex[:8]
    runs = {"Conflict": f"extraction_e2eq{tag}", "Value": f"extraction_e2ev{tag}", "Found document": f"discovery_e2e{tag}"}
    for label, run_id in runs.items():
        run_type = "discovery" if label == "Found document" else "extraction"
        store.save_manifest(RunManifest(run_id=run_id, run_type=run_type, status=JobStatus.COMPLETED, company_count=1,
                                        completed_count=1, params={"schema_name": "Green capex", "schema_version": "sch_g:v1"}))
    issuer = f"q{tag}"
    key = f"{issuer}:capex:2025-12-31"
    base = {"item_key": key, "company_id": f"acme{tag}", "issuer_key": issuer, "field_id": "capex", "period_end": "2025-12-31"}
    store.append_review_item(runs["Conflict"], {**base, "field": _field(14), "kind": "conflict", "new_value": 14,
                                                "accepted": {"value": 12, "fact_id": 1, "status": "approved"}})
    store.append_review_item(runs["Value"], {**base, "field": _field(11)})
    sha = uuid4().hex
    store.append_review_item(runs["Found document"], {
        "item_key": f"discovered:acme{tag}:{sha}", "company_id": f"acme{tag}", "name": "Acme", "url": f"https://example.com/{tag}.pdf",
        "doc_type": "annual", "local_path": None, "sha256": sha, "company_match": "absent", "page_count": 3,
        "reporting_year": 2025, "reason_codes": ["company_not_found"]})
    return runs


def _card(page, run_id):
    return page.locator(".review-item", has_text=run_id)


def test_one_queue_lists_a_conflict_a_found_document_and_a_value(page, three_kinds):  # AC-53
    page.goto(f"{URL}/#/review")
    for label, run_id in three_kinds.items():
        card = _card(page, run_id)
        card.first.wait_for()
        assert card.count() == 1, run_id
        assert f"· {label} ·" in card.inner_text(), (label, card.inner_text())
    assert page.console_errors == []


def test_tape_reader_is_the_queue_and_j_k_step_through_the_same_items(page, three_kinds):  # AC-54
    page.goto(f"{URL}/#/tape")
    page.wait_for_url("**/#/review")
    for run_id in three_kinds.values():
        _card(page, run_id).first.wait_for()
    cards = page.locator(".review-item")
    total = cards.count()
    seen = set()
    for _ in range(total):  # J from the top visits every card once, so it reaches each seeded one
        page.keyboard.press("j")
        focused = page.evaluate("document.activeElement?.closest('.review-item')?.innerText ?? ''")
        seen |= {r for r in three_kinds.values() if r in focused}
    assert seen == set(three_kinds.values())
    page.keyboard.press("k")  # K steps back: still on a queue card
    assert page.evaluate("!!document.activeElement?.closest('.review-item')")
    assert page.console_errors == []
