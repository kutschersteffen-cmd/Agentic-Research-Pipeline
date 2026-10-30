"""The score-lineage spec's fixture: authoritative framework F published for companies A..D, with A's Scope 1 input
traced to an observation and a grounded citation in document d1."""

from __future__ import annotations

from datetime import UTC, datetime

from tests.authoritative_fixtures import add_fact, ensure_field

F = "fw_f"
# company -> output -> (value, reason); reason set means no_value
VALUES = {
    "A": {"auth_scope1": (90, None), "auth_capex": (10, None)},
    "B": {"auth_scope1": (50, None), "auth_capex": (None, "no_rule_value")},
    "C": {"auth_scope1": (None, "not_in_dataset"), "auth_capex": (5, None)},
    "D": {"auth_scope1": (70, None), "auth_capex": (20, None)},
}
INPUT = {"auth_scope1": "scope1_tco2e", "auth_capex": "capex_eur"}


def seed(dsn: str) -> dict:
    """Returns {"company": {letter: uuid str}, "value_id": {(letter, output): id}, "obs_a_scope1": id}."""
    from arp.authoritative.models import AuthoritativeValue
    from arp.db import models as m
    from arp.db.companies import ensure_universe_company
    from arp.db.session import transaction

    out: dict = {"company": {}, "value_id": {}}
    now = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
    with transaction(dsn) as s:
        for field in INPUT.values():
            ensure_field(s, field)
        for letter, outputs in VALUES.items():
            cid = ensure_universe_company(s, f"U-{letter}", name=f"Company {letter}")
            out["company"][letter] = str(cid)
            for output, (value, reason) in outputs.items():
                field = INPUT[output]
                obs_id = None
                if value is not None:
                    obs_id = add_fact(s, cid, field, value, "2025-12-31", valid_from="2026-03-01", status="approved")
                inputs = {} if reason == "not_in_dataset" else {field: {
                    "value": value, "status": "approved" if value is not None else None,
                    "source": "extraction" if value is not None else None, "provider": None,
                    "period_end": "2025-12-31" if value is not None else None, "unit": "tCO2e",
                    "observation_id": obs_id, "published_fact_id": None,
                }}
                row = AuthoritativeValue(
                    framework_id=F, output_column=output, company_id=cid, value=value,
                    canonical_value=value, unit="tCO2e", period_end="2025-12-31" if value is not None else None,
                    status="value" if reason is None else "no_value", reason=reason,
                    derivation={"inputs": inputs, "trace": [{"node": "F", "expressions": [f"{output} = {field}"],
                                                           "output": {output: value}}],
                                "framework_id": F, "framework_version": 1, "dataset_id": "ds_src",
                                "dataset_as_of": "2026-10-29", "snapshot_id": "auth_1"},
                    framework_version=1, dataset_as_of="2026-10-29", snapshot_id="auth_1", published_by="Bob",  # gitleaks:allow
                    valid_from=now,
                )
                s.add(row)
                s.flush()
                out["value_id"][(letter, output)] = row.id
                if letter == "A" and output == "auth_scope1":
                    out["obs_a_scope1"] = obs_id
                    s.add(m.Document(doc_id="d1", company_id=cid, doc_type="annual_report", title="AR 2025",
                                     content_key="k_d1"))
                    s.flush()
                    s.add(m.ValueCitation(observation_id=obs_id, doc_id="d1", page=4, quote="Scope 1: 90 tCO2e",
                                          grounded=True))
    return out
