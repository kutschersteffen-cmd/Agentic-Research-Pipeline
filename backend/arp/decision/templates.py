"""Frameworks as portable scoring templates, and frameworks attached to runs.

A framework already applies to any table whose columns it knows (see
docs/DECISION_MECHANISM.md §2). This module adds the three things that
make it a template:

- **compatibility**: which columns a table must supply for the framework
  to mean the same thing on it, checkable against an extraction schema
  before its run has produced anything;
- **export / import** as a self-describing JSON file;
- **attachment to a run**, so an extraction or transition-plan run is
  scored with a pinned framework version as part of its workflow.
"""

from __future__ import annotations

import json
import re
from typing import Any

from arp.decision import sources
from arp.decision.dataset import Dataset
from arp.decision.roles import slug
from arp.schemas.common import RunManifest, new_id, now_iso
from arp.schemas.decision import AuditEntry, MechanismConfig
from arp.storage.run_store import RunStore

TEMPLATE_FORMAT = "arp.decision_template"
TEMPLATE_FORMAT_VERSION = 1

# Run types a framework can be attached to, and the table each one becomes.
RUN_SOURCES = {"extraction": "extraction_run", "transition_plan": "transition_plan_run"}


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
    if run_type == "extraction":
        return sources.extraction_columns(field_names or [])
    if run_type == "transition_plan":
        return sources.expected_transition_plan_columns()
    raise ValueError(f"Scoring templates attach to {', '.join(RUN_SOURCES)} runs, not {run_type!r}.")


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


def attach_to_run(run_store: RunStore, run_id: str, config: MechanismConfig) -> RunManifest:
    """Pins a framework version on a run. The version, not "latest": a run
    scored today must still be scored the same way after the framework is
    edited tomorrow."""
    with run_store.lock(run_id):
        manifest = run_store.load_manifest(run_id)
        if manifest is None:
            raise ValueError(f"Unknown run: {run_id}")
        manifest.params = {
            **manifest.params,
            "decision_framework": {"framework_id": config.framework_id, "version": config.version, "name": config.name},
        }
        run_store.save_manifest(manifest)
        return manifest


def run_dataset(run_store: RunStore, manifest: RunManifest) -> Dataset:
    if manifest.run_type == "extraction":
        return sources.from_extraction_run(run_store, manifest.run_id)
    if manifest.run_type == "transition_plan":
        return sources.from_transition_plan_run(run_store, manifest.run_id, include_indicators=True)
    raise ValueError(f"Scoring templates attach to {', '.join(RUN_SOURCES)} runs, not {manifest.run_type!r}.")
