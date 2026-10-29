"""Publishing a calculate-only framework's verdicts into `authoritative_values`, and reading them as of a time.

A key is (framework, output, company). A publish reconfirms an unchanged current row, otherwise closes it and inserts
the next version; a company missing from the dataset gets a `not_in_dataset` row. Source tables are only read."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from arp.authoritative.evaluate import Verdict, evaluate
from arp.authoritative.models import AuthoritativePublish, AuthoritativeValue
from arp.authoritative.source_values import _as_of_end
from arp.db import models as m
from arp.decision.dataset import Dataset
from arp.schemas.common import new_id
from arp.schemas.decision import MechanismConfig
from arp.storage.postgres_models import PublishedFactModel

NOT_IN_DATASET = "not_in_dataset"


class StalePublish(ValueError):
    """The dataset is older than one this framework already published: the timeline never runs backwards."""


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


def _row(v: AuthoritativeValue, *, derivation: bool = False) -> dict:
    out = {
        "id": v.id, "framework_id": v.framework_id, "output": v.output_column, "company_id": str(v.company_id),
        "value": v.value, "unit": v.unit, "period_end": v.period_end, "status": v.status, "reason": v.reason,
        "framework_version": v.framework_version, "dataset_as_of": v.dataset_as_of, "snapshot_id": v.snapshot_id,
        "published_by": v.published_by, "valid_from": _iso(v.valid_from), "valid_to": _iso(v.valid_to),
        "superseded_by": v.superseded_by, "reconfirmed_at": _iso(v.reconfirmed_at),
    }
    if derivation:
        out["derivation"] = v.derivation
    return out


def _same(current: AuthoritativeValue, verdict: Verdict, version: int) -> bool:
    return (current.value, current.unit, current.period_end, current.status, current.reason, current.framework_version) == (
        verdict.value, verdict.unit, verdict.period_end, verdict.status, verdict.reason, version)


def _link_published_facts(session: Session, verdicts: list[Verdict]) -> None:
    """Sets `published_fact_id` on every input whose observation's key has a current published fact."""
    obs_ids = {i["observation_id"] for v in verdicts for i in v.derivation["inputs"].values() if i.get("observation_id")}
    if not obs_ids:
        return
    keys = {o.id: (o.company_id, o.field_id, str(o.period_end) if o.period_end else None, o.basis)
            for o in session.scalars(select(m.FieldObservation).where(m.FieldObservation.id.in_(obs_ids)))}
    facts = {}
    for f in session.scalars(select(PublishedFactModel).where(
        PublishedFactModel.valid_to.is_(None), PublishedFactModel.company_id.in_({k[0] for k in keys.values()}),
    )):
        facts[(f.company_id, f.field_id, f.period_end, f.basis)] = f.fact_id
    for v in verdicts:
        for i in v.derivation["inputs"].values():
            i["published_fact_id"] = facts.get(keys.get(i.get("observation_id")))


