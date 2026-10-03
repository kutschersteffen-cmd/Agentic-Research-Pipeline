from __future__ import annotations

import pytest

from arp.bi.eval import offline_metas
from arp.bi.plan import ChartPlan, ChartSpec, DashboardTemplate
from arp.bi.validator import validate_plan
from arp.projects.dashboards import (
    plan_to_template,
    provision_project_dashboard,
    scope_to_project,
    slugify_dashboard,
)
from arp.projects.store import ProjectError
from tests.test_bi_service import FakeClient, _spec


def _tpl(*charts: ChartSpec) -> DashboardTemplate:
    return DashboardTemplate(slug="arp-x", title="X", charts=list(charts))


def test_scope_adds_filter_to_holdings_charts_only_and_is_pure():
    t = _tpl(_spec("A"), _spec("H", dataset="holdings_history"), _spec("C", dataset="company_facts"))
    before = t.model_dump()
    out = scope_to_project(t, "alpha")
    assert t.model_dump() == before
    assert out.charts[0].filters == {"project_id": "alpha"}
    assert out.charts[1].filters == {"project_id": "alpha"}
    assert "project_id" not in out.charts[2].filters


def test_scope_refuses_foreign_project_id():
    t = _tpl(_spec("A", filters={"project_id": "beta"}))
    with pytest.raises(ProjectError):
        scope_to_project(t, "alpha")
    assert scope_to_project(_tpl(_spec("A", filters={"project_id": "alpha"})), "alpha").charts[0].filters == {
        "project_id": "alpha"
    }


def test_slugify():
    assert slugify_dashboard("alpha", "My Exposure!") == "arp-alpha--my-exposure"
    with pytest.raises(ProjectError):
        slugify_dashboard("alpha", "!!!")
    s = slugify_dashboard("a" * 63, "word " * 50)
    assert len(s) <= 100 and s.startswith("arp-" + "a" * 63 + "--")


def test_plan_to_template_validates_and_provisions():
    plan = ChartPlan(title="My Exposure", charts=[_spec("A", groupby=["country"])])
    t = scope_to_project(plan_to_template("alpha", "My Exposure", plan), "alpha")
    assert t.slug == "arp-alpha--my-exposure"
    assert [f.name for f in t.native_filters] == ["Fund", "Sector", "Country"]
    assert validate_plan(ChartPlan(title=t.title, charts=t.charts), offline_metas(), max_charts=1) == []
    client = FakeClient()
    assert provision_project_dashboard(client, "alpha", t) == "created"
    assert provision_project_dashboard(client, "alpha", t) == "unchanged"


def test_plan_to_template_no_filters_without_holdings():
    plan = ChartPlan(title="T", charts=[_spec("C", dataset="company_facts")])
    assert plan_to_template("alpha", "T", plan).native_filters == []


def test_slug_collisions():
    assert slugify_dashboard("a", "b-c") != slugify_dashboard("a-b", "c")
    assert slugify_dashboard("a-", "t") != slugify_dashboard("a", "-t")


class _Capture(FakeClient):
    def __init__(self):
        super().__init__()
        self.params = []

    def create_chart(self, name, dataset_id, viz_type, params):
        self.params.append(params)
        return super().create_chart(name, dataset_id, viz_type, params)


def test_provision_scopes_unscoped_template_and_rejects_foreign_slug():
    t = DashboardTemplate(
        slug="arp-alpha--x", title="X", charts=[_spec("A"), _spec("H", dataset="holdings_history", groupby=["as_of_date"])]
    )
    client = _Capture()
    provision_project_dashboard(client, "alpha", t)
    assert len(client.params) == 2
    for p in client.params:
        want = {"expressionType": "SIMPLE", "subject": "project_id", "operator": "==", "comparator": "alpha", "clause": "WHERE"}
        assert want in p["adhoc_filters"]
        assert sum(f["subject"] == "project_id" for f in p["adhoc_filters"]) == 1
    with pytest.raises(ProjectError):
        provision_project_dashboard(FakeClient(), "beta", t)


def test_slug_remainder_may_not_contain_double_hyphen():
    t = DashboardTemplate(slug="arp-a--b--c", title="X", charts=[_spec("A")])
    with pytest.raises(ProjectError):
        provision_project_dashboard(FakeClient(), "a", t)
