from __future__ import annotations

import pytest
from fastapi import HTTPException

pytest.importorskip("zen")
pptx = pytest.importorskip("pptx")

from arp.api.routers.stewardship import (  # noqa: E402
    BenchmarkUpload,
    CreateStreamRequest,
    ProgramRequest,
    create_stream,
    post_program_simulate,
    upload_benchmark,
)
from arp.config import Settings  # noqa: E402
from arp.stewardship.benchmark import BenchmarkStore, parse_ishares_holdings, placeholder_clti  # noqa: E402
from arp.stewardship.process import StreamStore  # noqa: E402
from arp.stewardship.program import ProgramParams, build_proposal, simulate  # noqa: E402
from arp.storage.engagement_store import EngagementStore  # noqa: E402

HEADER = "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date"
ROWS = [
    ("AAA", "ALPHA CORP", "Information Technology", "Equity", "600,000.00", "United States", "NASDAQ"),
    ("MRK", "MERCK & CO", "Health Care", "Equity", "200,000.00", "United States", "New York Stock Exchange Inc."),
    ("MRK", "MERCK KGAA", "Health Care", "Equity", "100,000.00", "Germany", "Xetra"),
    ("BBB", "BETA AG", "Utilities", "Equity", "100,000.00", "Germany", "Xetra"),
    ("XXX", "UNLISTED CO", "Health Care", "Equity", "226.70", "United States", "NO MARKET (E.G. UNLISTED)"),
    ("USD", "USD CASH", "Cash and/or Derivatives", "Cash", "50,000.00", "United States", "-"),
    ("ESZ6", "S&P500 EMINI DEC 26", "Cash and/or Derivatives", "Futures", "0.00", "-", "Index And Options Market"),
]
CSV = "\n".join(
    [
        "iShares Test World ETF",
        'Fund Holdings as of,"Sep 25, 2026"',
        "",
        HEADER,
        *(
            f'"{t}","{n}","{s}","{a}","{mv}","0","{mv}","1","1","{loc}","{ex}","USD","1.00","USD","-"'
            for t, n, s, a, mv, loc, ex in ROWS
        ),
    ]
)


def test_holdings_export_becomes_equity_constituents_with_weights():
    b = parse_ishares_holdings(CSV)
    assert (b["name"], b["as_of"], b["dropped"]) == ("iShares Test World ETF", "Sep 25, 2026", 3)
    assert [c["issuer_id"] for c in b["constituents"]] == ["AAA@United States", "MRK@United States", "MRK@Germany", "BBB@Germany"]
    assert sum(c["weight_pct"] for c in b["constituents"]) == pytest.approx(100)
    assert b["constituents"][0]["weight_pct"] == pytest.approx(60)
    with pytest.raises(ValueError, match="Ticker"):
        parse_ishares_holdings("just,some,csv\n1,2,3")


def test_placeholder_scores_are_fixed_and_bounded():
    assert placeholder_clti("MRK@Germany") == placeholder_clti("MRK@Germany")
    assert all(5 <= placeholder_clti(f"T{i}@X") <= 95 for i in range(200))


def test_program_runs_on_an_uploaded_benchmark_and_says_the_scores_are_placeholders(tmp_path):
    streams = StreamStore(tmp_path)
    stream = streams.get(create_stream(CreateStreamRequest(name="Example Pension Fund"), streams)["stream_id"])
    bench = BenchmarkStore(tmp_path).save(parse_ishares_holdings(CSV), "Analyst")
    sim = simulate(tmp_path, stream, [], 45, {"benchmark": bench["benchmark_id"], "laggard_clti": 95, "leader_clti": 95})
    assert sim["constituents"] == 4 and "placeholder" in sim["score_note"].lower()
    assert sim["targets"] and all(t["reason"].startswith("Placeholder CLTI") for t in sim["targets"])
    assert sum(h["portfolio_pct"] for h in sim["holdings"]) == pytest.approx(100, abs=0.01)
    deck = build_proposal(sim, tmp_path / "p.pptx")
    first = [s for s in pptx.Presentation(deck).slides][1]  # title, then the one-pager
    assert "placeholders" in " ".join(sh.text_frame.text for sh in first.shapes if sh.has_text_frame)


def test_upload_and_unknown_benchmark_errors(tmp_path):
    streams = StreamStore(tmp_path)
    with pytest.raises(HTTPException) as bad:
        upload_benchmark(BenchmarkUpload(text="not,a,holdings,file", uploaded_by="A"), streams)
    assert bad.value.status_code == 422
    listed = upload_benchmark(BenchmarkUpload(text=CSV, uploaded_by="A"), streams)
    assert listed["constituents"] == 4
    stream_id = create_stream(CreateStreamRequest(name="Fund"), streams)["stream_id"]
    with pytest.raises(HTTPException) as unknown:
        post_program_simulate(
            stream_id,
            ProgramRequest(params=ProgramParams(benchmark="nope")),
            Settings(),
            streams,
            EngagementStore(tmp_path / "e"),
        )
    assert unknown.value.status_code == 422
