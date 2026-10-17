from __future__ import annotations

import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import get_settings
from arp.replication.characteristics_data import CharacteristicPanel
from arp.signal_lab.cutoffs import CutoffTable
from arp.signal_lab.lab import UNREGISTERED, Lab, Preview, load_recipe, save_recipe
from arp.signal_lab.methods import base
from arp.signal_lab.methods.base import MethodInput, MethodResult
from arp.signal_lab.registry import Recipe, Registry
from arp.storage.run_store import RunStore
from tests.postgres_helpers import reset_postgres_tables
from tests.test_signal_lab_cli import _write_panel

pytestmark = pytest.mark.usefixtures("pg")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ARP_TRAINING_CUTOFFS_PATH", str(tmp_path / "cutoffs.json"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def lab(pg, tmp_path) -> Lab:
    return Lab(registry=Registry(RunStore(pg, tmp_path / "lab-runs")), cutoffs=CutoffTable(entries={}))


def _recipe(dates, **extra) -> Recipe:
    fields = dict(
        category="sentiment_narrative", method="price_momentum", text_source=None, params={},
        universe="toy15", window_start=dates[0], window_end=dates[-1],
    )
    return Recipe(**{**fields, **extra})


def _inputs(lab, env, recipe) -> tuple[MethodInput, str]:
    return lab.inputs(recipe, env / "prices.csv")


def test_preview_registers_nothing_and_is_labelled(lab, env):
    dates = _write_panel(env, 40)
    recipe = _recipe(dates)
    inp, data_version = _inputs(lab, env, recipe)
    lab.run(recipe, inp, data_version)
    before, trials = lab.experiments(), lab.registry.trial_count(recipe)
    assert len(before) == trials == 1
    preview = lab.preview({"method": "price_momentum", "params": {"formation_period_months": 3}}, inp)
    assert isinstance(preview, Preview) and preview.label == UNREGISTERED == "unregistered, not evidence"
    assert lab.experiments() == before and lab.registry.trial_count(recipe) == trials
    assert repr(preview).startswith("[unregistered, not evidence]")
    assert f"IC mean={preview.ic.mean} n={preview.ic.n}" in repr(preview) and preview.ic.n > 0
    assert not hasattr(preview, "experiment_id")


def test_compare_and_decide_refuse_a_preview(lab, env):
    dates = _write_panel(env, 40)
    recipe = _recipe(dates)
    inp, data_version = _inputs(lab, env, recipe)
    record = lab.run(recipe, inp, data_version)
    preview = lab.preview({"method": "price_momentum", "params": {}}, inp)
    msg = "a preview is unregistered, not evidence; run it first"
    for a, b in ((preview, record.experiment_id), (record.experiment_id, preview)):
        with pytest.raises(ValueError) as exc:
            lab.compare(a, b)
        assert str(exc.value) == msg
    with pytest.raises(ValueError) as exc:
        lab.decide(preview, "shelve", approver="ann")
    assert str(exc.value) == msg
    with pytest.raises(ValueError, match="experiment id"):
        lab.compare(record.experiment_id, 7)
    assert lab.decide(record.experiment_id, "shelve", approver="ann").decision == "shelve"


def test_lab_run_matches_the_cli_run(env, pg):
    dates = _write_panel(env, 40)
    path = env / "r.json"
    recipe = _recipe(dates, params={"formation_period_months": 3})
    save_recipe(recipe, path)
    result = CliRunner().invoke(
        app, ["signals", "run", "--recipe", str(path), "--prices", str(env / "prices.csv")]
    )
    assert result.exit_code == 0, result.output
    cli_record = Registry(RunStore(pg, env / "runs")).list_experiments()[0]
    # Empty the registry so Lab.run computes and registers afresh; a re-registration would trivially echo the CLI row.
    reset_postgres_tables(pg)
    lab = Lab.from_settings()
    assert lab.experiments() == []
    inp, data_version = lab.inputs(load_recipe(path), env / "prices.csv")
    lab_record = lab.run(load_recipe(path), inp, data_version)
    assert result.stdout.splitlines()[0] == f"experiment_id: {lab_record.experiment_id}"
    assert lab_record.experiment_id == cli_record.experiment_id
    assert [w.model_dump() for w in lab_record.evidence.windows] == [w.model_dump() for w in cli_record.evidence.windows]
    assert len(lab.experiments()) == 1 and lab_record.evidence.windows[0].ic.n > 0


def test_recipe_round_trips_through_json(env):
    recipe = _recipe(["2015-01-31", "2016-12-31"], params={"formation_period_months": 3}, cost_bps=5.0)
    save_recipe(recipe, env / "r.json")
    assert json.loads((env / "r.json").read_text())["cost_bps"] == 5.0
    assert load_recipe(env / "r.json") == recipe


def test_load_recipe_rejects_invalid_files(env):
    (env / "bad.json").write_text("{not json")
    (env / "wrong.json").write_text(json.dumps({"method": "x"}))
    with pytest.raises(ValueError, match="invalid recipe .*bad.json"):
        load_recipe(env / "bad.json")
    with pytest.raises(ValueError, match="invalid recipe .*category"):
        load_recipe(env / "wrong.json")
    with pytest.raises(ValueError, match="cannot read recipe"):
        load_recipe(env / "missing.json")


def test_texts_without_a_text_store_raises(lab):
    with pytest.raises(ValueError, match="no text store"):
        lab.texts()


def test_check_finds_a_peeking_method(lab, env, monkeypatch):
    dates = _write_panel(env, 12)
    inp, _ = _inputs(lab, env, _recipe(dates))

    def peeking(params: dict, inp: MethodInput) -> MethodResult:
        vals = {t: r[1:] + [None] for t, r in inp.prices.returns.items()}
        return MethodResult(CharacteristicPanel(list(inp.prices.period_ends), vals, "peek"))

    monkeypatch.setitem(base._METHODS, "peeking", peeking)
    assert lab.check({"method": "peeking", "params": {}}, inp)
    assert lab.check({"method": "price_momentum", "params": {"formation_period_months": 3}}, inp) == []


def test_preview_label_cannot_be_overridden(lab, env):
    dates = _write_panel(env, 40)
    inp, _ = _inputs(lab, env, _recipe(dates))
    preview = lab.preview({"method": "price_momentum", "params": {}}, inp)
    with pytest.raises(TypeError):
        Preview(preview.panel, None, {}, preview.ic, label="evidence")


def test_importing_the_library_does_not_import_the_cli():
    code = "import arp.signal_lab.lab, sys; print(any(m.startswith('arp.cli') for m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_lab_run_records_history_from_in_notes_only_when_given(lab, env):
    dates = _write_panel(env, 40)
    recipe = _recipe(dates[13:])
    plain_inp, plain_version = lab.inputs(recipe, env / "prices.csv")
    hist_inp, hist_version = lab.inputs(recipe, env / "prices.csv", history_from=dates[0])
    plain = lab.run(recipe, plain_inp, plain_version)
    hist = lab.run(recipe, hist_inp, hist_version, history_from=dates[0])
    assert plain.notes == {} and hist.notes == {"history_from": dates[0]}
    assert plain.experiment_id != hist.experiment_id
