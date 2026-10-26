"""Theme position and standards (dossier step 5): a house position drafted from the approved research note, then
stewardship standards drafted from the approved position, checked against reviewed company facts
(docs/superpowers/specs/2026-10-25-theme-position-standards-design.md).

Positions live under `runs_dir/_positions/<dossier_id>/`: one immutable `v<n>.json` per version, an append-only
`approvals.jsonl`, and the latest standards check in `latest_check.json`. Standards are the dossier's own
`theme_standards` policy (`PolicyStore(streams_root / "themes" / <dossier_id>, theme=True)`)."""

from __future__ import annotations

import json
import operator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select

from arp.api.deps import settings_dep
from arp.api.review_endpoints import get_review_queue
from arp.config import Settings
from arp.db import models as m
from arp.db.session import transaction
from arp.schemas.common import CompanyRef, JobStatus, RunManifest, now_iso
from arp.schemas.datapoints import DataPointSchema, FieldDefinition, FieldStatus
from arp.stewardship.policies import PolicyStore
from arp.storage.atomic_io import atomic_write_text, read_text_utf8
from arp.storage.jsonl_io import append_jsonl
from arp.storage.locks import KeyedLock
from arp.storage.run_store import RunStore
from arp.storage.safe_path import safe_id
from arp.themes.research import ResearchRecord

POLICY = "theme_standards"
VersionPath = Literal["model_draft", "owner_edit"]


# The model's outputs. Their class names are the stand-in contract (model/<ClassName>.json): keep them.
class PositionParagraph(BaseModel):
    text: str
    cites: list[str]


class PositionDraft(BaseModel):
    summary: str
    paragraphs: list[PositionParagraph]


class Standard(BaseModel):
    standard_id: str
    title: str
    expectation: str
    definition: str
    where_reported: str
    rests_on: list[int]
    severity: Literal["low", "medium", "high"]
    field_id: str
    operator: Literal[">=", "<=", ">", "<", "=="]
    value: bool | int | float | str
    data: Literal["existing", "new"]


class StandardsDraft(BaseModel):
    standards: list[Standard]
    new_fields: list[FieldDefinition] = []


class PositionVersion(PositionDraft):
    version: int
    dossier_id: str
    note_version: int
    created_by: str
    created_at: str
    path: VersionPath
    instructions: str | None = None


class PositionApproval(BaseModel):
    version: int
    approved_by: str
    approved_at: str


class NoteItem(BaseModel):
    item_id: str
    kind: Literal["risk", "opportunity"]
    title: str
    summary: str


def note_items(research: ResearchRecord) -> list[NoteItem]:
    """The approved note's risks and opportunities; empty when no note is approved."""
    r = next((r for r in research.rounds if r.round == research.approved_round), None)
    if r is None or r.note is None:
        return []
    return [NoteItem(item_id=i.item_id, kind=kind, title=i.title, summary=i.text)
            for kind, items in (("risk", r.note.sections.risks), ("opportunity", r.note.sections.opportunities))
            for i in items]


def position_problem(paragraphs: list[PositionParagraph], item_ids: list[str]) -> str | None:
    if not paragraphs:
        return "no paragraphs"
    for n, p in enumerate(paragraphs, 1):
        if not p.text.strip():
            return f"paragraph {n} is blank"
    for n, p in enumerate(paragraphs, 1):
        if not p.cites:
            return f"paragraph {n} cites nothing"
    cited = [c for p in paragraphs for c in p.cites]
    for c in cited:
        if c not in item_ids:
            return f"unknown item '{c}'"
    for i in item_ids:
        if i not in cited:
            return f"item '{i}' not cited"
    return None


class PositionStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = KeyedLock(lambda key: root / f".{key}.lock")

    def _dir(self, dossier_id: str) -> Path:
        return self.root / safe_id(dossier_id, label="dossier id")

    def versions(self, dossier_id: str) -> list[PositionVersion]:
        d = self._dir(dossier_id)
        paths = sorted(d.glob("v*.json"), key=lambda p: int(p.stem[1:])) if d.is_dir() else []
        return [PositionVersion.model_validate_json(read_text_utf8(p)) for p in paths]

    def approvals(self, dossier_id: str) -> list[PositionApproval]:
        path = self._dir(dossier_id) / "approvals.jsonl"
        rows = path.read_text().splitlines() if path.exists() else []
        return [PositionApproval.model_validate_json(line) for line in rows if line.strip()]

    def approved(self, dossier_id: str) -> PositionVersion | None:
        log = self.approvals(dossier_id)
        return next((v for v in self.versions(dossier_id) if v.version == log[-1].version), None) if log else None

    def add(self, dossier_id: str, draft: PositionDraft, *, note_version: int, created_by: str, path: VersionPath,
            instructions: str | None) -> PositionVersion:
        key = safe_id(dossier_id, label="dossier id")
        self._dir(dossier_id).mkdir(parents=True, exist_ok=True)
        with self._lock.acquire(key):
            v = PositionVersion(**draft.model_dump(), version=len(self.versions(dossier_id)) + 1, dossier_id=dossier_id,
                                note_version=note_version, created_by=created_by, created_at=now_iso(), path=path,
                                instructions=instructions)
            atomic_write_text(self._dir(dossier_id) / f"v{v.version}.json", v.model_dump_json(indent=2))
            return v

    def approve(self, dossier_id: str, version: int, by: str) -> PositionApproval:
        row = PositionApproval(version=version, approved_by=by, approved_at=now_iso())
        append_jsonl(self._dir(dossier_id) / "approvals.jsonl", row.model_dump())
        return row

    def latest_check(self, dossier_id: str) -> dict | None:
        path = self._dir(dossier_id) / "latest_check.json"
        return json.loads(read_text_utf8(path)) if path.is_file() else None

    def save_check(self, dossier_id: str, check: dict) -> None:
        self._dir(dossier_id).mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._dir(dossier_id) / "latest_check.json", json.dumps(check, indent=2))


def get_position_store(settings: Settings = Depends(settings_dep)) -> PositionStore:
    return PositionStore(settings.runs_dir / "_positions")


def standards_store(streams_root: Path, dossier_id: str) -> PolicyStore:
    return PolicyStore(streams_root / "themes" / safe_id(dossier_id, label="dossier id"), theme=True)


def schema_id_for(dossier_id: str) -> str:
    return f"theme_std_{dossier_id.removeprefix('dos_')}"


def released_theme_fields(registry, schema_id: str) -> list[FieldDefinition]:
    """The fields of the newest released version of the theme schema; empty before the first release."""
    released = [r["version"] for r in registry.list_index() if r["schema_id"] == schema_id and r["release_flag"]]
    return registry.get(schema_id, max(released)).fields if released else []


def build_standards_content(draft: StandardsDraft, *, dossier_id: str, dossier_name: str, position_version: int,
                            path: VersionPath, carried: list[FieldDefinition]) -> dict:
    """A version's content: the standards plus the theme schema (released theme fields, then the new ones)."""
    new = [f.model_copy(update={"status": FieldStatus.DRAFT}) for f in draft.new_fields]
    schema = None
    if carried or new:
        schema = DataPointSchema(schema_id=schema_id_for(dossier_id), name=f"{dossier_name} standards",
                                 description=f"Data points for the stewardship standards of {dossier_name}",
                                 fields=[*carried, *new]).model_dump(mode="json")
    return {"policy_id": POLICY, "dossier_id": dossier_id, "position_version": position_version, "path": path,
            "standards": [s.model_dump() for s in draft.standards], "schema": schema}


def standards_view(store: PolicyStore) -> dict:
    versions = [{**store.content(POLICY, v["version"]), **v} for v in store.versions(POLICY)]
    active = store.active_version(POLICY)
    return {"versions": versions, "activations": store.activations(POLICY), "active_version": active,
            "active": store.content(POLICY, active)}


# --- the check ---

_OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt, "==": operator.eq}
_COUNTED = (m.FactStatus.AUTO_ACCEPTED, m.FactStatus.APPROVED, m.FactStatus.EDITED)


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def current_facts(dsn: str | None, entity_ids: list, field_ids: list[str]) -> dict[tuple[str, str], tuple[Any, date | None, str]]:
    """(entity_id, field_id) -> (value, period_end, value_state) of the counting current fact: reviewed status, the
    latest period_end (a null one counts as the only period), then the most recently recorded."""
    if not entity_ids or not field_ids:
        return {}
    with transaction(dsn) as s:
        rows = s.execute(
            select(m.CompanyFact, m.FieldObservation.value_state)
            .join(m.FieldObservation, m.FieldObservation.id == m.CompanyFact.observation_id)
            .where(m.CompanyFact.company_id.in_(entity_ids), m.CompanyFact.field_id.in_(field_ids),
                   m.CompanyFact.valid_to.is_(None), m.CompanyFact.status.in_(_COUNTED))
        ).all()
        best: dict[tuple[str, str], tuple] = {}
        for fact, state in rows:
            key = (str(fact.company_id), fact.field_id)
            rank = (fact.period_end or date.min, fact.valid_from, fact.id)
            value = fact.canonical_value if fact.canonical_value is not None else fact.value
            if key not in best or rank > best[key][0]:
                best[key] = (rank, (_plain(value), fact.period_end, str(state)))
    return {k: v for k, (_, v) in best.items()}


