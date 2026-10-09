from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arp.xbrl_pipeline.models import CatalogEntry, TagEntry
from arp.xbrl_pipeline.registry import STANDARD_PREFIXES, TAXONOMY_SOURCES, TaxonomyRegistry, parse_taxonomy, update_taxonomies
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
    assert set(TAXONOMY_SOURCES) == {"us-gaap", "ifrs-full", "dei", "esrs"}


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


def test_http_fetch_sends_user_agent_and_follows_redirects(monkeypatch):
    import httpx

    from arp.xbrl_pipeline import registry

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(302, headers={"location": "/new"})
        assert request.headers["user-agent"] == "Me me@example.com"
        return httpx.Response(200, content=b"body")

    real = httpx.AsyncClient
    monkeypatch.setattr(registry.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert asyncio.run(registry.http_fetch("http://x/old", user_agent="Me me@example.com")) == b"body"


def test_http_fetch_raises_on_non_2xx(monkeypatch):
    import httpx

    from arp.xbrl_pipeline import registry

    real = httpx.AsyncClient
    monkeypatch.setattr(registry.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(404)), **kw))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(registry.http_fetch("http://x/missing", user_agent="Me"))


def test_srt_and_invest_are_standard_prefixes(tmp_path):
    reg = _bare(tmp_path, ["srt:Foo", "invest:Bar", "xyz:Custom"])
    assert {e.tag_id: e.extension for e in reg.search()[0]} == {
        "srt:Foo": False, "invest:Bar": False, "xyz:Custom": True}


def _count_catalog_reads(monkeypatch, store):
    reads = []
    real = store.read_catalog
    monkeypatch.setattr(store, "read_catalog", lambda cik: reads.append(cik) or real(cik))
    return reads


def test_second_search_does_not_reread_catalogues(tmp_path, monkeypatch):
    store, reg = _registry(tmp_path, catalogues=[["us-gaap:Revenues"], ["us-gaap:Assets"]])
    reads = _count_catalog_reads(monkeypatch, store)
    first = reg.search("rev")
    assert len(reads) == 2
    assert TaxonomyRegistry(XbrlStore(tmp_path)).search("rev") == first  # a per-request registry shares the cache
    assert reg.search("rev") == first and len(reads) == 2


def test_changed_catalogue_invalidates(tmp_path, monkeypatch):
    store, reg = _registry(tmp_path, catalogues=[["us-gaap:Revenues"]])
    assert reg.search("revenues")[0][0].seen_count == 1
    store.set_meta("0000000099", source_sha="s", tags=None, company_id="new", company_name=None, fact_count=1)
    store.write_catalog("0000000099", [_cat("us-gaap", "Revenues")])
    assert reg.search("revenues")[0][0].seen_count == 2
    store.write_catalog("0000000099", [_cat("us-gaap", "Assets"), _cat("us-gaap", "Liabilities")])
    assert reg.search("revenues")[0][0].seen_count == 1


def test_new_snapshot_invalidates(tmp_path):
    store, reg = _registry(tmp_path)
    assert reg.search("zzz")[1] == 0
    reg.write_snapshot("dei", 2026, [TagEntry(taxonomy="dei", concept="ZzzConcept", label=None, data_type=None,
                                              period_type=None, balance=None, documentation=None)])
    assert [e.tag_id for e in reg.search("zzz")[0]] == ["dei:ZzzConcept"]


def test_cached_results_equal_uncached(tmp_path):
    from arp.xbrl_pipeline import registry

    _, reg = _registry(tmp_path, catalogues=[["us-gaap:Revenues", "xyz:Custom"], ["us-gaap:Revenues"]])
    registry._ROWS_CACHE.clear()
    cold = [reg.search(q, seen_only=s) for q in ("", "rev") for s in (False, True)]
    warm = [reg.search(q, seen_only=s) for q in ("", "rev") for s in (False, True)]
    assert warm == cold


def test_http_fetch_stops_at_the_size_cap(monkeypatch):
    import httpx

    from arp.xbrl_pipeline import registry

    monkeypatch.setattr(registry, "MAX_TAXONOMY_BYTES", 10)
    real = httpx.AsyncClient
    monkeypatch.setattr(registry.httpx, "AsyncClient", lambda **kw: real(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 11)), **kw))
    with pytest.raises(ValueError, match="larger than 10 bytes"):
        asyncio.run(registry.http_fetch("http://x/big", user_agent="Me"))


