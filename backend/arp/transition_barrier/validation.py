"""Rule book validator.

Works on the raw JSON dicts only: the pydantic models coerce "50" to 50.0 and raise on wrong shapes,
which would hide exactly what this module reports. Nothing here raises on malformed input.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from arp.transition_barrier.rule_book import RULE_BOOK_FILE, RuleBookError, RuleBookNotFound, compute_fingerprint

_OPS = {">=", "<=", ">", "<", "=", "in"}
_ORDERED = {">=", "<=", ">", "<"}
_FORMULAS = {"ratio", "ratio_pct", "difference"}
_TYPES = {"number", "boolean", "enum", "date"}
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}$")


def _text(x) -> bool:
    return isinstance(x, str) and bool(x.strip())


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _in(x, allowed) -> bool:
    return isinstance(x, str) and x in allowed


def _dicts(x) -> list[dict]:
    return [i for i in x if isinstance(i, dict)] if isinstance(x, list) else []


def _by_id(items) -> dict[str, dict]:
    return {i["id"]: i for i in _dicts(items) if isinstance(i.get("id"), str)}


def _type(fact: dict):
    return "number" if fact.get("formula") else fact.get("type")


def _unit(fact: dict, facts: dict, seen: tuple = ()):
    formula = fact.get("formula")
    if formula == "ratio":
        return None
    if formula == "ratio_pct":
        return "%"
    if formula == "difference":
        inputs = fact.get("inputs")
        first = facts.get(inputs[0]) if isinstance(inputs, list) and inputs and isinstance(inputs[0], str) else None
        if first is None or first.get("id") in seen + (fact.get("id"),):
            return None
        return _unit(first, facts, seen + (fact.get("id"),))
    return fact.get("unit") or None


def _desc(fact: dict, facts: dict) -> str:
    t = _type(fact)
    return (_unit(fact, facts) or "no unit") if t == "number" else str(t)


def _walk(node, depth: int, out: dict) -> None:
    if not isinstance(node, dict):
        out["bad"].append("expected an object")
    elif "fact" in node:
        out["conds"].append(node)
    else:
        kinds = [k for k in ("all", "any") if k in node]
        if len(kinds) != 1 or not isinstance(node[kinds[0]], list) or not node[kinds[0]]:
            out["bad"].append("expected a condition or one non-empty 'all' or 'any' list")
            return
        if depth > 2:
            out["deep"] = True
        for child in node[kinds[0]]:
            _walk(child, depth + 1, out)


def count_open(raw_rule_book: dict) -> int:
    criteria = raw_rule_book.get("criteria") if isinstance(raw_rule_book, dict) else None
    entries = [e for e in criteria.values() if isinstance(e, dict)] if isinstance(criteria, dict) else []
    return sum(p.get("status") == "open" for e in entries for p in _dicts(e.get("params")))


def _rule2(code, scans, facts, params):
    out = []
    for _, scan in scans:
        for c in scan["conds"]:
            if isinstance(c["fact"], str) and c["fact"] not in facts:
                out.append(f"{code}: condition names unknown fact '{c['fact']}'")
            if isinstance(c.get("other_fact"), str) and c["other_fact"] not in facts:
                out.append(f"{code}: condition names unknown fact '{c['other_fact']}'")
            if isinstance(c.get("param"), str) and c["param"] not in params:
                out.append(f"{code}: condition names unknown parameter '{c['param']}'")
    return out


def _condition_lines(code, c, facts, params) -> list[str]:
    fid, op = c["fact"], c.get("op")
    if not isinstance(fid, str):
        return [f"{code}: invalid condition: fact must be an id"]
    refs = [k for k in ("value", "param", "other_fact") if k in c]
    if not _in(op, _OPS):
        return [f"{code}: unknown operator '{op}'"]
    if len(refs) != 1:
        return [f"{code}: invalid condition on '{fid}': needs exactly one of value, param, other_fact"]
    kind = refs[0]
    if kind == "value" and _num(c["value"]):
        return [f"{code}: condition on '{fid}' uses an inline number; use a parameter"]
    fact = facts.get(fid) if isinstance(fid, str) else None
    if fact is None:
        return []
    bad = f"{code}: invalid condition on '{fid}': "
    t = _type(fact)
    if (op in _ORDERED and t not in ("number", "date")) or (op == "in" and not (t == "enum" and kind == "value")):
        return [bad + f"operator '{op}' does not fit a {t} fact"]
    if kind == "value":
        v, allowed = c["value"], fact.get("allowed_values")
        values = v if op == "in" and isinstance(v, list) else [v]
        ok = {
            "boolean": lambda x: isinstance(x, bool),
            "date": lambda x: isinstance(x, str) and bool(_DATE.match(x)),
            "enum": lambda x: isinstance(allowed, list) and _in(x, allowed),
        }.get(t, lambda x: False)
        return [] if values and all(ok(x) for x in values) else [bad + f"value does not fit the {t} fact"]
    if not isinstance(c[kind], str):
        return [bad + f"{kind} must be an id"]
    other = params.get(c[kind]) if kind == "param" else facts.get(c[kind])
    if other is None or (kind == "param" and other.get("status") == "open"):
        return []
    if kind == "param":
        other_desc = other.get("unit") or "no unit"
        same = t == "number" and _unit(fact, facts) == (other.get("unit") or None)
    else:
        other_desc = _desc(other, facts)
        same = _desc(fact, facts) == other_desc
    if same:
        return []
    return [f"{code}: '{fid}' ({_desc(fact, facts)}) compared with '{c[kind]}' ({other_desc})"]


def _rule3(code, scans, facts, params):
    out, deep = [], False
    for level, scan in scans:
        out += [f"{code}: invalid level {level}: {reason}" for reason in scan["bad"]]
        for c in scan["conds"]:
            out += _condition_lines(code, c, facts, params)
        deep = deep or scan["deep"]
    return out + ([f"{code}: conditions nested deeper than two levels"] if deep else [])


def _rule4(code, entry):
    out = []
    if entry.get("params") not in (None, []) and not isinstance(entry.get("params"), list):
        return [f"{code}: invalid params: expected a list"]
    for p in entry.get("params") or []:
        if not isinstance(p, dict) or not _text(p.get("id")):
            out.append(f"{code}: invalid parameter: expected an object with an id")
            continue
        pid = p["id"]
        if p.get("status") == "open":
            if not _text(p.get("question")):
                out.append(f"{code}: open parameter '{pid}' has no question")
            continue
        if not _num(p.get("value")):
            out.append(f"{code}: invalid {pid} value: expected a number")
        if not p.get("source"):
            out.append(f"{code}: parameter '{pid}' has no source")
        if not _text(p.get("rationale")):
            out.append(f"{code}: parameter '{pid}' has no rationale")
        regions = p.get("by_region") or {}
        if not isinstance(regions, dict):
            out.append(f"{code}: invalid {pid} by_region: expected an object")
            continue
        for region, o in regions.items():
            if not isinstance(o, dict):
                out.append(f"{code}: invalid {pid} override for {region}: expected an object")
                continue
            if not _num(o.get("value")):
                out.append(f"{code}: invalid {pid} override for {region}: expected a number")
            if not o.get("source"):
                out.append(f"{code}: parameter '{pid}' override for {region} has no source")
    return out


def _rule5(code, entry):
    levels = entry.get("levels")
    out = [] if _text(entry.get("rationale")) else [f"{code}: no rationale"]
    if not entry.get("facts"):
        out.append(f"{code}: no facts")
    if levels and not isinstance(levels, dict):
        out.append(f"{code}: invalid levels: expected an object")
    levels = levels if isinstance(levels, dict) else {}
    return out + [f"{code}: no {lv} level" for lv in "HM" if not levels.get(lv)]


def _rule6(code, entry, facts):
    out = []
    if entry.get("facts") and not isinstance(entry["facts"], list):
        return [f"{code}: invalid facts: expected a list"]
    for f in entry.get("facts") or []:
        if not isinstance(f, dict) or not _text(f.get("id")):
            out.append(f"{code}: invalid fact: expected an object with an id")
            continue
        fid = f["id"]
        if not _text(f.get("definition")):
            out.append(f"{code}: fact '{fid}' has no definition")
        if f.get("formula") is None:
            if not _in(f.get("type"), _TYPES):
                out.append(f"{code}: invalid fact '{fid}' type: expected number, boolean, enum or date")
            elif f["type"] == "enum" and not (isinstance(f.get("allowed_values"), list) and f["allowed_values"]):
                out.append(f"{code}: invalid fact '{fid}' allowed_values: expected a list of values")
            continue
        inputs = f.get("inputs")
        if not _in(f["formula"], _FORMULAS):
            out.append(f"{code}: invalid fact '{fid}' formula: expected ratio, ratio_pct or difference")
        elif not (isinstance(inputs, list) and len(inputs) == 2 and all(isinstance(i, str) for i in inputs)):
            out.append(f"{code}: invalid fact '{fid}' inputs: expected two fact ids")
        else:
            first = None
            for i in inputs:
                g = facts.get(i)
                if g is None:
                    out.append(f"{code}: computed fact '{fid}' names unknown input '{i}'")
                elif _type(g) != "number":
                    out.append(f"{code}: computed fact '{fid}' input '{i}' is not numeric")
                elif first is None:
                    first = g
                elif _unit(g, facts) != _unit(first, facts):
                    out.append(
                        f"{code}: computed fact '{fid}' input '{i}' is in {_unit(g, facts) or 'no unit'}, "
                        f"expected {_unit(first, facts) or 'no unit'}"
                    )
    return out


def _rule7(code, entry, sector_ids):
    actions = entry.get("actions")
    if actions and not isinstance(actions, list):
        return [f"{code}: invalid actions: expected a list"]
    return [f"{code}: unknown action '{a}'" for a in actions or [] if not (isinstance(a, str) and a in sector_ids)]


def validate_rule_book(raw_rule_book: dict, raw_schema: dict) -> list[str]:
    """Every rule book error, one line each, in spec rule order; criteria in schema order."""
    if not isinstance(raw_rule_book, dict) or not isinstance(raw_schema, dict):
        return ["invalid rule book or criteria schema: expected an object"]
    schema_criteria = [c for c in _dicts(raw_schema.get("criteria")) if isinstance(c.get("code"), str)]
    codes = [c["code"] for c in schema_criteria]
    entries_raw = raw_rule_book.get("criteria")
    entries_raw = entries_raw if isinstance(entries_raw, dict) else {}

    r1 = [] if isinstance(raw_rule_book.get("criteria"), dict) else ["invalid criteria: expected an object"]
    r1 += [f"Missing rule book entry: {c}" for c in codes if c not in entries_raw]
    r1 += [f"Rule book entry without criterion: {c}" for c in entries_raw if c not in codes]
    r1 += [f"{c}: invalid entry: expected an object" for c in codes if c in entries_raw and not isinstance(entries_raw[c], dict)]

    actions_raw = raw_rule_book.get("actions")
    actions_raw = actions_raw if isinstance(actions_raw, dict) else {}
    ctx = []
    for crit in schema_criteria:
        entry = entries_raw.get(crit["code"])
        if not isinstance(entry, dict):
            continue
        facts, params = _by_id(entry.get("facts")), _by_id(entry.get("params"))
        levels = entry.get("levels") if isinstance(entry.get("levels"), dict) else {}
        scans = []
        for level, node in levels.items():
            scan = {"conds": [], "bad": [], "deep": False}
            _walk(node, 1, scan)
            scans.append((level, scan))
        sector = crit.get("sector")
        sector_actions = actions_raw.get(sector) if isinstance(sector, str) else None
        sector_ids = {a["id"] for a in _dicts(sector_actions) if isinstance(a.get("id"), str)}
        ctx.append((crit["code"], entry, facts, params, scans, sector_ids))

    r8, seen = [], set()
    for crit in schema_criteria:
        for s in _dicts(crit.get("primary_sources")):
            key = s.get("key")
            if isinstance(key, str) and key not in seen:
                seen.add(key)
                if not _text(s.get("tier")):
                    r8.append(f"Source '{key}' has no tier")

    fingerprint_ok = raw_rule_book.get("fingerprint") == compute_fingerprint(raw_rule_book)
    r9 = [] if fingerprint_ok else [f"Rule book content changed but version is still {raw_rule_book.get('version')}"]

    return (
        r1
        + [e for c, _, f, p, s, _ in ctx for e in _rule2(c, s, f, p)]
        + [e for c, _, f, p, s, _ in ctx for e in _rule3(c, s, f, p)]
        + [e for c, entry, *_ in ctx for e in _rule4(c, entry)]
        + [e for c, entry, *_ in ctx for e in _rule5(c, entry)]
        + [e for c, entry, f, *_ in ctx for e in _rule6(c, entry, f)]
        + [e for c, entry, *_, ids in ctx for e in _rule7(c, entry, ids)]
        + r8
        + r9
    )


def read_and_validate(directory: Path) -> tuple[dict, dict, list[str]]:
    """Raw rule book and criteria schema from `directory`, plus their validation errors.

    Raises RuleBookNotFound or RuleBookError when the files can't be read as JSON objects.
    """
    path = Path(directory) / RULE_BOOK_FILE
    if not path.exists():
        raise RuleBookNotFound(f"Rule book not found: {path}")
    raws = []
    for p in (path, Path(directory) / "criteria_schema.json"):
        try:
            raws.append(json.loads(p.read_text(encoding="utf-8")))
        except FileNotFoundError:
            raise RuleBookError(f"File not found: {p}") from None
        except ValueError as exc:
            raise RuleBookError(f"{p.name} is not valid JSON: {exc}") from None
    raw, schema = raws
    if not isinstance(raw, dict) or not isinstance(schema, dict):
        raise RuleBookError("rule_book.json and criteria_schema.json must each hold a JSON object")
    return raw, schema, validate_rule_book(raw, schema)
