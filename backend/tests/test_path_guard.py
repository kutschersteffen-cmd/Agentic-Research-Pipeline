"""Path guard (spec server-paths-upload-limits, Design 4; AC-57, AC-60): every request-body property that may name
a server file is listed here with the folder its route confines it to. A new one fails this test until it is
checked and listed."""
from __future__ import annotations

import copy
import re

from arp.api.main import app

UNIVERSES = "runs/_universes (saved universe file)"
NAME_RULE = re.compile(r"^(path|funds|files)$|_(path|ref|refs)$")
INSTANTIATE = ("POST /api/plan-templates/{name}/instantiate", "source")  # the name rule does not match it
HAND_PICKED = {INSTANTIATE}

LISTED = {
    ("POST /api/argus/flows/{flow_id}/companies", "universe_path"): UNIVERSES,
    ("POST /api/discovery/runs", "universe_path"): UNIVERSES,
    ("POST /api/documents/readiness", "universe_path"): UNIVERSES,
    ("POST /api/emerging-themes/runs", "universe_path"): UNIVERSES,
    ("POST /api/extraction/runs", "universe_path"): UNIVERSES,
    ("POST /api/extraction/start", "universe_path"): UNIVERSES,
    ("POST /api/financials/runs", "universe_path"): UNIVERSES,
    ("POST /api/identity/runs", "universe_path"): UNIVERSES,
    ("POST /api/taxonomies", "universe_path"): UNIVERSES,
    ("POST /api/themes/runs", "universe_path"): UNIVERSES,
    ("POST /api/tnfd/runs", "universe_path"): UNIVERSES,
    ("POST /api/voting/runs", "universe_path"): UNIVERSES,
    ("POST /api/xbrl/runs", "universe_path"): UNIVERSES,
    ("POST /api/universe/workbench", "universe_path"): UNIVERSES,
    ("POST /api/universe/from-companies", "base_path"): UNIVERSES,
    ("PUT /api/discovery/schedule", "universe_path"): UNIVERSES + ", or the schedule's current value",
    ("PUT /api/emerging-themes/schedule", "universe_path"): UNIVERSES + ", or the schedule's current value",
    ("POST /api/etf-overlap", "funds"): "runs/_universes (uploaded holdings file)",
    ("POST /api/revenue-catalogue/suggest-mapping", "catalogue_path"): "runs/_universes (uploaded catalogue)",
    ("POST /api/themes/runs", "revenue_catalogue_path"): "runs/_universes (uploaded catalogue)",
    INSTANTIATE: UNIVERSES + " or a saved universe's file name",
    ("POST /api/authority-taxonomy/runs/{run_id}/sources", "files"): "documents_dir",
    ("POST /api/replication/specs/{spec_run_id}/backtest", "prices_ref"): "the spec's own uploads in its run folder, by file name",
    ("POST /api/replication/specs/{spec_run_id}/backtest", "characteristics_refs"): "the spec's own uploads in its run folder, by file name",
    ("POST /api/rfp/library/import", "files"): "not a server path: the uploaded file parts",
    ("POST /api/engagement/records/{company_id}/issues/{issue_id}/log-outreach-sent", "doc_ref"):
        "not a server path: a label stored with the log entry, never opened",
    ("POST /api/reports", "run_refs"): "not a server path: run and decision ids",
    ("PUT /api/reports/{report_id}/storyline", "source_refs"): "not a server path: dataset ids and note topics",
    ("POST /api/review/runs/{run_id}/items/{item_key}/decision", "table_ref"): "not a server path: Citation.table_ref",
    ("POST /api/taxonomies", "table_ref"): "not a server path: Citation.table_ref",
    ("POST /api/taxonomies/{taxonomy_id}/versions", "table_ref"): "not a server path: Citation.table_ref",
    ("POST /api/themes/runs", "table_ref"): "not a server path: Citation.table_ref",
    ("PUT /api/authority-taxonomy/runs/{run_id}/draft", "table_ref"): "not a server path: Citation.table_ref",
    ("PUT /api/replication/specs/{spec_run_id}", "table_ref"): "not a server path: Citation.table_ref",
}


def _properties(schema, components: dict, seen: frozenset = frozenset()):
    """Every property name in a schema, at any depth, following $refs once each."""
    if not isinstance(schema, dict):
        return
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name not in seen:
            yield from _properties(components.get(name), components, seen | {name})
        return
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        for sub in schema.get(key, []):
            yield from _properties(sub, components, seen)
    for key in ("items", "additionalProperties"):
        yield from _properties(schema.get(key), components, seen)
    for name, prop in schema.get("properties", {}).items():
        yield name
        yield from _properties(prop, components, seen)


def path_pairs(doc: dict) -> set[tuple[str, str]]:
    components = doc.get("components", {}).get("schemas", {})
    pairs = set()
    for route, ops in doc["paths"].items():
        for method, op in ops.items():
            for content in op.get("requestBody", {}).get("content", {}).values():
                for name in _properties(content.get("schema"), components):
                    pair = (f"{method.upper()} {route}", name)
                    if NAME_RULE.search(name) or pair in HAND_PICKED:
                        pairs.add(pair)
    return pairs


def check(doc: dict) -> list[str]:
    found = path_pairs(doc)
    return ([f"unlisted request field that may name a server file: {r} {p}" for r, p in sorted(found - LISTED.keys())]
            + [f"listed field no longer in the API: {r} {p}" for r, p in sorted(LISTED.keys() - found)])


def test_every_path_field_is_listed():
    assert check(app.openapi()) == []


def test_a_new_path_property_fails_the_guard():  # AC-57
    doc = copy.deepcopy(app.openapi())
    doc["components"]["schemas"]["OverlapRequest"]["properties"]["foo_path"] = {"type": "string"}
    errors = check(doc)
    assert errors and all("foo_path" in e for e in errors), errors
    assert check(app.openapi()) == []


def test_universe_path_on_an_unlisted_route_fails_the_guard():  # AC-60
    doc = copy.deepcopy(app.openapi())
    body = doc["paths"]["/api/plans"]["post"]["requestBody"]["content"]["application/json"]
    body["schema"] = {"allOf": [body["schema"], {"properties": {"universe_path": {"type": "string"}}}]}
    assert check(doc) == ["unlisted request field that may name a server file: POST /api/plans universe_path"]
