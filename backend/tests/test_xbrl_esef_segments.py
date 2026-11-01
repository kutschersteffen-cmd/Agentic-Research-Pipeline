from __future__ import annotations

import json

from arp.xbrl_pipeline.fetch_esef import EsefFiling
from arp.xbrl_pipeline.store import XbrlStore
from tests.test_xbrl_esef_fetch import ATTRS, JSON_BYTES, LEI, FakeSource, _run, _zip

FY = "2022-01-01T00:00:00/2023-01-01T00:00:00"
AXIS = "ifrs-full:SegmentsAxis"


def _fact(concept, value, member=None, unit="iso4217:EUR"):
    dims = {"concept": concept, "entity": "scheme:x", "period": FY}
    if unit:
        dims["unit"] = unit
    if member:
        dims[AXIS] = member
    return {"value": value, "dimensions": dims}


def _doc(*facts) -> bytes:
    doc = json.loads(JSON_BYTES)
    doc["facts"].update({f"seg-{i}": f for i, f in enumerate(facts)})
    return json.dumps(doc).encode()


async def _fetch(tmp_path, *facts):
    store = XbrlStore(tmp_path)
    st = await _run(FakeSource(EsefFiling(ATTRS, _doc(*facts), _zip(), "https://idx.example/x.zip")), store)
    return st, store, store.read_segments(LEI)


def _two(concept):
    return [_fact(concept, "600", "co:AMember"), _fact(concept, "400", "co:BMember")]


async def test_ac_13_esef_revenue(tmp_path):
    st, store, rows = await _fetch(tmp_path, *_two("ifrs-full:Revenue"))
    assert st.status == "ok" and len(rows) == 2 and {r.market for r in rows} == {"esef"}
    assert store.meta(LEI)["segment_count"] == 2
    assert all(r.sum_matches_total for r in rows)  # the fixture's non-dimensional Revenue is 1000


async def test_ac_20_skipped_dimensional_unchanged(tmp_path):
    _, store, _ = await _fetch(tmp_path, *_two("ifrs-full:Revenue"))
    base = XbrlStore(tmp_path / "base")
    await _run(FakeSource(), base)
    assert store.meta(LEI)["skipped_dimensional"] == base.meta(LEI)["skipped_dimensional"] + 2
    def plain(s):
        return [r.model_dump(exclude={"source_sha"}) for r in s.read_facts(LEI)]
    assert plain(store) == plain(base) and store.read_required(LEI) == base.read_required(LEI)


async def test_ac_28_esef_rnd(tmp_path):
    _, _, rows = await _fetch(tmp_path, *_two("ifrs-full:ResearchAndDevelopmentExpense"))
    assert [(r.metric, r.market) for r in rows] == [("rnd", "esef")] * 2


async def test_ac_31_esef_note(tmp_path):
    note = _fact("ifrs-full:DisclosureOfOperatingSegmentsExplanatory", "<p>Segment A makes steel.</p>", unit=None)
    _, store, _ = await _fetch(tmp_path, note)
    assert (store.company_dir(LEI) / "segment_note.txt").read_text() == "Segment A makes steel."
    assert store.meta(LEI)["segment_note_chars"] == len("Segment A makes steel.")


async def test_ac_38_no_esef_opex(tmp_path):
    facts = [*_two("ifrs-full:Revenue"), *_two("ifrs-full:ResearchAndDevelopmentExpense"),
             *_two("ifrs-full:CostOfSales"), *_two("ifrs-full:SellingGeneralAndAdministrativeExpense")]
    _, _, rows = await _fetch(tmp_path, *facts)
    assert len(rows) == 8 and not any(r.metric == "opex" for r in rows)
