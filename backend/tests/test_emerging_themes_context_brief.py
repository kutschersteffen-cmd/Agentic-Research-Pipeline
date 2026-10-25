"""Context brief (spec theme-context-brief): the spec's acceptance fixture run through the real pipeline."""

from datetime import datetime

import pytest

from arp.config import Settings
from arp.emerging_themes import pipeline as pipeline_module
from arp.emerging_themes.context_brief import _ContextBriefDraft, _pct, isic_division, isic_divisions
from arp.emerging_themes.ingestion.base import MentionSource
from arp.emerging_themes.pipeline import create_emerging_themes_run, execute_emerging_themes_run, load_candidates_with_status
from arp.llm.base import LLMUsage
from arp.schemas.common import CompanyRef
from arp.schemas.emerging_themes import (
    ActionType,
    ActivityGroup,
    BriefStatement,
    CompanyActionEvidence,
    CompanyActivity,
    ContradictionType,
    ExtractedTag,
    MentionSourceType,
    RawMention,
    TopicCluster,
)
from arp.storage.run_store import RunStore
from arp.storage.topic_store import TopicStateStore
from arp.themes.dossiers import Dossier, context_brief
from tests.conftest import FakeLLMClient

# mention id, published_at, companies, action, contradiction, quote
MENTIONS = [
    ("m1", "2026-09-01", ["Acme"], ActionType.CAPEX, ContradictionType.NONE, "Acme will invest $2bn in a cell plant."),
    ("m2", "2026-09-05", ["Beta"], ActionType.ORDERS, ContradictionType.NONE, "Beta ordered 40 electrolysers."),
    ("m3", "2026-09-10", ["Gamma"], ActionType.CAPACITY, ContradictionType.NONE, "Gamma doubled cell output."),
    ("m4", "2026-09-15", ["Delta", "Gamma"], ActionType.PARTNERSHIP, ContradictionType.NONE, "Delta partners with Gamma on cell supply."),
    ("m5", "2026-09-20", ["Acme"], ActionType.OTHER, ContradictionType.DELAY, "Acme delayed its second line to 2028."),
]


def _draft(**changes) -> _ContextBriefDraft:
    draft = {
        "why_now": [
            BriefStatement(text="Companies report spending on cell plants.", evidence_ids=["E1"]),
            BriefStatement(text="Orders reached 90 units.", evidence_ids=["E2"]),
            BriefStatement(text="Demand is booming.", evidence_ids=["E99"]),
        ],
        "early_evidence": [BriefStatement(text="Acme delayed its second line.", evidence_ids=["E6"])],
        "by_company": [
            CompanyActivity(company_id="gamma", activity="Expanding battery-cell output", evidence_ids=["E3"]),
            CompanyActivity(company_id="delta", activity="Supplying cells through a partnership", evidence_ids=["E4"]),
            CompanyActivity(company_id="acme", activity="Building a plant", evidence_ids=["E1"]),
        ],
        "groups": [ActivityGroup(activity="Battery-cell manufacturing", company_ids=["gamma", "acme", "delta"])],
    }
    return _ContextBriefDraft(**(draft | changes))


class _Source(MentionSource):
    name = "fixed"

    def __init__(self, mentions):
        self.mentions = mentions

    async def fetch(self, since: datetime):
        return self.mentions


async def _run(tmp_path, pg, monkeypatch, *, brief=None, isic=None, mentions=MENTIONS, dated=True):
    order = [m[0] for m in mentions]
    rows = {m[0]: m for m in mentions}
    raw = [
        RawMention(mention_id=mid, source_type=MentionSourceType.GDELT, title=f"Title {mid}", text=rows[mid][5],
                   url=f"https://{mid.replace('m', 'n')}.test/a", published_at=rows[mid][1] if dated else None)
        for mid in order
    ]

    async def tag_mention(mention, llm):
        _, _, names, action, contradiction, quote = rows[mention.mention_id]
        return [ExtractedTag(mention_id=mention.mention_id, label="cells", claim=quote, entity_names=names, action_type=action,
                             contradiction_type=contradiction, quote=quote, grounded=True)], LLMUsage()

    def cluster_tags(tags, mentions_by_id, company_ids_by_mention, period, **_):
        tags = sorted(tags, key=lambda t: order.index(t.mention_id))
        return [TopicCluster(cluster_id="cl", period=period, representative_label="cells", member_tag_ids=[t.tag_id for t in tags],
                             company_ids=sorted({c for ids in company_ids_by_mention.values() for c in ids}), mention_count=len(tags))]

    async def sec(company, source):
        return CompanyActionEvidence(company_id="acme", cik="1", capex_pct_change=0.25) if company.company_id == "acme" else None

    monkeypatch.setattr(pipeline_module, "tag_mention", tag_mention)
    monkeypatch.setattr(pipeline_module, "cluster_tags", cluster_tags)
    monkeypatch.setattr(pipeline_module, "check_company_action_evidence", sec)
    codes = {"acme": "2720", "beta": "2710", "gamma": None, "delta": None} | (isic or {})
    companies = [CompanyRef(company_id=c, name=c.title(), isic_code=code) for c, code in codes.items()]
    settings = Settings(runs_dir=tmp_path / "runs", emerging_themes_state_dir=tmp_path / "state", emerging_themes_min_cluster_size=3,
                        emerging_themes_min_independent_sources=2, emerging_themes_company_exposure_enabled=False)
    run_store = RunStore(pg, settings.runs_dir)
    from arp.emerging_themes.synthesis import _CandidateDraft

    script = {"_CandidateDraft": [_CandidateDraft(theme_name="Battery cells", description="d", economic_rationale="e", rationale="r")]}
    if brief is not False:
        script["_ContextBriefDraft"] = [brief or _draft()]
    run_id = create_emerging_themes_run(run_store, companies, "manual")
    await execute_emerging_themes_run(run_id, companies, llm=FakeLLMClient(script), sources=[_Source(raw)], settings=settings,
                                      run_store=run_store, topic_store=TopicStateStore(tmp_path / "topics"), xbrl_source=object())
    return run_store, run_id, load_candidates_with_status(run_store, run_id)


