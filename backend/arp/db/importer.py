"""One-time import of file-era history into Postgres (spec §6 step 8, §7) and the check that the two agree.

`import_all` order: universe files → identifier map → schema registry → documents → runs, oldest first
by `created_at` (rows and observations only) → facts → ESG loads → re-key legacy-keyed rows
(holdings, securities, published facts…) to the companies just created. Each unit (one source, one run, the
fact replay) is one transaction, so an interrupted import leaves whole units behind and a re-run
completes the rest.

Facts (ruling R42) are derived after every run is in, on ONE timeline across runs: each run's results
at its `updated_at`, decisions at `decided_at`, cosigns at `cosigned_at` (`_timeline`), through the
live writers (`observations.apply_observation`, `RunStore._apply_review` → `observations.apply_decision`).
The replay removes and re-derives the facts of the keys the imported runs observed, so it is
deterministic and runs on every import.

Idempotency: a run whose manifest row exists was imported in full (its manifest, companies, results,
errors, review rows, decisions and cosigns commit together), so it is skipped as a whole; the
manifest row is the import marker. Elsewhere natural keys skip what exists: companies and
identifiers by (scheme, value), schemas by (schema_id, version), documents by doc_id, ESG loads by
payload_sha (`record_load`).

Per-run side artifacts (schema.json, regrounds.jsonl, snapshots, events, restatement candidates)
stay files under `settings.runs_dir/<run_id>/`, which is where both stores read them: nothing is copied.

`verify` replays the files on the same timeline through the same pure rules (`to_observations`,
`observations.decide`, `review_queue.item_state`) and compares row counts and current facts."""

from __future__ import annotations

import hashlib
import heapq
import json
import logging
import sqlite3
import uuid
from collections import defaultdict, deque
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from arp.config import Settings
from arp.db import models as m
from arp.db import observations as observations_db
from arp.db.companies import lookup, resolve, resolve_company
from arp.db.fields import SchemaRegistry
from arp.db.observations import _DECIDED, _SKIP, _edited, _fits, _same, _status, decide
from arp.db.runs import RunStore, _decision_kind, _iso, _jsonb_safe, _ts
from arp.db.session import engine
from arp.db.to_observations import review_target, to_observations
from arp.schemas.common import CompanyRef, RunManifest
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.issuer import IdentifierMap
from arp.storage.jsonl_io import read_jsonl
from arp.storage.postgres_schema import rekey_company_ids
from arp.storage.run_store import LegacyRunStore
from arp.universe import load_company_universe, resolve_universe

logger = logging.getLogger(__name__)

AREAS = ("companies", "identifiers", "schemas", "documents", "runs", "results", "errors", "review_items",
         "decisions", "decisions_skipped", "cosigns", "esg_loads")
# run_errors rows the import itself derives (not in errors.jsonl): identity conflicts from save_companies,
# values left out of observations, citations to unregistered documents
_DERIVED_ERRORS = ("identity_conflict", "invalid_value", "unregistered_citation")
_IDENTITY_COLUMNS = ("family_id", "version", "supersedes", "published_at", "identity_confidence", "identity_review")


class ImportFailed(RuntimeError):
    """An import unit failed; the message names the source file or row."""


@dataclass
class ImportReport:
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(AREAS, 0))
    identity_conflicts: list[dict] = field(default_factory=list)
    fact_conflicts: list[dict] = field(default_factory=list)
    skipped_decisions: list[dict] = field(default_factory=list)  # decision values the enum refuses


@dataclass
class VerifyReport:
    differences: list[dict] = field(default_factory=list)
    skipped_decisions: list[dict] = field(default_factory=list)  # listed, not differences


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
        with _source(f"universe file {path}"):
            out += [(str(path), c) for c in load_company_universe(path)]
    out += [("portfolio_store", c) for c in build_portfolio_store(settings).list_companies()]
    return out


def _schemas(root: Path) -> list[DataPointSchema]:
    index = root / "index.json"
    with _source(str(index)):
        rows = sorted(json.loads(index.read_text(encoding="utf-8")) if index.exists() else [],
                      key=lambda r: (r["schema_id"], int(r["version"])))
    out = []
    for r in rows:
        path = root / r["schema_id"] / f"v{int(r['version'])}.json"
        with _source(str(path)):
            out.append(DataPointSchema.model_validate_json(path.read_text(encoding="utf-8")))
    return out


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
        with _source(f"document {d.get('doc_id')}"):
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


