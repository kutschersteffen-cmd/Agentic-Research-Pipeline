import random

from arp.research.stock_inference.schemas import InferStock
from arp.research.stock_inference.selection import load_stocks, select


def _csv(tmp_path, rows, header="Ticker,Name,Weight"):
    p = tmp_path / "h.csv"
    p.write_text(header + "\n" + "\n".join(rows) + "\n")
    return p


def test_cap_30_takes_30_largest(tmp_path):
    rows = [f"t{i:02d},Co {i},{0.025 + i * 1e-6}" for i in range(40)]
    stocks, total = load_stocks(_csv(tmp_path, rows))
    picked, sel = select(stocks, total)
    assert sel.cutoff_reason == "cap_30" and sel.method == "weighted"
    assert [s.company_id for s in picked] == [f"t{i:02d}" for i in range(39, 9, -1)]


def test_weight_80_inclusive(tmp_path):
    ws = [20, 10, 10, 8, 7, 6, 5, 4, 4, 3, 2, 1] + [0.5] * 28
    stocks, total = load_stocks(_csv(tmp_path, [f"t{i:02d},Co,{w}" for i, w in enumerate(ws)], "Ticker,Name,Weight (%)"))
    picked, sel = select(stocks, total)
    assert len(picked) == 10 and sel.cutoff_reason == "weight_80"


def test_unweighted_sample_is_order_independent(tmp_path):
    ids = [f"c{i:02d}" for i in range(50)]
    out = []
    for order in (ids, ids[::-1]):
        p = tmp_path / f"u{len(out)}.csv"
        p.write_text("company_id,name\n" + "\n".join(f"{i},{i}" for i in order) + "\n")
        stocks, total = load_stocks(p)
        picked, sel = select(stocks, total)
        assert sel.cutoff_reason == "sample" and total is None
        out.append([s.company_id for s in picked])
    assert len(out[0]) == 30 and out[0] == out[1]


def test_tie_at_cap_breaks_by_id():
    stocks = [InferStock(company_id=i, name=i, weight=0.01) for i in ("t30b", "t30a", *[f"a{n:02d}" for n in range(29)])]
    random.shuffle(stocks)
    picked, sel = select(stocks, 0.99)
    ids = {s.company_id for s in picked}
    assert "t30a" in ids and "t30b" not in ids and sel.cutoff_reason == "cap_30"


def test_duplicate_ticker_merged(tmp_path):
    stocks, total = load_stocks(_csv(tmp_path, ["AAA,A Co,0.3", " AAA ,A Co,0.2", "BBB,B Co,0.5"]))
    assert {s.company_id: round(s.weight, 6) for s in stocks} == {"AAA": 0.5, "BBB": 0.5}
    assert round(total, 6) == 1.0


def test_twelve_unweighted_all(tmp_path):
    p = tmp_path / "u.json"
    p.write_text('[' + ",".join(f'{{"company_id":"c{i}","name":"n{i}"}}' for i in range(12)) + ']')
    stocks, total = load_stocks(p)
    picked, sel = select(stocks, total)
    assert len(picked) == 12 and sel.cutoff_reason == "all"


def test_unweighted_duplicate_ticker_stays_unweighted(tmp_path):  # F2
    stocks, total = load_stocks(_csv(tmp_path, ["AAA,A Co", "AAA,A Co", "BBB,B Co", "CCC,C Co"], "Ticker,Name"))
    picked, sel = select(stocks, total)
    assert total is None and sel.cutoff_reason == "all"
    assert [s.company_id for s in picked] == ["AAA", "BBB", "CCC"]


def test_bom_universe_csv_is_a_universe(tmp_path):  # F7
    p = tmp_path / "u.csv"
    p.write_text("﻿company_id,name\nc1,One\nc2,Two\n", encoding="utf-8")
    stocks, total = load_stocks(p)
    assert [s.company_id for s in stocks] == ["c1", "c2"] and total is None


def test_nace_rev_reaches_nace_sectors(tmp_path, monkeypatch):  # F3
    from arp.research.stock_inference import stored

    p = tmp_path / "u.csv"
    p.write_text("company_id,name,nace_code,nace_rev\nc1,One,20.1,2.1\n")
    stocks, _ = load_stocks(p)
    seen = []
    monkeypatch.setattr(stored, "nace_sectors", lambda code, rev: seen.append((code, rev)) or set())
    stored.stored_data(None, stocks[0], None, {})
    assert seen == [("20.1", "2.1")]


def test_weight_80_stops_at_the_boundary_despite_float_sums(tmp_path):  # 0.2+0.15+...+0.1 == 0.7999...
    ws = [20, 15, 15, 10, 10, 10, 5, 5, 5, 5]
    stocks, total = load_stocks(_csv(tmp_path, [f"t{i:02d},Co,{w}" for i, w in enumerate(ws)]))
    picked, sel = select(stocks, total)
    assert len(picked) == 6 and sel.cutoff_reason == "weight_80"
