"""The theme funnel inside the match graph: spec 2026-11-01-theme-funnel-design AC-1...AC-17."""

import json

import numpy as np
import pytest

from arp.config import Settings
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research import funnel, funnel_thresholds, match_graph
from arp.research.matcher_agents import AdjudicatorOutput
from arp.research.pipeline import _match_company
from arp.research.revenue_exposure.resolver import RevenueResolverContext
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.revenue_exposure import ActivityCatalogueMapping, CatalogueDataPoint
from arp.schemas.thematic import ActivityDefinition, AgentOpinion, ExposureEstimate, MatchVerdict, ThemeDefinition
from tests.taxonomy_schema_helpers import released_schema

POS = "Manufactures electrolysers."
NEG = "Buys electrolysers made by others."
CON = "Supplies catalysts for electrolysers."
KEYS = ["electrolyser"]


class _Docs(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


def _settings(tmp_path, on=True) -> Settings:
    return Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc", models_universe_funnel_enabled=on,
    )


def _theme(theme_id="t0"):
    act = ActivityDefinition(name="Electrolysers", in_scope_description=POS, out_of_scope_description=NEG,
                             contrast_statements=[CON], seed_keywords=KEYS)
    return ThemeDefinition(theme_id=theme_id, name="Hydrogen", description="", activities=[act]), act


class Models:
    """Stand-ins for arp.models: fixed (cosine, rerank, {statement: entailment}) per passage text."""

    def __init__(self, monkeypatch, rows):
        self.calls = 0

        def embed(texts, load=None):
            self.calls += 1
            out = [[1.0 if t == POS else rows[t][0], 0.1] for t in texts]
            return np.asarray(out, dtype=np.float32), {"model": "embed"}

        def rerank(query, texts, score=None):
            self.calls += 1
            return [rows[t][1] for t in texts], {"model": "rerank"}

        def classify(texts, labels, hypothesis=""):
            self.calls += 1
            return [{lab: rows[t][2].get(lab, 0.1) for lab in labels} for t in texts], {"model": "nli"}

        monkeypatch.setattr(funnel.models, "embed", embed)
        monkeypatch.setattr(funnel.models, "rerank", rerank)
        monkeypatch.setattr(funnel.models, "classify", classify)
        monkeypatch.setattr(match_graph, "_funnel_content_store", lambda settings: None)


def _debate_script(fake_llm, n=1):
    op = AgentOpinion(stance="include", rationale="r", citations=[], exposure_estimate=ExposureEstimate.PURE_PLAY)
    adj = AdjudicatorOutput(verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.PURE_PLAY, confidence=0.9,
                            adjudicator_rationale="ok", citations=[])
    return fake_llm({"AgentOpinion": [op, op] * n, "AdjudicatorOutput": [adj] * n})


def _doc(cid, text):
    return SourceDocument(company_id=cid, doc_type=DocType.ANNUAL_REPORT_10K, title="AR", full_text=text)


async def _run(tmp_path, llm, docs, theme=None, on=True, **kw):
    theme = theme or _theme()[0]
    company = CompanyRef(company_id="c1", name="Co")
    reg = DocumentSourceRegistry([_Docs(docs)])
    return (await _match_company(company, theme, registry=reg, llm=llm, settings=_settings(tmp_path, on), **kw)).matches[0]


P_PASS = "We build electrolyser stacks."
P_LOW = "An electrolyser was mentioned."
PASS_ROWS = {P_PASS: (0.9, 3.0, {POS: 0.95, NEG: 0.10})}


async def test_setting_off_same_calls_as_all_pass(tmp_path, fake_llm, monkeypatch):  # AC-1
    Models(monkeypatch, PASS_ROWS)
    off, on = _debate_script(fake_llm), _debate_script(fake_llm)
    await _run(tmp_path, off, [_doc("c1", P_PASS)], on=False)
    await _run(tmp_path, on, [_doc("c1", P_PASS)], on=True)
    assert len(off.calls) == len(on.calls) == 3


async def test_setting_off_never_calls_models(tmp_path, fake_llm, monkeypatch):
    m = Models(monkeypatch, PASS_ROWS)
    match = await _run(tmp_path, _debate_script(fake_llm), [_doc("c1", P_PASS)], on=False)
    assert m.calls == 0
    assert match.funnel is None


async def test_passing_pair_reaches_debate(tmp_path, fake_llm, monkeypatch):  # AC-2, AC-3
    Models(monkeypatch, PASS_ROWS)
    llm = _debate_script(fake_llm)
    match = await _run(tmp_path, llm, [_doc("c1", P_PASS)])
    assert len(llm.calls) >= 1
    assert match.funnel.passed is True
    assert match.verdict == MatchVerdict.INCLUDE


async def test_screened_pair_no_llm(tmp_path, fake_llm, monkeypatch):  # AC-4, AC-5, AC-6
    Models(monkeypatch, {P_LOW: (0.9, 0.5, {POS: 0.99})})
    llm = fake_llm({})
    match = await _run(tmp_path, llm, [_doc("c1", P_LOW)])
    assert match.verdict == MatchVerdict.EXCLUDE
    assert match.adjudicator_rationale == "screened out by funnel"
    assert llm.calls == []
    assert match.funnel.passed is False
    assert match.advocate is None


