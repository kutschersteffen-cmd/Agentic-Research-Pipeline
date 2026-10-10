"""One-time import of file-era history into Postgres (spec §6 step 8, §7) and the check that the two agree.

`import_all` order: universe files → identifier map → schema registry → documents → runs, oldest first
by `created_at` → ESG loads. Each unit (one source, one run) is one transaction, so an interrupted
import leaves whole units behind and a re-run completes the rest.

Idempotency: a run whose manifest row exists was imported in full (its manifest, companies, results,
errors, review rows, decisions and cosigns commit together), so it is skipped as a whole; the
manifest row is the import marker. Elsewhere natural keys skip what exists: companies and
identifiers by (scheme, value), schemas by (schema_id, version), documents by doc_id, ESG loads by
payload_sha (`record_load`).

Per-run side artifacts (schema.json, regrounds.jsonl, snapshots, events, restatement candidates)
stay files under `settings.runs_dir/<run_id>/`, which is where both stores read them: nothing is copied.

`verify` replays the files oldest first through the same pure rules (`to_observations`,
`observations.decide`, `review_queue.item_state`) and compares row counts and current facts."""

from __future__ import annotations

import heapq
import json
import logging
import sqlite3
import uuid
from collections import defaultdict
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from arp.config import Settings
from arp.db import models as m
from arp.db.companies import lookup, resolve, resolve_company
from arp.db.fields import SchemaRegistry
from arp.db.observations import _DECIDED, _SKIP, _edited, _fits, _same, _status, decide
from arp.db.runs import RunStore, _jsonb_safe, _ts
from arp.db.session import engine
from arp.db.to_observations import review_target, to_observations
from arp.schemas.common import CompanyRef, RunManifest
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.issuer import IdentifierMap
from arp.storage.jsonl_io import read_jsonl
from arp.storage.run_store import LegacyRunStore
from arp.universe import load_company_universe, resolve_universe

logger = logging.getLogger(__name__)

AREAS = ("companies", "identifiers", "schemas", "documents", "runs", "results", "errors", "review_items",
         "decisions", "cosigns", "esg_loads")
# run_errors rows the import itself derives (not in errors.jsonl): identity conflicts from save_companies,
# values left out of observations, citations to unregistered documents
_DERIVED_ERRORS = ("identity_conflict", "invalid_value", "unregistered_citation")
_IDENTITY_COLUMNS = ("family_id", "version", "supersedes", "published_at", "identity_confidence", "identity_review")


@dataclass
class ImportReport:
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(AREAS, 0))
    identity_conflicts: list[dict] = field(default_factory=list)
    fact_conflicts: list[dict] = field(default_factory=list)


@dataclass
class VerifyReport:
    differences: list[dict] = field(default_factory=list)


# --- legacy readers -----------------------------------------------------------------------------


def _manifests(settings: Settings) -> list[RunManifest]:
    """Oldest first by created_at (run_id breaks ties)."""
    return sorted(LegacyRunStore(settings.runs_dir).list_runs(), key=lambda r: (_ts(r.created_at), r.run_id))


def _universe(settings: Settings, manifests: list[RunManifest]) -> list[tuple[str, CompanyRef]]:
    """(source, company): the scheduled universe files, universe files runs were started from, and
    the portfolio store's companies."""
    from arp.storage.portfolio_store_factory import build_portfolio_store

    paths = [settings.discovery_schedule_universe_path, settings.emerging_themes_schedule_universe_path]
    paths += [Path(p) for r in manifests if (p := r.params.get("universe_path"))]
    out = []
    for path in dict.fromkeys(p for p in paths if p and Path(p).is_file()):
        out += [(str(path), c) for c in load_company_universe(path)]
    out += [("portfolio_store", c) for c in build_portfolio_store(settings).list_companies()]
    return out


def _schemas(root: Path) -> list[DataPointSchema]:
    index = root / "index.json"
    rows = json.loads(index.read_text(encoding="utf-8")) if index.exists() else []
    return [
        DataPointSchema.model_validate_json((root / r["schema_id"] / f"v{int(r['version'])}.json").read_text(encoding="utf-8"))
        for r in sorted(rows, key=lambda r: (r["schema_id"], int(r["version"])))
    ]


