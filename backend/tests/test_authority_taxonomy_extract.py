from pathlib import Path

import pytest

from arp.research.authority_taxonomy.checklist import AUTHORITY_CHECKLIST
from arp.research.authority_taxonomy.extract import (
    _ActivitiesDraft,
    _BoundariesDraft,
    _DefinitionsDraft,
    _SectorCodesDraft,
    _TechnologiesDraft,
    _ThemeDescriptionDraft,
    _ThresholdsDraft,
    _ValueChainDraft,
    extract_source,
)
from tests.conftest import FakeLLMClient

FIX = Path(__file__).parent / "fixtures" / "authority_taxonomy"
URL = "https://example.org/source"
Q = "Manufacture of electrolysers for the production of hydrogen is an eligible activity under this report."
EU_ACT = "Manufacture of electrolysers used for the production of hydrogen through water electrolysis."
OP = "Operation of electrolysers to produce hydrogen is covered under a separate activity and is excluded here."
R = "at least 50 % of revenue from hydrogen"
SCOPE = "manufacture of electrolysers only"


def _llm(**drafts) -> FakeLLMClient:
    defaults = {
        "_ThemeDescriptionDraft": _ThemeDescriptionDraft(),
        "_ActivitiesDraft": _ActivitiesDraft(),
        "_BoundariesDraft": _BoundariesDraft(),
        "_TechnologiesDraft": _TechnologiesDraft(),
        "_DefinitionsDraft": _DefinitionsDraft(),
        "_SectorCodesDraft": _SectorCodesDraft(),
        "_ValueChainDraft": _ValueChainDraft(),
        "_ThresholdsDraft": _ThresholdsDraft(),
    }
    defaults.update(drafts)
    return FakeLLMClient({k: [v] for k, v in defaults.items()})


async def _extract(fixture: str, llm, value_chain: bool = False, scope: str = SCOPE):
    text = (FIX / fixture).read_text()
    return await extract_source(URL, text, theme_name="hydrogen", scope=scope, value_chain=value_chain, llm=llm)


def _act(name, quote):
    return {"name": name, "in_scope_description": name, "quote": quote}


def test_checklist_keys():
    assert [i.key for i in AUTHORITY_CHECKLIST] == [
        "theme_description", "activities", "boundaries", "technologies",
        "definitions", "sector_codes", "value_chain", "thresholds",
    ]


@pytest.mark.asyncio
async def test_reads_beyond_100k():
    llm = _llm(_ActivitiesDraft=_ActivitiesDraft(activities=[_act("Electrolyser manufacturing", Q)]))
    out = await _extract("long_report.txt", llm)
    assert Q in llm.prompts[llm.calls.index("_ActivitiesDraft")]
    assert any(c.quote == Q for a in out.activities for c in a.citations)
    assert out.report["activities"] == "found"


@pytest.mark.asyncio
async def test_ungrounded_activity_dropped():
    llm = _llm(_ActivitiesDraft=_ActivitiesDraft(activities=[
        _act("Electrolyser manufacturing", EU_ACT), _act("Fuel cell trucks", "Fuel cell trucks are a core activity."),
    ]))
    out = await _extract("eu_310.txt", llm)
    assert [a.name for a in out.activities] == ["Electrolyser manufacturing"]


@pytest.mark.asyncio
async def test_ungrounded_definition_and_threshold_dropped():
    llm = _llm(
        _DefinitionsDraft=_DefinitionsDraft(definitions=[{"term": "Green", "text": "x", "quote": "Green hydrogen means anything."}]),
        _ThresholdsDraft=_ThresholdsDraft(thresholds=[{"text": "x", "quote": "at least 90 % of capex"}]),
    )
    out = await _extract("eu_310.txt", llm)
    assert out.definitions == [] and out.thresholds == []
    assert out.report["thresholds"] == "not_in_source"


@pytest.mark.asyncio
async def test_missing_thresholds_reported():
    out = await _extract("bom_paper.txt", _llm())
    assert out.report["thresholds"] == "not_in_source"


@pytest.mark.asyncio
async def test_definition_and_technology():
    tech = "Proton exchange membrane electrolysis"
    llm = _llm(
        _DefinitionsDraft=_DefinitionsDraft(definitions=[{
            "term": "Low-carbon hydrogen", "text": "below 3 tCO2e/t",
            "quote": '"Low-carbon hydrogen" means hydrogen whose life-cycle emissions are below 3 tCO2e per tonne of hydrogen.',
        }]),
        _TechnologiesDraft=_TechnologiesDraft(technologies=[{
            "name": tech, "quote": "Proton exchange membrane electrolysis is the key technology for low-carbon hydrogen production.",
        }]),
    )
    out = await _extract("eu_310.txt", llm)
    assert [d.term for d in out.definitions] == ["Low-carbon hydrogen"] and out.definitions[0].citations
    assert [t.name for t in out.technologies] == [tech]
    assert out.report["definitions"] == out.report["technologies"] == "found"


@pytest.mark.asyncio
async def test_threshold_found():
    llm = _llm(_ThresholdsDraft=_ThresholdsDraft(thresholds=[{"text": "50 % revenue", "quote": R}]))
    out = await _extract("eu_310.txt", llm)
    assert out.report["thresholds"] == "found"
    assert any(c.quote == R for t in out.thresholds for c in t.citations)