async def test_contrast_screens_out(tmp_path, fake_llm, monkeypatch):  # AC-7, AC-8
    Models(monkeypatch, {P_PASS: (0.9, 3.0, {POS: 0.95, CON: 0.97})})
    match = await _run(tmp_path, fake_llm({}), [_doc("c1", P_PASS)])
    assert match.verdict == MatchVerdict.EXCLUDE
    assert match.funnel.entail_negatives[CON] == 0.97


async def test_second_passage_reaches_debate(tmp_path, fake_llm, monkeypatch):  # AC-9, AC-10
    p1, p2 = "Electrolyser purchases rose.", "Our electrolyser factory ships stacks."
    Models(monkeypatch, {p1: (0.9, 3.0, {POS: 0.95, NEG: 0.97}), p2: (0.8, 2.0, {POS: 0.90, NEG: 0.2, CON: 0.2})})
    llm = _debate_script(fake_llm)
    match = await _run(tmp_path, llm, [_doc("c1", p1), _doc("c1", p2)])
    assert len(llm.calls) >= 1
    assert match.funnel.best_passage == p2


async def test_tie_screens_out(tmp_path, fake_llm, monkeypatch):  # AC-11
    Models(monkeypatch, {P_PASS: (0.9, 3.0, {POS: 0.90, NEG: 0.90})})
    assert (await _run(tmp_path, fake_llm({}), [_doc("c1", P_PASS)])).verdict == MatchVerdict.EXCLUDE


@pytest.fixture
def thresholds_file(tmp_path, monkeypatch):
    def write(data):
        p = tmp_path / "funnel_thresholds.json"
        p.write_text(json.dumps(data))
        monkeypatch.setattr(funnel_thresholds, "_DEFAULT_PATH", p)
    return write


D = {"k1": 25, "k2": 6, "t_rerank": 1.5, "t_entail": 0.8}
G_ROWS = {P_PASS: (0.9, 3.0, {POS: 0.95, NEG: 0.1, CON: 0.1})}


async def test_theme_specific_threshold(tmp_path, fake_llm, monkeypatch, thresholds_file):  # AC-13
    thresholds_file({"default": D, "t1": {"t_rerank": 5.0}})
    Models(monkeypatch, G_ROWS)
    match = await _run(tmp_path, fake_llm({}), [_doc("c1", P_PASS)], theme=_theme("t1")[0])
    assert match.verdict == MatchVerdict.EXCLUDE


async def test_default_threshold(tmp_path, fake_llm, monkeypatch, thresholds_file):  # AC-14
    thresholds_file({"default": {**D, "t_rerank": 5.0}})
    Models(monkeypatch, G_ROWS)
    match = await _run(tmp_path, fake_llm({}), [_doc("c1", P_PASS)], theme=_theme("t2")[0])
    assert match.verdict == MatchVerdict.EXCLUDE


async def test_run_json_funnel_keys(tmp_path, fake_llm, monkeypatch):  # AC-17
    Models(monkeypatch, {P_LOW: (0.9, 0.5, {POS: 0.99})})
    match = await _run(tmp_path, fake_llm({}), [_doc("c1", P_LOW)])
    assert set(json.loads(match.model_dump_json())["funnel"]) == {
        "passed", "rerank_max", "entail_positive", "entail_negatives", "best_passage", "best_doc_id",
        "passages_scored", "thresholds", "models"}


async def test_revenue_resolved_pair_skips_funnel(tmp_path, fake_llm, monkeypatch):  # Review Focus 1
    m = Models(monkeypatch, PASS_ROWS)
    theme, act = _theme()
    doc = _doc("c1", P_PASS)
    reg = DocumentSourceRegistry([_Docs([doc])])
    rows = [CatalogueDataPoint(data_point_id="d1", company_id="c1", metric="revenue", label="Electrolysers", as_pct_of_total=0.4)]
    maps = [ActivityCatalogueMapping(activity_id=act.activity_id, metric="revenue", matched_labels=["Electrolysers"], rationale="x")]
    resolver = RevenueResolverContext(catalogue_by_company={"c1": rows}, mappings=maps, registry=reg,
                                      settings=_settings(tmp_path), schema=released_schema(*theme.activities))
    real = match_graph.resolve_company_activity_exposure

    async def no_documents(*args, **kwargs):  # catalogue path only: the extraction fallback sees no documents
        return await real(*args, **{**kwargs, "documents": []})

    monkeypatch.setattr(match_graph, "resolve_company_activity_exposure", no_documents)
    match = await _run(tmp_path, fake_llm({}), [doc], theme=theme, revenue_resolver=resolver)
    assert match.revenue_exposure.revenue.source == "catalogue"
    assert match.funnel is None
    assert m.calls == 0
    assert match.verdict == MatchVerdict.INCLUDE


async def test_no_keyword_evidence_unchanged(tmp_path, fake_llm, monkeypatch):
    m = Models(monkeypatch, {})
    match = await _run(tmp_path, fake_llm({}), [_doc("c1", "We sell shoes.")])
    assert match.adjudicator_rationale.startswith("No evidence of this activity")
    assert match.funnel is None
    assert m.calls == 0