def _documents(settings: Settings, session: Session) -> list[dict]:
    """content.db `documents` rows, then the legacy Postgres `document_registry` rows (deployments that
    ran embeddings_backend=postgres); one row per doc_id, the Postgres row winning for identity columns."""
    docs: dict[str, dict] = {}
    path = settings.document_store_dir / "content.db"
    if path.exists():
        with closing(sqlite3.connect(path)) as conn:
            conn.row_factory = sqlite3.Row
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'").fetchone():
                docs = {r["doc_id"]: dict(r) for r in conn.execute("SELECT * FROM documents")}
    if inspect(session.connection()).has_table("document_registry"):
        for r in session.execute(text("SELECT * FROM document_registry")).mappings():
            if r["doc_id"] in docs:
                docs[r["doc_id"]].update({k: r[k] for k in _IDENTITY_COLUMNS})
            else:
                docs[r["doc_id"]] = dict(r)
    return list(docs.values())


def _esg_loads(settings: Settings) -> list[dict]:
    """Each successful ESG file load (portfolio governance log) with the rows it wrote: per company,
    the latest observation of every ESG field for that month as of the load."""
    from arp.portfolio.climate.esg_intake import FIELD_IDS
    from arp.storage.portfolio_store_factory import build_portfolio_store

    store = build_portfolio_store(settings)
    keys = [(c, f) for c, f in store.list_observation_keys() if f in FIELD_IDS]
    history = {k: store.load_observations(*k) for k in keys}
    loads = []
    for e in store.list_governance_events():
        if (e.get("event_type"), e.get("kind"), e.get("status")) != ("load_recorded", "esg", "ok"):
            continue
        # ponytail: observations do not record their provider; two providers loading the same month blend
        rows: dict[str, dict] = defaultdict(dict)
        for (company, fid), obs in history.items():
            hits = [o for o in obs if o.period == e["month"] and o.observed_at <= e["at"]]
            if hits:
                rows[company][fid] = hits[-1].value
        complete = [{"company_id": c, **v} for c, v in rows.items() if set(v) == set(FIELD_IDS)]
        if complete:
            loads.append({"provider": e["source_id"], "month": e["month"], "rows": complete})
    return loads


# --- import -------------------------------------------------------------------------------------


def _import_universe(s: Session, settings: Settings, manifests, report: ImportReport) -> None:
    for source, company in _universe(settings, manifests):
        r = resolve_company(s, company.model_copy(update={"entity_id": None}))
        if r.conflict:
            report.identity_conflicts.append(
                {"source": source, "company_id": company.company_id, "conflict": [str(u) for u in r.conflict]})
        report.counts["companies"] += r.created


def _import_identifier_map(s: Session, settings: Settings, report: ImportReport) -> None:
    """Current rows attach their identifiers to the company the issuer's other identifiers already
    name; a security master never creates a company."""
    today = date.today().isoformat()
    by_issuer: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in read_jsonl(settings.identifier_map_path):
        r = IdentifierMap.model_validate(row)
        if (r.valid_from is None or r.valid_from <= today) and (r.valid_to is None or today < r.valid_to):
            by_issuer[r.issuer_key].append((r.scheme, r.value))
    for issuer, ids in by_issuer.items():
        new = sum(lookup(s, scheme, value) is None for scheme, value in ids)
        res = resolve(s, ids, name=issuer, allow_create=False)
        if res.conflict:
            report.identity_conflicts.append(
                {"source": "identifier_map", "issuer_key": issuer, "conflict": [str(u) for u in res.conflict]})
        elif res.company_id is not None:
            report.counts["identifiers"] += new


