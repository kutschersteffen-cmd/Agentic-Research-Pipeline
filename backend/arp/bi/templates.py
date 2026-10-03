"""Standard dashboards, committed as JSON in arp/bi/templates/, that
`arp bi bootstrap` provisions into Superset.

A template is validated against the live datasets before anything is
written. Present with at least as many charts as the template: left alone,
so a dashboard a person extended or made public is never touched. Fewer: only
the dashboard is deleted and rebuilt; its old charts stay. A rebuild comes
back as a draft, even if the old dashboard was public in Superset."""

from __future__ import annotations

import json
from importlib import resources

from arp.bi.compiler import compile_native_filters
from arp.bi.plan import ChartPlan, DashboardTemplate
from arp.bi.service import BIError, _datasets, _ensure_dashboard
from arp.bi.superset_client import SupersetClient
from arp.bi.validator import validate_plan


def load_templates() -> list[DashboardTemplate]:
    files = sorted((f for f in (resources.files("arp.bi") / "templates").iterdir() if f.name.endswith(".json")), key=str)
    return [DashboardTemplate.model_validate(json.loads(f.read_text())) for f in files]


def provision(client: SupersetClient, template: DashboardTemplate) -> str:
    """Returns "created", "rebuilt" or "unchanged". Raises BIError naming every problem
    when the template does not fit the live datasets, before any write."""
    ids, metas = _datasets(client)
    plan = ChartPlan(title=template.title, goal=template.goal, charts=template.charts)
    problems = validate_plan(plan, metas, max_charts=max(1, len(plan.charts)))
    for f in template.native_filters:
        if f.dataset not in metas:
            problems.append(f"Native filter '{f.name}': unknown dataset '{f.dataset}'.")
        elif f.column not in metas[f.dataset].columns:
            problems.append(f"Native filter '{f.name}': unknown column '{f.column}' in dataset '{f.dataset}'.")
        else:
            problems += [
                f"Native filter '{f.name}': unknown filter column '{c}' in dataset '{f.dataset}'."
                for c in f.filters
                if c not in metas[f.dataset].columns
            ]
    if problems:
        raise BIError(f"Template {template.slug}: " + " ".join(problems))
    json_metadata = compile_native_filters(template.native_filters, ids)
    return _ensure_dashboard(client, template.slug, plan, ids, json_metadata)[1]
