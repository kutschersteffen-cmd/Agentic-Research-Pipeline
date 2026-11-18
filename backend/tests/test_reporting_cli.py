import re

import click
from typer.testing import CliRunner

from arp.cli import reporting as cli
from arp.schemas.reporting import DeckSettings, RunRef, Storyline
from arp.storage.reporting_store import ReportingStore


def _setup(tmp_path, monkeypatch, llm):
    store = ReportingStore(tmp_path / "reports", tmp_path / "tpl")
    monkeypatch.setattr(cli, "_reporting_store", lambda: store)
    monkeypatch.setattr(cli, "build_llm_client", lambda settings: llm)
    monkeypatch.setattr("arp.reporting.service.with_run_datasets", lambda request, settings: request)
    notes = tmp_path / "notes.txt"
    notes.write_text("notes")
    return store, notes


def test_run_rejects_house_deck_before_any_llm_call(tmp_path, monkeypatch, fake_llm):
    llm = fake_llm({})
    store, notes = _setup(tmp_path, monkeypatch, llm)
    result = CliRunner().invoke(cli.reporting_app, ["run", "--title", "T", "--notes", str(notes), "--out", str(tmp_path / "o"), "--format", "house_deck"])
    assert result.exit_code == 1 and "arp report plan" in result.output and llm.calls == [] and store.list_reports() == []


def test_plan_takes_goal_theme_and_run_refs(tmp_path, monkeypatch, fake_llm):
    store, notes = _setup(tmp_path, monkeypatch, fake_llm({"Storyline": [Storyline(title="D", slides=[])]}))
    result = CliRunner().invoke(cli.reporting_app, [
        "plan", "--title", "T", "--notes", str(notes), "--out", str(tmp_path / "s.json"), "--format", "house_deck",
        "--goal", "Decide", "--theme", "dark", "--run-ref", "run:run_1", "--run-ref", "decision:d_2",
    ])
    assert result.exit_code == 0, result.output
    [m] = store.list_reports()
    request = store.load_request(m.report_id)
    assert (request.goal, request.layout.theme) == ("Decide", "dark")
    assert request.run_refs == [RunRef(kind="run", ref_id="run_1"), RunRef(kind="decision", ref_id="d_2")]


def test_plan_passes_deck_settings_to_the_request(tmp_path, monkeypatch, fake_llm):
    store, notes = _setup(tmp_path, monkeypatch, fake_llm({"Storyline": [Storyline(title="D", slides=[])]}))
    result = CliRunner().invoke(cli.reporting_app, [
        "plan", "--title", "T", "--notes", str(notes), "--out", str(tmp_path / "s.json"), "--format", "house_deck",
        "--max-slides", "22", "--profile", "workshop", "--purpose", "review", "--detail", "comprehensive", "--target-length", "20",
    ])
    assert result.exit_code == 0, result.output
    [m] = store.list_reports()
    request = store.load_request(m.report_id)
    assert request.deck.model_dump() == {"profile": "workshop", "purpose": "review", "detail": "comprehensive", "max_slides": 22}
    assert request.layout.target_length == 20


def test_plan_defaults_keep_the_old_deck_settings(tmp_path, monkeypatch, fake_llm):
    store, notes = _setup(tmp_path, monkeypatch, fake_llm({"Storyline": [Storyline(title="D", slides=[])]}))
    result = CliRunner().invoke(cli.reporting_app, ["plan", "--title", "T", "--notes", str(notes), "--out", str(tmp_path / "s.json"), "--format", "house_deck"])
    assert result.exit_code == 0, result.output
    [m] = store.list_reports()
    assert store.load_request(m.report_id).deck == DeckSettings()


def test_plan_rejects_a_target_length_above_the_slide_cap_before_any_llm_call(tmp_path, monkeypatch, fake_llm):
    llm = fake_llm({})
    store, notes = _setup(tmp_path, monkeypatch, llm)
    for extra in (["--target-length", "18"], ["--target-length", "10", "--max-slides", "20", "--profile", "executive"]):
        result = CliRunner().invoke(cli.reporting_app, [
            "plan", "--title", "T", "--notes", str(notes), "--out", str(tmp_path / "s.json"), "--format", "house_deck", *extra,
        ])
        flat = re.sub(r"[^a-z0-9]", "", click.unstyle(result.output).lower())  # rich adds colours and wraps the error box
        assert result.exit_code == 2 and "morethanthedeckkeeps" in flat
    assert llm.calls == [] and store.list_reports() == []


def test_plan_rejects_max_slides_outside_3_to_25(tmp_path, monkeypatch, fake_llm):
    store, notes = _setup(tmp_path, monkeypatch, fake_llm({}))
    for n in ("2", "26"):
        result = CliRunner().invoke(cli.reporting_app, [
            "plan", "--title", "T", "--notes", str(notes), "--out", str(tmp_path / "s.json"), "--format", "house_deck", "--max-slides", n,
        ])
        assert result.exit_code == 2