def _import_schemas(s: Session, settings: Settings, report: ImportReport) -> None:
    """Every stored version keeps its number (runs name it); a released one marks its field versions released."""
    quality_path = settings.schema_registry_dir / "field_quality.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
    for schema in _schemas(settings.schema_registry_dir):
        if s.get(m.DataSchema, (schema.schema_id, schema.version)) is not None:
            continue
        SchemaRegistry._write(s, schema)
        row = s.get(m.DataSchema, (schema.schema_id, schema.version))
        row.released_at = _ts(schema.released_at) if schema.released_at else None
        for f in schema.fields:
            d = s.get(m.FieldDefinition, (f.field_id, f.version))
            if schema.release_flag and d.released_at is None:
                d.released_at = row.released_at or datetime.now(UTC)
            if d.quality is None and (q := quality.get(f"{f.field_id}:v{f.version}")):
                d.quality = q
        report.counts["schemas"] += 1
    s.flush()


def _import_documents(s: Session, settings: Settings, report: ImportReport) -> None:
    """Existing doc_ids are kept; a doc_id already in `documents` is left as it is."""
    from arp.db.companies import ensure_universe_company

    added = []
    for d in _documents(settings, s):
        stmt = insert(m.Document).values(
            doc_id=d["doc_id"], company_id=ensure_universe_company(s, d["company_id"]), universe_id=d["company_id"],
            doc_type=d["doc_type"], content_key=d["content_key"], title=d["title"], local_path=d.get("local_path"),
            source_url=d.get("source_url"), storage_uri=d.get("storage_uri"),
            first_seen_at=_ts(d["first_seen_at"]) if d.get("first_seen_at") else func.now(),
            last_seen_at=_ts(d["last_seen_at"]) if d.get("last_seen_at") else func.now(),
            family_id=d.get("family_id"), version=d.get("version"),
            published_at=date.fromisoformat(d["published_at"][:10]) if d.get("published_at") else None,
            identity_confidence=d.get("identity_confidence"),
            identity_review=None if d.get("identity_review") is None else bool(d["identity_review"]),
        ).on_conflict_do_nothing().returning(m.Document.doc_id)
        if s.execute(stmt).first() is not None:
            added.append(d)
    for d in added:  # after every row exists: supersedes points at another document
        if d.get("supersedes") and s.get(m.Document, d["supersedes"]) is not None:
            s.execute(update(m.Document).where(m.Document.doc_id == d["doc_id"]).values(supersedes=d["supersedes"]))
    report.counts["documents"] += len(added)


def _events(decisions: list[dict], cosigns: list[dict]):
    """Decisions and cosigns merged in the order they happened; each file keeps its own order."""
    return heapq.merge(
        (("decision", r) for r in decisions), (("cosign", r) for r in cosigns),
        key=lambda e: str(e[1].get("decided_at") if e[0] == "decision" else e[1].get("cosigned_at") or ""),
    )


def _fact_conflicts(s: Session, run_id: str) -> list[dict]:
    """Current facts of an earlier run this run replaced with a different value."""
    old, new = aliased(m.CompanyFact), aliased(m.CompanyFact)
    o_old, o_new = aliased(m.FieldObservation), aliased(m.FieldObservation)
    rows = s.execute(
        select(old.company_id, old.field_id, old.period_end, old.basis, old.value, new.value, o_old.run_id)
        .join(new, new.id == old.superseded_by).join(o_new, o_new.id == new.observation_id)
        .join(o_old, o_old.id == old.observation_id)
        .where(o_new.run_id == run_id, o_old.run_id.is_distinct_from(run_id))
    ).all()
    return [
        {"run_id": run_id, "company_id": str(c), "field_id": f, "period_end": p.isoformat() if p else None, "basis": b,
         "previous": before, "value": after, "previous_run_id": prev_run}
        for c, f, p, b, before, after, prev_run in rows if not _same(before, after)
    ]


