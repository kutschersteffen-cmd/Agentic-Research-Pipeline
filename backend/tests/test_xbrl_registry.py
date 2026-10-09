from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arp.xbrl_pipeline.models import CatalogEntry
from arp.xbrl_pipeline.registry import TAXONOMY_SOURCES, TaxonomyRegistry, parse_taxonomy, update_taxonomies
from arp.xbrl_pipeline.store import XbrlStore

FIX = Path(__file__).parent / "fixtures" / "xbrl"
XSD = (FIX / "taxonomy_small.xsd").read_bytes()
LAB = (FIX / "taxonomy_small_lab.xml").read_bytes()


def _cat(tax, concept):
    return CatalogEntry(taxonomy=tax, concept=concept, label=None, fact_count=1, first_year=2020, last_year=2024,
                        units=["USD"])


def _registry(tmp_path, *, catalogues=None):
    store = XbrlStore(tmp_path)
    reg = TaxonomyRegistry(store)
    reg.write_snapshot("us-gaap", 2026, parse_taxonomy(XSD, LAB, taxonomy="us-gaap"))
    for i, ids in enumerate(catalogues or []):
        cik = f"{i + 1:010d}"
        store.set_meta(cik, source_sha="s", tags=None, company_id=f"c{i}", company_name="n", fact_count=1)
        store.write_catalog(cik, [_cat(*t.split(":")) for t in ids])
    return store, reg


def test_parse_taxonomy_fields():
    by = {e.concept: e for e in parse_taxonomy(XSD, LAB, taxonomy="us-gaap")}
    assert set(by) == {"Revenues", "PaymentsToAcquirePropertyPlantAndEquipment", "Assets", "OldLeaseCost"}
    rev, assets, old = by["Revenues"], by["Assets"], by["OldLeaseCost"]
    assert rev.taxonomy == "us-gaap" and rev.tag_id == "us-gaap:Revenues"
    assert rev.label == "Revenues" and rev.documentation == "Amount of revenue recognized from goods sold."
    assert rev.period_type == "duration" and rev.balance == "credit" and rev.data_type == "monetaryItemType"
    assert assets.period_type == "instant" and assets.balance == "debit" and assets.label == "Assets"
    assert old.deprecated and not rev.deprecated


def test_search_empty_query_pins_revenue_and_capex_first(tmp_path):
    _, reg = _registry(tmp_path)
    items, total = reg.search()
    assert total == 4
    assert [e.concept for e in items] == ["Revenues", "PaymentsToAcquirePropertyPlantAndEquipment", "Assets",
                                          "OldLeaseCost"]


def test_search_filters_by_text_taxonomy_and_deprecated(tmp_path):
    _, reg = _registry(tmp_path)
    assert [e.concept for e in reg.search("payments to acquire")[0]] == ["PaymentsToAcquirePropertyPlantAndEquipment"]
    assert [e.concept for e in reg.search("ASSETS")[0]] == ["Assets"]
    assert reg.search("revenues", taxonomy="ifrs-full")[1] == 0
    assert reg.search("lease")[1] == 1
    assert reg.search("lease", include_deprecated=False)[1] == 0


def test_seen_count_follows_catalogues(tmp_path):
    _, reg = _registry(tmp_path, catalogues=[["us-gaap:Revenues", "us-gaap:Assets"], ["us-gaap:Assets"]])
    by = {e.concept: e for e in reg.search()[0]}
    assert by["Revenues"].seen_count == 1 and by["Assets"].seen_count == 2


def test_seen_only_hides_unused_tags(tmp_path):
    _, reg = _registry(tmp_path, catalogues=[["us-gaap:Assets"]])
    assert [e.concept for e in reg.search(seen_only=True)[0]] == ["Assets"]


def test_extension_tag_from_catalogue_is_marked(tmp_path):
    _, reg = _registry(tmp_path, catalogues=[["xyz:CustomRevenue", "us-gaap:Assets"]])
    items, total = reg.search("custom")
    assert total == 1 and items[0].tag_id == "xyz:CustomRevenue" and items[0].extension and items[0].seen_count == 1
    assert [e.tag_id for e in reg.search(extension_only=True)[0]] == ["xyz:CustomRevenue"]
    assert not any(e.extension for e in reg.search("assets")[0])


