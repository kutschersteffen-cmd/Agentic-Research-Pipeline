"""Theme dossiers: one record per theme that links its candidate, taxonomy and theme runs.

One JSON file per dossier under `runs_dir/_dossiers/`, like the Argus draft flows. A dossier stores only links
and decisions; every step state is derived on read from the records it links to."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends
from pydantic import BaseModel

from arp.api.deps import settings_dep
from arp.api.review_endpoints import get_review_queue
from arp.config import Settings
from arp.emerging_themes.pipeline import load_candidates_with_status
from arp.schemas.common import CompanyRef, JobStatus, RunManifest, now_iso
from arp.schemas.emerging_themes import CandidateStatus, ContextBrief
from arp.schemas.taxonomy import TaxonomyStatus
from arp.storage.atomic_io import atomic_write_text, read_text_utf8
from arp.storage.locks import KeyedLock
from arp.storage.run_store import RunStore
from arp.storage.safe_path import UnsafeIdentifierError, safe_id
from arp.storage.taxonomy_store import TaxonomyStore
from arp.themes.position import PositionStore, step5
from arp.themes.research import ResearchRecord

logger = logging.getLogger(__name__)

StepState = Literal["done", "waiting", "running", "failed", "not_started", "skipped", "not_built"]
STEP_TITLES = ("Spot", "Define", "Research", "Find companies", "Position and standards")


class Dossier(BaseModel):
    dossier_id: str
    name: str
    created_by: str
    created_at: str
    origin: Literal["candidate", "topic"]
    run_id: str | None = None  # the Emerging Themes run, origin `candidate` only
    theme_id: str | None = None
    taxonomy_id: str | None = None
    status: Literal["active", "shelved"] = "active"
    shelved_by: str | None = None
    shelved_at: str | None = None
    shelve_reason: str | None = None


class DossierStep(BaseModel):
    number: int
    title: str
    state: StepState
    detail: str
    href: str | None


class TaxonomyTaken(Exception):
    def __init__(self, taxonomy_id: str, dossier_id: str) -> None:
        super().__init__(f"taxonomy '{taxonomy_id}' already belongs to dossier '{dossier_id}'")


class DossierStore:
    def __init__(self, dossiers_dir: Path) -> None:
        self.dossiers_dir = dossiers_dir
        self._lock = KeyedLock(lambda key: dossiers_dir / f".{key}.lock")

    def _path(self, dossier_id: str) -> Path | None:
        try:
            return self.dossiers_dir / f"{safe_id(dossier_id, label='dossier id')}.json"
        except UnsafeIdentifierError:
            return None

    def get(self, dossier_id: str) -> Dossier | None:
        path = self._path(dossier_id)
        return Dossier.model_validate_json(read_text_utf8(path)) if path and path.is_file() else None

    def _save(self, dossier: Dossier) -> Dossier:
        self.dossiers_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path(dossier.dossier_id), dossier.model_dump_json(indent=2))
        return dossier

    def list(self) -> list[Dossier]:
        """Newest `created_at` first, ties by `dossier_id`."""
        if not self.dossiers_dir.is_dir():
            return []
        dossiers = []
        for p in self.dossiers_dir.glob("*.json"):
            try:
                dossiers.append(Dossier.model_validate_json(read_text_utf8(p)))
            except (OSError, ValueError):  # one unreadable file must not hide every other dossier
                logger.warning("unreadable dossier file %s", p.name)
        dossiers.sort(key=lambda d: d.dossier_id)
        return sorted(dossiers, key=lambda d: d.created_at, reverse=True)

    def owner_of(self, taxonomy_id: str) -> Dossier | None:
        return next((d for d in self.list() if d.taxonomy_id == taxonomy_id), None)

    def create(self, name: str, created_by: str, *, taxonomy_id: str | None = None, run_id: str | None = None,
               theme_id: str | None = None) -> Dossier:
        """Raises TaxonomyTaken when another dossier already has `taxonomy_id`."""
        dossier = Dossier(
            dossier_id=f"dos_{uuid4().hex[:12]}", name=name, created_by=created_by, created_at=now_iso(),
            origin="candidate" if run_id else "topic", run_id=run_id, theme_id=theme_id, taxonomy_id=taxonomy_id,
        )
        self.dossiers_dir.mkdir(parents=True, exist_ok=True)
        with self._lock.acquire("taxonomies"):  # one taxonomy, one dossier: check and write under one lock
            if taxonomy_id and (owner := self.owner_of(taxonomy_id)):
                raise TaxonomyTaken(taxonomy_id, owner.dossier_id)
            return self._save(dossier)

    def attach(self, dossier_id: str, taxonomy_id: str) -> Dossier | None:
        """None for an unknown dossier; TaxonomyTaken when this or another dossier holds a different link."""
        self.dossiers_dir.mkdir(parents=True, exist_ok=True)
        with self._lock.acquire("taxonomies"):
            dossier = self.get(dossier_id)
            if dossier is None or dossier.taxonomy_id == taxonomy_id:
                return dossier
            if dossier.taxonomy_id:
                raise TaxonomyTaken(dossier.taxonomy_id, dossier.dossier_id)
            if owner := self.owner_of(taxonomy_id):
                raise TaxonomyTaken(taxonomy_id, owner.dossier_id)
            dossier.taxonomy_id = taxonomy_id
            return self._save(dossier)

    def shelve(self, dossier_id: str, by: str, reason: str) -> Dossier | None:
        self.dossiers_dir.mkdir(parents=True, exist_ok=True)
        with self._lock.acquire("taxonomies"):  # the same lock as attach, so neither write loses the other
            dossier = self.get(dossier_id)
            if dossier is None:
                return None
            dossier.status, dossier.shelved_by, dossier.shelved_at, dossier.shelve_reason = "shelved", by, now_iso(), reason
            return self._save(dossier)


def get_dossier_store(settings: Settings = Depends(settings_dep)) -> DossierStore:
    return DossierStore(settings.runs_dir / "_dossiers")


def context_brief(d: Dossier, run_store: RunStore) -> ContextBrief | None:
    """The origin candidate's brief; None for a topic dossier, a missing candidate or one without a brief."""
    if d.origin == "topic":
        return None
    candidate = next((c for c in load_candidates_with_status(run_store, d.run_id) if c.theme_id == d.theme_id), None)
    return candidate.context_brief if candidate else None


