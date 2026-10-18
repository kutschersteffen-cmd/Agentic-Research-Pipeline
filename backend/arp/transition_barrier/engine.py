"""The rules engine: three-valued evaluation of a criterion's levels over cited values.

Pure code. It never calls a model, fetches a document or touches the database.
"""

from __future__ import annotations

import itertools
import operator
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel

from arp.transition_barrier.rule_book import CriterionRules

MAX_COMBINATIONS = 1000
_RANK = {"low": 0, "medium": 1, "high": 2}
_OPS = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "=": operator.eq,
    "in": lambda a, b: a in b,
}


@dataclass(frozen=True)
class Value:
    id: str
    fact: str
    value: float | bool | str | date
    unit: str | None
    document: str | None  # the cited title: an uploaded document's, or a registered source's source_name
    page: int | None
    locator: str | None
    confidence: Literal["high", "medium", "low"]
    machine_checked: bool
    entered_by: str | None = None
    counted: bool = True
    reason: str | None = None
    document_id: int | None = None


class ConditionResult(BaseModel):
    fact: str
    outcome: str  # pass | fail | unknown | mixed (combinations disagree)
    clause: str = ""


class LevelResult(BaseModel):
    outcome: str
    text: str = ""
    detail: str = ""
    conditions: list[ConditionResult] = []


class Result(BaseModel):
    run_id: str
    rating: Literal["H", "M", "L", "not_rated", "conflict"]
    confidence: Literal["high", "medium", "low"]
    missing_facts: list[str] = []
    open_params: list[str] = []
    notes: list[str] = []
    rule_book_version: int
    snapshot: dict
    levels: dict[str, LevelResult] = {}
    values: list[dict] = []


def fact_confidence(tier: str | None, as_of: date | None, max_age_days: int | None, today: date, has_document: bool) -> str:
    if not has_document:
        return "low"
    fresh = max_age_days is None or (as_of is not None and (today - as_of).days <= max_age_days)
    return "high" if tier == "primary" and fresh else "medium"


def _lowest(confidences) -> str:
    return min(confidences, key=_RANK.__getitem__, default="low")


def _coerce(x, kind):
    if kind == "date":
        return date.fromisoformat(x) if isinstance(x, str) else x
    if kind == "number" or kind is None:
        return float(x)
    return x


class _Combo:
    """Evaluates the levels for one pick of a counted value per fact."""

    def __init__(self, rules: CriterionRules, region: str, picked: dict[str, Value]):
        self.facts = {f.id: f for f in rules.facts}
        self.params = {p.id: p for p in rules.params}
        self.region = region
        self.picked = picked
        self.computed: dict[str, Value] = {}

    def resolve(self, fid: str) -> tuple[Value | None, list[str]]:
        """The value of a fact, or the labels that keep it from having one."""
        f = self.facts[fid]
        if not f.formula:
            v = self.picked.get(fid)
            return (v, []) if v else (None, [f.label])
        got = [self.resolve(i) for i in f.inputs]
        missing = [m for _, ms in got for m in ms]
        if missing:
            return None, missing
        a, b = got[0][0], got[1][0]
        x, y = float(a.value), float(b.value)
        reason = "Division by zero" if f.formula != "difference" and y == 0 else None
        out = {"ratio": lambda: x / y, "ratio_pct": lambda: x / y * 100, "difference": lambda: x - y}
        unit = {"ratio": None, "ratio_pct": "%", "difference": a.unit}[f.formula]
        v = Value(
            id=fid, fact=fid, value=None if reason else out[f.formula](), unit=unit, document=None,
            page=None, locator=None, confidence=_lowest([a.confidence, b.confidence]),
            machine_checked=a.machine_checked and b.machine_checked, counted=reason is None, reason=reason,
        )  # fmt: skip
        self.computed[fid] = v
        return (None, [f.label]) if reason else (v, [])

    def leaf(self, node: dict) -> dict:
        fact = self.facts[node["fact"]]
        left, missing = self.resolve(node["fact"])
        opens: list[str] = []
        right = None
        if "param" in node:
            p = self.params[node["param"]]
            if p.status == "open":
                opens.append(p.label)
            else:
                override = p.by_region.get(self.region)
                right = override.value if override else p.value
        elif "other_fact" in node:
            right, more = self.resolve(node["other_fact"])
            missing += more
        else:
            right = node["value"]
        if missing or opens:
            return {"fact": node["fact"], "outcome": "unknown", "missing": missing, "opens": opens}
        kind = fact.type
        if "other_fact" in node:
            right = right.value
        right = [_coerce(r, kind) for r in right] if isinstance(right, list) else _coerce(right, kind)
        ok = _OPS[node["op"]](_coerce(left.value, kind), right)
        return {"fact": node["fact"], "outcome": "pass" if ok else "fail", "missing": [], "opens": []}

    def group(self, node: dict, leaves: list[dict]) -> str:
        if "all" not in node and "any" not in node:
            leaves.append(self.leaf(node))
            return leaves[-1]["outcome"]
        key = "all" if "all" in node else "any"
        start = len(leaves)
        outs = [self.group(c, leaves) for c in node[key]]
        decisive, other = ("fail", "pass") if key == "all" else ("pass", "fail")
        out = decisive if decisive in outs else other if all(o == other for o in outs) else "unknown"
        if out != "unknown":  # a decided group: its unknown leaves could not change the outcome
            for lf in leaves[start:]:
                lf["blocking"] = False
        return out

    def run(self, levels: dict[str, dict]) -> dict:
        res = {}
        for name in ("H", "M"):
            leaves: list[dict] = []
            res[name] = (self.group(levels[name], leaves), leaves)
        (h, h_leaves), (m, m_leaves) = res["H"], res["M"]
        rating = "H" if h == "pass" else "not_rated" if h == "unknown" else "M" if m == "pass" else (
            "not_rated" if m == "unknown" else "L"
        )  # fmt: skip
        deciding = h_leaves if h == "unknown" else m_leaves if rating == "not_rated" else []
        unknown = [lf for lf in deciding if lf["outcome"] == "unknown" and lf.get("blocking", True)]
        return {
            "rating": rating,
            "levels": res,
            "missing": [m for lf in unknown for m in lf["missing"]],
            "opens": [o for lf in unknown for o in lf["opens"]],
        }


