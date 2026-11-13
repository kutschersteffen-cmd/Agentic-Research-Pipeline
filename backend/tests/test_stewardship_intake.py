import threading

import pytest
from sqlalchemy import func, select

from arp.db.companies import ensure_universe_company
from arp.db.session import transaction
from arp.stewardship.intake import intake_engagements
from arp.storage.postgres_engagement_store import PostgresEngagementStore
from arp.storage.postgres_models import StwActivityModel, StwCompanyModel, StwEngagementModel, StwEventModel, StwObjectiveModel


def _count(dsn, model):
    with transaction(dsn) as s:
        return s.scalar(select(func.count()).select_from(model))


def _batch(**eng):
    return {
        "engagements": [{"external_id": "e1", "company_id": "C1", "theme": "climate", "fir_theme": "climate_mitigation", **eng}],
        "objectives": [{"external_id": "o1", "engagement_external_id": "e1", "description": "Set a target", "objective_type": "strategic"}],
    }


def test_unknown_company_rejected(pg):
    report = intake_engagements(_batch(), pg, "api")
    assert [r.model_dump() for r in report.rejected] == [
        {"sheet": "engagements", "row": 1, "field": "company_id", "reason": "unknown company"}
    ]
    assert report.created == 0


def test_valid_batch(pg):
    PostgresEngagementStore(pg).get_or_create("C1", "Acme")
    report = intake_engagements(_batch(), pg, "api")
    assert (report.created, report.updated, report.unchanged, report.rejected) == (2, 0, 0, [])
    again = intake_engagements(_batch(), pg, "api")
    assert (again.created, again.updated, again.unchanged) == (0, 0, 2)
    changed = intake_engagements(_batch(theme="pay"), pg, "api")
    assert (changed.created, changed.updated, changed.unchanged) == (0, 1, 1)
    with transaction(pg) as s:
        kinds = [e.event_type for e in s.scalars(select(StwEventModel).order_by(StwEventModel.event_id))]
    assert kinds.count("intake_upserted") == 3  # 2 creates + 1 update, nothing for unchanged


def test_bad_enum_rejected_nothing_stored(pg):
    PostgresEngagementStore(pg).get_or_create("C1", "Acme")
    batch = _batch()
    batch["objectives"][0]["objective_type"] = "bogus"
    report = intake_engagements(batch, pg, "api")
    assert report.rejected[0].field == "objective_type"
    assert report.rejected[0].reason == "not one of transparency, operational, strategic"
    assert [_count(pg, m) for m in (StwEngagementModel, StwObjectiveModel, StwActivityModel)] == [0, 0, 0]


def test_isin_normalised(pg):
    PostgresEngagementStore(pg).get_or_create("isin_US0378331005", "Apple")
    batch = _batch(isin=" us0378331005 ", company_id="")
    report = intake_engagements(batch, pg, "api")
    assert report.rejected == []
    with transaction(pg) as s:
        assert s.scalar(select(StwEngagementModel.company_id)) == "isin_US0378331005"


def test_registry_company_gets_a_row_from_name(pg):
    with transaction(pg) as s:
        ensure_universe_company(s, "C9", name="Nine")
    report = intake_engagements(_batch(company_id="C9", company_name="Nine plc"), pg, "api")
    assert (report.created, report.rejected) == (3, [])  # company row, engagement, objective
    with transaction(pg) as s:
        assert s.get(StwCompanyModel, "C9").name == "Nine plc"


@pytest.mark.parametrize("field", ["follows_external_id", "engagement_external_id"])
def test_follow_up_must_exist(pg, field):
    PostgresEngagementStore(pg).get_or_create("C1", "Acme")
    batch = _batch()
    batch["objectives"][0][field] = "nope"
    report = intake_engagements(batch, pg, "api")
    assert [r.field for r in report.rejected] == [field]


def test_follows_resolves_within_batch_in_any_order(pg):
    PostgresEngagementStore(pg).get_or_create("C1", "Acme")
    batch = _batch()
    batch["objectives"].insert(0, {**batch["objectives"][0], "external_id": "o2", "follows_external_id": "o1"})
    assert intake_engagements(batch, pg, "api").created == 3


def test_malformed_values_rejected_not_500(pg):
    PostgresEngagementStore(pg).get_or_create("C1", "Acme")
    report = intake_engagements(_batch(esg_pillars=5, theme=["x"]), pg, "api")
    assert sorted(r.field for r in report.rejected) == ["esg_pillars", "theme"]
    assert intake_engagements(_batch(theme=5), pg, "api").created == 2  # a scalar text value is coerced


def test_concurrent_intakes_serialise(pg):
    PostgresEngagementStore(pg).get_or_create("C1", "Acme")
    barrier = threading.Barrier(2)
    reports = []

    def run():
        barrier.wait()
        reports.append(intake_engagements(_batch(), pg, "api"))

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted((r.created, r.unchanged) for r in reports) == [(0, 2), (2, 0)]
