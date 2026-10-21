"""Consistency flags (pure; spec 2026-10-21 sections 1-2), over hand-built inputs that mirror C's defaults."""

from __future__ import annotations

from arp.schemas.transition_alignment import ActionOut, B02Out, RedlineOut
from arp.transition_alignment.delivery import score_coverage
from arp.transition_alignment.flags import score_flags
from tests.test_transition_alignment_delivery import (
    CN,
    EU,
    P2,
    US,
    fact,
    num,
    o1,
    savings,
    targets,
)

BF = "No new blast furnace without CCS or a near-zero route"
IDS = ["no_lowcarbon_capex", "net_zero_no_phaseout", "expansion_vs_net_zero", "regions_left_out", "offsets_emphasised"]


def _action(key, year, region):
    b = B02Out(met=False, text="")
    return ActionOut(key=key, action_id=None, act_lever=None, text=key, status="planned", year=year, region=region,
                     citation=None, timeframe=None, b02={"b": b, "c": b, "d": b}, barriers=[], note=None, fact_ids=[])


def actions(a1_year=2028, regions=(EU, US, CN)):
    keys, years = ("action:p1:12:1", "action:p1:15:1", "action:p1:16:1"), (a1_year, 2022, None)
    return [_action(k, y, r) for k, y, r in zip(keys, years, regions, strict=True)]


def capex_facts():
    return [num("tc_capex_total", 1000, 44, unit="EUR million", year=2025, doc=P2),
            num("tc_lowcarbon_capex", 120, 45, unit="EUR million", year=2025, doc=P2),
            num("tc_lowcarbon_capex_share_pct", 12, 45, unit="%", year=2025, doc=P2)]


def redline(breached=False, label=BF, rid="stl_bf"):
    f = fact("tc_new_blast_furnace", breached, 48, doc=P2)
    return RedlineOut(id=rid, label=label, status="breached" if breached else "not breached", text=label,
                      citation=f.citation, fact_id=f.fact_id, source="owner-defined (2026-10-19)")


def operates(*codes):
    return [fact(f"ta_operates_{c}", True, 3, doc=P2) for c in codes]


def yes_no(field_id, value, page):
    return fact(field_id, value, page)


def inputs(**over):
    ts, _ = targets()
    acts = over.pop("actions", None) or actions()
    kw = dict(
        reporting_year=2025, capex_facts=capex_facts(), redlines=[redline()], targets=ts,
        coverage=score_coverage(ts, acts, savings()), phaseouts=[o1()], actions=acts, regions=[EU, US, CN],
        operates=operates("eu", "us", "cn"), net_zero=yes_no("tp_a_ambition_3", True, 25),
        offsets=yes_no("tp_a_offsetting_13", False, 26),
    )
    kw.update(over)
    return kw


def flags(**over):
    out, header = score_flags(**inputs(**over))
    return {f.id: f for f in out}, header


def no_capex(**over):
    return flags(capex_facts=[num("tc_capex_total", 1000, 44, unit="EUR million", year=2025, doc=P2)], **over)


def test_ac130_order_and_titles():
    out, _ = score_flags(**inputs())
    assert [(f.id, f.title) for f in out] == [
        ("no_lowcarbon_capex", "Falling emissions claimed, no low-carbon capex"),
        ("net_zero_no_phaseout", "Net zero without phase-out"),
        ("expansion_vs_net_zero", "Expansion against net zero"),
        ("regions_left_out", "Regions left out"),
        ("offsets_emphasised", "Offsets emphasised"),
    ]


def test_ac150_cites():
    out, _ = score_flags(**inputs())
    assert [f.cite for f in out] == ["ACT Framework p.64", "ACT Framework pp.61–62", "ACT Framework p.62",
                                     "ACT Framework p.61", "ACT Framework p.62; ACT Core p.26"]


def test_ac131_offsets_raised():
    f = flags()[0]["offsets_emphasised"]
    assert (f.state, f.text) == ("raised", "Does not state that credits are used only for residual emissions.")


def test_ac132_others_clear():
    out = flags()[0]
    assert [(out[i].state, out[i].text) for i in IDS[:4]] == [("clear", "No flag.")] * 4


