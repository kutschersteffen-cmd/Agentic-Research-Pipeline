"""Trusted synthetic voting data preparation and artifact validation."""

from __future__ import annotations

import sqlite3
import stat
from fractions import Fraction
from itertools import repeat
from pathlib import Path
from typing import Self, TypedDict

from .analysis_job import SNAPSHOT_ID, IssuerCount, rank_issuers, ranking_csv

MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_CHART_PIXELS = 4_000_000
ISSUER_FIXTURE = (
    ("Information Technology", "SYN03", 30_000, 6_000),
    ("Information Technology", "SYN07", 3_000, 0),
    ("Financials", "SYN11", 15_000, 2_000),
    ("Financials", "SYN12", 12_000, 1_600),
)


class SectorCount(TypedDict):
    sector: str
    eligible_votes: int
    against_votes: int


class VotingFixture:
    def __init__(self) -> None:
        self._db = sqlite3.connect(":memory:")
        try:
            self._db.execute("CREATE TABLE votes (sector TEXT, issuer_id TEXT, opposed INTEGER)")
            with self._db:
                for sector, issuer_id, eligible, against in ISSUER_FIXTURE:
                    self._db.executemany("INSERT INTO votes VALUES (?, ?, ?)", repeat((sector, issuer_id, 1), against))
                    self._db.executemany("INSERT INTO votes VALUES (?, ?, ?)", repeat((sector, issuer_id, 0), eligible - against))
        except BaseException:
            self._db.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._db.close()

    def list_voting_snapshots(self, args: dict[str, object]) -> list[dict[str, str]]:
        if args != {}:
            raise ValueError("listVotingSnapshots expects empty arguments.")
        return [{"snapshot_id": SNAPSHOT_ID}]

    def aggregate_votes_by_sector(self, args: dict[str, object]) -> list[SectorCount]:
        """Return the sector rows that the registered tool delivers to JavaScript."""
        if args != {"snapshot_id": SNAPSHOT_ID}:
            raise ValueError("aggregateVotesBySector expects the authorized synthetic snapshot.")
        rows: list[SectorCount] = [
            {"sector": sector, "eligible_votes": eligible, "against_votes": against}
            for sector, eligible, against in self._db.execute("SELECT sector, COUNT(*), SUM(opposed) FROM votes GROUP BY sector")
        ]
        return sorted(rows, key=lambda row: (-Fraction(row["against_votes"], row["eligible_votes"]), row["sector"]))

    def _issuer_counts(self) -> list[IssuerCount]:
        return [
            {"snapshot_id": SNAPSHOT_ID, "sector": sector, "issuer_id": issuer_id,
             "eligible_votes": eligible, "against_votes": against}
            for sector, issuer_id, eligible, against in self._db.execute(
                "SELECT sector, issuer_id, COUNT(*), SUM(opposed) FROM votes GROUP BY sector, issuer_id ORDER BY sector, issuer_id"
            )
        ]

    def stage_parquet(self, path: Path) -> None:
        import pyarrow as arrow
        import pyarrow.parquet as parquet

        parquet.write_table(arrow.Table.from_pylist(self._issuer_counts()), path, compression="NONE")

    def validate_csv(self, path: Path, min_issuer_votes: int) -> None:
        _check_artifact(path)
        expected = ranking_csv(rank_issuers(self._issuer_counts(), min_issuer_votes)).encode("utf-8")
        if path.read_bytes() != expected:
            raise ValueError("The CSV does not match the trusted ranking and column order.")


def _check_artifact(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError("The sandbox artifact is missing or inaccessible.") from exc
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_ARTIFACT_BYTES:
        raise ValueError("The sandbox artifact has an invalid type or size.")


def validate_png(path: Path) -> None:
    from PIL import Image

    _check_artifact(path)
    try:
        with Image.open(path, formats=["PNG"]) as image:
            if image.width * image.height > MAX_CHART_PIXELS:
                raise ValueError("The PNG pixel count exceeds the prototype limit.")
            image.verify()
        with Image.open(path, formats=["PNG"]) as image:
            image.load()
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("The sandbox chart is not a decodable PNG.") from exc
