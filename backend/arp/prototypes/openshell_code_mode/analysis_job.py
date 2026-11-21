"""Trusted Python entry point run in the voting sandbox.

This file is also copied into the sandbox image and uses no ARP imports.
"""

from __future__ import annotations

import argparse
import csv
import io
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import TypedDict

SNAPSHOT_ID = "synthetic-votes-v1"
MAX_ELIGIBLE_VOTES = 60_000
COUNT_FIELDS = ("snapshot_id", "sector", "issuer_id", "eligible_votes", "against_votes")
RANKING_FIELDS = (
    "sector", "eligible_votes", "against_votes", "included_issuers",
    "vote_weighted_pct", "issuer_weighted_pct", "vote_rank", "issuer_rank",
)


class IssuerCount(TypedDict):
    snapshot_id: str
    sector: str
    issuer_id: str
    eligible_votes: int
    against_votes: int


class RankingRow(TypedDict):
    sector: str
    eligible_votes: int
    against_votes: int
    included_issuers: int
    vote_weighted_pct: str
    issuer_weighted_pct: str
    vote_rank: int
    issuer_rank: int | str


def validate_minimum(min_issuer_votes: int) -> None:
    if type(min_issuer_votes) is not int or not 1 <= min_issuer_votes <= MAX_ELIGIBLE_VOTES:
        raise ValueError("Minimum issuer votes must be an integer from 1 to 60000.")


def _percentage(rate: Fraction) -> str:
    whole, fraction = divmod(round(rate * 1_000_000), 10_000)
    return f"{whole}.{fraction:04d}"


def rank_issuers(counts: list[IssuerCount], min_issuer_votes: int) -> list[RankingRow]:
    validate_minimum(min_issuer_votes)
    by_sector: dict[str, list[IssuerCount]] = defaultdict(list)
    issuer_keys = set()
    for row in counts:
        if set(row) != set(COUNT_FIELDS) or row["snapshot_id"] != SNAPSHOT_ID:
            raise ValueError("Unexpected issuer-count schema or snapshot ID.")
        sector, issuer_id = row["sector"], row["issuer_id"]
        if not isinstance(sector, str) or not sector or not isinstance(issuer_id, str) or not issuer_id:
            raise ValueError("Issuer and sector labels must be nonempty strings.")
        if (sector, issuer_id) in issuer_keys:
            raise ValueError("Duplicate issuer in sector.")
        issuer_keys.add((sector, issuer_id))
        eligible, against = row["eligible_votes"], row["against_votes"]
        if type(eligible) is not int or type(against) is not int or not 0 <= against <= eligible or eligible == 0:
            raise ValueError("Invalid eligible or opposing vote count.")
        by_sector[sector].append(row)
    if sum(row["eligible_votes"] for row in counts) != MAX_ELIGIBLE_VOTES:
        raise ValueError("Unexpected number of votes in the synthetic snapshot.")

    totals = {}
    vote_rates: dict[str, Fraction] = {}
    issuer_rates: dict[str, Fraction] = {}
    for sector, rows in by_sector.items():
        eligible = sum(row["eligible_votes"] for row in rows)
        against = sum(row["against_votes"] for row in rows)
        rates = [
            Fraction(row["against_votes"], row["eligible_votes"])
            for row in rows if row["eligible_votes"] >= min_issuer_votes
        ]
        totals[sector] = (eligible, against, len(rates))
        vote_rates[sector] = Fraction(against, eligible)
        if rates:
            issuer_rates[sector] = sum(rates, Fraction(0)) / len(rates)

    issuer_ranks = {
        sector: rank for rank, sector in enumerate(sorted(issuer_rates, key=lambda key: (-issuer_rates[key], key)), 1)
    }
    results: list[RankingRow] = []
    for rank, sector in enumerate(sorted(vote_rates, key=lambda key: (-vote_rates[key], key)), 1):
        eligible, against, included = totals[sector]
        results.append({
            "sector": sector,
            "eligible_votes": eligible,
            "against_votes": against,
            "included_issuers": included,
            "vote_weighted_pct": _percentage(vote_rates[sector]),
            "issuer_weighted_pct": _percentage(issuer_rates[sector]) if sector in issuer_rates else "",
            "vote_rank": rank,
            "issuer_rank": issuer_ranks.get(sector, ""),
        })
    return results


def ranking_csv(rows: list[RankingRow]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=RANKING_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def draw_chart(rows: list[RankingRow]):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(9, 4), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    positions = list(range(len(rows)))
    axis.barh(
        [position - 0.18 for position in positions],
        [float(row["vote_weighted_pct"]) for row in rows],
        height=0.32, label="Vote-weighted", color="#17658a",
    )
    available = [(position, row["issuer_weighted_pct"]) for position, row in enumerate(rows) if row["issuer_weighted_pct"]]
    axis.barh(
        [position + 0.18 for position, _ in available],
        [float(rate) for _, rate in available],
        height=0.32, label="Issuer-weighted", color="#b45123",
    )
    axis.set_yticks(positions, [row["sector"] for row in rows])
    axis.invert_yaxis()
    axis.set_xlabel("Opposition (%)")
    axis.legend()
    return figure


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank opposition by sector in a synthetic issuer-count snapshot.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--min-issuer-votes", type=int, default=1)
    args = parser.parse_args()
    validate_minimum(args.min_issuer_votes)

    import pyarrow.parquet as parquet

    with args.input.open("rb") as source:
        table = parquet.read_table(source)
    rows = rank_issuers(table.to_pylist(), args.min_issuer_votes)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "ranking.csv").write_bytes(ranking_csv(rows).encode("utf-8"))
    draw_chart(rows).savefig(args.output_dir / "ranking.png", format="png", dpi=120)


if __name__ == "__main__":
    main()
