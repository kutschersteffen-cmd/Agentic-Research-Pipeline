from __future__ import annotations

import csv
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from arp.prototypes.openshell_code_mode import analysis_job
from arp.prototypes.openshell_code_mode.voting_analysis import SNAPSHOT_ID, VotingFixture, validate_png

HEADER = (
    "sector,eligible_votes,against_votes,included_issuers,"
    "vote_weighted_pct,issuer_weighted_pct,vote_rank,issuer_rank\n"
)
DEFAULT_ROWS = (
    "Information Technology,33000,6000,2,18.1818,10.0000,1,2\n"
    "Financials,27000,3600,2,13.3333,13.3333,2,1\n"
)


def test_sql_lists_only_the_known_snapshot_and_gets_sorted_sector_aggregates():
    with VotingFixture() as fixture:
        assert fixture.list_voting_snapshots({}) == [{"snapshot_id": SNAPSHOT_ID}]
        assert fixture.aggregate_votes_by_sector({"snapshot_id": SNAPSHOT_ID}) == [
            {"sector": "Information Technology", "eligible_votes": 33_000, "against_votes": 6_000},
            {"sector": "Financials", "eligible_votes": 27_000, "against_votes": 3_600},
        ]
        with pytest.raises(ValueError, match="authorized synthetic snapshot"):
            fixture.aggregate_votes_by_sector({"snapshot_id": "another-snapshot"})


@pytest.mark.parametrize(("minimum", "expected"), [
    (1, DEFAULT_ROWS),
    (4_000, "Information Technology,33000,6000,1,18.1818,20.0000,1,1\nFinancials,27000,3600,2,13.3333,13.3333,2,2\n"),
    (30_001, "Information Technology,33000,6000,0,18.1818,,1,\nFinancials,27000,3600,0,13.3333,,2,\n"),
])
def test_voting_csv_strictly_checks_both_sectors_and_keeps_vote_weighted_baseline(tmp_path, minimum, expected):
    ranking = tmp_path / "ranking.csv"
    ranking.write_text(HEADER + expected, encoding="utf-8")
    with VotingFixture() as fixture:
        fixture.validate_csv(ranking, minimum)
        ranking.write_text(HEADER + expected.replace("18.1818", "19.1818"), encoding="utf-8")
        with pytest.raises(ValueError, match="trusted ranking"):
            fixture.validate_csv(ranking, minimum)


def test_chart_contains_expected_labels_and_uses_only_available_series():
    rows = list(csv.DictReader((HEADER + DEFAULT_ROWS).splitlines()))
    figure = analysis_job.draw_chart(rows)
    axis = figure.axes[0]
    assert axis.get_xlabel() == "Opposition (%)"
    assert [tick.get_text() for tick in axis.get_yticklabels()] == ["Information Technology", "Financials"]
    assert axis.get_legend_handles_labels()[1] == ["Vote-weighted", "Issuer-weighted"]
    assert [bar.get_width() for bar in axis.patches] == pytest.approx([18.1818, 13.3333, 10.0000, 13.3333])
    rows[0]["issuer_weighted_pct"] = ""
    assert len(analysis_job.draw_chart(rows).axes[0].patches) == 3


def test_png_validation_rejects_non_png_or_linked_artifacts(tmp_path):
    ranking = tmp_path / "ranking.png"
    Image.new("RGB", (2, 2)).save(ranking)
    validate_png(ranking)
    link = tmp_path / "linked.png"
    link.symlink_to(ranking)
    with pytest.raises(ValueError, match="invalid type or size"):
        validate_png(link)
    ranking.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError, match="decodable PNG"):
        validate_png(ranking)


def test_standalone_analysis_job_uses_only_four_issuer_count_rows(tmp_path):
    parquet = pytest.importorskip("pyarrow.parquet")
    snapshot = tmp_path / "snapshot.parquet"
    isolated_script = shutil.copyfile(Path(analysis_job.__file__), tmp_path / "analysis_job.py")
    output = tmp_path / "output"
    with VotingFixture() as fixture:
        fixture.stage_parquet(snapshot)
        table = parquet.read_table(snapshot)
        assert table.column_names == list(analysis_job.COUNT_FIELDS)
        assert table.num_rows == 4
        assert sum(table["eligible_votes"].to_pylist()) == 60_000
        assert sum(table["against_votes"].to_pylist()) == 9_600
        subprocess.run(
            [sys.executable, "-I", str(isolated_script), "--input", str(snapshot), "--output-dir", str(output)],
            check=True, cwd=tmp_path, timeout=30,
        )
        fixture.validate_csv(output / "ranking.csv", 1)
        validate_png(output / "ranking.png")
    assert {path.name for path in output.iterdir()} == {"ranking.csv", "ranking.png"}
