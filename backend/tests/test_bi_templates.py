"""Template provisioning, offline: the in-memory Superset from test_bi_service."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from arp.bi import templates
from arp.bi.eval import offline_metas
from arp.bi.plan import ChartPlan, DashboardTemplate, NativeFilter
from arp.bi.service import BIError
from arp.bi.templates import load_templates, provision
from arp.bi.validator import validate_plan
from tests.test_bi_service import FakeClient, _spec

TEMPLATE = DashboardTemplate(
    slug="arp-test",
    title="Test",
    charts=[_spec("A"), _spec("B", groupby=["country"])],
    native_filters=[NativeFilter(name="Portfolio", dataset="holdings", column="portfolio_name")],
)


def test_provision_creates_dashboard_when_absent():
    client = FakeClient()
    assert provision(client, TEMPLATE) == "created"
    dash = client.dashboards["arp-test"]
    assert dash["published"] is False and dash["charts"] == [101, 102]
    (nf,) = dash["meta"]["native_filter_configuration"]
    assert nf["id"] == "NATIVE_FILTER-holdings-portfolio_name" and nf["targets"][0]["datasetId"] == 1


def test_provision_is_unchanged_when_complete():
    client = FakeClient()
    provision(client, TEMPLATE)
    n = len(client.writes())
    assert provision(client, TEMPLATE) == "unchanged"
    assert len(client.writes()) == n


def test_provision_rebuilds_only_when_fewer_charts():
    client = FakeClient()
    client.charts[7] = "Old"
    client.dashboards["arp-test"] = {"id": 50, "published": False, "charts": [7], "position": {}}
    assert provision(client, TEMPLATE) == "rebuilt"
    assert [c for c in client.calls if c[0].startswith("delete")] == [("delete_dashboard", 50)]
    assert client.charts[7] == "Old" and client.dashboards["arp-test"]["charts"] == [101, 102]


def test_provision_leaves_extended_dashboard_alone():
    client = FakeClient()
    provision(client, TEMPLATE)
    client.charts[200] = "Added by hand"
    client.dashboards["arp-test"]["charts"].append(200)
    client.dashboards["arp-test"]["published"] = True  # a person published it
    n = len(client.writes())
    assert provision(client, TEMPLATE) == "unchanged"
    assert len(client.writes()) == n and client.dashboards["arp-test"]["published"] is True


def test_provision_never_sets_published():
    client = FakeClient()
    provision(client, TEMPLATE)
    assert all(d["published"] is False for d in client.dashboards.values())
    assert "published" not in Path(templates.__file__).read_text()


@pytest.mark.parametrize(
    "bad, needle",
    [
        ({"charts": [_spec("A", groupby=["portfolio"])]}, "unknown groupby column 'portfolio'"),
        ({"native_filters": [NativeFilter(name="F", dataset="holdings", column="fund")]}, "column 'fund'"),
        ({"native_filters": [NativeFilter(name="F", dataset="nope", column="sector")]}, "dataset 'nope'"),
        ({"charts": []}, "between 1 and 1"),
    ],
)
def test_template_with_unknown_column_fails_before_any_write(bad, needle):
    client = FakeClient()
    with pytest.raises(BIError, match="arp-test") as e:
        provision(client, TEMPLATE.model_copy(update=bad))
    assert needle in str(e.value) and client.writes() == []


def test_chart_failure_cleans_up_and_raises():
    client = FakeClient(fail_on_chart=2)
    with pytest.raises(BIError, match="'B'"):
        provision(client, TEMPLATE)
    assert client.charts == {} and client.dashboards == {}


def test_bundled_templates_validate_against_catalog():
    loaded = load_templates()
    assert "arp-risk-exposure" in {t.slug for t in loaded}
    metas = offline_metas()
    for t in loaded:
        plan = ChartPlan(title=t.title, charts=t.charts)
        assert validate_plan(plan, metas, max_charts=len(t.charts)) == [], t.slug
        assert all(f.column in metas[f.dataset].columns for f in t.native_filters), t.slug


def test_template_slug_must_start_with_arp():
    with pytest.raises(ValidationError, match="arp-"):
        DashboardTemplate(slug="risk", title="T", charts=[_spec("A")])