@pytest.mark.asyncio
async def test_scope_excludes_operation():
    llm = _llm(
        _ActivitiesDraft=_ActivitiesDraft(activities=[_act("Electrolyser manufacturing", EU_ACT)]),
        _BoundariesDraft=_BoundariesDraft(boundaries=[
            {"activity_name": "electrolyser-manufacturing", "kind": "exclude", "text": "Operating electrolysers", "quote": OP},
            {"activity_name": "Unknown", "kind": "exclude", "text": "made up", "quote": "Not in the source at all, really."},
        ]),
    )
    out = await _extract("eu_310.txt", llm)
    assert [c.quote for c in out.activities[0].out_of_scope_citations] == [OP]
    assert out.activities[0].out_of_scope_description == "Operating electrolysers"
    assert out.report["boundaries"] == "found"


@pytest.mark.asyncio
async def test_unmatched_grounded_boundary_dropped():
    llm = _llm(
        _ActivitiesDraft=_ActivitiesDraft(activities=[_act("Electrolyser manufacturing", EU_ACT)]),
        _BoundariesDraft=_BoundariesDraft(boundaries=[
            {"activity_name": "Hydrogen operation", "kind": "exclude", "text": "Operating electrolysers", "quote": OP},
        ]),
    )
    out = await _extract("eu_310.txt", llm)
    assert all(a.out_of_scope_citations == [] and a.out_of_scope_description == "" for a in out.activities)
    assert out.report["boundaries"] == "not_in_source"


@pytest.mark.asyncio
async def test_scope_in_every_prompt():
    llm = _llm()
    await _extract("eu_310.txt", llm, value_chain=True)
    assert llm.prompts and all(SCOPE in p for p in llm.prompts)


@pytest.mark.asyncio
async def test_boundary_without_activities_dropped():
    llm = _llm(_BoundariesDraft=_BoundariesDraft(boundaries=[{"activity_name": "x", "kind": "exclude", "text": "t", "quote": OP}]))
    out = await _extract("eu_310.txt", llm)
    assert out.activities == []


@pytest.mark.asyncio
async def test_value_chain_off():
    llm = _llm()
    del llm._script["_ValueChainDraft"]
    out = await _extract("bom_paper.txt", llm)
    assert "value_chain" not in out.report
    assert "_ValueChainDraft" not in llm.calls


@pytest.mark.asyncio
async def test_value_chain_on_sets_role():
    quote = "Electrolyser stacks depend on upstream supply of platinum group metal catalysts and titanium bipolar plates."
    llm = _llm(_ValueChainDraft=_ValueChainDraft(activities=[{**_act("PGM catalysts", quote), "value_chain_role": "upstream"}]))
    out = await _extract("bom_paper.txt", llm, value_chain=True)
    assert out.report["value_chain"] == "found"
    assert [(a.name, a.value_chain_role) for a in out.activities] == [("PGM catalysts", "upstream")]


@pytest.mark.asyncio
async def test_threshold_not_in_activities():
    llm = _llm(
        _ActivitiesDraft=_ActivitiesDraft(activities=[
            _act("Electrolyser manufacturing", EU_ACT),
            {"name": "Pure-play hydrogen", "in_scope_description": f"Companies with {R} activities", "quote": R},
        ]),
        _BoundariesDraft=_BoundariesDraft(boundaries=[
            {"activity_name": "Electrolyser manufacturing", "kind": "include", "text": f"Only {R}", "quote": EU_ACT},
            {"activity_name": "Electrolyser manufacturing", "kind": "include", "text": "Water electrolysis", "quote": EU_ACT},
        ]),
        _ThresholdsDraft=_ThresholdsDraft(thresholds=[{"text": "50 % revenue", "quote": R}]),
    )
    out = await _extract("eu_310.txt", llm)
    assert any(c.quote == R for t in out.thresholds for c in t.citations)
    assert [a.name for a in out.activities] == ["Electrolyser manufacturing"]
    assert [c.text for c in out.activities[0].criteria] == ["Water electrolysis"]


@pytest.mark.asyncio
async def test_guard_removing_all_activities_reports_not_in_source():
    llm = _llm(
        _ActivitiesDraft=_ActivitiesDraft(activities=[
            {"name": "Pure-play hydrogen", "in_scope_description": f"Companies with {R} activities", "quote": R},
        ]),
        _ThresholdsDraft=_ThresholdsDraft(thresholds=[{"text": "50 % revenue", "quote": R}]),
    )
    out = await _extract("eu_310.txt", llm)
    assert out.activities == [] and out.report["activities"] == "not_in_source"


@pytest.mark.asyncio
async def test_citation_location_is_page_of_grounded_quote():
    page1 = "Intro page about the index family and nothing else."
    text = page1 + "\n\n" + Q
    llm = _llm(_ActivitiesDraft=_ActivitiesDraft(activities=[_act("Electrolyser manufacture", Q)]))
    out = await extract_source(URL, text, theme_name="hydrogen", scope=SCOPE, value_chain=False, llm=llm,
                               page_breaks=[0, len(page1) + 2])
    assert out.activities[0].citations[0].location == "p. 2"


@pytest.mark.asyncio
async def test_citation_location_is_nearest_heading_without_pages():
    text = "# Overview\n\nGeneral text.\n\n## Eligible activities\n\n" + Q + "\n\n## Exclusions\n\nOther."
    llm = _llm(_ActivitiesDraft=_ActivitiesDraft(activities=[_act("Electrolyser manufacture", Q)]))
    out = await extract_source(URL, text, theme_name="hydrogen", scope=SCOPE, value_chain=False, llm=llm)
    assert out.activities[0].citations[0].location == "Eligible activities"