def test_never_used_tag_has_zero_seen_count(tmp_path):
    _, reg = _registry(tmp_path, catalogues=[["us-gaap:Assets"]])
    assert {e.concept: e.seen_count for e in reg.search()[0]}["Revenues"] == 0


def test_paging_returns_total_and_slice(tmp_path):
    _, reg = _registry(tmp_path)
    items, total = reg.search(offset=1, limit=2)
    assert total == 4 and [e.concept for e in items] == ["PaymentsToAcquirePropertyPlantAndEquipment", "Assets"]
    assert reg.search(offset=10)[0] == []


def test_latest_snapshot_year_wins(tmp_path):
    _, reg = _registry(tmp_path)
    reg.write_snapshot("us-gaap", 2025, parse_taxonomy(XSD, LAB, taxonomy="us-gaap")[:1])
    assert reg.search()[1] == 4


def test_update_taxonomies_writes_snapshots_with_stub_fetch(tmp_path, monkeypatch):
    from arp.xbrl_pipeline import registry
    from arp.xbrl_pipeline.registry import TaxonomySource

    monkeypatch.setitem(registry.TAXONOMY_SOURCES, "us-gaap", TaxonomySource(2026, "http://x/s.xsd", ("http://x/l.xml",)))
    seen: list[str] = []

    async def fetch(url: str) -> bytes:
        seen.append(url)
        return XSD if url.endswith(".xsd") else LAB

    store = XbrlStore(tmp_path)
    assert asyncio.run(update_taxonomies(store, fetch=fetch, taxonomies=["us-gaap"])) == {"us-gaap": 4}
    assert (store.taxonomy_dir / "us-gaap-2026.jsonl").exists() and len(seen) == 2
    assert TaxonomyRegistry(store).search()[1] == 4


def test_update_taxonomies_names_taxonomy_without_url(tmp_path, monkeypatch):
    from arp.xbrl_pipeline import registry
    from arp.xbrl_pipeline.registry import TaxonomySource

    monkeypatch.setitem(registry.TAXONOMY_SOURCES, "dei", TaxonomySource(2026, None, ()))
    with pytest.raises(ValueError, match="dei"):
        asyncio.run(update_taxonomies(XbrlStore(tmp_path), fetch=None, taxonomies=["dei"]))  # type: ignore[arg-type]
    assert set(TAXONOMY_SOURCES) == {"us-gaap", "ifrs-full", "dei"}


def _bare(tmp_path, ids):
    store = XbrlStore(tmp_path)
    store.set_meta("0000000001", source_sha="s", tags=None, company_id="c", company_name="n", fact_count=1)
    store.write_catalog("0000000001", [_cat(*t.split(":")) for t in ids])
    return TaxonomyRegistry(store)


def test_standard_tag_without_snapshot_is_not_extension(tmp_path):
    items, total = _bare(tmp_path, ["us-gaap:Revenues"]).search()
    assert total == 1 and items[0].tag_id == "us-gaap:Revenues"
    assert not items[0].extension and items[0].seen_count == 1


def test_extension_only_returns_only_non_standard_prefix(tmp_path):
    reg = _bare(tmp_path, ["us-gaap:Revenues", "xyz:CustomRevenue"])
    assert [e.tag_id for e in reg.search(extension_only=True)[0]] == ["xyz:CustomRevenue"]


def test_standard_tag_missing_from_snapshot_is_not_extension(tmp_path):
    _, reg = _registry(tmp_path, catalogues=[["us-gaap:RetiredConcept"]])
    items, _ = reg.search("retired")
    assert [e.tag_id for e in items] == ["us-gaap:RetiredConcept"] and not items[0].extension


def test_oversized_taxonomy_file_is_rejected(monkeypatch):
    from arp.xbrl_pipeline import registry

    monkeypatch.setattr(registry, "MAX_TAXONOMY_BYTES", 10)
    with pytest.raises(ValueError, match="us-gaap"):
        parse_taxonomy(XSD, LAB, taxonomy="us-gaap")


@pytest.mark.parametrize("enc", ["utf-16", "utf-16-le", "utf-16-be", "utf-8"])
def test_entity_declaration_is_rejected_in_any_encoding(enc):
    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>'.encode(enc)
    with pytest.raises(ValueError, match="entities"):
        parse_taxonomy(evil, LAB, taxonomy="us-gaap")