def _import_run(s: Session, store: RunStore, legacy: LegacyRunStore, manifest: RunManifest, report: ImportReport) -> None:
    run_id = manifest.run_id
    if s.scalar(select(m.Run.run_type).where(m.Run.run_id == run_id)):
        return  # imported in full already (one transaction per run)
    counts = report.counts
    with store.bind(run_id, s):
        store.save_manifest(manifest.model_copy())
        s.execute(update(m.Run).where(m.Run.run_id == run_id).values(updated_at=_ts(manifest.updated_at)))
        counts["runs"] += 1

        companies = legacy.load_companies(run_id)
        by_key: dict[str, CompanyRef] = {}
        if companies is not None:
            resolved, conflicts = resolve_universe([c.model_copy(update={"entity_id": None}) for c in companies], s)
            for conflict in conflicts:
                store.append_error(run_id, conflict)  # as save_companies records them
                report.identity_conflicts.append({"source": f"run {run_id}", **conflict})
            by_key = {c.company_id: c for c in store.save_companies(run_id, resolved)}

        def company_for(key) -> CompanyRef | None:
            return _company_for(s, by_key, key, have_companies=companies is not None)

        trial = bool(manifest.params.get("trial"))
        for row in legacy.read_results(run_id):
            company = company_for(row.get("_key"))
            errors: list[dict] = []
            observations = (
                to_observations(manifest.run_type, company.entity_id, run_id, row, trial=trial, errors=errors)
                if company is not None else []
            )
            store.record_company_result(run_id, row, observations=observations, review_items=[], company=company, errors=errors)
            counts["results"] += 1

        for row in legacy.read_errors(run_id):
            store.append_error(run_id, row)
            counts["errors"] += 1

        links = {
            (o.company_id, o.field_id, o.period_end.isoformat() if o.period_end else None, o.basis): o.id
            for o in s.scalars(select(m.FieldObservation).where(m.FieldObservation.run_id == run_id).order_by(m.FieldObservation.id))
        }
        for row in legacy.read_review_queue(run_id):
            if not row.get("item_key"):
                logger.warning("run %s: review row without item_key skipped", run_id)
                continue
            target = review_target(row)
            entity = _entity(row.get("company_id"), lambda k: getattr(company_for(k), "entity_id", None))
            link = links.get((entity, *target)) if target and entity else None
            store.append_review_item(run_id, row, observation_id=link)
            counts["review_items"] += 1

        for kind, row in _events(legacy.read_decisions(run_id), legacy.read_cosigns(run_id)):
            if kind == "cosign":
                store.append_cosign(run_id, row)
                counts["cosigns"] += 1
                continue
            try:
                with s.begin_nested():
                    store.append_decision_row(run_id, row)
                counts["decisions"] += 1
            except ValueError as exc:  # not a DecisionKind: refused by the enum, reported by verify
                logger.warning("run %s: decision row skipped: %s", run_id, exc)
    report.fact_conflicts += _fact_conflicts(s, run_id)


def _entity(company_id, company_of) -> uuid.UUID | None:
    """A review row's company: its `company_id` is the company UUID or a universe id."""
    try:
        return uuid.UUID(str(company_id))
    except ValueError:
        return company_of(company_id)


def _company_for(s: Session, by_key: dict[str, CompanyRef], key, *, have_companies: bool) -> CompanyRef | None:
    """The run's company for a result row; a run that stored no companies (voting, older runs) falls
    back to the registry's universe alias."""
    if key is None:
        return None
    if have_companies:
        return by_key.get(str(key))
    entity = lookup(s, m.IdScheme.UNIVERSE, str(key))
    return CompanyRef(company_id=str(key), name=str(key), entity_id=entity) if entity else None


def _import_esg(s: Session, settings: Settings, report: ImportReport) -> None:
    from arp.portfolio.climate.esg_intake import record_esg_load

    for load in _esg_loads(settings):
        ingested = record_esg_load(s, load["rows"], provider=load["provider"], month=load["month"], source_ref="import")
        report.counts["esg_loads"] += ingested is not None


@contextmanager
def _units(dsn: str, dry_run: bool):
    """Yields `unit()`: a transaction per unit of work, committed on exit; under `dry_run` a savepoint
    inside one transaction that is rolled back at the end."""
    with Session(engine(dsn)) as s:
        outer = s.begin() if dry_run else None

        @contextmanager
        def unit():
            with s.begin_nested() if dry_run else s.begin():
                yield s

        try:
            yield unit
        finally:
            if outer is not None:
                outer.rollback()