def test_ac133_header():
    assert flags()[1] == "Consistency: 1 of 5 checks raise a flag"


def test_ac134_no_lowcarbon_capex():
    f = no_capex()[0]["no_lowcarbon_capex"]
    assert (f.state, f.text) == (
        "raised", "2030 target −30% and actions saving 3.5 MtCO2e/yr, but no low-carbon capex disclosed for 2025.")


def test_zero_lowcarbon_capex_counts_as_none():  # "> 0": a disclosed 0 is no low-carbon capex
    facts = [num("tc_lowcarbon_capex", 0, 45, unit="EUR million", year=2025, doc=P2),
             num("tc_lowcarbon_capex_share_pct", 0, 45, unit="%", year=2025, doc=P2)]
    assert flags(capex_facts=facts)[0]["no_lowcarbon_capex"].state == "raised"


def test_lowcarbon_capex_of_another_year_does_not_count():
    facts = [num("tc_lowcarbon_capex", 120, 45, unit="EUR million", year=2024, doc=P2)]
    assert flags(capex_facts=facts)[0]["no_lowcarbon_capex"].state == "raised"


def test_ac136_no_target_clear():
    f = no_capex(targets=[], coverage=None)[0]["no_lowcarbon_capex"]
    assert (f.state, f.text, f.fact_ids) == ("clear", "No flag.", [])


def test_ac151_no_summed_action():
    acts = actions(a1_year=2031)
    ts, _ = targets()
    f = no_capex(actions=acts, coverage=score_coverage(ts, acts, savings()))[0]["no_lowcarbon_capex"]
    assert f.text == "2030 target −30%, but no low-carbon capex disclosed for 2025."


def test_ac137_no_phaseout():
    f = flags(phaseouts=[])[0]["net_zero_no_phaseout"]
    assert (f.state, f.text) == ("raised", "Net-zero target reported, but no phase-out commitment disclosed.")


def test_ac138_no_net_zero():
    f = flags(net_zero=None)[0]["net_zero_no_phaseout"]
    assert (f.state, f.text, f.fact_ids) == ("not checked", "No net-zero answer", [])


def test_ac152_no_net_zero_expansion():
    f = flags(net_zero=None)[0]["expansion_vs_net_zero"]
    assert (f.state, f.text, f.fact_ids) == ("not checked", "No net-zero answer", [])


def test_ac139_redline_breached():
    f = flags(redlines=[redline(True)])[0]["expansion_vs_net_zero"]
    assert (f.state, f.text) == (
        "raised", "Net-zero target reported, but redline breached: No new blast furnace without CCS or a near-zero route.")


def test_ac153_no_redline_disclosure():
    r = RedlineOut(id="stl_bf", label=BF, status="no disclosure", text=BF, citation=None, fact_id=None, source="x")
    f = flags(redlines=[r])[0]["expansion_vs_net_zero"]
    assert (f.state, f.text, f.fact_ids) == ("not checked", "No redline disclosure", [])


def test_ac140_china_left_out():
    f = flags(actions=actions(regions=(EU, US, EU)))[0]["regions_left_out"]
    assert (f.state, f.text) == ("raised", "Operates in China, but no listed action covers it.")


def test_ac141_one_region():
    f = flags(regions=[EU], operates=operates("eu"))[0]["regions_left_out"]
    assert (f.state, f.text, f.fact_ids) == ("not checked", "Fewer than two operating regions", [])


def test_ac142_offsets_clear():
    f = flags(offsets=yes_no("tp_a_offsetting_13", True, 26))[0]["offsets_emphasised"]
    assert (f.state, f.text) == ("clear", "No flag.")


def test_ac154_rf5_header_none_raised():
    out, header = flags(offsets=yes_no("tp_a_offsetting_13", True, 26))
    assert header == "Consistency: no check raises a flag"
    assert {f.state for f in out.values()} == {"clear"}


def test_ac155_no_offsets():
    f = flags(offsets=None)[0]["offsets_emphasised"]
    assert (f.state, f.text, f.fact_ids) == ("not checked", "No offsets answer", [])


def test_ac158_expansion_fact_ids():
    nz, r = yes_no("tp_a_ambition_3", True, 25), redline(True)
    assert flags(net_zero=nz, redlines=[r])[0]["expansion_vs_net_zero"].fact_ids == [nz.fact_id, r.fact_id]


