"""Consumers read the ratified rating (AC-96, AC-97), and nothing writes into the rule-book data (AC-71)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arp.cli.transition_barrier import transition_barrier_app
from arp.config import get_settings
from arp.decision import sources
from arp.transition_barrier import dataset
from tests import test_tb_derivation, test_tb_facts, test_tb_ratings
from tests.test_tb_derivation import decide, env  # noqa: F401  (env is a fixture)
from tests.test_tb_ratings import KEY, client, ratify_change  # noqa: F401  (client is a fixture)
from tests.test_transition_barrier_rule_book import REPO, _node_with
from tests.transition_barrier_helpers import A_APPROVER

pytestmark = pytest.mark.usefixtures("pg")


def eu_feasibility() -> str:
    """The one pillar value of the STL-R1 European Union row in Decision Studio (50.0 is M, 100.0 is H)."""
    ds = sources.from_transition_barrier()
    [row] = [r for r in ds.rows if r["Assessment"] == "Steel - European Union"]
    [value] = [row[c] for c in ds.columns if c.endswith("_Feasibility_0_100") and row[c]]
    return value


def test_ac97_decision_studio_sees_the_confirmation(client):  # noqa: F811
    run_id = ratify_change(client)
    assert eu_feasibility() == "100.0"  # hand-rated H until the approver confirms
    decide(client, A_APPROVER, run_id, KEY)
    assert eu_feasibility() == "50.0"  # M, in the same process


def test_ac96_export_carries_the_ratified_rating(client, tmp_path, monkeypatch):  # noqa: F811
    decide(client, A_APPROVER, ratify_change(client), KEY)
    # the report script needs the full 35-criterion book, so export from the bundled data; the ratified M is in the database
    monkeypatch.delenv("ARP_TRANSITION_BARRIER_DATA_DIR")
    get_settings.cache_clear()
    dataset.reset_caches()
    out = tmp_path / "export.json"
    result = CliRunner().invoke(transition_barrier_app, ["export", "--out", str(out)])
    assert result.exit_code == 0, result.output
    export = json.loads(out.read_text(encoding="utf-8"))
    ratings = {(s["code"], s["region"]): s["rating"] for s in export["scores"]}
    assert ratings[("STL-R1", "European Union")] == "M"

    reason = _node_with("docx", "adm-zip")
    if reason:
        pytest.skip(f"{reason}; the export half of AC-96 ran")
    docx = tmp_path / "report.docx"
    run = subprocess.run(
        ["node", str(REPO / "scripts" / "build_transition_barrier_report.js"), str(docx), str(out)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stderr
    import re
    import zipfile

    xml = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
    shown = re.findall(r">([HML])  \((?:high|medium|low)\)<", xml)
    regions = ("European Union", "United States", "China")
    assert shown == [ratings[(c["code"], r)] for c in export["criteria"] for r in regions]
    codes = [c["code"] for c in export["criteria"]]
    assert shown[codes.index("STL-R1") * len(regions)] == "M"


def snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize(
    "flow",
    [
        test_tb_facts.test_ac49,
        test_tb_derivation.test_ac51_ac53_ac139_choice,
        test_tb_ratings.test_ac56_to_ac59_ratified_cell_on_scores,
        test_tb_ratings.test_ac63_rejected_change_leaves_hand_rating,
        test_tb_ratings.test_ac65_bulk_accept_ratifies_each_cell,
    ],
    ids=["ac49", "ac51", "ac57", "ac63", "ac65"],
)
def test_ac71_flows_leave_the_data_files_untouched(flow, client, env):  # noqa: F811
    before = snapshot(env[1])
    flow(client)
    assert snapshot(env[1]) == before


def test_current_scores_without_postgres(monkeypatch):
    monkeypatch.delenv("ARP_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("ARP_TRANSITION_BARRIER_DATA_DIR", raising=False)
    get_settings.cache_clear()
    dataset.reset_caches()
    try:
        assert not get_settings().postgres_dsn
        assert len(dataset.current_scores()) == 105
    finally:
        get_settings.cache_clear()
        dataset.reset_caches()
