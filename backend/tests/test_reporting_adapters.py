import json

import pytest

from arp.config import Settings
from arp.reporting.adapters import load_run_datasets
from arp.schemas.common import RunManifest
from arp.schemas.decision import PublishedDecision, PublishedRow
from arp.schemas.reporting import ColumnKind, RunRef
from arp.storage.decision_store import DecisionStore
from arp.storage.run_store import RunStore


def _settings(tmp_path) -> Settings:
    return Settings(runs_dir=tmp_path / "runs", frameworks_dir=tmp_path / "frameworks", reports_dir=tmp_path / "reports")


def test_decision_adapter_turns_published_rows_into_dataset(tmp_path):
    s = _settings(tmp_path)
    pub = DecisionStore(s.frameworks_dir).save_published(PublishedDecision(
        framework_id="fw", framework_version=1, framework_name="Climate tiers", dataset_id="d", dataset_name="D",
        as_of="2026-06-30", id_column="id", published_by="A",
        rows=[PublishedRow(entity_id="e1", name="Acme", score=72.5, tier=1), PublishedRow(entity_id="e2", name="Beta", score=40.0, tier=2)],
    ))
    [ds] = load_run_datasets([RunRef(kind="decision", ref_id=pub.snapshot_id)], s)
    assert ds.name == "Climate tiers" and "2026-06-30" in ds.description
    assert [r["score"] for r in ds.rows] == [72.5, 40.0]
    kinds = {c.name: c.kind for c in ds.columns}
    assert kinds["score"] == ColumnKind.NUMBER and kinds["name"] == ColumnKind.CATEGORY


def test_run_adapter_flattens_results_jsonl(tmp_path):
    s = _settings(tmp_path)
    runs = RunStore(s.runs_dir)
    runs.save_manifest(RunManifest(run_id="run_1", run_type="theme"))
    runs.results_path("run_1").write_text("\n".join(json.dumps(r) for r in [
        {"company": "Acme", "revenue_share": 0.4, "evidence": [{"q": "x"}], "meta": {"a": 1}},
        {"company": "Beta", "revenue_share": 0.1, "evidence": []},
    ]) + "\n")
    [ds] = load_run_datasets([RunRef(kind="run", ref_id="run_1")], s)
    assert ds.name == "theme"
    assert ds.column_names() == ["company", "revenue_share"]  # nested fields dropped
    assert ds.rows == [{"company": "Acme", "revenue_share": 0.4}, {"company": "Beta", "revenue_share": 0.1}]


def test_unknown_ref_raises(tmp_path):
    s = _settings(tmp_path)
    with pytest.raises(ValueError, match="unknown decision pub_x"):
        load_run_datasets([RunRef(kind="decision", ref_id="pub_x")], s)
    with pytest.raises(ValueError, match="unknown run run_x"):
        load_run_datasets([RunRef(kind="run", ref_id="run_x")], s)
