"""`arp golden-set theme` (spec theme-precision-scorecard, slice 1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import get_settings
from arp.storage.taxonomy_store import TaxonomyStore

EXPOSURE = Path(__file__).parent / "golden" / "exposure"
TAX = json.loads((EXPOSURE / "electrolyser_makers/taxonomies/tax_electrolyser_makers/v1.json").read_text())
CASES = [  # case, label, document text, adjudicator (verdict, confidence, quote) or None
    ("a", "core", "We manufacture electrolyser stacks.", ("include", 0.95, "We manufacture electrolyser stacks.")),
    ("b", "core", "Our electrolyser unit is small.", ("exclude", 0.55, None)),
    ("c", "peripheral", "An electrolyser line opened.", ("include", 0.80, "This sentence is not in the file.")),
    ("d", "peripheral", None, None),
    ("e", "not", "We buy electrolyser systems.", ("include", 0.60, None)),
    ("f", "not", "We operate an electrolyser plant.", ("exclude", 0.92, None)),
    ("g", "not", "We make cement.", None),
]


def _set(root, split="tune"):
    root.mkdir()
    rows = [{"case_id": c, "company": c.upper(), "label": lab, "role": "r", "rationale": "x", "split": split,
             "label_sources": ["https://example.com/a"], "documents": [{"url": "https://example.com/d.pdf"}]}
            for c, lab, _, _ in CASES]
    (root / "cases.json").write_text(json.dumps({"set_id": "fixture_set", "kind": "activity", "subject": "s",
                                                 "labels": ["core", "peripheral", "not"], "checked_on": "2026-11-02",
                                                 "cases": rows}))
    tax = json.loads(json.dumps(TAX))
    tax["taxonomy_id"] = "tax_fixture_set"
    tax["theme"]["activities"][0]["seed_keywords"] = ["electrolyser"]
    d = root / "taxonomies" / "tax_fixture_set"
    d.mkdir(parents=True)
    (d / "latest.json").write_text('{"latest_version": 1}')
    (d / "v1.json").write_text(json.dumps(tax))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("arp.db.session.require_postgres", lambda s: None)
    monkeypatch.setattr("arp.db.session.require_cutover", lambda s: None)
    docs, standins, scorecards = tmp_path / "docs", tmp_path / "standins", tmp_path / "S"
    (standins / "model").mkdir(parents=True)
    scorecards.mkdir()
    adjudications = []
    for case, _, text, adj in CASES:
        if text is None:
            continue
        f = docs / case / "annual_report" / f"{case}.txt"
        f.parent.mkdir(parents=True)
        f.write_text(text)
        if adj is not None:
            verdict, conf, quote = adj
            doc_id = f"{case}_{hashlib.sha256(f.read_bytes()).hexdigest()[:16]}"
            cites = [{"doc_id": doc_id, "doc_type": "other", "quote": quote}] if quote else []
            adjudications.append({"output": {"verdict": verdict, "confidence": conf, "adjudicator_rationale": "r",
                                             "exposure_estimate": "pure_play" if verdict == "include" else "none",
                                             "citations": cites}})
    (standins / "model" / "AgentOpinion.json").write_text(json.dumps(
        {"output": {"stance": "s", "rationale": "r", "citations": [], "exposure_estimate": "pure_play"}}))
    (standins / "model" / "AdjudicatorOutput.json").write_text(json.dumps(adjudications))
    for k, v in {"ARP_STANDINS_DIR": standins, "ARP_SCORECARDS_DIR": scorecards, "ARP_HYBRID_RETRIEVAL_ENABLED": "false",
                 "ARP_MODELS_UNIVERSE_FUNNEL_ENABLED": "false"}.items():
        monkeypatch.setenv(k, str(v))
    for key in ("ARP_ANTHROPIC_API_KEY", "ARP_GEMINI_API_KEY"):  # stand-ins refuse to run beside a real key
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _run(*args):
    return CliRunner().invoke(app, ["golden-set", "theme", *args])


def _adjudicator_calls(env):
    path = env / "standins" / "calls.jsonl"
    lines = path.read_text().splitlines() if path.exists() else []
    return sum('"name": "AdjudicatorOutput"' in line for line in lines)


def test_fixture_set_scores_tune_split(env):
    _set(env / "F")
    r = _run("--set", str(env / "F"), "--documents-dir", str(env / "docs"), "--split", "tune", "--out", str(env / "r.json"))
    assert r.exit_code == 0, r.output
    assert """split: tune
companies: 7 (core 2, peripheral 2, not 3)
not assessed: 1
put in: 3
precision: 0.667
recall core: 0.500
recall peripheral: 0.500
quotes found in source: 0.500
confidence 0.90-1.00: calls 2, correct 2, rate 1.000
confidence 0.70-0.90: calls 1, correct 1, rate 1.000
confidence 0.50-0.70: calls 2, correct 0, rate 0.000
confidence 0.00-0.50: calls 0, correct 0, rate n/a""" in r.output
    assert _adjudicator_calls(env) == 5
    report = json.loads((env / "r.json").read_text())
    assert list(report) == ["set_id", "taxonomy_id", "taxonomy_version", "created_at", "splits"]
    tune = report["splits"]["tune"]
    assert [c["case_id"] for c in tune["cases"]] == list("abcdefg")
    assert tune["cases"][3] == {"case_id": "d", "label": "peripheral", "assessed": False, "put_in": False,
                                "confidence": None, "correct": None}
    assert tune["confidence"][3] == {"low": 0.0, "high": 0.5, "calls": 0, "correct": 0, "rate": None}
    assert not list((env / "S").iterdir())


def test_holdout_gate_and_stored_scorecard(env):
    _set(env / "H", split="holdout")
    r = _run("--set", str(env / "H"), "--documents-dir", str(env / "docs"), "--split", "holdout", "--min-precision", "0.7")
    assert r.exit_code == 1
    assert "Holdout precision 0.667 is below 0.7." in r.output
    assert json.loads((env / "S" / "tax_fixture_set_v1.json").read_text())["splits"]["holdout"]["precision"] == 0.667


def test_gate_needs_holdout_before_any_model_call(env):
    _set(env / "F")
    r = _run("--set", str(env / "F"), "--documents-dir", str(env / "docs"), "--split", "tune", "--min-precision", "0.5")
    assert r.exit_code == 1
    assert "The gate needs the holdout split." in r.output
    assert _adjudicator_calls(env) == 0


def test_refusals(env):
    r = _run("--set", "water_scarcity_exposed", "--documents-dir", str(env / "docs"))
    assert r.exit_code == 1 and "Risk sets can't be scored yet: water_scarcity_exposed" in r.output
    r = _run("--set", "no_such_set")
    assert r.exit_code == 1 and "Golden set not found: no_such_set" in r.output
    _set(env / "F")
    r = _run("--set", str(env / "F"), "--documents-dir", str(env / "docs"), "--split", "tune", "--taxonomy", "tax_nope")
    assert r.exit_code == 1 and "Taxonomy not found: tax_nope" in r.output


def test_ai_datacentre_taxonomy():
    tax = TaxonomyStore(EXPOSURE / "ai_datacentre_operators" / "taxonomies").get("tax_ai_datacentre_operators")
    [activity] = tax.theme.activities
    assert activity.name == "AI data-centre operation"
    assert len(activity.seed_keywords) == 6 and len(activity.contrast_statements) == 2
