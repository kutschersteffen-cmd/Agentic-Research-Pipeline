"""The authoritative-layer spec's fixture (companies A and B, provider and extracted Scope 1) for Postgres tests."""

from __future__ import annotations

from datetime import UTC, date, datetime


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


def add_fact(session, company_id, field_id, value, period_end, *, valid_from, source_kind="extraction",
             source_id=None, status=None, basis="", unit="tCO2e"):
    """One observation plus its current fact, dated `valid_from`; `status` overrides auto_accepted."""
    from arp.db import models as m
    from arp.db.observations import ObservationIn, apply_observation, record

    o = ObservationIn(
        company_id=company_id, field_id=field_id, field_version=1, source_kind=m.SourceKind(source_kind),
        period_end=date.fromisoformat(period_end), basis=basis, value=value, value_state=m.ValueState.FOUND,
        unit=unit, canonical_value=value if isinstance(value, int | float) else None,
        canonical_unit=unit if isinstance(value, int | float) else None, route=m.Route.AUTO_ACCEPT,
        method="extracted" if source_kind == "extraction" else None, source_id=source_id, confidence=0.9,
    )
    [obs_id] = record(session, [o], apply_facts=False)
    apply_observation(session, session.get(m.FieldObservation, obs_id), o, at=_at(valid_from))
    if status:
        fact = session.query(m.CompanyFact).filter_by(observation_id=obs_id).one()
        fact.status = m.FactStatus(status)
    session.flush()
    return obs_id


def ensure_field(session, field_id, data_type="number"):
    from arp.db import models as m
    from arp.db.fields import ensure_extracted_field

    ensure_extracted_field(
        session, field_id, m.FieldDefinition(version=1, name=field_id, data_type=data_type, unit="tCO2e", definition={})
    )


def seed(dsn):
    """The spec's fixture: A (provider 100 + approved extraction 90) and B (provider 50)."""
    from arp.db.companies import ensure_universe_company
    from arp.db.fields import register_provider_field
    from arp.db.models import IdScheme, Licence
    from arp.db.providers import ensure_source
    from arp.db.session import transaction

    with transaction(dsn) as s:
        a = ensure_universe_company(s, "U-A", name="Company A")
        b = ensure_universe_company(s, "U-B", name="Company B")
        src = ensure_source(s, "esg_demo", name="ESG demo", kind="file", licence=Licence.INTERNAL_ONLY,
                            id_scheme=IdScheme.UNIVERSE)
        prov = register_provider_field(s, src, "scope1", name="Scope 1", unit="tCO2e", data_type="number")
        ensure_field(s, "scope1_tco2e")
        ids = {
            "a_prov": add_fact(s, a, prov, 100, "2026-09-30", valid_from="2026-10-01", source_kind="provider", source_id=src),
            "b_prov": add_fact(s, b, prov, 50, "2026-09-30", valid_from="2026-10-01", source_kind="provider", source_id=src),
            "a_ext": add_fact(s, a, "scope1_tco2e", 90, "2025-12-31", valid_from="2026-03-01", status="approved"),
        }
    return {"A": str(a), "B": str(b), "prov": prov, "src": src, **ids}


PICKS = [{"field_id": "prov:esg_demo:scope1"}, {"field_id": "scope1_tco2e"}]


def build(dsn, fx, *, as_of="2026-10-15", picks=None, company_ids=None, portfolio_store=None):
    from arp.authoritative.source_values import SourcePick, from_source_values
    from arp.db.session import transaction

    with transaction(dsn) as s:
        return from_source_values(
            s, company_ids=company_ids or [fx["A"], fx["B"]],
            picks=[SourcePick(**p) for p in (picks or PICKS)], as_of=as_of, portfolio_store=portfolio_store,
        )


def row(ds, company_id):
    return next(r for r in ds.rows if r["company_id"] == company_id)