def import_all(dsn: str, settings: Settings, *, dry_run: bool) -> ImportReport:
    report = ImportReport()
    manifests = _manifests(settings)
    legacy = LegacyRunStore(settings.runs_dir)
    store = RunStore(dsn, settings.runs_dir)
    with _units(dsn, dry_run) as unit:
        with unit() as s:
            _import_universe(s, settings, manifests, report)
        with unit() as s:
            _import_identifier_map(s, settings, report)
        with unit() as s:
            _import_schemas(s, settings, report)
        with unit() as s:
            _import_documents(s, settings, report)
        for manifest in manifests:
            with unit() as s:
                _import_run(s, store, legacy, manifest, report)
        with unit() as s:
            _import_esg(s, settings, report)
    return report


# --- verify -------------------------------------------------------------------------------------


@dataclass(eq=False)
class _Obs:
    key: tuple
    field_id: str
    value: Any
    value_state: m.ValueState
    route: m.Route | None


@dataclass
class _Fact:
    value: Any
    status: m.FactStatus
    obs: _Obs


def _distinct(rows: list[dict], key: str) -> int:
    """Rows the database keeps one of per `key` (rows without one are all kept)."""
    return len({r.get(key) or f"~{i}" for i, r in enumerate(rows)})


def _db_counts(s: Session, run_id: str) -> dict[str, int]:
    def n(model, *where):
        return s.scalar(select(func.count()).select_from(model).where(model.run_id == run_id, *where))

    return {
        "results": n(m.RunResult),
        "errors": n(m.RunError, ~func.coalesce(m.RunError.error["kind"].astext.in_(_DERIVED_ERRORS), False)),
        "review_items": n(m.ReviewItem),
        "decisions": n(m.ReviewDecision),
        "cosigns": n(m.ReviewCosign),
    }


class _Replay:
    """The current facts the files imply, by the database's own rules, without the database."""

    def __init__(self, types: dict[tuple[str, int], str]) -> None:
        self.types = types
        self.facts: dict[tuple, _Fact] = {}

    def _set(self, o: _Obs, value, status: m.FactStatus, state: m.ValueState) -> None:
        if decide(self.facts.get(o.key), value, status, state) in ("insert", "supersede"):
            self.facts[o.key] = _Fact(value, status, o)

    def run(self, manifest: RunManifest, legacy: LegacyRunStore, company_of) -> None:
        run_id, trial = manifest.run_id, bool(manifest.params.get("trial"))
        by_company: dict[uuid.UUID, list[_Obs]] = defaultdict(list)
        links: dict[tuple, _Obs] = {}
        seen: set[str] = set()
        for row in legacy.read_results(run_id):
            key = row.get("_key")
            if key in seen:
                continue  # the database keeps the first row per _key
            seen.add(key)
            entity = company_of(key)
            if entity is None:
                continue
            for o in to_observations(manifest.run_type, entity, run_id, row, trial=trial):
                if not _fits(self.types.get((o.field_id, o.field_version), ""), o.value):
                    continue
                period = o.period_end.isoformat() if o.period_end else None
                obs = _Obs((entity, o.field_id, period, o.basis), o.field_id, _jsonb_safe(o.value), o.value_state, o.route)
                by_company[entity].append(obs)
                links[obs.key] = obs
                if not trial:
                    self._set(obs, obs.value, _status(o), o.value_state)

        items: dict[str, tuple] = {}
        for row in legacy.read_review_queue(run_id):
            if not row.get("item_key"):
                continue
            entity = _entity(row.get("company_id"), company_of)
            target = review_target(row)
            link = links.get((entity, *target)) if target and entity else None
            prev = items.get(row["item_key"])
            items[row["item_key"]] = (entity, link or (prev[1] if prev else None), row)

        from arp.orchestration.review_queue import FINAL_STATES, item_state
        from arp.review.items import cosign_rule

        decided: dict[str, list[dict]] = defaultdict(list)
        signed: dict[str, set[str]] = defaultdict(set)
        valid = {d.value for d in m.DecisionKind}
        for kind, row in _events(legacy.read_decisions(run_id), legacy.read_cosigns(run_id)):
            key = row.get("item_key")
            if kind == "decision":
                if row.get("decision") not in valid:
                    continue
                decided[key].append(row)
            else:
                signed[key].add(row.get("decision_decided_at"))
            if key not in items or trial:
                continue
            state = item_state(decided[key], cosigned_at=signed[key], cosign_required=cosign_rule(manifest.run_type))
            if state.state in FINAL_STATES:
                eff = state.effective
                self._apply(items[key], key, m.DecisionKind(eff["decision"]),
                            eff.get("corrected_value") or eff.get("edited_value"), by_company)

    def _apply(self, item: tuple, key: str, decision: m.DecisionKind, edited, by_company) -> None:
        """observations.apply_decision over the replayed facts."""
        entity, link, payload = item
        if decision == m.DecisionKind.ESCALATE:
            return
        whole_record = link is None
        if link is not None:
            targets = [link]
        elif entity is not None and key == payload.get("company_id"):
            targets = [o for o in by_company[entity] if o.route == m.Route.REVIEW]
        else:
            return
        status = _DECIDED.get(decision)
        for o in targets:
            if decision == m.DecisionKind.REJECT:
                cur = self.facts.get(o.key)
                if cur is not None and cur.obs is o and cur.status == m.FactStatus.PENDING_REVIEW:
                    del self.facts[o.key]
                continue
            value, state = o.value, o.value_state
            if status == m.FactStatus.EDITED and edited is not None:
                value = _edited(o, edited, whole_record=whole_record)
                if value is _SKIP:
                    continue
                state = m.ValueState.NOT_FOUND if value is None else m.ValueState.FOUND
            self._set(o, value, status, state)