def test_prompt_shows_sec_fractions_as_percent():
    assert [_pct(0.25), _pct(-0.1), _pct(None)] == ["+25.0%", "-10.0%", "n/a"]


def test_isic_divisions_reference():
    assert len(isic_divisions()) == 88
    assert isic_divisions()["35"] == "Electricity, gas, steam and air conditioning supply"
    assert [isic_division(c) for c in ("2720", "X9", "0012", None, "27")] == ["27", None, None, None, "27"]


async def test_fixture_brief(tmp_path, pg, monkeypatch):
    run_store, run_id, candidates = await _run(tmp_path, pg, monkeypatch)
    assert len(candidates) == 1
    candidate = candidates[0]
    brief = candidate.context_brief.model_dump(mode="json")
    assert (brief["status"], brief["error"]) == ("written", None)
    assert datetime.fromisoformat(brief["written_at"]).utcoffset().total_seconds() == 0

    evidence = brief["evidence"]
    assert [e["evidence_id"] for e in evidence] == [f"E{n}" for n in range(1, 8)]
    assert [e["kind"] for e in evidence] == ["quote"] * 5 + ["counter", "financials"]
    assert (evidence[0]["quote"], evidence[0]["url"], evidence[0]["published_at"][:10], evidence[0]["action_type"]) == (
        "Acme will invest $2bn in a cell plant.", "https://n1.test/a", "2026-09-01", "capex")
    assert evidence[3]["company_ids"] == ["delta", "gamma"]
    assert evidence[5]["quote"] == "Acme delayed its second line to 2028."
    assert (evidence[6]["company_id"], evidence[6]["capex_pct_change"], evidence[6]["rnd_pct_change"]) == ("acme", 0.25, None)

    facts = brief["facts"]
    assert (facts["first_seen"], facts["last_seen"], facts["independent_sources"], facts["company_count"]) == ("2026-09-01", "2026-09-20", 5, 4)
    assert facts["action_counts"] == {"capex": 1, "hiring": 0, "orders": 1, "capacity": 1, "partnership": 1}
    assert facts["velocity"] == candidate.signal_velocity

    assert brief["sectors"] == [{"isic_division": "27", "label": "Manufacture of electrical equipment", "company_ids": ["acme", "beta"],
                                 "evidence_ids": ["E1", "E2", "E5", "E6", "E7"]}]
    assert brief["why_now"] == [{"text": "Companies report spending on cell plants.", "evidence_ids": ["E1"]}]
    assert brief["early_evidence"] == [{"text": "Acme delayed its second line.", "evidence_ids": ["E6"]}]
    assert brief["activities"] == {
        "by_company": [
            {"company_id": "delta", "activity": "Supplying cells through a partnership", "evidence_ids": ["E4"]},
            {"company_id": "gamma", "activity": "Expanding battery-cell output", "evidence_ids": ["E3"]},
        ],
        "groups": [{"activity": "Battery-cell manufacturing", "company_ids": ["delta", "gamma"], "evidence_ids": ["E3", "E4"]}],
        "unclassified_company_ids": [],
    }
    assert brief["dropped_statements"] == 3
    assert brief["companies"] == [
        {"company_id": "acme", "name": "Acme", "isic_division": "27"}, {"company_id": "beta", "name": "Beta", "isic_division": "27"},
        {"company_id": "delta", "name": "Delta", "isic_division": None}, {"company_id": "gamma", "name": "Gamma", "isic_division": None},
    ]
    dossier = Dossier(dossier_id="d", name="n", created_by="ana", created_at="t", origin="candidate", run_id=run_id, theme_id=candidate.theme_id)
    assert context_brief(dossier, run_store) == candidate.context_brief
    assert context_brief(dossier.model_copy(update={"origin": "topic", "run_id": None}), run_store) is None


