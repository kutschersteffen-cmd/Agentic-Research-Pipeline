import json

from arp.ask import benchmark_sectors
from arp.stewardship.benchmark import BenchmarkStore
from arp.stewardship.process import SAMPLE_PATH


def write_benchmark(root, *, name="Test Index", as_of="Oct 20, 2026", dropped=0, constituents=(("A", "Energy", 100.0),)) -> str:
    benchmark = {
        "name": name, "as_of": as_of, "source": "iShares holdings export", "dropped": dropped,
        "constituents": [
            {"issuer_id": t.lower(), "ticker": t, "name": t, "sector": s, "country": "US", "weight_pct": w}
            for t, s, w in constituents
        ],
    }
    return BenchmarkStore(root).save(benchmark, "tests")["benchmark_id"]


def test_sectors_sum_sort_and_unclassified(tmp_path):  # AC-14, AC-15
    bid = write_benchmark(tmp_path, name="iShares MSCI World ETF", as_of="Oct 20, 2026", dropped=3, constituents=[
        ("A", "Information Technology", 30.0), ("B", "Information Technology", 20.004),
        ("C", "Financials", 40.0), ("D", "", 9.996),
    ])
    card, text = benchmark_sectors(tmp_path, bid)
    assert [(s.sector, s.weight_pct) for s in card.sectors] == [
        ("Information Technology", 50.0), ("Financials", 40.0), ("Unclassified", 10.0),
    ]
    assert card.check.model_dump() == {
        "source": "iShares holdings export", "as_of": "Oct 20, 2026", "constituents": 4, "dropped": 3,
        "unclassified_pct": 10.0, "total_pct": 100.0,
    }
    assert card.is_sample is False and card.name == "iShares MSCI World ETF" and card.benchmark_id == bid
    assert text == "Sector weights of iShares MSCI World ETF as of Oct 20, 2026."


def test_unclassified_is_a_share_of_total(tmp_path):  # AC-16
    bid = write_benchmark(tmp_path, constituents=[("A", "Energy", 72.0), ("B", "", 8.0)])
    card, _ = benchmark_sectors(tmp_path, bid)
    assert (card.check.total_pct, card.check.unclassified_pct) == (80.0, 10.0)


def test_sample_when_nothing_uploaded(tmp_path):  # AC-17
    issuers = json.loads(SAMPLE_PATH.read_text())["issuers"]
    card, text = benchmark_sectors(tmp_path, None)
    assert card.is_sample and card.benchmark_id is None and card.name == "Synthetic sample"
    assert card.check.source == "synthetic sample" and card.check.as_of is None
    assert card.check.constituents == 12 and card.check.dropped == 0
    assert card.check.total_pct == round(sum(i["holding"]["index_weight_pct"] for i in issuers), 2)
    assert text.startswith("Synthetic sample: 12 fictional companies standing in for MSCI World.")


def test_unknown_or_missing_id_asks_which(tmp_path):  # AC-18
    write_benchmark(tmp_path, name="B Index")
    write_benchmark(tmp_path, name="A Index")
    for bid in (None, "nope"):
        assert benchmark_sectors(tmp_path, bid) == (None, "Which benchmark do you mean: A Index, B Index?")


def test_empty_benchmark_has_no_division_by_zero(tmp_path):  # Review Focus 3
    card, _ = benchmark_sectors(tmp_path, write_benchmark(tmp_path, constituents=[]))
    assert (card.check.total_pct, card.check.unclassified_pct, card.sectors) == (0.0, 0.0, [])
