"""refine-chat golden set: scoring of a turn's ops against the expected ops (AC-45), with the stand-in model."""

from __future__ import annotations

import asyncio
import json

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import get_settings
from arp.golden_set.refine import run_refine_golden
from arp.standins import StandInLLMClient


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "standins" / "model").mkdir(parents=True)
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "rfp.json").write_text(json.dumps({"questions": [
        {"id": 1, "status": "drafted", "question": "Q?", "answer": "A"}]}))
    return tmp_path


def write_cases(folder, expected):
    case = {"doc_fixture": "rfp", "history": [], "message": "redo 1", "expected_ops": expected}
    path = folder / "cases.json"
    path.write_text(json.dumps({"cases": [case]}))
    return path


def model_says(folder, ops):
    (folder / "standins" / "model" / "RefineOps.json").write_text(json.dumps({"output": {"reply": "ok", "ops": ops}}))


def run(folder):
    return asyncio.run(run_refine_golden(folder / "cases.json", StandInLLMClient(folder / "standins")))


def test_case_passes_ignoring_instruction_text(folder):
    write_cases(folder, [{"op": "rewrite", "question_ids": [1, 2], "instruction": "shorter"}])
    model_says(folder, [{"op": "rewrite", "question_ids": [2, 1], "instruction": "make it tighter"}])
    assert run(folder) == (1, 1)


def test_case_fails_on_wrong_target(folder):
    write_cases(folder, [{"op": "rewrite", "question_ids": [1], "instruction": "x"}])
    model_says(folder, [{"op": "rewrite", "question_ids": [2], "instruction": "x"}])
    assert run(folder) == (0, 1)


def test_cli_exit_code_below_threshold(folder, pg, monkeypatch):
    write_cases(folder, [{"op": "leave_blank", "question_ids": [1]}])
    model_says(folder, [])
    for key in ("ARP_ANTHROPIC_API_KEY", "ARP_GEMINI_API_KEY"):  # stand-ins refuse to run beside a real key
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARP_STANDINS_DIR", str(folder / "standins"))
    get_settings.cache_clear()
    args = ["golden-set", "refine", "--cases", str(folder / "cases.json"), "--min-accuracy", "0.9"]
    try:
        r = CliRunner().invoke(app, args)
        assert r.exit_code == 1 and "accuracy 0.000" in r.output
        model_says(folder, [{"op": "leave_blank", "question_ids": [1]}])
        r = CliRunner().invoke(app, args)
        assert r.exit_code == 0
    finally:
        get_settings.cache_clear()