async def test_two_sectors_sorted_by_size_then_division(tmp_path, pg, monkeypatch):
    *_, candidates = await _run(tmp_path, pg, monkeypatch, isic={"beta": "3510"})
    sectors = [s.model_dump() for s in candidates[0].context_brief.sectors]
    assert sectors == [
        {"isic_division": "27", "label": "Manufacture of electrical equipment", "company_ids": ["acme"], "evidence_ids": ["E1", "E5", "E6", "E7"]},
        {"isic_division": "35", "label": "Electricity, gas, steam and air conditioning supply", "company_ids": ["beta"], "evidence_ids": ["E2"]},
    ]


@pytest.mark.parametrize(("changes", "by_company", "unclassified", "dropped"), [
    ({"by_company": [CompanyActivity(company_id="gamma", activity="x", evidence_ids=["E3"])]}, ["gamma"], ["delta"], 3),
    ({"by_company": [CompanyActivity(company_id="gamma", activity="x", evidence_ids=["E3"]),
                     CompanyActivity(company_id="delta", activity="y", evidence_ids=["E1"]),
                     CompanyActivity(company_id="acme", activity="z", evidence_ids=["E1"])]}, ["gamma"], ["delta"], 5),
])
async def test_activity_lines_need_evidence_covering_their_company(tmp_path, pg, monkeypatch, changes, by_company, unclassified, dropped):
    *_, candidates = await _run(tmp_path, pg, monkeypatch, brief=_draft(**changes))
    brief = candidates[0].context_brief
    assert [line.company_id for line in brief.activities.by_company] == by_company
    assert brief.activities.groups == []
    assert (brief.activities.unclassified_company_ids, brief.dropped_statements) == (unclassified, dropped)


@pytest.mark.parametrize(("extra", "kept", "dropped"), [
    ("Acme will invest $2bn.", True, 3),  # "2" is in E1's quote
    ("The second line slips to 2028.", False, 4),  # "2028" is only in E5/E6, not the cited E1
])
async def test_numbers_must_appear_in_a_cited_quote(tmp_path, pg, monkeypatch, extra, kept, dropped):
    why_now = [*_draft().why_now, BriefStatement(text=extra, evidence_ids=["E1"])]
    *_, candidates = await _run(tmp_path, pg, monkeypatch, brief=_draft(why_now=why_now))
    brief = candidates[0].context_brief
    assert [s.text for s in brief.why_now] == ["Companies report spending on cell plants."] + ([extra] if kept else [])
    assert brief.dropped_statements == dropped


async def test_failed_wording_keeps_candidate_and_code_parts(tmp_path, pg, monkeypatch):
    _, _, written = await _run(tmp_path / "a", pg, monkeypatch)
    run_store, run_id, candidates = await _run(tmp_path / "b", pg, monkeypatch, brief=False)
    assert run_store.load_manifest(run_id).status.value == "completed"
    brief = candidates[0].context_brief
    assert (brief.status, brief.error, brief.dropped_statements) == ("failed", "brief wording failed", 0)
    assert brief.why_now == brief.early_evidence == brief.activities.by_company == brief.activities.groups == []
    assert brief.activities.unclassified_company_ids == ["delta", "gamma"]
    assert len(brief.evidence) == 7 and brief.sectors == written[0].context_brief.sectors
    fields = {"theme_name", "signal_velocity", "breadth", "novelty", "corroborating_sources", "contradiction_evidence", "status"}
    assert candidates[0].model_dump(include=fields) == written[0].model_dump(include=fields)
    no_as_of = {"xbrl_corroboration": {"__all__": {"as_of"}}}  # as_of is the lookup time
    assert candidates[0].model_dump(include={"xbrl_corroboration"}, exclude=no_as_of) == written[0].model_dump(include={"xbrl_corroboration"}, exclude=no_as_of)


async def test_extra_quote_for_uncovered_unclassified_company(tmp_path, pg, monkeypatch):
    acme = [(f"a{i}", "2026-09-02", ["Acme"], ActionType.CAPEX, ContradictionType.NONE, f"Acme plant {i}.") for i in range(1, 7)]
    mentions = [MENTIONS[0], MENTIONS[1], *acme, *MENTIONS[2:]]
    *_, candidates = await _run(tmp_path, pg, monkeypatch, mentions=mentions, dated=False)
    candidate = candidates[0]
    evidence = candidate.context_brief.evidence
    assert [c.mention_id for c in candidate.corroborating_sources] == ["m1", "m2"] + [f"a{i}" for i in range(1, 7)]
    assert len(evidence) == 12
    assert (evidence[8].kind, evidence[8].mention_id, evidence[8].company_ids) == ("quote", "m3", ["gamma"])
    assert (evidence[9].kind, evidence[9].mention_id, evidence[9].company_ids) == ("quote", "m4", ["delta", "gamma"])
    assert (evidence[10].kind, evidence[10].mention_id, evidence[11].kind) == ("counter", "m5", "financials")
    assert (candidate.context_brief.facts.first_seen, candidate.context_brief.facts.last_seen) == (None, None)
