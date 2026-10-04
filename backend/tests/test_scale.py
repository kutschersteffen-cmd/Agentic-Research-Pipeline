"""Load script and cost/time report: RunReport math, the simulated driver, the CLI."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import get_settings
from arp.scale.load import simulate
from arp.scale.report import RunReport, render_markdown, run_report
from arp.schemas.common import JobStatus, RunManifest
from arp.storage.run_store import RunStore


def _manifest(completed: int, failed: int, seconds: float, cost: float) -> RunManifest:
    t = datetime(2026, 10, 4, tzinfo=UTC)
    return RunManifest(
        run_id="r1",
        run_type="load_test",
        status=JobStatus.COMPLETED,
        created_at=t.isoformat(),
        updated_at=(t + timedelta(seconds=seconds)).isoformat(),
        params={"concurrency": 8},
        completed_count=completed,
        failed_count=failed,
        estimated_cost_usd=cost,
    )


def test_run_report_math():
    r = run_report(_manifest(200, 0, 100, 6.0))
    assert r.concurrency == 8
    assert r.cost_per_1000_usd == 30.0
    assert r.minutes_per_1000 == pytest.approx(8.333, rel=1e-3)
    assert r.issuers_per_minute == 120.0


def test_run_report_zero_issuers():
    r = run_report(_manifest(0, 0, 100, 0.0))
    assert (r.cost_per_1000_usd, r.minutes_per_1000, r.issuers_per_minute) == (0.0, 0.0, 0.0)


def test_simulate_records_counts_and_cost(tmp_path):
    store = RunStore(tmp_path)
    run_id = asyncio.run(simulate(20, 4, run_store=store, latency_s=0, fail_every=5))
    m = store.load_manifest(run_id)
    assert (m.completed_count, m.failed_count) == (16, 4)
    assert m.estimated_cost_usd == pytest.approx(16 * 0.03)
    assert m.status == JobStatus.PARTIALLY_COMPLETED


def test_render_markdown_has_row_per_run():
    reports = [run_report(_manifest(10, 0, 5, 1.0).model_copy(update={"run_id": f"run-{i}"})) for i in range(2)]
    assert all(isinstance(r, RunReport) for r in reports)
    md = render_markdown(reports, title="T", note="N")
    rows = [line for line in md.splitlines() if line.startswith("|") and "run-" in line]
    assert len(rows) == 2


def test_cli_scale_load_writes_report(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    get_settings.cache_clear()
    out = tmp_path / "tmp" / "x.md"
    result = CliRunner().invoke(
        app, ["scale", "load", "--issuers", "10", "--concurrency", "2,4", "--latency", "0", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    rows = [line for line in out.read_text().splitlines() if line.startswith("| load_test")]
    assert len(rows) == 2
    get_settings.cache_clear()