def test_esrs_source_urls():
    base = "https://xbrl.efrag.org/taxonomy/esrs/2023-12-22/common/"
    src = TAXONOMY_SOURCES["esrs"]
    assert src.year == 2023 and src.url == base + "esrs_cor.xsd"
    assert src.labels == (base + "labels/lab_esrs-en.xml", base + "labels/doc_esrs-en.xml")


def test_esrs_is_a_standard_prefix():
    assert "esrs" in STANDARD_PREFIXES


def test_esrs_concepts_not_flagged_extension(tmp_path):
    store, reg = _registry(tmp_path, catalogues=[["esrs:Foo"]])
    reg.write_snapshot("esrs", 2023, [])
    hits, total = reg.search(taxonomy="esrs")
    assert total == 1 and hits[0].concept == "Foo" and hits[0].extension is False


_ESRS_XSD = b"""<?xml version="1.0" encoding="UTF-8"?>
<xsd:schema targetNamespace="https://xbrl.efrag.org/taxonomy/esrs/2023-12-22" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldt="http://xbrl.org/2005/xbrldt" xmlns:dtr-types="http://www.xbrl.org/dtr/type/2024-01-31">
  <xsd:element name="AbsoluteValueOfLocationBasedScope2GreenhouseGasEmissionsReduction" id="esrs_AbsoluteValueOfLocationBasedScope2GreenhouseGasEmissionsReduction" type="dtr-types:ghgEmissionsItemType" substitutionGroup="xbrli:item" abstract="false" nillable="true" xbrli:periodType="duration"/>
  <xsd:element name="TargetCoverageAxis" id="esrs_TargetCoverageAxis" type="xbrli:stringItemType" substitutionGroup="xbrldt:dimensionItem" abstract="true" nillable="true" xbrli:periodType="duration"/>
  <xsd:element name="ReferenceToLocationInSustainabilityStatementOfDisclosureRequirementsCompliedWithInPreparingSustainabilityStatement" id="esrs_ReferenceToLocationInSustainabilityStatementOfDisclosureRequirementsCompliedWithInPreparingSustainabilityStatement" type="xbrli:stringItemType" substitutionGroup="xbrli:item" abstract="false" nillable="true" xbrli:periodType="duration"/>
</xsd:schema>"""
_ESRS_LAB = b"""<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:labelLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">
    <link:loc xlink:type="locator" xlink:href="../esrs_cor.xsd#esrs_AbsoluteValueOfLocationBasedScope2GreenhouseGasEmissionsReduction" xlink:label="loc_6"/>
    <link:label xlink:type="resource" xlink:label="res_6" xlink:role="http://www.xbrl.org/2003/role/label" xml:lang="en">Absolute value of location-based Scope 2 Greenhouse gas emissions reduction</link:label>
    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" xlink:from="loc_6" xlink:to="res_6"/>
    <link:loc xlink:type="locator" xlink:href="../esrs_cor.xsd#esrs_TargetCoverageAxis" xlink:label="loc_3"/>
    <link:label xlink:type="resource" xlink:label="res_3" xlink:role="http://www.xbrl.org/2003/role/label" xml:lang="en">Target coverage [axis]</link:label>
    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" xlink:from="loc_3" xlink:to="res_3"/>
  </link:labelLink>
</link:linkbase>"""
_ESRS_DOC = b"""<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:labelLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">
    <link:loc xlink:type="locator" xlink:href="../esrs_cor.xsd#esrs_AbsoluteValueOfLocationBasedScope2GreenhouseGasEmissionsReduction" xlink:label="loc_1"/>
    <link:label xlink:type="resource" xlink:label="res_1" xlink:role="http://www.xbrl.org/2003/role/documentation" xml:lang="en">The value should be presented in tCO2e.</link:label>
    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" xlink:from="loc_1" xlink:to="res_1"/>
  </link:labelLink>
</link:linkbase>"""


def test_parse_small_esrs_excerpt():
    by = {e.concept: e for e in parse_taxonomy(_ESRS_XSD, [_ESRS_LAB, _ESRS_DOC], taxonomy="esrs")}
    assert set(by) == {"AbsoluteValueOfLocationBasedScope2GreenhouseGasEmissionsReduction",
                       "ReferenceToLocationInSustainabilityStatementOfDisclosureRequirementsCompliedWithInPreparingSustainabilityStatement"}
    e = by["AbsoluteValueOfLocationBasedScope2GreenhouseGasEmissionsReduction"]
    assert e.tag_id.startswith("esrs:") and e.data_type == "ghgEmissionsItemType" and e.period_type == "duration"
    assert e.label.startswith("Absolute value of location-based") and e.documentation == "The value should be presented in tCO2e."
