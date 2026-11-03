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
        return np.asarray([[1.0 if t == POS else ROWS[t][0], 0.1] for t in texts], dtype=np.float32), {}

    def rerank(query, texts, score=None):
        return [ROWS[t][1] for t in texts], {}

    def classify(texts, labels, hypothesis=""):
        return [{lab: ROWS[t][2].get(lab, 0.1) for lab in labels} for t in texts], {}

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
