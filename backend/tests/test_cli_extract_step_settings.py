from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import arp.cli.extraction as cli
from arp.cli.extraction import extract_app
from arp.config import Settings
from arp.extraction.steps import StepSettings
from arp.llm.batching_client import BatchingLLMClient
from arp.orchestration.job_manager import JobManager
from arp.schemas.datapoints import DataPointSchema
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.verify import CircularRunError, assert_xbrl_off

RUN_ID = "run_cli_1"


def _run_cli(tmp_path, monkeypatch, *, xbrl_facts_enabled: bool):
    settings = Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache", xbrl_facts_enabled=xbrl_facts_enabled
    )
    store = RunStore(settings.runs_dir)

    async def fake_run_extraction(schema, companies, **kwargs):
        store.run_dir(RUN_ID)  # the real pipeline creates the run directory
        return RUN_ID

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "_run_store", lambda: store)
    monkeypatch.setattr(cli, "_xbrl_source", lambda: None)
    monkeypatch.setattr(cli, "build_llm_client", lambda s: object())
    monkeypatch.setattr(cli, "build_verifier_llm_client", lambda s: object())
    monkeypatch.setattr(cli, "run_extraction", fake_run_extraction)
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(DataPointSchema(schema_id="s1", name="Demo", description="d", fields=[]).model_dump_json())
    universe = tmp_path / "universe.csv"
    universe.write_text("company_id,name\nAAA,Alpha Inc\n")
    res = CliRunner().invoke(extract_app, ["run", "--schema", str(schema_file), "--universe", str(universe)])
    return res, settings, store


def test_cli_run_records_the_step_settings_the_api_records(tmp_path, monkeypatch):
    res, settings, store = _run_cli(tmp_path, monkeypatch, xbrl_facts_enabled=False)
    assert res.exit_code == 0, res.output
    saved = store.run_dir(RUN_ID) / "step_settings.json"
    assert saved.read_text() == StepSettings.effective(settings).model_dump_json()
    assert json.loads(saved.read_text())["xbrl_facts_enabled"] is False


def test_cli_run_with_xbrl_off_can_be_verified(tmp_path, monkeypatch):
    _, _, store = _run_cli(tmp_path, monkeypatch, xbrl_facts_enabled=False)
    assert_xbrl_off(RUN_ID, run_store=store)  # raises CircularRunError when it cannot prove XBRL was off


def test_cli_run_with_xbrl_on_is_recorded_and_refused(tmp_path, monkeypatch):
    _, _, store = _run_cli(tmp_path, monkeypatch, xbrl_facts_enabled=True)
    assert json.loads((store.run_dir(RUN_ID) / "step_settings.json").read_text())["xbrl_facts_enabled"] is True
    with pytest.raises(CircularRunError, match="xbrl_facts_enabled"):
        assert_xbrl_off(RUN_ID, run_store=store)


def test_cli_run_batch_marks_the_run_and_batches_the_clients(tmp_path, monkeypatch):
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    store = RunStore(settings.runs_dir)
    seen = {}

    async def fake_run_extraction(schema, companies, *, llm, settings, **kwargs):
        seen.update(llm=llm, settings=settings)
        return JobManager(store).create_run("extraction", {}, 1).run_id

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "_run_store", lambda: store)
    monkeypatch.setattr(cli, "_xbrl_source", lambda: None)
    monkeypatch.setattr(cli, "run_extraction", fake_run_extraction)
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(DataPointSchema(schema_id="s1", name="Demo", description="d", fields=[]).model_dump_json())
    universe = tmp_path / "universe.csv"
    universe.write_text("company_id,name\nAAA,Alpha Inc\n")
    args = ["run", "--schema", str(schema_file), "--universe", str(universe)]
    res = CliRunner().invoke(extract_app, [*args, "--batch"])
    assert res.exit_code == 0, res.output
    assert isinstance(seen["llm"], BatchingLLMClient) and seen["settings"].llm_batch
    assert [m.params.get("batch") for m in store.list_runs()] == [True]
    seen.clear()
    res = CliRunner().invoke(extract_app, args)
    assert res.exit_code == 0, res.output
    assert not isinstance(seen["llm"], BatchingLLMClient)
    assert sorted(str(m.params.get("batch")) for m in store.list_runs()) == ["None", "True"]