def _merged(decisions: list[tuple[dict, Any]], cosigns: list[tuple[dict, Any]]):
    """("decision" | "cosign", row, ref) merged in the order they happened (`decided_at` /
    `cosigned_at`); each list keeps its own order."""
    return heapq.merge(
        (("decision", r, ref) for r, ref in decisions), (("cosign", r, ref) for r, ref in cosigns),
        key=lambda e: str(e[1].get("decided_at" if e[0] == "decision" else "cosigned_at") or ""),
    )


def _when(value) -> datetime | None:
    try:
        return _ts(str(value))
    except ValueError:
        return None


def _timeline(runs: list[tuple[str, str, list, list]]) -> list[tuple[str, str, dict | None, Any]]:
    """One global order over every run's events (ruling R42). `runs`: (run_id, updated_at, decisions,
    cosigns), oldest run first, decisions/cosigns as (row, ref) in stored order. Each run's results
    happen at its `updated_at`, a decision at `decided_at`, a cosign at `cosigned_at` (missing or
    unparsable: the run's `updated_at`, so after its results). Ties: results first, then the order
    the files list them. Returns (kind, run_id, row, ref, at), kind "results" | "decision" | "cosign"."""
    events, seq = [], 0
    for run_id, updated_at, decisions, cosigns in runs:
        run_ts = _when(updated_at) or datetime.min.replace(tzinfo=UTC)
        events.append((run_ts, 0, seq, ("results", run_id, None, None, run_ts)))
        for kind, row, ref in _merged(decisions, cosigns):
            seq += 1
            ts = _when(row.get("decided_at" if kind == "decision" else "cosigned_at")) or run_ts
            events.append((ts, 1, seq, (kind, run_id, row, ref, ts)))
        seq += 1
    return [e[3] for e in sorted(events, key=lambda e: e[:3])]


def _stored_decision(row: dict) -> bool:
    """Whether `append_decision_row` stores the row (a DecisionKind, or a non-review action)."""
    try:
        _decision_kind(row)
        return True
    except ValueError:
        return False


@contextmanager
def _source(label: str):
    """Names the file or row a failure came from."""
    try:
        yield
    except ImportFailed:
        raise
    except Exception as exc:
        raise ImportFailed(f"{label}: {exc}") from exc


def _import_run(s: Session, store: RunStore, legacy: LegacyRunStore, manifest: RunManifest, report: ImportReport) -> None:
    """The run's rows and observations, no facts (`apply_facts=False`): `_replay_facts` derives those
    once every run is in."""
    run_id = manifest.run_id
    if s.scalar(select(m.Run.run_type).where(m.Run.run_id == run_id)):
        return  # imported in full already (one transaction per run)
    counts = report.counts
    with store.bind(run_id, s):
        with _source(f"run {run_id} manifest.json"):
            store.save_manifest(manifest.model_copy())
        counts["runs"] += 1

        with _source(f"run {run_id} companies.json"):
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
        with _source(f"run {run_id} results.jsonl"):
            for row in legacy.read_results(run_id):
                company = company_for(row.get("_key"))
                errors: list[dict] = []
                observations = (
                    to_observations(manifest.run_type, company.entity_id, run_id, row, trial=trial, errors=errors)
                    if company is not None else []
                )
                store.record_company_result(
                    run_id, row, observations=observations, review_items=[], company=company, errors=errors, apply_facts=False,
                )
                counts["results"] += 1

        with _source(f"run {run_id} errors.jsonl"):
            for row in legacy.read_errors(run_id):
                store.append_error(run_id, row)
                counts["errors"] += 1

        with _source(f"run {run_id} review_queue.jsonl"):
            links = {
                (o.company_id, o.field_id, o.period_end.isoformat() if o.period_end else None, o.basis): o.id
                for o in s.scalars(
                    select(m.FieldObservation).where(m.FieldObservation.run_id == run_id).order_by(m.FieldObservation.id))
            }
            for row in legacy.read_review_queue(run_id):
                if not row.get("item_key"):
                    logger.warning("run %s: review row without item_key skipped", run_id)
                    continue
                target = review_target(row)
                entity = _entity(row.get("company_id"), lambda k: getattr(company_for(k), "entity_id", None))
                store.append_review_item(run_id, row, observation_id=links.get((entity, *target)) if target and entity else None)
                counts["review_items"] += 1

        with _source(f"run {run_id} review_decisions.jsonl / review_cosigns.jsonl"):
            decisions = [(r, None) for r in legacy.read_decisions(run_id)]
            for kind, row, _ in _merged(decisions, [(r, None) for r in legacy.read_cosigns(run_id)]):
                if kind == "cosign":
                    store.append_cosign(run_id, row, apply_facts=False)
                    counts["cosigns"] += 1
                elif _stored_decision(row):
                    store.append_decision_row(run_id, row, apply_facts=False)
                    counts["decisions"] += 1
                else:  # not a DecisionKind: refused by the enum
                    counts["decisions_skipped"] += 1
                    report.skipped_decisions.append(
                        {"run_id": run_id, "item_key": row.get("item_key"), "decision": row.get("decision")})
        # last: writes to the run row above (save_companies, ...) stamp updated_at now(); the timeline needs the file's
        s.execute(update(m.Run).where(m.Run.run_id == run_id).values(updated_at=_ts(manifest.updated_at)))


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