def _spot(d: Dossier, run_store: RunStore) -> tuple[StepState, str, str | None]:
    if d.origin == "topic":
        return "skipped", "started from a topic", None
    href = "#/emergingThemes"
    candidate = next((c for c in load_candidates_with_status(run_store, d.run_id) if c.theme_id == d.theme_id), None)
    if candidate is None:
        return "failed", "candidate not found", href
    if candidate.status == CandidateStatus.PROMOTED:
        return "done", f"promoted: {candidate.decision_reason}", href
    if candidate.status in (CandidateStatus.REJECTED, CandidateStatus.DISCONFIRMED):
        return "failed", f"{candidate.status.value}: {candidate.decision_reason}", href
    return "waiting", "awaiting decision", href


def _newest_theme_run(d: Dossier, theme_runs: list[RunManifest]) -> RunManifest | None:
    runs = [m for m in theme_runs if d.taxonomy_id and m.params.get("taxonomy_id") == d.taxonomy_id]
    return max(runs, key=lambda m: m.created_at) if runs else None


def _find_companies(d: Dossier, run_store: RunStore, theme_runs: list[RunManifest], latest_ratified: int | None) -> tuple[StepState, str, str]:
    run = _newest_theme_run(d, theme_runs)
    if run is None:
        return "not_started", "no run yet", "#/theme"
    href = f"#/theme/{run.run_id}"
    if run.status in (JobStatus.PENDING, JobStatus.RUNNING):
        return "running", "run in progress", href
    if run.status in (JobStatus.FAILED, JobStatus.CANCELLED):
        return "failed", f"last run {run.status.value}", href
    pending = [r for r in get_review_queue(run_store, run.run_id)["pending"] if not r["item_key"].startswith("isic:")]
    version = run.params.get("taxonomy_version")
    if pending:
        state, detail = "waiting", f"{len(pending)} to review"
    else:
        companies = sum(1 for row in run_store.read_results(run.run_id) if row.get("company_matches"))
        state, detail = "done", f"{companies} companies, taxonomy v{version}"
    if latest_ratified is not None and version is not None and version < latest_ratified:
        state, detail = "waiting", f"{detail} · older than v{latest_ratified}"
    return state, detail, href