def verify(dsn: str, settings: Settings) -> VerifyReport:
    """Per run: result/error/review/decision/cosign row counts, files vs database; then per company,
    field, period and basis: the current fact replaying the files oldest first vs `company_facts`."""
    report = VerifyReport()
    legacy = LegacyRunStore(settings.runs_dir)
    manifests = _manifests(settings)
    with Session(engine(dsn)) as s:
        types = {(d.field_id, d.version): d.data_type for d in s.scalars(select(m.FieldDefinition))}
        replay = _Replay(types)
        for manifest in manifests:
            run_id = manifest.run_id
            files = {
                "results": _distinct(legacy.read_results(run_id), "_key"),
                "errors": len(legacy.read_errors(run_id)),
                "review_items": len({r["item_key"] for r in legacy.read_review_queue(run_id) if r.get("item_key")}),
                "decisions": len(legacy.read_decisions(run_id)),
                "cosigns": len(legacy.read_cosigns(run_id)),
            }
            db = _db_counts(s, run_id)
            report.differences += [
                {"run_id": run_id, "area": area, "files": files[area], "db": db[area]} for area in files if files[area] != db[area]
            ]
            refs = dict(s.execute(
                select(m.RunCompany.ref["company_id"].astext, m.RunCompany.company_id).where(m.RunCompany.run_id == run_id)
            ).all())
            stored = legacy.has_companies(run_id)

            def company_of(key, refs=refs, stored=stored):
                if key is None:
                    return None
                return refs.get(str(key)) if stored else lookup(s, m.IdScheme.UNIVERSE, str(key))

            replay.run(manifest, legacy, company_of)

        run_ids = [r.run_id for r in manifests]
        current = {
            (f.company_id, f.field_id, f.period_end.isoformat() if f.period_end else None, f.basis): f
            for f in s.scalars(
                select(m.CompanyFact).join(m.FieldObservation, m.FieldObservation.id == m.CompanyFact.observation_id)
                .where(m.CompanyFact.valid_to.is_(None), m.FieldObservation.run_id.in_(run_ids))
            )
        }
    for key in sorted(set(current) | set(replay.facts), key=str):
        want, have = replay.facts.get(key), current.get(key)
        if want is not None and have is not None and _same(want.value, have.value) and want.status == have.status:
            continue
        company_id, field_id, period_end, basis = key
        report.differences.append({
            "area": "fact", "company_id": str(company_id), "field_id": field_id, "period_end": period_end, "basis": basis,
            "files": None if want is None else {"value": want.value, "status": want.status.value},
            "db": None if have is None else {"value": have.value, "status": have.status.value},
        })
    return report
