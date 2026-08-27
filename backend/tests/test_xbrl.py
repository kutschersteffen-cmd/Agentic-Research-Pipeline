from __future__ import annotations

import json
import time

import httpx

from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.xbrl import XbrlFactSource


class _FailingClient:
    """Same shape as tests/test_edgar_cache.py's fake -- if a test using
    this reaches the network, .get() raises immediately rather than
    hanging in a sandboxed environment."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, *args, **kwargs):
        raise httpx.ConnectError("simulated network failure")


_COMPANY_FACTS = {
    "facts": {
        "us-gaap": {
            "PaymentsToAcquirePropertyPlantAndEquipment": {
                "units": {
                    "USD": [
                        {"end": "2024-12-31", "val": 300000000, "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-01", "accn": "0001-24-000001"},
                        {"end": "2025-12-31", "val": 340000000, "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-01", "accn": "0001-25-000001"},
                        # A quarterly row with a later filed date but not a full fiscal year -- must not win over the annual row.
                        {"end": "2026-03-31", "val": 90000000, "fy": 2026, "fp": "Q1", "form": "10-Q", "filed": "2026-04-15", "accn": "0001-26-000002"},
                    ]
                }
            },
            "ResearchAndDevelopmentExpense": {
                "units": {"USD": [{"end": "2025-12-31", "val": 120000000, "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-01", "accn": "0001-25-000001"}]}
            },
        }
    }
}


def _write_cache(cache_dir, cik10, data, fetched_at=None):
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {"_fetched_at": fetched_at if fetched_at is not None else time.time(), "data": data}
    (cache_dir / f"xbrl_companyfacts_{cik10}.json").write_text(json.dumps(payload))


def _source(tmp_path) -> XbrlFactSource:
    edgar = EdgarDocumentSource(user_agent="test-agent test@example.com", cache_dir=tmp_path / "cache")
    return XbrlFactSource(edgar, tmp_path / "cache")


async def test_picks_most_recent_full_fiscal_year_not_latest_filed_quarter(tmp_path, monkeypatch):
    source = _source(tmp_path)
    _write_cache(tmp_path / "cache", "0000320193", _COMPANY_FACTS)
    monkeypatch.setattr("arp.ingestion.xbrl.httpx.AsyncClient", _FailingClient)

    facts = await source.fetch_capex_rnd_revenue("apple", "320193")

    assert facts is not None
    assert facts.capex is not None
    assert facts.capex.value == 340000000
    assert facts.capex.fiscal_year == 2025
    assert facts.capex.tag == "PaymentsToAcquirePropertyPlantAndEquipment"
    assert facts.rnd is not None
    assert facts.rnd.value == 120000000
    assert facts.revenue is None  # not present in the fixture -- must not be invented


async def test_falls_back_through_tag_priority_list(tmp_path, monkeypatch):
    facts_json = {
        "facts": {
            "us-gaap": {
                "CapitalExpenditures": {
                    "units": {"USD": [{"end": "2025-12-31", "val": 50000000, "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-01", "accn": "x"}]}
                }
            }
        }
    }
    source = _source(tmp_path)
    _write_cache(tmp_path / "cache", "0000320193", facts_json)
    monkeypatch.setattr("arp.ingestion.xbrl.httpx.AsyncClient", _FailingClient)

    facts = await source.fetch_capex_rnd_revenue("apple", "320193")

    assert facts is not None
    assert facts.capex is not None
    assert facts.capex.tag == "CapitalExpenditures"  # not the higher-priority (absent) tag


async def test_no_matching_tags_returns_none_fields_not_zero(tmp_path, monkeypatch):
    source = _source(tmp_path)
    _write_cache(tmp_path / "cache", "0000320193", {"facts": {"us-gaap": {}}})
    monkeypatch.setattr("arp.ingestion.xbrl.httpx.AsyncClient", _FailingClient)

    facts = await source.fetch_capex_rnd_revenue("apple", "320193")

    assert facts is not None
    assert facts.capex is None
    assert facts.rnd is None


async def test_stale_cache_is_refetched(tmp_path, monkeypatch):
    source = _source(tmp_path)
    _write_cache(tmp_path / "cache", "0000320193", _COMPANY_FACTS, fetched_at=time.time() - 8 * 24 * 3600)
    monkeypatch.setattr("arp.ingestion.xbrl.httpx.AsyncClient", _FailingClient)

    try:
        await source.fetch_capex_rnd_revenue("apple", "320193")
        raised = False
    except httpx.ConnectError:
        raised = True
    assert raised  # stale cache must not be trusted -- proves TTL is actually checked


async def test_xbrl_fact_citation_is_grounded_without_a_source_document():
    from arp.ingestion.xbrl import XbrlFact

    fact = XbrlFact(tag="PaymentsToAcquirePropertyPlantAndEquipment", value=340000000, unit="USD", fiscal_year=2025, fiscal_period="FY", form="10-K", filed="2026-02-01", accession="0001-25-000001")
    citation = fact.as_citation("320193")

    assert citation.grounded is True
    assert "PaymentsToAcquirePropertyPlantAndEquipment" in citation.quote
    assert citation.doc_id == "xbrl:320193:0001-25-000001"