def _research(d: Dossier, record: ResearchRecord, latest_ratified: int | None) -> tuple[StepState, str, str | None]:
    if latest_ratified is None:
        return "not_started", "ratify a taxonomy first", None
    href, r = f"#/themes/{d.dossier_id}/research", record.latest
    note = r.note if r else None
    if r is None:
        return "not_started", "propose sources", href
    if r.plan_status == "proposing":
        return "running", "proposing sources", href
    if r.plan_status == "proposal_failed":
        return "failed", "source proposal failed", href
    if r.plan_status == "proposed":
        if note and note.status == "rejected":
            return "waiting", f"note rejected: {note.reject_reason}", href
        return "waiting", f"approve {len(r.sources)} sources" if r.sources else "add sources", href
    if note is None or note.status == "rejected":
        return "waiting", "write the note", href
    if note.status == "writing":
        return "running", "writing note", href
    if note.status == "write_failed":
        return "failed", f"note failed: {note.error}", href
    if note.status == "written":
        return "waiting", "approve the note", href
    detail = f"note r{r.round} approved by {note.approved_by}"
    if latest_ratified > r.taxonomy_version:
        return "waiting", f"{detail} · older than v{latest_ratified}", href
    return "done", detail, href


def _latest_ratified(d: Dossier, taxonomy_store: TaxonomyStore) -> int | None:
    ratified = [t for t in taxonomy_store.list_versions(d.taxonomy_id) if t.status == TaxonomyStatus.RATIFIED] if d.taxonomy_id else []
    return ratified[-1].version if ratified else None


def exposed_companies(d: Dossier, run_store: RunStore, taxonomy_store: TaxonomyStore) -> list[CompanyRef] | None:
    """The companies with at least one match in the newest theme run, in run order; None while step 4 is not done."""
    theme_runs = run_store.list_runs("theme")
    if _find_companies(d, run_store, theme_runs, _latest_ratified(d, taxonomy_store))[0] != "done":
        return None
    run = _newest_theme_run(d, theme_runs)
    refs = {c.company_id: c for c in run_store.load_companies(run.run_id) or []}
    exposed = []
    for row in run_store.read_results(run.run_id):
        if matches := row.get("company_matches"):
            key = row.get("_key") or matches[0].get("company_id")
            exposed.append(refs.get(key) or CompanyRef(company_id=key, name=matches[0].get("name") or key))
    return exposed


def derive_steps(d: Dossier, run_store: RunStore, taxonomy_store: TaxonomyStore, research: ResearchRecord,
                 theme_runs: list[RunManifest] | None = None, *, positions: PositionStore, streams_root: Path) -> list[DossierStep]:
    """The five steps, read fresh from the stores. Pass `theme_runs` to share one run listing across dossiers."""
    latest_ratified = None
    if not d.taxonomy_id:
        define: tuple[StepState, str, str | None] = ("not_started", "choose a taxonomy", None)
    else:
        versions = taxonomy_store.list_versions(d.taxonomy_id)
        ratified = [t for t in versions if t.status == TaxonomyStatus.RATIFIED]
        if not versions:
            define = ("failed", "taxonomy not found", "#/taxonomy")
        elif not ratified:
            define = ("waiting", "ratify a version", "#/taxonomy")
        else:
            latest = ratified[-1]
            latest_ratified = latest.version
            define = ("done", f"v{latest.version} ratified by {latest.ratified_by}", "#/taxonomy")
    if theme_runs is None:
        theme_runs = run_store.list_runs("theme")
    states = [
        _spot(d, run_store),
        define,
        _research(d, research, latest_ratified),
        _find_companies(d, run_store, theme_runs, latest_ratified),
        step5(d.dossier_id, research, positions, streams_root, run_store),
    ]
    return [DossierStep(number=i + 1, title=STEP_TITLES[i], state=s, detail=detail, href=href)
            for i, (s, detail, href) in enumerate(states)]


def current_step(steps: list[DossierStep]) -> int | None:
    return next((s.number for s in steps if s.state not in ("done", "skipped", "not_built")), None)
