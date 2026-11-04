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


def test_ac3_universe_from_holdings(tmp_path, pg):  # the CLI root pings Postgres at startup
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


def test_decimal_comma_weight(tmp_path):  # F4
    from arp.research.taxonomy_sources.etf_holdings import _parse_weight

    rows = _load(tmp_path, 'Ticker,Name,Weight (%)\nA,Alpha,"16,20"\nB,Beta,"83,80"\n')
    assert [r.weight for r in rows] == pytest.approx([0.162, 0.838])
    assert _parse_weight("31,526.89") == pytest.approx(31526.89)


def test_name_only_file_keeps_cash_word_companies(tmp_path):  # F5
    rows = _load(tmp_path, "Name,Weight\nDollar General Corp,0.5\nEuronext NV,0.5\n")
    assert [r.ticker for r in rows] == ["Dollar General Corp", "Euronext NV"]
    assert len(load_holdings_with_weights(FIX)) == 5


def test_total_row_dropped(tmp_path):  # F6
    rows = _load(tmp_path, "Ticker,Name,Weight\nA,Alpha,60\nB,Beta,40\n, Totals ,100\n")
    assert [r.ticker for r in rows] == ["A", "B"]
    rows = _load(tmp_path, "Name,Weight\nAlpha,0.6\nTOTAL,1.0\n")
    assert [r.ticker for r in rows] == ["Alpha"]


def test_percent_check_uses_the_column_read(tmp_path):  # F14
    rows = _load(tmp_path, "Ticker,Name,Weight,Weight (%)\nA,Alpha,0.6,\nB,Beta,0.4,\n")
    assert [r.weight for r in rows] == pytest.approx([0.6, 0.4])
