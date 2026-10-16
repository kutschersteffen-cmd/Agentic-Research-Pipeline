from __future__ import annotations

import numpy as np

from arp.replication.characteristics_data import CharacteristicPanel
from arp.signal_lab.methods.base import MethodInput, MethodResult, register_method, run_method
from arp.signal_lab.stats import _average_ranks


def _positive_int(step: dict, key: str, default: int | None = None) -> int:
    v = step.get(key, default)
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise ValueError(f"step {step['op']!r} needs {key} as an integer >= 1, got {v!r}")
    return v


def _per_name(panel: CharacteristicPanel, fn) -> dict[str, list[float | None]]:
    return {t: [fn(v, i) for i in range(len(v))] for t, v in panel.values.items()}


def _cross_section(panel: CharacteristicPanel, scale) -> dict[str, list[float | None]]:
    out: dict[str, list[float | None]] = {t: [None] * len(panel.period_ends) for t in panel.values}
    for i in range(len(panel.period_ends)):
        names = [t for t, v in panel.values.items() if v[i] is not None]
        x = np.array([panel.values[t][i] for t in names], dtype=float)
        if len(names) < 3 or x.std() == 0.0:
            continue
        for t, s in zip(names, scale(x), strict=True):
            out[t][i] = float(s)
    return out


def apply_step(panel: CharacteristicPanel, step: dict) -> CharacteristicPanel:
    op = step.get("op")
    if op == "change":
        lag = _positive_int(step, "lag", 1)
        values = _per_name(
            panel, lambda v, i: v[i] - v[i - lag] if i >= lag and v[i] is not None and v[i - lag] is not None else None
        )
    elif op == "decay":
        hl = step.get("half_life_months")
        if not isinstance(hl, (int, float)) or isinstance(hl, bool) or hl <= 0:
            raise ValueError(f"step 'decay' needs half_life_months > 0, got {hl!r}")

        def decay(v: list[float | None], i: int) -> float | None:
            if v[i] is None:
                return None
            w = [(0.5 ** ((i - j) / hl), v[j]) for j in range(i + 1) if v[j] is not None]
            return sum(a * b for a, b in w) / sum(a for a, _ in w)

        values = _per_name(panel, decay)
    elif op == "zscore":
        values = _cross_section(panel, lambda x: (x - x.mean()) / x.std())
    elif op == "rank":
        values = _cross_section(panel, lambda x: (_average_ranks(x) + 1) / len(x))
    elif op == "mean_last":
        n = _positive_int(step, "months")

        def mean_last(v: list[float | None], i: int) -> float | None:
            win = v[i - n + 1 : i + 1] if i >= n - 1 else []
            return sum(win) / n if len(win) == n and None not in win else None

        values = _per_name(panel, mean_last)
    else:
        raise ValueError(f"unknown transform op {op!r}; known: change, decay, zscore, rank, mean_last")
    return CharacteristicPanel(list(panel.period_ends), values, f"{panel.source}|{op}")


@register_method("transform")
def _transform(params: dict, inp: MethodInput) -> MethodResult:
    base = run_method(params["base"], inp)
    panel = base.panel
    for step in params.get("steps", []):
        panel = apply_step(panel, step)
    return MethodResult(panel, model=base.model, notes=base.notes)


@register_method("composite")
def _composite(params: dict, inp: MethodInput) -> MethodResult:
    specs = params.get("components") or []
    if not specs:
        raise ValueError("composite needs at least one component")
    weights = params.get("weights") or [1.0] * len(specs)
    if len(weights) != len(specs):
        raise ValueError(f"composite got {len(weights)} weights for {len(specs)} components")
    if any(w <= 0 for w in weights):
        raise ValueError("composite weights must be positive")
    need = params.get("min_components") or len(specs)
    if not 1 <= need <= len(specs):
        raise ValueError(f"min_components must be between 1 and {len(specs)}, got {need}")

    results = [run_method(s, inp) for s in specs]
    models = sorted({r.model for r in results if r.model})
    if len(models) > 1:
        raise ValueError(f"composite of different models is not supported: {', '.join(models)}")
    ends = results[0].panel.period_ends
    if any(r.panel.period_ends != ends for r in results):
        raise ValueError("composite components are on different grids")

    ranked = [apply_step(r.panel, {"op": "rank"}).values for r in results]
    values: dict[str, list[float | None]] = {}
    for t in dict.fromkeys(t for r in ranked for t in r):
        row: list[float | None] = []
        for i in range(len(ends)):
            have = [(w, r[t][i]) for w, r in zip(weights, ranked, strict=True) if t in r and r[t][i] is not None]
            row.append(sum(w * x for w, x in have) / sum(w for w, _ in have) if len(have) >= need else None)
        values[t] = row
    return MethodResult(CharacteristicPanel(list(ends), values, "composite"), model=models[0] if models else None)
