import json

import numpy as np
import pytest
from typer.testing import CliRunner

from arp.cli import taxonomy as taxonomy_cli
from arp.cli import taxonomy_infer as cli
from arp.config import get_settings
from arp.db.runs import RunStore
from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.stock_inference.run import WrongStage
from arp.research.stock_inference.themes import ProposedTheme, Support, ThemeProposals
from tests.test_stock_inference_profile import _doc, _extract, _FixedDocSource

RUN_KEYS = {"run_id", "stage", "name", "extractor_model", "verifier_model", "selection", "profiles", "clusters",
            "themes", "outliers", "index_rules", "taxonomy_id", "activities", "mapping", "coverage"}


class _NoCalls:
    async def complete_structured(self, **_):
        raise AssertionError("no model call expected")


def _reply(*themes):
    return ThemeProposals(themes=[
        ProposedTheme(name=n, description=f"{n} desc", supporting=[Support(company_id=i, reason="r") for i in ids])
        for n, ids in themes
    ])


@pytest.fixture
def env(pg, tmp_path, monkeypatch, fake_llm):
    """`env.setup(n, replies, behaviour, docs)` wires fakes; returns the stocks CSV path."""
    monkeypatch.setenv("ARP_ANTHROPIC_API_KEY", "unused")
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    get_settings.cache_clear()
    monkeypatch.setattr(cli, "_run_store", lambda: RunStore(pg, tmp_path / "runs"))  # a fresh instance per command
    monkeypatch.setattr(cli, "build_verifier_llm_client", lambda s: _NoCalls())
    monkeypatch.setattr(cli, "cluster_points", lambda e: np.full(len(e), -1))
    monkeypatch.setattr(cli, "embed_texts", lambda texts: np.zeros((len(texts), 4)))

    class Env:
        llm = None

        def setup(self, n, replies=(), behaviour=None, docs=None, found=None):
            ids = [f"s{i}" for i in range(1, n + 1)]
            source = _FixedDocSource(docs if docs is not None else {c: [_doc(f"D{c}", c)] for c in ids})

            async def discover(stocks, settings):
                source.docs.update(found or {})

            self.llm = fake_llm({"ThemeProposals": list(replies)})
            monkeypatch.setattr(cli, "_registry", lambda: DocumentSourceRegistry([source]))
            monkeypatch.setattr(cli, "build_llm_client", lambda s: self.llm)
            monkeypatch.setattr(cli, "discover_missing", discover)
            monkeypatch.setattr(cli, "_extract_company", _extract(behaviour or {}))
            path = tmp_path / "fund.csv"
            path.write_text("company_id,name\n" + "".join(f"{c},Stock {c}\n" for c in ids))
            return path

    yield Env()
    get_settings.cache_clear()


def _invoke(*args):
    return CliRunner().invoke(taxonomy_cli.taxonomy_app, ["infer", *args])


def _run_id(res):
    first = res.stdout.splitlines()[0]
    assert first.startswith("Run ")
    return first.split()[1]


def _show(run_id):
    res = _invoke("show", run_id, "--json")
    assert res.exit_code == 0, res.output
    return json.loads(res.stdout)


def test_start_reaches_themes_ready(env):
    path = env.setup(3, [_reply(("Hydrogen", ["s1", "s2"]), ("Fuel", ["s3"]))])
    res = _invoke("start", "--stocks", str(path))
    assert res.exit_code == 0, res.output
    run = _show(_run_id(res))
    assert run["stage"] == "themes_ready"
    assert run["name"] == "fund"
    assert [t["name"] for t in run["themes"]] == ["Hydrogen", "Fuel"]
    assert "Hydrogen" in res.stdout


def test_ac14_no_stock_profiled(env):
    path = env.setup(3, behaviour={"s1": RuntimeError("boom"), "s2": RuntimeError("boom")},
                     docs={"s1": [_doc("D1", "s1")], "s2": [_doc("D2", "s2")]})
    res = _invoke("start", "--stocks", str(path))
    assert res.exit_code == 1
    run_id = _run_id(res)
    assert res.stderr.strip() == "No stock could be profiled: 2 failed, 1 had no document."
    assert _show(run_id)["stage"] == "failed"


