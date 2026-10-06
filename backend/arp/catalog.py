"""The output catalog: every stored output one function produces and another can consume, in one shape, with what
uses it. Read-only and stateless: it reads the existing stores and the input links consumers already record; nothing
new is stored.

Kinds: universe (saved company lists), run, publication (Decision Studio), taxonomy, calibration (Index Construction).
"Used by" comes from: a run's universe_path / taxonomy_id (params or inputs.json), a Decision Studio dataset's source
run, an index review's publications and calibration, and a report's run and decision refs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from arp.storage.decision_store import DecisionStore
from arp.storage.index_store import IndexStore
from arp.storage.reporting_store import ReportingStore
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore

KINDS = ("universe", "run", "publication", "taxonomy", "calibration")


def _path_key(p: str) -> str:
    return str(Path(p).resolve())


def universes(runs_dir: Path) -> list[dict]:
    out = []
    for f in sorted((runs_dir / "_universes").glob("*.json")):
        stem, _, epoch = f.stem.rpartition("_")
        try:
            count = len(json.loads(f.read_text()))
        except (ValueError, OSError):
            continue  # not a universe file
        when = datetime.fromtimestamp(int(epoch), UTC).isoformat() if epoch.isdigit() else None
        out.append({"kind": "universe", "id": _path_key(str(f)), "name": f"{(stem if epoch.isdigit() else f.stem).replace('_', ' ')} ({count} companies)",
                    "version": None, "as_of": when, "status": "saved", "by": None, "count": count})
    return out


def runs(manifests: list) -> list[dict]:
    return [{
        "kind": "run", "id": m.run_id, "version": None, "as_of": m.created_at, "status": m.status.value,
        "name": f"{m.run_type.replace('_', ' ')} · {m.params.get('theme_name') or m.run_id}", "run_type": m.run_type,
        "by": m.params.get("triggered_by"),
    } for m in manifests]


def publications(decisions: DecisionStore) -> list[dict]:
    return [{
        "kind": "publication", "id": p.snapshot_id, "version": p.framework_version, "as_of": p.as_of or p.published_at,
        "status": "published", "name": f"{p.framework_name} v{p.framework_version} · {p.dataset_name}", "by": p.published_by,
    } for p in decisions.list_published()]


def taxonomies(store: TaxonomyStore) -> list[dict]:
    return [{
        "kind": "taxonomy", "id": t.taxonomy_id, "version": t.version, "as_of": t.ratified_at or t.created_at,
        "status": str(getattr(t.status, "value", t.status)), "name": t.name, "by": t.ratified_by,
    } for t in store.list_all()]


def calibrations(store: IndexStore) -> list[dict]:
    return [{
        "kind": "calibration", "id": c.calibration_id, "version": c.version, "as_of": c.effective_from,
        "status": "approved" if c.is_approved else "draft", "name": c.name, "by": c.created_by,
    } for c in store.list_calibrations()]


def used_by(manifests: list, run_store: RunStore, decisions: DecisionStore, index: IndexStore, reports: ReportingStore) -> dict[tuple[str, str], list[dict]]:
    """(input kind, input id) -> the consumers that recorded reading it."""
    links: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for m in manifests:
        consumer = {"kind": "run", "id": m.run_id, "label": f"{m.run_type.replace('_', ' ')} run {m.run_id}"}
        inputs_file = run_store.run_dir(m.run_id) / "inputs.json"
        recorded = {**m.params, **(json.loads(inputs_file.read_text()) if inputs_file.exists() else {})}
        if recorded.get("universe_path"):
            links[("universe", _path_key(recorded["universe_path"]))].append(consumer)
        if recorded.get("taxonomy_id"):
            links[("taxonomy", recorded["taxonomy_id"])].append({**consumer, "version": recorded.get("taxonomy_version")})
    for d in decisions.list_datasets():
        if d.source_ref:
            links[("run", d.source_ref)].append({"kind": "dataset", "id": d.dataset_id, "label": f"Decision Studio table {d.name}"})
    for index_id in index.list_indices():
        for day in index.list_review_dates(index_id):
            r = index.get_review(index_id, day)
            if r is None:
                continue
            consumer = {"kind": "index_review", "id": f"{index_id}:{day}", "label": f"index {index_id} review {day}"}
            for snap in r.decision_snapshot_ids:
                links[("publication", snap)].append(consumer)
            if r.calibration_id:
                links[("calibration", r.calibration_id)].append(consumer)
    for rep in reports.list_reports():
        req = reports.load_request(rep.report_id)
        for ref in (req.run_refs if req else []):
            kind = "publication" if ref.kind == "decision" else "run"
            links[(kind, ref.ref_id)].append({"kind": "report", "id": rep.report_id, "label": f"report {rep.title or rep.report_id}"})
    return links


def catalog(*, runs_dir: Path, run_store: RunStore, decisions: DecisionStore, taxonomy: TaxonomyStore, index: IndexStore,
            reports: ReportingStore, kind: str | None = None) -> list[dict]:
    """Every output (or one kind), newest first, each with `used_by`."""
    manifests = run_store.list_runs()
    sources = {
        "universe": lambda: universes(runs_dir), "run": lambda: runs(manifests), "publication": lambda: publications(decisions),
        "taxonomy": lambda: taxonomies(taxonomy), "calibration": lambda: calibrations(index),
    }
    items = [i for k, load in sources.items() if kind in (None, k) for i in load()]
    links = used_by(manifests, run_store, decisions, index, reports)
    return sorted(({**i, "used_by": links.get((i["kind"], i["id"]), [])} for i in items), key=lambda i: i["as_of"] or "", reverse=True)
