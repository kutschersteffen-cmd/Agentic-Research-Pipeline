"""`arp theme funnel` / `funnel-compare` over an exposure golden set (spec theme-funnel AC-18...AC-20)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.cli import theme as theme_cli
from arp.research import funnel
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.taxonomy_store import TaxonomyStore
from tests.test_funnel import entail

POS = "Makes electrolysers."
NEG = "Buys electrolysers."
CON = "Supplies catalysts."
KEEP = "We manufacture electrolyser stacks."
DROP = "We buy electrolysers from others."
ROWS = {KEEP: (0.9, 3.0, {POS: 0.95}), DROP: (0.9, 3.0, {POS: 0.85, CON: 0.9})}


@pytest.fixture(autouse=True)
def _no_postgres(monkeypatch):
    monkeypatch.setattr("arp.db.session.require_postgres", lambda s: None)
    monkeypatch.setattr("arp.db.session.require_cutover", lambda s: None)
    monkeypatch.setattr(theme_cli, "_funnel_content_store", lambda settings: None)


@pytest.fixture
def models(monkeypatch):
    calls = {"n": 0}

    def embed(texts, load=None):
        calls["n"] += 1
        return np.asarray([[ROWS[t][0] if t in ROWS else 1.0, 0.1] for t in texts], dtype=np.float32), {}

    def rerank(query, texts, score=None):
        return [ROWS[t][1] for t in texts], {}

    def classify(texts, labels, hypothesis=""):
        return [{lab: entail(ROWS[t][2], lab, POS) for lab in labels} for t in texts], {}

    monkeypatch.setattr(funnel.models, "embed", embed)
    monkeypatch.setattr(funnel.models, "rerank", rerank)
    monkeypatch.setattr(funnel.models, "classify", classify)
    return calls


def _taxonomy(tmp_path, contrast=(CON,)):
    act = ActivityDefinition(name="e", in_scope_description=POS, out_of_scope_description=NEG,
                             contrast_statements=list(contrast), seed_keywords=["electrolyser"])
    store = TaxonomyStore(tmp_path / "tax")
    t = store.create("t", ThemeDefinition(name="t", description="", activities=[act]), DerivationMethod.MANUAL)
    return store, t


def _set(tmp_path, cases, missing=()):
    """cases: [(case_id, label, split, document text)]"""
    rows = []
    for cid, label, split, text in cases:
        rows.append({"case_id": cid, "company": cid.upper(), "label": label, "role": "r", "rationale": "x",
                     "label_sources": ["https://example.com/a"], "documents": [{"url": "https://example.com/d.pdf"}],
                     "split": split})
        if cid not in missing:
            d = tmp_path / "docs" / cid / "10-K"
            d.mkdir(parents=True)
            (d / "ar.txt").write_text(text)
    data = {"set_id": "s", "kind": "activity", "subject": POS, "labels": ["core", "peripheral", "not"],
            "checked_on": "2026-11-02", "cases": rows}
    (tmp_path / "cases.json").write_text(json.dumps(data))
    return tmp_path / "cases.json"


def _invoke(tmp_path, *extra, taxonomy_id=None, version=None):
    args = ["theme", "funnel", "--taxonomies-dir", str(tmp_path / "tax"), "--cases", str(tmp_path / "cases.json"),
            "--documents-dir", str(tmp_path / "docs"), *extra]
    if taxonomy_id:
        args += ["--taxonomy", taxonomy_id]
    if version:
        args += ["--taxonomy-version", str(version)]
    return CliRunner().invoke(app, args)


FIVE = [("a", "core", "holdout", KEEP), ("b", "core", "holdout", KEEP), ("c", "peripheral", "holdout", KEEP),
        ("d", "not", "holdout", DROP), ("e", "not", "holdout", DROP)]


def test_label_lines(tmp_path, models):  # AC-18
    _, t = _taxonomy(tmp_path)
    _set(tmp_path, FIVE)
    r = _invoke(tmp_path, taxonomy_id=t.taxonomy_id)
    assert r.exit_code == 0, r.output
    assert r.output.strip().splitlines()[-3:] == ["core: 2/2", "peripheral: 1/1", "not: 0/2"]


def _ten(kept_pos, kept_not):
    pos = [(f"p{i}", "core", "tune", KEEP if i < kept_pos else DROP) for i in range(10)]
    neg = [(f"n{i}", "not", "tune", KEEP if i < kept_not else DROP) for i in range(10)]
    return pos + neg


def test_min_kept_positive_fails(tmp_path, models):  # AC-19
    _, t = _taxonomy(tmp_path)
    _set(tmp_path, _ten(9, 0))
    assert _invoke(tmp_path, "--min-kept-positive", "0.95", taxonomy_id=t.taxonomy_id).exit_code == 1
    assert _invoke(tmp_path, "--min-kept-positive", "0.90", taxonomy_id=t.taxonomy_id).exit_code == 0


def test_max_kept_negative_fails(tmp_path, models):  # AC-20
    _, t = _taxonomy(tmp_path)
    _set(tmp_path, _ten(10, 4))
    assert _invoke(tmp_path, "--max-kept-negative", "0.30", taxonomy_id=t.taxonomy_id).exit_code == 1
    assert _invoke(tmp_path, "--max-kept-negative", "0.40", taxonomy_id=t.taxonomy_id).exit_code == 0


def test_split_filter(tmp_path, models):
    _, t = _taxonomy(tmp_path)
    _set(tmp_path, FIVE + [("f", "core", "tune", KEEP)])
    r = _invoke(tmp_path, "--split", "holdout", taxonomy_id=t.taxonomy_id)
    assert "core: 2/2" in r.output
    r = _invoke(tmp_path, "--split", "tune", taxonomy_id=t.taxonomy_id)
    assert r.output.strip().splitlines()[-3:] == ["core: 1/1", "peripheral: 0/0", "not: 0/0"]


def test_contrast_from_taxonomy_version(tmp_path, models):
    store, t = _taxonomy(tmp_path, contrast=())
    store.new_version(t.taxonomy_id, t.theme.model_copy(update={"activities": [
        t.theme.activities[0].model_copy(update={"contrast_statements": [CON]})]}), DerivationMethod.MANUAL)
    _set(tmp_path, [("d", "not", "all", DROP)])
    assert _invoke(tmp_path, taxonomy_id=t.taxonomy_id, version=1).output.strip().splitlines()[-1] == "not: 1/1"
    assert _invoke(tmp_path, taxonomy_id=t.taxonomy_id, version=2).output.strip().splitlines()[-1] == "not: 0/1"
    assert _invoke(tmp_path, taxonomy_id=t.taxonomy_id).output.strip().splitlines()[-1] == "not: 0/1"


def test_theme_option_refused(tmp_path, models):
    _set(tmp_path, FIVE)
    r = _invoke(tmp_path, "--theme", str(tmp_path / "theme.json"))
    assert r.exit_code == 1
    assert "Theme runs start from a taxonomy version" in r.output


def test_unknown_taxonomy(tmp_path, models):  # Review Focus 4
    _set(tmp_path, FIVE)
    r = _invoke(tmp_path, taxonomy_id="tax_nope")
    assert r.exit_code == 1
    assert "Taxonomy not found: tax_nope" in r.output
    assert models["n"] == 0


def test_missing_document_counts_not_kept(tmp_path, models):  # Review Focus 5
    _, t = _taxonomy(tmp_path)
    _set(tmp_path, FIVE, missing=("a",))
    r = _invoke(tmp_path, taxonomy_id=t.taxonomy_id)
    assert r.exit_code == 0, r.output
    assert "a: no document" in r.output
    assert "core: 1/2" in r.output


def test_golden_taxonomy_loads():
    from pathlib import Path

    store = TaxonomyStore(Path(__file__).parent / "golden" / "exposure" / "electrolyser_makers" / "taxonomies")
    t = store.get("tax_electrolyser_makers")
    assert len(t.theme.activities) == 1
    assert len(t.theme.activities[0].contrast_statements) == 2


class _AlwaysInclude:
    """Counting stand-in LLM: every debate ends in `include`."""

    def __init__(self):
        self.calls = 0

    async def complete_structured(self, *, system, prompt, output_model, **kwargs):
        from arp.llm.base import LLMUsage
        from arp.research.matcher_agents import AdjudicatorOutput
        from arp.schemas.thematic import AgentOpinion, ExposureEstimate, MatchVerdict

        self.calls += 1
        if output_model is AdjudicatorOutput:
            out = AdjudicatorOutput(verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.PURE_PLAY,
                                    confidence=0.9, adjudicator_rationale="ok", citations=[])
        else:
            out = AgentOpinion(stance="s", rationale="r", citations=[], exposure_estimate=ExposureEstimate.PURE_PLAY)
        return out, LLMUsage(input_tokens=1, output_tokens=1, provider="fake")


@pytest.fixture
def llm(monkeypatch):
    fake = _AlwaysInclude()
    monkeypatch.setattr(theme_cli, "build_llm_client", lambda settings: fake)
    monkeypatch.setattr(theme_cli, "build_verifier_llm_client", lambda settings: fake)
    return fake


def _compare(tmp_path, *extra, taxonomy_id):
    return CliRunner().invoke(app, ["theme", "funnel-compare", "--taxonomy", taxonomy_id, "--taxonomies-dir",
                                    str(tmp_path / "tax"), "--cases", str(tmp_path / "cases.json"),
                                    "--documents-dir", str(tmp_path / "docs"), *extra])


def test_compare_prints_counts(tmp_path, models, llm):
    _, t = _taxonomy(tmp_path)
    _set(tmp_path, FIVE)
    r = _compare(tmp_path, taxonomy_id=t.taxonomy_id)
    assert r.exit_code == 0, r.output
    # off: 5 debates x 3 calls; on: the 3 kept cases debate. Every debate includes, so off precision = 3/5.
    for line in ("llm_calls_off: 15", "llm_calls_on: 9", "precision_off: 0.600", "precision_on: 1.000"):
        assert line in r.output


def test_compare_call_ratio_exit(tmp_path, models, llm):
    _, t = _taxonomy(tmp_path)
    _set(tmp_path, FIVE)
    assert _compare(tmp_path, "--max-call-ratio", "0.5", taxonomy_id=t.taxonomy_id).exit_code == 1  # 9/15 = 0.6
    assert _compare(tmp_path, "--max-call-ratio", "0.6", taxonomy_id=t.taxonomy_id).exit_code == 0


def test_compare_negatives_only_counts(tmp_path, models, llm):  # AC-23 as amended
    _, t = _taxonomy(tmp_path)
    _set(tmp_path, FIVE)
    r = _compare(tmp_path, "--negatives-only", "--max-call-ratio", "0.5", taxonomy_id=t.taxonomy_id)
    assert r.exit_code == 0, r.output
    assert "llm_calls_off: 6" in r.output and "llm_calls_on: 0" in r.output


def test_compare_precision_drop_exit(tmp_path, models, llm, monkeypatch):
    _, t = _taxonomy(tmp_path)
    # the funnel screens one core case: precision stays 1.0 on both arms -> no drop
    _set(tmp_path, [("a", "core", "holdout", KEEP), ("b", "core", "holdout", DROP)])
    assert _compare(tmp_path, "--max-precision-drop", "0.0", taxonomy_id=t.taxonomy_id).exit_code == 0
    # with every case screened there are no includes: precision_on 0.0, a drop of 1.0
    ROWS_ALL_DROP = {KEEP: (0.9, 0.1, {POS: 0.95}), DROP: ROWS[DROP]}
    monkeypatch.setitem(ROWS, KEEP, ROWS_ALL_DROP[KEEP])
    assert _compare(tmp_path, "--max-precision-drop", "0.02", taxonomy_id=t.taxonomy_id).exit_code == 1


def test_case_documents_get_distinct_content_ids(tmp_path):  # review: same file stem in two doc_type dirs
    for sub, text in (("10-K", "Annual text."), ("other", "Other text.")):
        (tmp_path / "c" / sub).mkdir(parents=True)
        (tmp_path / "c" / sub / "2023.txt").write_text(text)
    docs = theme_cli._case_documents(tmp_path, "c")
    assert len({d.doc_id for d in docs}) == 2
    (tmp_path / "c" / "other" / "2023.txt").write_text("Changed text.")
    assert theme_cli._case_documents(tmp_path, "c")[1].doc_id != docs[1].doc_id


def _b_store(tmp_path, activities):
    store = TaxonomyStore(tmp_path / "tax")
    return store.create("t", ThemeDefinition(name="t", description="", activities=activities), DerivationMethod.MANUAL)


def test_draft_taxonomy_runs(tmp_path, models):  # AC-40
    t = _b_store(tmp_path, [ActivityDefinition(name="Electrolysers", in_scope_description=POS, out_of_scope_description=NEG,
                                               seed_keywords=["electrolyser"])])
    _set(tmp_path, [("a", "core", "all", KEEP)])
    assert _invoke(tmp_path, taxonomy_id=t.taxonomy_id).exit_code == 0


def test_out_rows_carry_rerank_query(tmp_path, models):  # AC-42
    act = ActivityDefinition(name="Electrolysers", in_scope_description="Makes stacks.", out_of_scope_description=NEG,
                             seed_keywords=["electrolyser"])
    t = _b_store(tmp_path, [act])
    _set(tmp_path, [("a", "core", "all", KEEP)])
    assert _invoke(tmp_path, "--out", str(tmp_path / "rows.json"), taxonomy_id=t.taxonomy_id).exit_code == 0
    row = json.loads((tmp_path / "rows.json").read_text())[0]
    assert row["funnel"]["rerank_query"] == ("Electrolysers: Makes stacks.\nEvidence: Electrolysers: revenue share; "
                                             "Electrolysers: CapEx share; Electrolysers: OpEx share; "
                                             "Electrolysers: R&D intensity")


def test_out_rows_best_activity(tmp_path, monkeypatch, models):  # AC-48
    a = ActivityDefinition(name="A", in_scope_description="a.", out_of_scope_description=NEG, seed_keywords=["x"])
    b = ActivityDefinition(name="B", in_scope_description="b.", out_of_scope_description=NEG, seed_keywords=["x"])
    t = _b_store(tmp_path, [a, b])
    _set(tmp_path, [("a", "core", "all", KEEP)])

    def classify(texts, labels, hypothesis=""):  # A's positives 0.85, B's 0.95
        def score(lab):
            if lab.startswith(funnel.POSITIVE_PREFIX):
                return 0.95 if (lab.endswith(" B.") or lab.endswith(": b.")) else 0.85
            return 0.1
        return [{lab: score(lab) for lab in labels} for _ in texts], {}

    monkeypatch.setattr(funnel.models, "classify", classify)
    _invoke(tmp_path, "--out", str(tmp_path / "rows.json"), taxonomy_id=t.taxonomy_id)
    assert json.loads((tmp_path / "rows.json").read_text())[0]["funnel"]["query"] == "B: b."