def _merge(outcomes: list[str]) -> str:
    return outcomes[0] if len(set(outcomes)) == 1 else "mixed"


def _in_order(labels, order: list[str]) -> list[str]:
    return sorted(set(labels), key=order.index)


def derive(
    rules: CriterionRules,
    region: str,
    values: list[Value],
    *,
    rule_book_version: int,
    run_id: str,
    snapshot: dict,
    notes: list[str] = [],  # noqa: B006 -- copied, never mutated
) -> Result:
    notes = list(notes)
    known = {f.id for f in rules.facts if not f.formula}
    counted: dict[str, list[Value]] = {}
    for v in values:
        if v.counted and v.fact in known:
            counted.setdefault(v.fact, []).append(v)
    confidence = _lowest(v.confidence for vs in counted.values() for v in vs)
    entries = [asdict(v) for v in values]

    def result(rating, levels=None, missing=(), opens=()):
        return Result(
            run_id=run_id, rating=rating, confidence=confidence, notes=notes,
            missing_facts=_in_order(missing, [f.label for f in rules.facts]),
            open_params=_in_order(opens, [p.label for p in rules.params]),
            rule_book_version=rule_book_version, snapshot=snapshot, levels=levels or {}, values=entries,
        )  # fmt: skip

    size = 1
    for vs in counted.values():
        size *= len(vs)
    if size > MAX_COMBINATIONS:
        notes.append(f"Too many value combinations ({size})")
        return result("conflict")

    runs = []
    for pick in itertools.product(*counted.values()):
        combo = _Combo(rules, region, {v.fact: v for v in pick})
        runs.append(combo.run(rules.levels))
        for v in combo.computed.values():
            entry = asdict(v)
            if entry not in entries:
                entries.append(entry)

    levels = {}
    for name in ("H", "M"):
        per_run = [r["levels"][name] for r in runs]
        conditions = [
            ConditionResult(fact=per_run[0][1][i]["fact"], outcome=_merge([p[1][i]["outcome"] for p in per_run]))
            for i in range(len(per_run[0][1]))
        ]
        levels[name] = LevelResult(outcome=_merge([p[0] for p in per_run]), conditions=conditions)

    ratings = {r["rating"] for r in runs}
    rating = ratings.pop() if len(ratings) == 1 else "not_rated" if "not_rated" in ratings else "conflict"
    unrated = [r for r in runs if r["rating"] == "not_rated"] if rating == "not_rated" else []
    missing = [m for r in unrated for m in r["missing"]]
    opens = [o for r in unrated for o in r["opens"]]
    return result(rating, levels, missing, opens)