def test_ac23a_no_supported_theme_fails(env):
    path = env.setup(2, [_reply(("T2", ["x1"]))])
    res = _invoke("start", "--stocks", str(path))
    assert res.exit_code == 1
    assert res.stderr.strip() == "No common theme is supported by the profiled stocks."
    assert _show(_run_id(res))["stage"] == "failed"


def test_ac15_model_ids(env, monkeypatch):
    monkeypatch.setenv("ARP_LLM_MODEL", "model-a")
    monkeypatch.setenv("ARP_LLM_VERIFIER_MODEL", "model-b")
    get_settings.cache_clear()
    path = env.setup(2, [_reply(("T1", ["s1", "s2"]))])
    run = _show(_run_id(_invoke("start", "--stocks", str(path))))
    assert (run["extractor_model"], run["verifier_model"]) == ("model-a", "model-b")


def test_show_json_has_exactly_the_spec_keys(env):
    path = env.setup(2, [_reply(("T1", ["s1"]))])
    run = _show(_run_id(_invoke("start", "--stocks", str(path), "--name", "Hydrogen set")))
    assert set(run) == RUN_KEYS
    assert run["name"] == "Hydrogen set"
    assert set(run["profiles"][0]["citation"]) == {"doc_id", "page", "quote"}
    assert run["outliers"] == ["s2"]
    assert all("error" not in p for p in run["profiles"])  # absent on success


def test_failed_profile_keeps_its_error(env):
    path = env.setup(2, [_reply(("T1", ["s1"]))], behaviour={"s2": RuntimeError("boom")})
    run = _show(_run_id(_invoke("start", "--stocks", str(path))))
    by_id = {p["company_id"]: p for p in run["profiles"]}
    assert "error" not in by_id["s1"] and by_id["s2"]["error"] == "RuntimeError: boom"


def test_settings_threshold_reaches_theme_grounding(env, monkeypatch):
    from arp.research.stock_inference import themes as themes_mod

    monkeypatch.setenv("ARP_GROUNDING_FUZZY_THRESHOLD", "0.77")
    get_settings.cache_clear()
    seen = []
    real = themes_mod.ground_citations
    monkeypatch.setattr(themes_mod, "ground_citations",
                        lambda c, d, t=0.92, **kw: seen.append(t) or real(c, d, t, **kw))
    path = env.setup(2, [_reply(("T1", ["s1"]))])
    meth = path.parent / "rules.txt"
    meth.write_text("Some rules.")
    reply = ThemeProposals(themes=[ProposedTheme(name="T1", description="d", supporting=[Support(company_id="s1",
                           reason="r")], stated_in_methodology=True, methodology_quote="Some rules.")])
    env.llm._script["ThemeProposals"] = [reply]
    assert _invoke("start", "--stocks", str(path), "--methodology", str(meth)).exit_code == 0
    assert seen == [0.77]


def test_wrong_stage_message():
    e = WrongStage("r1", "drafted", "pick", "themes_ready")
    assert str(e) == "Run r1 is at stage 'drafted'; 'pick' needs 'themes_ready'."
    assert (e.run_id, e.stage, e.command, e.needed) == ("r1", "drafted", "pick", "themes_ready")


def test_show_makes_no_model_call(env, monkeypatch):
    path = env.setup(2, [_reply(("T1", ["s1"]))])
    run_id = _run_id(_invoke("start", "--stocks", str(path)))
    monkeypatch.setattr(cli, "build_llm_client", lambda s: _NoCalls())
    res = _invoke("show", run_id)
    assert res.exit_code == 0 and "T1" in res.stdout and "themes_ready" in res.stdout
    assert _show(run_id)["themes"][0]["name"] == "T1"


def test_methodology_file_grounds_quote(env, tmp_path):
    meth = tmp_path / "rules.txt"
    meth.write_text("The index tracks makers of PEM stacks.")
    reply = ThemeProposals(themes=[ProposedTheme(
        name="PEM", description="d", supporting=[Support(company_id="s1", reason="r")], stated_in_methodology=True,
        methodology_quote="The index tracks makers of PEM stacks.")])
    path = env.setup(2, [reply])
    run = _show(_run_id(_invoke("start", "--stocks", str(path), "--methodology", str(meth))))
    assert run["themes"][0]["stated_in_methodology"] is True


def test_show_unknown_run_exits_1(env):
    env.setup(1)
    res = _invoke("show", "nope")
    assert res.exit_code == 1 and res.stderr.strip()