def test_ac159_regions_fact_ids():
    ops = operates("eu", "us", "cn")
    f = flags(operates=list(reversed(ops)), actions=actions(regions=(EU, US, EU)))[0]["regions_left_out"]
    assert f.fact_ids == [o.fact_id for o in ops]


def test_ac165_net_zero_fact_ids():
    nz = yes_no("tp_a_ambition_3", True, 25)
    assert flags(net_zero=nz)[0]["net_zero_no_phaseout"].fact_ids == [nz.fact_id]


def test_ac166_capex_flag_fact_ids():
    ts, _ = targets()
    f = flags(targets=ts)[0]["no_lowcarbon_capex"]
    t = next(t for t in ts if t.kind == "running")
    assert f.fact_ids == t.fact_ids and len(f.fact_ids) == 6 and f.fact_ids == sorted(f.fact_ids)


def test_ac160_no_sector_redline():
    f = flags(redlines=[])[0]["expansion_vs_net_zero"]
    assert (f.state, f.text, f.fact_ids) == ("not checked", "No redline for this sector", [])


def test_ac161_two_regions_left_out():
    f = flags(actions=actions(regions=(EU, EU, EU)))[0]["regions_left_out"]
    assert (f.state, f.text) == ("raised", "Operates in United States and China, but no listed action covers them.")


def test_ac162_net_zero_no():
    nz, r = yes_no("tp_a_ambition_3", False, 25), redline(True)
    out = flags(net_zero=nz, redlines=[r])[0]
    assert [(out[i].state, out[i].text) for i in IDS[1:3]] == [("clear", "No flag.")] * 2
    assert out["net_zero_no_phaseout"].fact_ids == [nz.fact_id]


def test_ac164_no_capex_year():
    f = flags(reporting_year=None, capex_facts=[])[0]["no_lowcarbon_capex"]
    assert (f.state, f.text, f.fact_ids) == ("not checked", "No capex reporting year", [])


def test_rf1_other_action_covers_no_region():
    # spec §1: raised needs one region with an action and one without; `other` adds no region
    regions, ops = [EU, US], operates("eu", "us")
    f = flags(regions=regions, operates=ops, actions=actions(regions=(EU, "other", "other")))[0]["regions_left_out"]
    assert (f.state, f.text) == ("raised", "Operates in United States, but no listed action covers it.")
    f = flags(regions=regions, operates=ops, actions=actions(regions=("other",) * 3))[0]["regions_left_out"]
    assert f.state == "clear"  # no region has an action (spec §1 "while another has one")


def test_action_without_region_covers_every_operating_region():
    f = flags(actions=actions(regions=(EU, None, EU)))[0]["regions_left_out"]
    assert f.state == "clear"


def test_rf2_string_yes_is_not_counted():
    out = flags(net_zero=yes_no("tp_a_ambition_3", "YES", 25), offsets=yes_no("tp_a_offsetting_13", "No", 26))[0]
    assert [out[i].state for i in ("net_zero_no_phaseout", "expansion_vs_net_zero", "offsets_emphasised")] == [
        "not checked"] * 3


def test_rf3_several_breached_redlines():
    a, b = redline(True, "First redline", "r1"), redline(True, "Second redline", "r2")
    nz = yes_no("tp_a_ambition_3", True, 25)
    f = flags(net_zero=nz, redlines=[b, a])[0]["expansion_vs_net_zero"]
    assert f.text == "Net-zero target reported, but redline breached: Second redline; First redline."
    assert f.fact_ids == [nz.fact_id, a.fact_id, b.fact_id]  # ascending within the redline group


def test_breach_beats_no_disclosure():
    gap = RedlineOut(id="r0", label="Other", status="no disclosure", text="Other", citation=None, fact_id=None, source="x")
    assert flags(redlines=[gap, redline(True)])[0]["expansion_vs_net_zero"].state == "raised"


def test_header_counts_raised():
    _, header = flags(phaseouts=[], redlines=[redline(True)], capex_facts=[])
    assert header == "Consistency: 4 of 5 checks raise a flag"
