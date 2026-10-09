from __future__ import annotations

from pathlib import Path

import pytest

from arp.storage.safe_path import UnsafeIdentifierError
from arp.xbrl_pipeline.selection import cut_selection, list_selections, parse_tag_ids, read_selection_facts
from arp.xbrl_pipeline.store import XbrlStore

FIXTURE = Path(__file__).parent / "fixtures" / "xbrl" / "companyfacts_small.json"
REV = "us-gaap:Revenues"


def _store_company(store: XbrlStore, cik: str, tags: list[str]) -> None:
    sha = store.save_original(cik, FIXTURE.read_bytes())
    store.set_meta(cik, source_sha=sha, tags=tags, company_id=f"c{cik}", company_name=None, fact_count=5)


def test_cut_from_original_after_a_different_fetch(tmp_path):
    s = XbrlStore(tmp_path)
    _store_company(s, "0000000001", ["us-gaap:NetIncomeLoss"])  # fetch used tag set B only
    assert cut_selection(s, "rev", frozenset({REV})) == 3
    rows, total = read_selection_facts(s, "rev")
    assert total == 3 and len(rows) == 3
    assert {r.tag_id for r in rows} == {REV}
    assert {r.company_id for r in rows} == {"c0000000001"}


def test_cut_covers_every_stored_company(tmp_path):
    s = XbrlStore(tmp_path)
    _store_company(s, "0000000001", None)
    _store_company(s, "0000000002", None)
    assert cut_selection(s, "rev", frozenset({REV})) == 6
    rows, _ = read_selection_facts(s, "rev", limit=100)
    assert sorted({r.cik for r in rows}) == ["0000000001", "0000000002"]


def test_cut_with_unused_tag_returns_zero_and_still_saves(tmp_path):
    s = XbrlStore(tmp_path)
    _store_company(s, "0000000001", None)
    assert cut_selection(s, "none", frozenset({"us-gaap:Nope"})) == 0
    assert [x["name"] for x in list_selections(s)] == ["none"]
    assert read_selection_facts(s, "none") == ([], 0)


@pytest.mark.parametrize("name", ["../x", ""])
def test_unsafe_name_rejected(tmp_path, name):
    s = XbrlStore(tmp_path)
    with pytest.raises(UnsafeIdentifierError):
        cut_selection(s, name, frozenset({REV}))
    with pytest.raises(UnsafeIdentifierError):
        read_selection_facts(s, name)


def test_list_and_read_paging(tmp_path):
    s = XbrlStore(tmp_path)
    _store_company(s, "0000000001", None)
    cut_selection(s, "b", frozenset({REV, "us-gaap:NetIncomeLoss"}))
    cut_selection(s, "a", frozenset({REV}))
    listed = list_selections(s)
    assert [x["name"] for x in listed] == ["a", "b"]
    assert listed[0]["tags"] == [REV] and listed[0]["created_at"]
    all_rows, total = read_selection_facts(s, "a")
    assert total == 3
    page, total = read_selection_facts(s, "a", offset=1, limit=1)
    assert total == 3 and page == all_rows[1:2]
    assert read_selection_facts(s, "a", offset=5) == ([], 3)


def test_parse_tag_ids_accepts_taxonomy_concept_pairs():
    assert parse_tag_ids(["us-gaap:Revenues", "ifrs-full:Revenue", "us-gaap:Revenues"]) == frozenset(
        {"us-gaap:Revenues", "ifrs-full:Revenue"})


@pytest.mark.parametrize("bad", ["Revenues", "us-gaap:", ":Revenues", "a b:C", "us-gaap:Rev enues", ""])
def test_parse_tag_ids_rejects_malformed(bad):
    with pytest.raises(ValueError, match="tag"):
        parse_tag_ids(["us-gaap:Revenues", bad])


def test_parse_tag_ids_rejects_empty_list():
    with pytest.raises(ValueError, match="tags must not be empty"):
        parse_tag_ids([])


ESEF_FIXTURE = Path(__file__).parent / "fixtures" / "xbrl_esef_sample.json"
LEI = "529900FIXTURELEI0001"
FILING = {"fxo_id": f"{LEI}-2022-12-31-ESEF-DE-0", "date_added": "2023-04-01 10:00:00.000000"}


def _store_esef(store: XbrlStore, filing: dict | None = FILING) -> None:
    sha = store.save_original(LEI, ESEF_FIXTURE.read_bytes(), prefix="xbrl-json")
    store.set_meta(LEI, source_sha=sha, tags=None, company_id="eu1", company_name=None, fact_count=5,
                   market="esef", original_file=f"xbrl-json-{sha[:16]}.json", filing=filing)


def test_cut_mixes_sec_and_esef_companies(tmp_path):
    s = XbrlStore(tmp_path)
    _store_company(s, "0000000001", None)
    _store_esef(s)
    n = cut_selection(s, "mix", frozenset({REV, "ifrs-full:Revenue"}))
    rows, total = read_selection_facts(s, "mix", limit=100)
    assert n == total and {(r.market, r.tag_id) for r in rows} == {("sec", REV), ("esef", "ifrs-full:Revenue")}
    esef = next(r for r in rows if r.market == "esef")
    assert (esef.cik, esef.company_id, esef.form, esef.accession, esef.filed) == (
        LEI, "eu1", "ESEF", FILING["fxo_id"], "2023-04-01")


def test_cut_esef_without_stored_filing_info(tmp_path):
    s = XbrlStore(tmp_path)
    _store_esef(s, filing=None)  # stored before meta.json recorded the filing
    assert cut_selection(s, "rev", frozenset({"ifrs-full:Revenue"})) > 0
    rows, _ = read_selection_facts(s, "rev")
    assert {(r.accession, r.filed) for r in rows} == {(None, None)}


def test_cut_does_not_crash_on_a_non_companyfacts_original(tmp_path):
    s = XbrlStore(tmp_path)
    sha = s.save_original("0000000001", b'{"facts": {"fact-1": {"value": "x"}, "t": "s"}}')
    s.set_meta("0000000001", source_sha=sha, tags=None, company_id="c1", company_name=None, fact_count=0)
    assert cut_selection(s, "x", frozenset({"fact-1:value"})) == 0
