"""Benchmarks file: capex benchmarks, R&D tests and redlines per matrix sector, ACT lever wording, assumptions.

Validated on the raw JSON first (as the barrier rule book validator does), so a bad shape reads as an error
line instead of a traceback; the pydantic models only load a file that passed.
"""

from __future__ import annotations

import json
import math
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from arp.config import get_settings
from arp.presets.transition_capex import BOOLEAN_FIELDS, FIELD_IDS
from arp.transition_barrier import dataset as barrier_dataset
from arp.transition_barrier import validation as barrier_validation
from arp.transition_barrier.rule_book import compute_fingerprint
from arp.transition_barrier.validation import _by_id, _dicts, _num, _text, _unit

BENCHMARKS_FILE = "benchmarks.json"
BUNDLED_DIR = Path(__file__).parent / "data"
# Scenario-price region group of each company region (spec section 6).
REGION_GROUP = {"European Union": "advanced economies", "United States": "advanced economies", "China": "selected EMDE"}
STALE = "Benchmarks content changed but version is still"
# The sectors of the bundled barrier criteria_schema.json, in its order (a unit test pins this).
MATRIX_SECTORS: tuple[str, ...] = (
    "Power & Utilities",
    "Steel",
    "Cement",
    "Chemicals",
    "Critical Minerals & Mining",
    "Aviation",
    "Shipping",
    "Heavy-Duty Road Transport",
    "Oil & Gas Upstream",
)


class BenchmarksError(ValueError):
    """The benchmarks file can't be read or fails validation; the message is the first error line."""


class Source(BaseModel):
    title: str
    url: str | None = None
    page: str | None = None
    rationale: str | None = None
    licence: str | None = None


class CapexBenchmark(BaseModel):
    value: float
    unit: str = "%"
    method: str
    source: Source
    licence: str = ""


class RndTest(BaseModel):
    id: str
    label: str
    numerator: str
    denominator: str
    value: float
    unit: str = "%"
    source: Source


class Redline(BaseModel):
    id: str
    label: str
    fact: str
    source: Source


class SectorEntry(BaseModel):
    isic_prefixes: list[str]
    capex: CapexBenchmark
    rnd_tests: list[RndTest] = []
    redlines: list[Redline] = []


class Assumption(BaseModel):
    label: str
    unit: str
    barrier_facts: list[str]


class ScenarioGroup(BaseModel):
    group: str
    source: Source
    prices: dict[int, float]


class Benchmarks(BaseModel):
    version: int = Field(strict=True)
    fingerprint: str
    history: list[dict]
    licence_note: str
    sectors: dict[str, SectorEntry]
    act_levers: dict[str, dict | None]
    assumptions: dict[str, Assumption]
    scenario_prices: list[ScenarioGroup] = []


def data_dir() -> Path:
    return get_settings().transition_alignment_data_dir


def _sourced(item: dict) -> bool:
    s = item.get("source")
    return isinstance(s, dict) and _text(s.get("title"))


def _positive(x) -> bool:  # benchmarks divide the company's share; 0, NaN or Inf would break scoring
    return _num(x) and math.isfinite(x) and x > 0


def _items(name: str, kind: str, value) -> tuple[list[dict], list[str]]:
    """The entries of an R&D test or redline list that have an id, plus a line for each that doesn't."""
    if value is None:
        return [], []
    if not isinstance(value, list):
        return [], [f"{name}: invalid {kind}s: expected a list"]
    good = [i for i in value if isinstance(i, dict) and isinstance(i.get("id"), str)]
    bad = [f"{name}: invalid {kind}: expected an object with an id"] * (len(value) - len(good))
    return good, bad


def _rule2(name: str, entry: dict) -> list[str]:
    out = []
    capex = entry.get("capex")
    if not isinstance(capex, dict):
        out.append(f"{name}: invalid capex: expected an object")
    else:
        if not _sourced(capex):
            out.append(f"{name}: capex benchmark has no source")
        if not _positive(capex.get("value")):
            out.append(f"{name}: invalid capex value: expected a number above 0")
    tests, bad = _items(name, "R&D test", entry.get("rnd_tests"))
    out += bad
    for t in tests:
        if not _sourced(t):
            out.append(f"{name}: R&D test '{t['id']}' has no source")
        if not _positive(t.get("value")):
            out.append(f"{name}: invalid R&D test '{t['id']}' value: expected a number above 0")
    redlines, bad = _items(name, "redline", entry.get("redlines"))
    out += bad
    out += [f"{name}: redline '{r['id']}' has no source" for r in redlines if not _sourced(r)]
    return out


