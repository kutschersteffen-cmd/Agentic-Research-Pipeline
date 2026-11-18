"""Re-fetch the URTH N-PX vote CSVs in this folder from SEC EDGAR (see README.md). Standard library only.

    python3 fetch_npx.py --user-agent "<organisation> <contact address>"   # or set SEC_USER_AGENT

SEC asks every automated client for a User-Agent naming who it is. Each vote table (85-90 MB) is streamed and
not stored; only proxyTable records of series S000035395 are kept, flattened to one CSV row per voteRecord.
`arp stewardship load-npx` reads the CSVs and never fetches.
"""

from __future__ import annotations

import argparse
import csv
import os
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SERIES = "S000035395"
FILINGS = [  # (period of report, accession, vote table)
    ("2024-06-30", "0001021408-24-004974", "proxyvote.xml"),
    ("2025-06-30", "0001438934-25-002318", "BRDWLB_0000930667_2025.xml"),
    ("2026-06-30", "0001438934-26-002287", "BRDWLB_0000930667_2026.xml"),
]
COLUMNS = [
    "period", "accession", "issuer_name", "cusip", "isin", "figi", "meeting_date", "vote_description",
    "other_vote_description", "vote_categories", "other_vote_category", "vote_source", "shares_voted",
    "shares_on_loan", "how_voted", "record_shares_voted", "management_recommendation", "for_against_management",
    "vote_manager", "vote_series",
]  # fmt: skip
PROPOSAL = {  # column -> element directly under proxyTable
    "issuer_name": "issuerName", "cusip": "cusip", "isin": "isin", "figi": "figi", "meeting_date": "meetingDate",
    "vote_description": "voteDescription", "other_vote_description": "otherVoteDescription",
    "other_vote_category": "otherVoteCategory", "vote_source": "voteSource", "shares_voted": "sharesVoted",
    "shares_on_loan": "sharesOnLoan", "vote_series": "voteSeries",
}  # fmt: skip


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _all(el: ET.Element, name: str) -> list[ET.Element]:
    return [d for d in el.iter() if _local(d.tag) == name]


def for_against_management(how_voted: str, recommendation: str) -> str:
    """Derived here, not filed: empty when there is no recommendation (NONE or missing) or for a frequency vote,
    whose recommendation is filed as FOR/AGAINST, not as a frequency."""
    if not how_voted or recommendation in ("", "NONE") or "YEAR" in how_voted:
        return ""
    return "FOR" if how_voted == recommendation else "AGAINST"


def rows(table: ET.Element, period: str, accession: str) -> list[list[str]]:
    base = {k: _text(_child(table, e)) for k, e in PROPOSAL.items()}
    base |= {"period": period, "accession": accession}
    base["vote_categories"] = "; ".join(_text(c) for c in _all(table, "categoryType"))
    base["vote_manager"] = "; ".join(_text(m) for m in _all(table, "otherManager"))
    records = _all(table, "voteRecord") or [None]  # a proposal with no vote record still gives one row
    out = []
    for rec in records:
        how = _text(_child(rec, "howVoted")) if rec is not None else ""
        recommendation = _text(_child(rec, "managementRecommendation")) if rec is not None else ""
        vote = {
            "how_voted": how,
            "record_shares_voted": _text(_child(rec, "sharesVoted")) if rec is not None else "",
            "management_recommendation": recommendation,
            "for_against_management": for_against_management(how, recommendation),
        }
        out.append([(base | vote)[c] for c in COLUMNS])
    return out


def fetch(period: str, accession: str, table: str, user_agent: str, out_dir: Path) -> int:
    url = f"https://www.sec.gov/Archives/edgar/data/930667/{accession.replace('-', '')}/{table}"
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    path = out_dir / f"urth_npx_{period}.csv"
    n = 0
    with urllib.request.urlopen(req, timeout=120) as resp, path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for _, el in ET.iterparse(resp, events=("end",)):
            if _local(el.tag) != "proxyTable":
                continue
            if _text(_child(el, "voteSeries")) == SERIES:
                for row in rows(el, period, accession):
                    writer.writerow(row)
                    n += 1
            el.clear()  # keep memory flat while streaming
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user-agent", default=os.environ.get("SEC_USER_AGENT"), help="or env SEC_USER_AGENT")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    if not args.user_agent:
        parser.error("SEC requires a User-Agent: pass --user-agent or set SEC_USER_AGENT")
    for period, accession, table in FILINGS:
        print(f"urth_npx_{period}.csv: {fetch(period, accession, table, args.user_agent, args.out)} rows")


if __name__ == "__main__":
    main()