class AuthoritativeStore:
    def __init__(self, dsn: str):
        from arp.storage.postgres import get_engine

        self.engine = get_engine(dsn)

    def publish(self, dataset: Dataset, config: MechanismConfig, *, published_by: str) -> str:
        """Returns the snapshot id. Raises StalePublish when `dataset.as_of` is older than the framework's latest."""
        snapshot_id = new_id("auth")
        verdicts = evaluate(dataset, config, snapshot_id=snapshot_id)
        with Session(self.engine) as s, s.begin():
            s.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"authoritative:{config.framework_id}"))))
            latest = s.scalars(select(AuthoritativePublish.dataset_as_of).where(
                AuthoritativePublish.framework_id == config.framework_id)).all()
            if dataset.as_of and any(a and _as_of_end(a) > _as_of_end(dataset.as_of) for a in latest):
                raise StalePublish(f"Dataset as of {dataset.as_of} is older than one already published for "
                                   f"{config.framework_id}; build a newer dataset.")
            now = s.scalar(select(func.clock_timestamp()))
            _link_published_facts(s, verdicts)
            current = {(v.output_column, v.company_id): v for v in s.scalars(select(AuthoritativeValue).where(
                AuthoritativeValue.framework_id == config.framework_id, AuthoritativeValue.valid_to.is_(None)))}
            seen = {(v.output, UUID(v.company_id)) for v in verdicts}
            dropped = [
                Verdict(company_id=str(cid), output=out, status="no_value", reason=NOT_IN_DATASET, unit=row.unit,
                        derivation={"inputs": {}, "trace": [], "framework_id": config.framework_id,
                                    "framework_version": config.version, "dataset_id": dataset.dataset_id,
                                    "dataset_as_of": dataset.as_of, "snapshot_id": snapshot_id})
                for (out, cid), row in current.items()
                if (out, cid) not in seen and not (row.reason == NOT_IN_DATASET and row.framework_version == config.version)
            ]
            for verdict in verdicts + dropped:
                key = (verdict.output, UUID(verdict.company_id))
                old = current.get(key)
                if old is not None and _same(old, verdict, config.version):
                    old.reconfirmed_at = now
                    continue
                if old is not None:
                    old.valid_to = now
                    s.flush()  # the partial unique index allows one open row per key
                new = AuthoritativeValue(
                    framework_id=config.framework_id, output_column=verdict.output, company_id=key[1],
                    value=verdict.value,
                    canonical_value=Decimal(str(verdict.value)) if isinstance(verdict.value, int | float)
                    and not isinstance(verdict.value, bool) else None,
                    unit=verdict.unit, period_end=verdict.period_end, status=verdict.status, reason=verdict.reason,
                    derivation=verdict.derivation, framework_version=config.version, dataset_as_of=dataset.as_of,
                    snapshot_id=snapshot_id, published_by=published_by, valid_from=now,
                )
                s.add(new)
                s.flush()
                if old is not None:
                    old.superseded_by = new.id
            s.add(AuthoritativePublish(
                snapshot_id=snapshot_id, framework_id=config.framework_id, framework_version=config.version,
                dataset_id=dataset.dataset_id, dataset_as_of=dataset.as_of, published_by=published_by, published_at=now,
            ))
        return snapshot_id

    def values(self, *, framework_id: str, output: str | None = None, company_id: str | None = None,
               as_of: str | None = None) -> list[dict]:
        """Current rows, or the rows visible at `as_of` (a date means the end of that day, UTC)."""
        q = select(AuthoritativeValue).where(AuthoritativeValue.framework_id == framework_id)
        if output:
            q = q.where(AuthoritativeValue.output_column == output)
        if company_id:
            q = q.where(AuthoritativeValue.company_id == UUID(company_id))
        if as_of is None:
            q = q.where(AuthoritativeValue.valid_to.is_(None))
        else:
            at = _as_of_end(as_of)
            q = q.where(AuthoritativeValue.valid_from <= at,
                        or_(AuthoritativeValue.valid_to.is_(None), AuthoritativeValue.valid_to > at))
        with Session(self.engine) as s:
            return [_row(v) for v in s.scalars(q.order_by(AuthoritativeValue.company_id, AuthoritativeValue.output_column))]

    def history(self, *, framework_id: str, output: str, company_id: str) -> list[dict]:
        with Session(self.engine) as s:
            return [_row(v) for v in s.scalars(select(AuthoritativeValue).where(
                AuthoritativeValue.framework_id == framework_id, AuthoritativeValue.output_column == output,
                AuthoritativeValue.company_id == UUID(company_id)).order_by(AuthoritativeValue.id))]

    def get(self, value_id: int) -> dict | None:
        with Session(self.engine) as s:
            v = s.get(AuthoritativeValue, value_id)
            return _row(v, derivation=True) if v else None

    def publishes(self, framework_id: str) -> list[dict]:
        with Session(self.engine) as s:
            return [
                {"snapshot_id": p.snapshot_id, "framework_version": p.framework_version, "dataset_id": p.dataset_id,
                 "dataset_as_of": p.dataset_as_of, "published_by": p.published_by, "published_at": _iso(p.published_at)}
                for p in s.scalars(select(AuthoritativePublish).where(AuthoritativePublish.framework_id == framework_id)
                                   .order_by(AuthoritativePublish.published_at))
            ]
