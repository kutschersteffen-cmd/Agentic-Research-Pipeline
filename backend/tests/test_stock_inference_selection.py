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