def _replay_facts(s: Session, run_ids: list[str], report: ImportReport) -> None:
    """Re-derives the current facts of every (company, field, period_end, basis) the imported runs
    observed: the facts made from their observations are removed, then results, decisions and cosigns
    are applied on one timeline (`_timeline`) through the live fact writers, each fact version dated
    by its event (R43: as-of queries see the file-era history). Deterministic, so a
    re-run derives the same facts. Refuses when such a key has a current fact from elsewhere (data
    written after cut-over), which the replay would otherwise bury."""
    obs_ids = select(m.FieldObservation.id).where(m.FieldObservation.run_id.in_(run_ids))
    keys = select(m.FieldObservation.company_id, m.FieldObservation.field_id, m.FieldObservation.period_end,
                  m.FieldObservation.basis).where(m.FieldObservation.run_id.in_(run_ids)).distinct().subquery()
    foreign = s.scalar(
        select(func.count()).select_from(m.CompanyFact).join(keys, (keys.c.company_id == m.CompanyFact.company_id)
            & (keys.c.field_id == m.CompanyFact.field_id) & keys.c.period_end.is_not_distinct_from(m.CompanyFact.period_end)
            & (keys.c.basis == m.CompanyFact.basis))
        .where(m.CompanyFact.valid_to.is_(None), m.CompanyFact.observation_id.not_in(obs_ids))
    )
    if foreign:
        raise ImportFailed(
            f"already cut over; re-import not supported: {foreign} current fact(s) on imported keys come from outside the import")
    s.execute(update(m.CompanyFact).where(m.CompanyFact.observation_id.in_(obs_ids)).values(superseded_by=None))
    s.execute(delete(m.CompanyFact).where(m.CompanyFact.observation_id.in_(obs_ids)))

    runs = {r.run_id: r for r in s.scalars(select(m.Run).where(m.Run.run_id.in_(run_ids)))}
    timeline = _timeline([
        (
            rid, _iso(runs[rid].updated_at),
            [(d.row, d) for d in s.scalars(select(m.ReviewDecision).where(m.ReviewDecision.run_id == rid).order_by(m.ReviewDecision.id))],
            [(c.row, c) for c in s.scalars(select(m.ReviewCosign).where(m.ReviewCosign.run_id == rid).order_by(m.ReviewCosign.id))],
        )
        for rid in run_ids if rid in runs
    ])
    last_decision: dict[tuple, int] = {}
    last_cosign: dict[tuple, int] = {}
    for kind, run_id, row, ref, at in timeline:
        with _source(f"run {run_id} {kind}"):
            if kind == "results":
                _apply_results(s, runs[run_id], at)
                continue
            key = (run_id, row.get("item_key"))
            if kind == "cosign":
                last_cosign[key] = ref.id
            else:
                last_decision[key] = ref.id
                if ref.decision is None:
                    continue  # a non-review action: never applied
            RunStore._apply_review(s, run_id, row.get("item_key"), decisions_upto=last_decision.get(key, 0),
                                   cosigns_upto=last_cosign.get(key, 0), at=at)
    report.fact_conflicts += _fact_conflicts(s, run_ids)


def _apply_results(s: Session, run: m.Run, at: datetime) -> None:
    """The fact updates `record_company_result` would have made for the run's stored results: its
    observations, paired in order with what `to_observations` gives for each result row."""
    trial = bool((run.params or {}).get("trial"))
    stored: dict[uuid.UUID, deque] = defaultdict(deque)
    for o in s.scalars(select(m.FieldObservation).where(m.FieldObservation.run_id == run.run_id).order_by(m.FieldObservation.id)):
        stored[o.company_id].append(o)
    for company_id, result in s.execute(
        select(m.RunResult.company_id, m.RunResult.result)
        .where(m.RunResult.run_id == run.run_id, m.RunResult.company_id.is_not(None)).order_by(m.RunResult.id)
    ):
        ins = to_observations(run.run_type, company_id, run.run_id, result, trial=trial)
        for o, ok in zip(ins, observations_db.fits(s, ins), strict=True):
            if not ok:
                continue
            row = stored[company_id].popleft()
            if (row.field_id, row.period_end, row.basis) != (o.field_id, o.period_end, o.basis):
                raise ImportFailed(f"observation {row.id} does not match result row field {o.field_id}")
            observations_db.apply_observation(s, row, o, at=at)


