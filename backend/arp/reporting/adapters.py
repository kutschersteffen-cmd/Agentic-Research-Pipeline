"""Pipeline adapters: published decisions and run results as report datasets.

Portfolio/climate analytics are computed on request and have no stored result to read, so they have no
adapter; add one that calls the aggregation engine when a periodic portfolio deck needs it.
"""

from __future__ import annotations

from arp.config import Settings, get_settings
from arp.reporting.datasets import _build_dataset
from arp.schemas.reporting import QuantitativeDataset, ReportRequest, RunRef
from arp.storage.decision_store import DecisionStore
from arp.storage.run_store import RunStore

_SCALAR = (str, int, float, bool, type(None))


def _table(name: str, rows: list[dict]) -> QuantitativeDataset:
    header = list(dict.fromkeys(k for r in rows for k, v in r.items() if isinstance(v, _SCALAR)))
    return _build_dataset(name, header, [[r.get(h) for h in header] for r in rows])


def _load(ref: RunRef, settings: Settings) -> QuantitativeDataset:
    if ref.kind == "decision":
        pub = DecisionStore(settings.frameworks_dir).get_published(ref.ref_id)
        if pub is None:
            raise ValueError(f"unknown decision {ref.ref_id}")
        ds = _table(pub.framework_name, [r.model_dump(mode="json") for r in pub.rows])
        ds.description = f"Published decision {pub.snapshot_id}, as of {pub.as_of or pub.published_at}."
    else:
        runs = RunStore(settings.runs_dir)
        manifest = runs.load_manifest(ref.ref_id)
        if manifest is None:
            raise ValueError(f"unknown run {ref.ref_id}")
        ds = _table(manifest.run_type, runs.read_results(ref.ref_id))
        ds.description = f"Results of {manifest.run_type} run {ref.ref_id}."
    ds.dataset_id = f"{ref.kind}_{ref.ref_id}"  # stable, so a re-run replaces it instead of adding a copy
    return ds


def load_run_datasets(refs: list[RunRef], settings: Settings) -> list[QuantitativeDataset]:
    return [_load(r, settings) for r in refs]


def with_run_datasets(request: ReportRequest, settings: Settings | None = None, only_missing: bool = False) -> ReportRequest:
    """`request` with its run_refs' datasets freshly loaded, replacing any earlier copy of them.
    `only_missing` returns `request` as is when it already holds every one of them."""
    have = {d.dataset_id for d in request.datasets}
    if not request.run_refs or only_missing and all(f"{r.kind}_{r.ref_id}" in have for r in request.run_refs):
        return request
    fresh = load_run_datasets(request.run_refs, settings or get_settings())
    ids = {d.dataset_id for d in fresh}
    return request.model_copy(update={"datasets": [d for d in request.datasets if d.dataset_id not in ids] + fresh})