def _rule3(name: str, entry: dict) -> list[str]:
    tests, _ = _items(name, "R&D test", entry.get("rnd_tests"))
    redlines, _ = _items(name, "redline", entry.get("redlines"))
    named = [(t.get(k), FIELD_IDS) for t in tests for k in ("numerator", "denominator")]
    named += [(r.get("fact"), BOOLEAN_FIELDS) for r in redlines]  # a redline needs a Yes/No field
    return [f"{name}: unknown field '{f}'" for f, allowed in named if f not in allowed]


def _rule4(entries: dict[str, dict]) -> list[str]:
    out, prefixes = [], []
    for name, entry in entries.items():
        p = entry.get("isic_prefixes")
        if not (isinstance(p, list) and p and all(_text(x) for x in p)):
            out.append(f"{name}: invalid isic_prefixes: expected a list of prefixes")
            continue
        prefixes += [(name, x) for x in p]
    for i, (s1, p1) in enumerate(prefixes):
        for s2, p2 in prefixes[i + 1 :]:
            if s1 != s2 and (p1.startswith(p2) or p2.startswith(p1)):
                out.append(f"ISIC prefix '{min(p1, p2, key=len)}' is in two sectors")
    return out


def _rule5(raw: dict, raw_rule_book: dict) -> list[str]:
    actions = raw_rule_book.get("actions")
    ids = [
        a["id"]
        for v in (actions.values() if isinstance(actions, dict) else [])
        for a in _dicts(v)
        if isinstance(a.get("id"), str)
    ]
    levers = raw.get("act_levers")
    if not isinstance(levers, dict):
        return ["Benchmarks: invalid act_levers: expected an object"]
    return [f"No ACT lever entry for action: {a}" for a in ids if a not in levers] + [
        f"Unknown action in act_levers: {a}" for a in levers if a not in ids
    ]


def _rule6(raw: dict, raw_rule_book: dict) -> list[str]:
    assumptions = raw.get("assumptions")
    if not isinstance(assumptions, dict):
        return ["Benchmarks: invalid assumptions: expected an object"]
    criteria = raw_rule_book.get("criteria")
    criteria = criteria if isinstance(criteria, dict) else {}
    out = []
    for aid, a in assumptions.items():
        refs = a.get("barrier_facts") if isinstance(a, dict) else None
        if not (isinstance(refs, list) and all(isinstance(r, str) for r in refs)):
            out.append(f"Benchmarks: invalid assumption '{aid}': expected barrier_facts as a list of ids")
            continue
        for ref in refs:
            code, _, fid = ref.partition(".")
            entry = criteria.get(code)
            facts = _by_id(entry.get("facts")) if isinstance(entry, dict) else {}
            if fid not in facts:
                out.append(f"Assumption '{aid}' names unknown barrier fact '{ref}'")
                continue
            unit = _unit(facts[fid], facts)
            if unit != a.get("unit"):
                out.append(f"Assumption '{aid}' is in {a.get('unit')}, '{ref}' is in {unit or 'no unit'}")
    return out


def _scenario_lines(raw: dict, required: bool) -> list[str]:
    """Scenario prices: optional in a file (older signed files stay valid), required in the bundled one."""
    if "scenario_prices" not in raw:
        return ["Scenario prices: missing"] if required else []
    groups = raw["scenario_prices"]
    if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
        return ["Scenario prices: invalid scenario_prices: expected a list of objects"]
    known = set(REGION_GROUP.values())
    out = []
    for g in groups:
        name = g.get("group")
        if name not in known:
            out.append(f"Scenario prices: unknown region group '{name}'")
        if not _sourced(g):
            out.append(f"Scenario prices: {name} has no source")
    return out