def check_standards(companies: list[CompanyRef], standards: list[dict], facts: dict) -> list[dict]:
    results = []
    for c in sorted(companies, key=lambda c: (c.name, c.company_id)):
        for s in sorted(standards, key=lambda s: int(s["standard_id"][1:])):
            value, period_end, result = None, None, "no_data"
            fact = facts.get((str(c.entity_id), s["field_id"])) if c.entity_id else None
            if fact and fact[2] not in ("not_found", "not_applicable"):
                value, period_end = (0 if fact[2] == "zero" else fact[0]), fact[1]
                try:
                    result = "met" if _OPS[s["operator"]](value, s["value"]) else "unmet"
                except TypeError:  # a stored value of the wrong type is no data, never a flag
                    value, result = None, "no_data"
            results.append({"company_id": c.company_id, "name": c.name, "standard_id": s["standard_id"], "value": value,
                            "period_end": period_end.isoformat() if period_end else None, "result": result})
    return results


def standards_triggers(results: list[dict], standards: list[dict], companies: list[CompanyRef], *, dossier_id: str,
                       theme: str) -> list[dict]:
    by_id, sectors = {s["standard_id"]: s for s in standards}, {c.company_id: c.sector for c in companies}
    return [
        {"issuer_id": r["company_id"], "company": r["name"], "sector": sectors.get(r["company_id"]) or "unknown",
         "type": "theme_standard", "theme": theme, "severity": by_id[r["standard_id"]]["severity"],
         "rule": f"std:{dossier_id}:{r['standard_id']}",
         "reason": f"{by_id[r['standard_id']]['title']}: {json.dumps(r['value'])}, expected "
                   f"{by_id[r['standard_id']]['operator']} {json.dumps(by_id[r['standard_id']]['value'])}"}
        for r in results if r["result"] == "unmet"
    ]


# --- dossier step 5 ---

def newest_extraction_run(run_store: RunStore, schema_id: str) -> RunManifest | None:
    return next((r for r in run_store.extraction_runs() if r.params.get("schema_id") == schema_id), None)


def step5(dossier_id: str, research: ResearchRecord, positions: PositionStore, streams_root: Path,
          run_store: RunStore) -> tuple[str, str, str]:
    href = f"#/themes/{dossier_id}/position"
    note = research.approved_round
    if note is None:
        return "not_started", "research note not approved", href
    versions = positions.versions(dossier_id)
    if not versions:
        return "not_started", "draft the position", href
    approved = positions.approved(dossier_id)
    if approved is None or approved.version != versions[-1].version:
        return "waiting", f"approve position v{versions[-1].version}", href
    if approved.note_version < note:
        return "waiting", f"position rests on note v{approved.note_version}, v{note} approved", href
    store = standards_store(streams_root, dossier_id)
    latest = max(v["version"] for v in store.versions(POLICY))
    if latest == 0:
        return "not_started", "draft standards", href
    active_version = store.active_version(POLICY)
    if latest > active_version:
        return "waiting", f"approve standards v{latest}", href
    active = store.content(POLICY, active_version)
    if active["position_version"] != approved.version:
        return "waiting", f"standards rest on position v{active['position_version']}, v{approved.version} approved", href
    since = store.activations(POLICY)[-1]["approved_at"]
    if active.get("schema") and (run := newest_extraction_run(run_store, active["schema"]["schema_id"])):
        if run.status in (JobStatus.PENDING, JobStatus.RUNNING):
            return "running", f"extracting {len(active['schema']['fields'])} data points", href
        if run.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            return "failed", f"extraction {run.status.value}", href
        open_items = get_review_queue(run_store, run.run_id)["pending"]
        if open_items:
            return "waiting", f"{len(open_items)} to review", href
        since = max(since, run.updated_at)
    check = positions.latest_check(dossier_id)
    if check is None or check["checked_at"] < since:
        return "waiting", "check companies", href
    return "done", f"{len(active['standards'])} standards · {check['flagged']} flagged", href