def _fact_conflicts(s: Session, run_ids: list[str]) -> list[dict]:
    """Facts of one imported run that a later imported run replaced with a different value."""
    old, new = aliased(m.CompanyFact), aliased(m.CompanyFact)
    o_old, o_new = aliased(m.FieldObservation), aliased(m.FieldObservation)
    rows = s.execute(
        select(old.company_id, old.field_id, old.period_end, old.basis, old.value, new.value, o_old.run_id, o_new.run_id)
        .join(new, new.id == old.superseded_by).join(o_new, o_new.id == new.observation_id)
        .join(o_old, o_old.id == old.observation_id)
        .where(o_new.run_id.in_(run_ids), o_old.run_id.in_(run_ids), o_old.run_id != o_new.run_id)
        .order_by(old.id)
    ).all()
    return [
        {"run_id": run_id, "company_id": str(c), "field_id": f, "period_end": p.isoformat() if p else None, "basis": b,
         "previous": before, "value": after, "previous_run_id": prev_run}
        for c, f, p, b, before, after, prev_run, run_id in rows if not _same(before, after)
    ]


def _import_esg(s: Session, settings: Settings, report: ImportReport, *, dry_run: bool) -> None:
    """Under `dry_run` only counts the loads whose payload is new: `record_load` would write the blob."""
    from arp.portfolio.climate.esg_intake import esg_payload, esg_source_slug, record_esg_load

    for load in _esg_loads(settings):
        with _source(f"ESG load {load['provider']} {load['month']}"):
            if dry_run:
                sha = hashlib.sha256(esg_payload(load["rows"], load["month"])).hexdigest()
                seen = s.scalar(select(m.SourceLoad.load_id).join(m.DataSource).where(
                    m.DataSource.slug == esg_source_slug(load["provider"]), m.SourceLoad.payload_sha == sha))
                report.counts["esg_loads"] += seen is None
                continue
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
        with unit() as s, _source(str(settings.identifier_map_path)):
            _import_identifier_map(s, settings, report)
        with unit() as s:
            _import_schemas(s, settings, report)
        with unit() as s:
            _import_documents(s, settings, report)
        for manifest in manifests:
            with unit() as s:
                _import_run(s, store, legacy, manifest, report)
        if manifests:
            with unit() as s:
                _replay_facts(s, [r.run_id for r in manifests], report)
        with unit() as s:
            _import_esg(s, settings, report, dry_run=dry_run)
        with unit() as s:  # legacy-keyed rows whose companies this import created
            rekey_company_ids(s.connection())
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


