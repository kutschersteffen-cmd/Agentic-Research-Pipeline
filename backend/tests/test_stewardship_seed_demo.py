import collections

import pytest
from sqlalchemy import func, select

from arp.db.companies import resolve_company
from arp.db.session import transaction
from arp.schemas.common import CompanyRef
from arp.stewardship.seed_demo import MSCI_WORLD, seed_demo, select_companies
from arp.stewardship.style import check, load_blocklist
from arp.storage.postgres_models import (
    StwActivityModel,
    StwCompanyModel,
    StwEngagementModel,
    StwEventModel,
    StwObjectiveModel,
)

TABLES = (StwCompanyModel, StwEngagementModel, StwObjectiveModel, StwActivityModel, StwEventModel)


def _register(dsn, n):
    picked = select_companies(MSCI_WORLD, n)
    with transaction(dsn) as s:
        for isin, name, sector in picked:
            resolve_company(s, CompanyRef(company_id=f"isin_{isin}", name=name, isin=isin, sector=sector))
    return picked


def _counts(dsn):
    with transaction(dsn) as s:
        return [s.scalar(select(func.count()).select_from(m)) for m in TABLES]


def _objectives(dsn):
    with transaction(dsn) as s:
        rows = s.scalars(select(StwObjectiveModel)).all(), s.scalars(select(StwEngagementModel)).all()
        s.expunge_all()  # readable after the session closes
        return rows


def test_select_companies_top_n_distinct_equities():
    picked = select_companies(MSCI_WORLD, 400)
    assert len(picked) == len({p[0] for p in picked}) == 400
    assert picked[0][:2] == ("US0378331005", "APPLE")


@pytest.fixture
def seeded(pg):
    _register(pg, 20)
    seed_demo(pg, n=20, seed=7)
    return pg


def test_ac23_objectives_per_company(seeded):
    with transaction(seeded) as s:
        per_company = collections.Counter()
        for company, n in s.execute(
            select(StwEngagementModel.company_id, func.count(StwObjectiveModel.objective_id))
            .join(StwObjectiveModel, StwObjectiveModel.engagement_id == StwEngagementModel.engagement_id)
            .where(StwEngagementModel.source == "mock_voice_seed")
            .group_by(StwEngagementModel.engagement_id, StwEngagementModel.company_id)
        ):
            per_company[company] += n
    assert len(per_company) == 20
    assert set(per_company.values()) <= {3, 4, 5}


def test_ac24_closed_objectives_complete(seeded):
    objectives, _ = _objectives(seeded)
    closed = [o for o in objectives if o.status == "closed"]
    assert closed
    assert all(o.result and o.closed_at and o.outcome and o.influence_level for o in closed)
    assert all(o.description and o.objective_type and o.receptiveness and o.started_at for o in objectives)


def test_ac25_follow_ups(seeded):
    objectives, _ = _objectives(seeded)
    by_id = {o.objective_id: o for o in objectives}
    follows = [o for o in objectives if o.follows_objective_id]
    assert 0.25 <= len(follows) / len(objectives) <= 0.45
    for o in follows:
        parent = by_id[o.follows_objective_id]
        assert parent.engagement_id == o.engagement_id and parent.started_at < o.started_at


def test_follow_up_wording_differs_from_parent(seeded):
    objectives, _ = _objectives(seeded)
    by_id = {o.objective_id: o for o in objectives}
    follows = [o for o in objectives if o.follows_objective_id]
    assert follows and all(o.description.startswith("Follow-up:") and o.description != by_id[o.follows_objective_id].description for o in follows)


def test_ac26_passive_support_has_no_high_influence(seeded):
    objectives, engagements = _objectives(seeded)
    role = {e.engagement_id: e.engager_role for e in engagements}
    assert "passive_support" in role.values()
    assert not [o for o in objectives if role[o.engagement_id] == "passive_support" and o.influence_level in ("4A", "4B", "5")]


def test_ac29_rerun_changes_nothing(seeded):
    before = _counts(seeded)
    seed_demo(seeded, n=20, seed=7)
    assert _counts(seeded) == before


def test_different_seed_replaces_only_seed_rows(seeded):
    with transaction(seeded) as s:
        s.add(StwEventModel(source="api", company_id="x", event_type="note"))
    seed_demo(seeded, n=20, seed=8)
    with transaction(seeded) as s:
        assert s.scalar(select(func.count()).select_from(StwEventModel).where(StwEventModel.source == "api")) == 1
        assert {e.external_id.split(":")[0] for e in s.scalars(select(StwEngagementModel))} == {"s8"}
        assert {o.external_id.split(":")[0] for o in s.scalars(select(StwObjectiveModel))} == {"s8"}


def test_missing_registry_exit(pg, capsys):
    with pytest.raises(SystemExit) as exc:
        seed_demo(pg, n=20, seed=7)
    assert exc.value.code == 1
    assert capsys.readouterr().err.strip() == "run arp showcase load first"


def test_missing_registry_writes_nothing(pg):
    with pytest.raises(SystemExit):
        seed_demo(pg, n=20, seed=7)
    assert _counts(pg) == [0, 0, 0, 0, 0]


def test_mock_text_passes_style_check(seeded):
    blocklist = load_blocklist()
    objectives, engagements = _objectives(seeded)
    with transaction(seeded) as s:
        activities = s.scalars(select(StwActivityModel)).all()
        s.expunge_all()
    texts = [o.description for o in objectives] + [o.outcome for o in objectives if o.outcome] + [o.influence_evidence for o in objectives if o.influence_evidence]
    texts += [e.rationale for e in engagements] + [a.summary for a in activities]
    assert texts and all(check(t, blocklist) == [] for t in texts)


@pytest.mark.slow
def test_full_400(pg):
    _register(pg, 400)
    seed_demo(pg)
    with transaction(pg) as s:
        assert s.scalar(select(func.count(func.distinct(StwEngagementModel.company_id)))) == 400
    before = _counts(pg)
    seed_demo(pg)
    assert _counts(pg) == before
