"""Frameworks as portable scoring templates, and frameworks attached to runs.

A framework already applies to any table whose columns it knows (see
docs/DECISION_MECHANISM.md §2). This module adds the three things that
make it a template:

- **compatibility**: which columns a table must supply for the framework
  to mean the same thing on it, checkable against an extraction schema
  before its run has produced anything;
- **export / import** as a self-describing JSON file;
- **attachment to a run**, so any extraction pipeline's run is scored with
  a pinned framework version as its last step (`score_run`, called from
  arp.orchestration.batch_runner once every company is done).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from arp.decision import sources
from arp.decision.dataset import Dataset
from arp.decision.roles import slug
from arp.schemas.common import RunManifest, new_id, now_iso
from arp.schemas.decision import AuditEntry, MechanismConfig
from arp.storage.atomic_io import atomic_write_text
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

TEMPLATE_FORMAT = "arp.decision_template"
TEMPLATE_FORMAT_VERSION = 1

PINNED_FILE = "decision_framework.json"
RESULT_FILE = "decision.json"

# Every extraction pipeline a framework can be attached to: how its results
# become a table, and which columns it will produce before it has any
# (extraction takes the schema's field names; the others are fixed).
RUN_ADAPTERS: dict[str, tuple[Callable[[RunStore, str], Dataset], Callable[[list[str] | None], list[str]]]] = {
    "extraction": (sources.from_extraction_run, lambda fields: sources.extraction_columns(fields or [])),
    "transition_plan": (
        lambda run_store, run_id: sources.from_transition_plan_run(run_store, run_id, include_indicators=True),
        lambda _fields: sources.expected_transition_plan_columns(),
    ),
    "financials": (sources.from_financials_run, lambda _fields: list(sources.FINANCIALS_COLUMNS)),
    "tnfd": (sources.from_tnfd_run, lambda _fields: sources.tnfd_columns()),
}


def _adapter(run_type: str):
    if run_type not in RUN_ADAPTERS:
        raise ValueError(f"Scoring templates attach to {', '.join(RUN_ADAPTERS)} runs, not {run_type!r}.")
    return RUN_ADAPTERS[run_type]


def required_columns(config: MechanismConfig) -> list[str]:
    """The columns a table has to supply for this framework.

    Everything the framework names (criteria, gates, label/size/segment,
    peer cohort) counts, except columns its own rule graph calculates. Those
    are told apart by `source_columns`, the table it was derived on; a
    framework saved before that field existed has none recorded, so every
    named column counts. Source columns a rule graph reads are found by name
    in the graph, which is a text match: a column mentioned only in a note
    counts too, which errs towards reporting a gap rather than hiding one.
    """
    named = [c.column for c in config.criteria if c.enabled] + [g.column for g in config.gates]
    named += [c for c in (config.label_column, config.size_column, config.segment_column, config.normalise_within) if c]
    if config.source_columns:
        source = set(config.source_columns)
        named = [c for c in named if c in source]
        if config.rule_graph or config.tier_graph:
            graph_text = json.dumps([config.rule_graph, config.tier_graph])
            named += [c for c in config.source_columns if f'"{c}"' in graph_text or slug(c) and re.search(rf"\b{re.escape(slug(c))}\b", graph_text)]
    return list(dict.fromkeys(named))


def missing_columns(config: MechanismConfig, columns: list[str]) -> list[str]:
    present = set(columns) | {slug(c) for c in columns}
    return [c for c in required_columns(config) if c not in present]


def expected_run_columns(run_type: str, field_names: list[str] | None = None) -> list[str]:
    """What a run of this type will produce, known before it has results."""
    return _adapter(run_type)[1](field_names)


# --- export / import ---


def export_template(config: MechanismConfig, audit: list[AuditEntry]) -> dict[str, Any]:
    """A framework version as a file another installation can import. The
    audit trail goes with it: rules nobody can trace back are numbers nobody
    can defend."""
    return {
        "format": TEMPLATE_FORMAT,
        "format_version": TEMPLATE_FORMAT_VERSION,
        "exported_at": now_iso(),
        "origin": {
            "framework_id": config.framework_id,
            "version": config.version,
            "ratified": config.ratified,
            "ratified_by": config.ratified_by,
            "ratified_at": config.ratified_at,
        },
        "required_columns": required_columns(config),
        "config": json.loads(config.model_dump_json()),
        "audit": [json.loads(e.model_dump_json()) for e in audit],
    }


def import_template(payload: dict[str, Any], *, by: str | None = None) -> tuple[MechanismConfig, list[AuditEntry]]:
    """A template file -> a new framework, version 1, unratified.

    Ratification does not travel with a file: it is a sign-off inside one
    installation, and an imported copy is signed off where it is used. The
    config is validated like any inline framework (rule graphs stay
    declarative), since a file is as much a trust boundary as a request.
    """
    if payload.get("format") != TEMPLATE_FORMAT:
        raise ValueError(f"Not a scoring template: expected format {TEMPLATE_FORMAT!r}.")
    if int(payload.get("format_version") or 0) > TEMPLATE_FORMAT_VERSION:
        raise ValueError(f"Template format version {payload.get('format_version')} is newer than this installation reads.")
    imported = MechanismConfig.model_validate(payload.get("config") or {})
    config = imported.model_copy(
        update={"framework_id": new_id("fw"), "version": 1, "ratified": False, "ratified_at": None, "ratified_by": None, "created_at": now_iso()}
    )
    audit = [AuditEntry.model_validate(e) for e in payload.get("audit") or []]
    origin = payload.get("origin") or {}
    ratified = f", ratified by {origin.get('ratified_by') or 'unknown'}" if origin.get("ratified") else ""
    audit.append(
        AuditEntry(
            stage="Import",
            item=config.name,
            decision=f"imported from {origin.get('framework_id', 'unknown')} v{origin.get('version', '?')}{ratified}",
            why="ratification does not travel with a file -- this copy starts as a draft and is ratified where it is used",
            origin="human",
            by=by,
        )
    )
    return config, audit


# --- attachment to runs ---


def attach_to_run(
    run_store: RunStore, run_id: str, config: MechanismConfig, audit: list[AuditEntry] | None = None
) -> RunManifest:
    """Pins a framework version on a run. The version, not "latest": a run
    scored today must still be scored the same way after the framework is
    edited tomorrow. A copy of the framework and its audit trail is written
    into the run folder, so the rules that scored a run travel with it and
    the last step needs nothing outside the run to score it."""
    with run_store.lock(run_id):
        manifest = run_store.load_manifest(run_id)
        if manifest is None:
            raise ValueError(f"Unknown run: {run_id}")
        atomic_write_text(
            run_store.run_dir(run_id) / PINNED_FILE,
            json.dumps({"config": json.loads(config.model_dump_json()), "audit": [json.loads(e.model_dump_json()) for e in audit or []]}),
        )
        manifest.params = {
            **manifest.params,
            "decision_framework": {"framework_id": config.framework_id, "version": config.version, "name": config.name},
        }
        run_store.save_manifest(manifest)
        return manifest


def pinned_framework(run_store: RunStore, run_id: str) -> tuple[MechanismConfig, list[AuditEntry]] | None:
    path = run_store.run_dir(run_id) / PINNED_FILE
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return MechanismConfig.model_validate(payload["config"]), [AuditEntry.model_validate(e) for e in payload.get("audit") or []]


def run_dataset(run_store: RunStore, manifest: RunManifest) -> Dataset:
    return _adapter(manifest.run_type)[0](run_store, manifest.run_id)


def stored_decision(run_store: RunStore, run_id: str) -> dict[str, Any] | None:
    path = run_store.run_dir(run_id) / RESULT_FILE
    return json.loads(path.read_text()) if path.exists() else None


def score_run(run_store: RunStore, run_id: str) -> dict[str, Any] | None:
    """The rules step: scores a run's results with its pinned framework and
    stores the outcome in the run folder. Returns None when no framework is
    attached.

    Called as the last step of every extraction pipeline, and again when a
    framework is attached to a finished run or a person asks for a re-score.
    A failure is recorded on the run and in the stored outcome, never raised
    into the pipeline: the extracted results are the run's product and stay
    valid whether or not the rules could be applied to them.
    """
    from arp.decision.mechanism import apply_mechanism

    pinned = pinned_framework(run_store, run_id)
    manifest = run_store.load_manifest(run_id)
    if pinned is None or manifest is None:
        return None
    config, audit = pinned
    framework = {"framework_id": config.framework_id, "version": config.version, "name": config.name}
    try:
        dataset = run_dataset(run_store, manifest)
        outcome: dict[str, Any] = {
            "framework": framework,
            "ratified": config.ratified,
            "scored_at": now_iso(),
            "missing_columns": missing_columns(config, dataset.columns),
            "result": json.loads(apply_mechanism(dataset, config, derivation_audit=audit).model_dump_json()),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - the rules step must not fail the extraction run
        logger.exception("Scoring run %s with %s v%s failed", run_id, config.framework_id, config.version)
        outcome = {"framework": framework, "ratified": config.ratified, "scored_at": now_iso(), "missing_columns": [], "result": None, "error": str(exc)}
    atomic_write_text(run_store.run_dir(run_id) / RESULT_FILE, json.dumps(outcome))
    with run_store.lock(run_id):
        current = run_store.load_manifest(run_id)
        if current is not None:
            current.params = {
                **current.params,
                "decision_framework": {**framework, "scored_at": outcome["scored_at"], "status": "failed" if outcome["error"] else "scored"},
            }
            run_store.save_manifest(current)
    return outcome