@dataclass
class _RunFiles:
    manifest: RunManifest
    results: list[dict]
    review_queue: list[dict]
    decisions: list[dict]  # the rows the database stores
    cosigns: list[dict]
    company_of: Any


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
    """The current facts the files imply, by the database's own rules and on the import's timeline,
    without the database."""

    def __init__(self, types: dict[tuple[str, int], str]) -> None:
        self.types = types
        self.facts: dict[tuple, _Fact] = {}

    def _set(self, o: _Obs, value, status: m.FactStatus, state: m.ValueState) -> None:
        if decide(self.facts.get(o.key), value, status, state) in ("insert", "supersede"):
            self.facts[o.key] = _Fact(value, status, o)

    def replay(self, runs: list[_RunFiles]) -> None:
        from arp.orchestration.review_queue import FINAL_STATES, item_state
        from arp.review.items import cosign_rule

        by_id = {r.manifest.run_id: r for r in runs}
        state: dict[str, dict] = {r.manifest.run_id: {} for r in runs}
        timeline = _timeline([
            (r.manifest.run_id, r.manifest.updated_at, [(d, i) for i, d in enumerate(r.decisions)],
             [(c, i) for i, c in enumerate(r.cosigns)])
            for r in runs
        ])
        last_decision: dict[tuple, int] = {}
        last_cosign: dict[tuple, int] = {}
        for kind, run_id, row, idx, _ in timeline:
            run, st = by_id[run_id], state[run_id]
            if kind == "results":
                st.update(self._results(run))
                continue
            item_key = row.get("item_key")
            key = (run_id, item_key)
            if kind == "cosign":
                last_cosign[key] = idx
            else:
                last_decision[key] = idx
                if row.get("decision") is None:
                    continue
            if item_key not in st["items"] or run.manifest.params.get("trial"):
                continue
            # as RunStore._apply_review with decisions_upto / cosigns_upto: the item's rows up to here
            d_upto, c_upto = last_decision.get(key, -1), last_cosign.get(key, -1)
            rows = [d for i, d in enumerate(run.decisions) if i <= d_upto and d.get("item_key") == item_key]
            signed = {c.get("decision_decided_at") for i, c in enumerate(run.cosigns) if i <= c_upto and c.get("item_key") == item_key}
            s = item_state(rows, cosigned_at=signed, cosign_required=cosign_rule(run.manifest.run_type))
            if s.state in FINAL_STATES:
                eff = s.effective
                self._apply(st["items"][item_key], item_key, m.DecisionKind(eff["decision"]),
                            eff.get("corrected_value") or eff.get("edited_value"), st["by_company"])

    def _results(self, run: _RunFiles) -> dict:
        manifest = run.manifest
        run_id, trial = manifest.run_id, bool(manifest.params.get("trial"))
        by_company: dict[uuid.UUID, list[_Obs]] = defaultdict(list)
        links: dict[tuple, _Obs] = {}
        seen: set[str] = set()
        for row in run.results:
            key = row.get("_key")
            if key in seen:
                continue  # the database keeps the first row per _key
            seen.add(key)
            entity = run.company_of(key)
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
        for row in run.review_queue:
            if not row.get("item_key"):
                continue
            entity = _entity(row.get("company_id"), run.company_of)
            target = review_target(row)
            link = links.get((entity, *target)) if target and entity else None
            prev = items.get(row["item_key"])
            items[row["item_key"]] = (entity, link or (prev[1] if prev else None), row)
        return {"by_company": by_company, "items": items}

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
    """Per run: result/error/review/decision/cosign row counts, files vs database (decision rows the
    enum refuses are listed in `skipped_decisions`, not counted as differences); then per company,
    field, period and basis: the current fact replaying the files on the import's timeline vs
    `company_facts`."""
    report = VerifyReport()
    legacy = LegacyRunStore(settings.runs_dir)
    manifests = _manifests(settings)
    runs: list[_RunFiles] = []
    with Session(engine(dsn)) as s:
        types = {(d.field_id, d.version): d.data_type for d in s.scalars(select(m.FieldDefinition))}
        for manifest in manifests:
            run_id = manifest.run_id
            decisions = legacy.read_decisions(run_id)
            report.skipped_decisions += [
                {"run_id": run_id, "item_key": d.get("item_key"), "decision": d.get("decision")}
                for d in decisions if not _stored_decision(d)
            ]
            refs = dict(s.execute(
                select(m.RunCompany.ref["company_id"].astext, m.RunCompany.company_id).where(m.RunCompany.run_id == run_id)
            ).all())

            def company_of(key, refs=refs, stored=legacy.has_companies(run_id)):
                if key is None:
                    return None
                return refs.get(str(key)) if stored else lookup(s, m.IdScheme.UNIVERSE, str(key))

            run = _RunFiles(manifest, legacy.read_results(run_id), legacy.read_review_queue(run_id),
                            [d for d in decisions if _stored_decision(d)], legacy.read_cosigns(run_id), company_of)
            runs.append(run)
            files = {
                "results": _distinct(run.results, "_key"),
                "errors": len(legacy.read_errors(run_id)),
                "review_items": len({r["item_key"] for r in run.review_queue if r.get("item_key")}),
                "decisions": len(run.decisions),
                "cosigns": len(run.cosigns),
            }
            db = _db_counts(s, run_id)
            report.differences += [
                {"run_id": run_id, "area": area, "files": files[area], "db": db[area]} for area in files if files[area] != db[area]
            ]
        replay = _Replay(types)
        replay.replay(runs)

        current = {
            (f.company_id, f.field_id, f.period_end.isoformat() if f.period_end else None, f.basis): f
            for f in s.scalars(
                select(m.CompanyFact).join(m.FieldObservation, m.FieldObservation.id == m.CompanyFact.observation_id)
                .where(m.CompanyFact.valid_to.is_(None), m.FieldObservation.run_id.in_([r.run_id for r in manifests]))
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
