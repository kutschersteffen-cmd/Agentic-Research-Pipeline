import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.research.taxonomy_sources.etf_holdings import load_holdings_with_weights

FIX = Path(__file__).parent / "fixtures/holdings/hydr_layout.csv"


def _load(tmp_path, text):
    p = tmp_path / "h.csv"
    p.write_text(text, encoding="utf-8")
    return load_holdings_with_weights(p)


def test_ac1_rows_and_order():
    assert [r.ticker for r in load_holdings_with_weights(FIX)] == ["BE", "PLUG", "NEL NO", "NANO SP", "288620 KS"]


def test_ac2_weights_scaled_per_column():
    assert [r.weight for r in load_holdings_with_weights(FIX)] == pytest.approx([0.162, 0.079, 0.0512, 0.0065, 0.0039], abs=1e-9)


def test_ac3_universe_from_holdings(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_POSTGRES_DSN", "postgresql://unused/unused")  # CLI startup requires it; this command never connects
    out = tmp_path / "u.json"
    result = CliRunner().invoke(app, ["universe", "from-holdings", str(FIX), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert len(json.loads(out.read_text())) == 5


def test_ac4_ticker_rows_kept(tmp_path):
    rows = _load(tmp_path, "Ticker,Name,Weight\n,CASH,1.0\nABC,Cash Holdings Corp,2.0\n")
    assert [(r.ticker, r.weight) for r in rows] == [("ABC", pytest.approx(0.02))]


def test_ac5_fractions_unchanged(tmp_path):
    rows = _load(tmp_path, "Ticker,Name,Weight\nA,Alpha,0.6\nB,Beta,0.4\n")
    assert [r.weight for r in rows] == [0.6, 0.4]


def test_bom_header_found(tmp_path):
    rows = _load(tmp_path, "﻿Ticker,Name,Weight\nA,Alpha,60\n")
    assert [(r.ticker, r.weight) for r in rows] == [("A", pytest.approx(0.6))]


def test_ids_kept(tmp_path):
    rows = _load(tmp_path, "Ticker,Name,Weight,ISIN,SEDOL,LEI,CIK\nA,Alpha,0.5,US1,SD1,LEI1,CIK1\n")
    assert (rows[0].isin, rows[0].sedol, rows[0].lei, rows[0].cik) == ("US1", "SD1", "LEI1", "CIK1")
