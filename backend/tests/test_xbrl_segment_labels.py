"""Spec xbrl-segment-labels: Fixture L = Fixture S + a filing-folder index.json and _lab.xml label linkbase."""

from __future__ import annotations

import httpx
import pytest

from arp.xbrl_pipeline.store import XbrlStore
from tests.segment_fixture import FY25, GEO, REV, fixture_s, ixbrl
from tests.test_cli_xbrl import _invoke, env  # noqa: F401 -- env is a pytest fixture
from tests.test_edgar_annual_original import CIK as EDGAR_CIK
from tests.test_edgar_annual_original import _client, _source
from tests.test_xbrl_fetch import CIK10, FakeSource, _company, _fetch

STD = "http://www.xbrl.org/2003/role/label"
TERSE = "http://www.xbrl.org/2003/role/terseLabel"
ALPHA, BETA = ("x_AlphaSegmentMember", "Alpha, Beta & Co Segment [Member]"), ("x_BetaMember", "Beta Products [Member]")


def lab_xml(*labels) -> bytes:
    """labels: (href fragment, text) or (href fragment, text, lang, role)."""
    parts = []
    for i, lab in enumerate(labels):
        frag, text, lang, role = (*lab, "en-US", STD)[:4] if len(lab) == 2 else lab
        parts.append(f'<link:loc xlink:type="locator" xlink:href="x-20251231.xsd#{frag}" xlink:label="loc{i}"/>'
                     f'<link:labelArc xlink:type="arc" xlink:from="loc{i}" xlink:to="lab{i}"/>'
                     f'<link:label xlink:type="resource" xlink:label="lab{i}" xlink:role="{role}" xml:lang="{lang}">'
                     f'{text.replace("&", "&amp;")}</link:label>')
    return ('<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">'
            f'<link:labelLink xlink:type="extended">{"".join(parts)}</link:labelLink></link:linkbase>').encode()


async def _run(tmp_path, *, labels=(ALPHA, BETA), names=("x-20251231_lab.xml",), files=None, lab_status=200,
               facts=None, store=None):
    files = files or {names[0]: lab_xml(*labels)} if names else {}
    index = {"directory": {"item": [{"name": "doc1.htm"}, *({"name": n} for n in names)]}}
    content = ixbrl(facts or fixture_s())

    def handler(req):
        name = req.url.path.rpartition("/")[2]
        if name == "index.json":
            return httpx.Response(200, json=index)
        if name in files:
            return httpx.Response(lab_status, content=files[name])
        return httpx.Response(200, content=content)

    async with _client(handler) as c:
        annual = await _source(tmp_path, ["10-K"]).fetch_latest_annual_original(EDGAR_CIK, client=c, labels=True)
    store = store or XbrlStore(tmp_path / "xbrl")
    st = await _fetch(FakeSource(annual=annual), store, company=_company("s1"))
    return st, store, {r.member: r for r in store.read_segments(CIK10)}


def _seg(rows, member):
    return rows[member].segment, rows[member].segment_source


async def test_ac_1_alpha_label(tmp_path):
    _, _, rows = await _run(tmp_path)
    assert _seg(rows, "x:AlphaSegmentMember") == ("Alpha, Beta & Co", "label")


async def test_ac_2_beta_label(tmp_path):
    _, _, rows = await _run(tmp_path)
    assert _seg(rows, "x:BetaMember") == ("Beta Products", "label")


async def test_ac_3_gamma_derived(tmp_path):
    _, _, rows = await _run(tmp_path)
    assert _seg(rows, "x:GammaSegmentMember") == ("Gamma", "derived")


async def test_ac_4_label_file_stored(tmp_path):
    _, store, _ = await _run(tmp_path)
    acc = store.report_meta(CIK10).accession
    assert (store.company_dir(CIK10) / f"labels-{acc}.xml").read_bytes() == lab_xml(ALPHA, BETA)


async def test_ac_5_other_lang_and_role_ignored(tmp_path):
    labels = (("x_AlphaSegmentMember", "Alpha DE [Member]", "de", STD),
              ("x_AlphaSegmentMember", "Alpha [Member]", "en-US", TERSE), ALPHA, BETA)
    _, _, rows = await _run(tmp_path, labels=labels)
    assert rows["x:AlphaSegmentMember"].segment == "Alpha, Beta & Co"


def _all_derived(st, store, rows):
    assert len(rows) == 3 and {r.segment_source for r in rows.values()} == {"derived"} and st.status == "ok"
    assert not list(store.company_dir(CIK10).glob("labels-*.xml"))


async def test_ac_6_no_label_file_in_index(tmp_path):
    _all_derived(*await _run(tmp_path, names=()))


async def test_ac_7_label_download_404(tmp_path):
    _all_derived(*await _run(tmp_path, lab_status=404))


async def test_ac_8_standard_member_never_labelled(tmp_path):
    facts = fixture_s(extra=[(REV, {GEO: "country:US"}, 400, FY25)])
    _, _, rows = await _run(tmp_path, labels=(ALPHA, BETA, ("country_US", "United States [Member]")), facts=facts)
    assert _seg(rows, "country:US") == ("US", "derived")


async def test_ac_9_esef_rows_derived(tmp_path):
    from tests.test_xbrl_esef_segments import _fetch as esef_fetch
    from tests.test_xbrl_esef_segments import _two

    _, _, rows = await esef_fetch(tmp_path, *_two("ifrs-full:Revenue"))
    assert rows and {r.segment_source for r in rows} == {"derived"}


@pytest.mark.usefixtures("pg")
async def test_ac_10_cli_shows_label(env):  # noqa: F811
    await _run(env, store=XbrlStore(env / "xbrl"))
    result = _invoke("segments", "s1")
    assert result.exit_code == 0, result.output
    assert any("Alpha, Beta & Co" in line for line in result.stdout.splitlines())


async def test_ac_12_en_us_beats_en(tmp_path):
    labels = (("x_AlphaSegmentMember", "Alpha One [Member]", "en", STD),
              ("x_AlphaSegmentMember", "Alpha Two [Member]", "en-US", STD))
    _, _, rows = await _run(tmp_path, labels=labels)
    assert rows["x:AlphaSegmentMember"].segment == "Alpha Two"


async def test_ac_13_first_label_file_in_index_order(tmp_path):
    names = ("x-20251231_lab.xml", "y-20251231_lab.xml")
    files = {names[0]: lab_xml(ALPHA, BETA), names[1]: lab_xml(("x_AlphaSegmentMember", "Alpha Wrong [Member]"))}
    _, store, rows = await _run(tmp_path, names=names, files=files)
    assert rows["x:AlphaSegmentMember"].segment == "Alpha, Beta & Co"
    assert (store.company_dir(CIK10) / f"labels-{store.report_meta(CIK10).accession}.xml").read_bytes() == files[names[0]]


async def test_ac_14_trailing_segment_stripped(tmp_path):
    _, _, rows = await _run(tmp_path, labels=(ALPHA, ("x_BetaMember", "Delta segment [Member]")))
    assert rows["x:BetaMember"].segment == "Delta"
