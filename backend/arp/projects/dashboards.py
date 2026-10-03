"""Project-scoped dashboards: slug, project_id filter injection, provisioning.

Slug format: `arp-<project_id>--<slugified title>`. The title part never contains `--`
(runs of non-alphanumerics collapse to one `-`, ends stripped), so two projects cannot collide."""

from __future__ import annotations

import re

from arp.bi.plan import ChartPlan, DashboardTemplate
from arp.bi.templates import load_templates, provision
from arp.projects.store import ProjectError

SCOPED_DATASETS = {"holdings", "holdings_history"}
MAX_SLUG = 100


def slugify_dashboard(project_id: str, title: str) -> str:
    part = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not part:
        raise ProjectError(f"Dashboard title {title!r} has no usable characters")
    prefix = f"arp-{project_id}--"
    return prefix + part[: MAX_SLUG - len(prefix)].strip("-")  # prefix <= 69 chars (ID_RE), so room remains


def scope_to_project(template: DashboardTemplate, project_id: str) -> DashboardTemplate:
    out = template.model_copy(deep=True)
    for chart in out.charts:
        if chart.dataset not in SCOPED_DATASETS:
            continue
        if chart.filters.get("project_id", project_id) != project_id:
            raise ProjectError(f"Chart {chart.title!r} filters on another project")
        chart.filters["project_id"] = project_id
    return out


def plan_to_template(project_id: str, title: str, plan: ChartPlan) -> DashboardTemplate:
    filters = []
    if any(c.dataset in SCOPED_DATASETS for c in plan.charts):
        exposure = next(t for t in load_templates() if t.slug == "arp-risk-exposure")
        filters = exposure.native_filters
    template = DashboardTemplate(
        slug=slugify_dashboard(project_id, title),
        title=title,
        goal=plan.goal,
        charts=plan.charts,
        native_filters=filters,
    )
    return scope_to_project(template, project_id)


def provision_project_dashboard(client, project_id: str, template: DashboardTemplate) -> str:
    if not template.slug.startswith(f"arp-{project_id}--"):
        raise ProjectError(f"Dashboard {template.slug!r} does not belong to project {project_id!r}")
    return provision(client, scope_to_project(template, project_id))
