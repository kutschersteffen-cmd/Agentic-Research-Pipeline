from __future__ import annotations

import csv
import json

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import get_settings
from tests.test_signal_lab_cli import TICKERS, _write_panel

pytestmark = pytest.mark.usefixtures("pg")

TRANSCRIPTS = (
    "issuer_key,event_time,title,text\n"
    "iss_a,2020-01-31T23:10:00Z,Q4 call,We grew.\n"
)


def _run(*args):
    return CliRunner().invoke(app, ["signals", *args])


@pytest.fixture
def tx(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(TRANSCRIPTS)
    return path


def test_ingest_then_manifest_round_trip_and_idempotent(tx, tmp_path):
    first = _run("ingest-transcripts", "--csv", str(tx))
    assert first.exit_code == 0, first.output
    assert "1 new" in first.stdout
    assert "0 new" in _run("ingest-transcripts", "--csv", str(tx)).stdout
    out = tmp_path / "m.json"
    assert _run("text-manifest", "--out", str(out)).exit_code == 0
    [entry] = json.loads(out.read_text())
    assert (entry["ticker"], entry["period_end"], entry["text"]) == ("iss_a", "2020-01-01", "Q4 call\n\nWe grew.")


def test_manifest_known_by_before_ingestion_excludes(tx, tmp_path):
    _run("ingest-transcripts", "--csv", str(tx))
    out = tmp_path / "m.json"
    result = _run("text-manifest", "--out", str(out), "--known-by", "2000-01-01")
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text()) == []


def test_manifest_naive_time_exits_1(tmp_path):
    result = _run("text-manifest", "--out", str(tmp_path / "m.json"), "--event-from", "2020-01-01T00:00:00")
    assert result.exit_code == 1
    assert "ambiguous" in result.stderr


def test_build_panel_fundamentals_feeds_evaluate(tmp_path):
    dates = _write_panel(tmp_path, 40)
    fund = tmp_path / "f.csv"
    with fund.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["issuer_key", "metric", "fiscal_period_end", "available_time", "value"])
        for i, t in enumerate(TICKERS):
            w.writerow([t, "eps", "2014-12-31", "2015-01-15", i * 0.1])
    panel = tmp_path / "panel.csv"
    result = _run("build-panel", "--kind", "fundamentals", "--csv", str(fund), "--prices",
                  str(tmp_path / "prices.csv"), "--out", str(panel), "--metric", "eps")
    assert result.exit_code == 0, result.output
    rows = list(csv.reader(panel.open()))
    assert rows[0] == ["date", *TICKERS] and [r[0] for r in rows[1:]] == dates
    get_settings.cache_clear()
    ev = _run("evaluate", "--scores", str(panel), "--prices", str(tmp_path / "prices.csv"),
              "--category", "sentiment_narrative", "--method", "toy", "--universe", "u",
              "--start", dates[0], "--end", dates[-1])
    assert "grid" not in ev.output and ev.exit_code == 0, ev.output


def test_build_panel_revisions_blank_for_none(tmp_path):
    _write_panel(tmp_path, 12)
    rev = tmp_path / "r.csv"
    rev.write_text("issuer_key,event_time,direction\nT00,2015-02-10T00:00:00Z,up\n")
    panel = tmp_path / "panel.csv"
    result = _run("build-panel", "--kind", "revisions", "--csv", str(rev), "--prices",
                  str(tmp_path / "prices.csv"), "--out", str(panel), "--window-months", "1")
    assert result.exit_code == 0, result.output
    rows = list(csv.reader(panel.open()))
    assert rows[1][1] == "" and rows[2][1] == "1.0" and rows[2][2] == ""


def test_build_panel_fundamentals_requires_metric(tmp_path):
    _write_panel(tmp_path, 12)
    result = _run("build-panel", "--kind", "fundamentals", "--csv", str(tmp_path / "x.csv"),
                  "--prices", str(tmp_path / "prices.csv"), "--out", str(tmp_path / "p.csv"))
    assert result.exit_code == 1
    assert "--metric" in result.stderr


def test_pull_news_text_missing_credentials_exits_1(monkeypatch):
    monkeypatch.delenv("ARP_NEWS_API_CLIENT_ID", raising=False)
    monkeypatch.setenv("ARP_NEWS_API_CLIENT_SECRET", "s3cret-value")
    get_settings.cache_clear()
    result = _run("pull-news-text")
    assert result.exit_code == 1
    assert "News API is not configured" in result.stderr
    assert "s3cret-value" not in result.output + result.stderr