def validate_benchmarks(raw: dict, raw_rule_book: dict, raw_schema: dict, require_scenarios: bool = False) -> list[str]:
    """Every benchmarks error, one line each, in spec rule order (1-7); within a rule, file order."""
    if not all(isinstance(x, dict) for x in (raw, raw_rule_book, raw_schema)):
        return ["Benchmarks: invalid benchmarks, rule book or criteria schema: expected an object"]
    sectors = raw.get("sectors")
    r1 = [] if isinstance(sectors, dict) else ["Benchmarks: invalid sectors: expected an object"]
    sectors = sectors if isinstance(sectors, dict) else {}
    active = dict.fromkeys(c["sector"] for c in _dicts(raw_schema.get("criteria")) if isinstance(c.get("sector"), str))
    r1 += [f"Sector not in the transition-barrier matrix: {s}" for s in sectors if s not in MATRIX_SECTORS]
    r1 += [f"Missing benchmarks entry: {s}" for s in active if s not in sectors]
    r1 += [f"{s}: invalid entry: expected an object" for s, e in sectors.items() if not isinstance(e, dict)]
    entries = {s: e for s, e in sectors.items() if isinstance(e, dict)}

    stale = raw.get("fingerprint") != compute_fingerprint(raw)
    return (
        r1
        + [e for s, entry in entries.items() for e in _rule2(s, entry)]
        + [e for s, entry in entries.items() for e in _rule3(s, entry)]
        + _rule4(entries)
        + _rule5(raw, raw_rule_book)
        + _rule6(raw, raw_rule_book)
        + _scenario_lines(raw, require_scenarios)
        + ([f"{STALE} {raw.get('version')}"] if stale else [])
    )


def _model_errors(raw: dict) -> list[str]:
    """Backstop: whatever the raw rules let through must still load, so "valid" always means "loads"."""
    try:
        Benchmarks.model_validate(raw)
    except ValidationError as exc:
        return [f"Benchmarks: invalid {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return []


def _read(directory: Path) -> dict:
    path = Path(directory) / BENCHMARKS_FILE
    if not path.exists():
        raise BenchmarksError(f"Benchmarks not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:  # IsADirectoryError, PermissionError
        raise BenchmarksError(f"Cannot read {path}: {exc.strerror or exc}") from None
    except ValueError as exc:
        raise BenchmarksError(f"{BENCHMARKS_FILE} is not valid JSON: {exc}") from None


def read_and_validate(directory: Path, barrier_dir: Path) -> tuple[dict, list[str]]:
    """Raw benchmarks from `directory` and their errors, checked against the barrier data in `barrier_dir`.

    Raises BenchmarksError when the file can't be read as JSON; the barrier loader's own errors propagate.
    """
    raw = _read(directory)
    raw_rule_book, raw_schema, _ = barrier_validation.read_and_validate(barrier_dir)
    errors = validate_benchmarks(raw, raw_rule_book, raw_schema, Path(directory).resolve() == BUNDLED_DIR.resolve())
    if isinstance(raw, dict) and all(e.startswith(STALE) for e in errors):
        errors = _model_errors(raw) + errors
    return raw, errors


def count_redlines(raw: dict) -> int:
    sectors = raw.get("sectors") if isinstance(raw, dict) else None
    entries = [e for e in sectors.values() if isinstance(e, dict)] if isinstance(sectors, dict) else []
    return sum(len(_dicts(e.get("redlines"))) for e in entries)


def sign_benchmarks(directory: Path, approved_by: str, today: date) -> int:
    """Bump the version, refresh the fingerprint and log the approval. Returns the new version."""
    raw = _read(directory)
    raw["version"] += 1
    raw["fingerprint"] = compute_fingerprint(raw)
    raw.setdefault("history", []).append(
        {
            "version": raw["version"],
            "fingerprint": raw["fingerprint"],
            "approved_by": approved_by,
            "approved_at": today.isoformat(),
        }
    )
    (Path(directory) / BENCHMARKS_FILE).write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return raw["version"]


def _validated(directory: Path | None) -> dict:
    raw, errors = read_and_validate(directory or data_dir(), barrier_dataset.data_dir())
    if errors:
        raise BenchmarksError(errors[0])
    return raw


def check_benchmarks(directory: Path | None = None) -> None:
    """Raise BenchmarksError naming the first error unless the benchmarks file is valid."""
    _validated(directory)


@lru_cache
def load_benchmarks(directory: Path | None = None) -> Benchmarks:
    return Benchmarks.model_validate(_validated(directory))


def reset_cache() -> None:
    """Drop the loader cache; needed after the data directory setting changes."""
    load_benchmarks.cache_clear()


def sector_for_isic(b: Benchmarks, isic: str | None) -> str | None:
    """The matrix sector whose prefix the ISIC code starts with (prefixes never overlap), else None."""
    if not isic:
        return None
    return next((name for name, s in b.sectors.items() if any(isic.startswith(p) for p in s.isic_prefixes)), None)


def citation(s: Source) -> str:
    return f"{s.title} p.{s.page}" if s.page else s.title
