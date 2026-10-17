from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.signal_lab.baselines import momentum_panel
from arp.signal_lab.cutoffs import CutoffTable
from arp.signal_lab.evidence import evaluate_signal, sentiment_spec
from arp.signal_lab.registry import ExperimentRecord, Recipe, Registry, experiment_id_for
from arp.signal_lab.text_store import TextRecord
from arp.signal_lab.times import month_end_time


@dataclass
class MethodInput:
    texts: list[TextRecord]
    prices: PricePanel
    panels: dict[str, CharacteristicPanel] = field(default_factory=dict)
    # Optional heavy dependencies a method may need: llm, embedder, finbert, search.
    resources: dict[str, Any] = field(default_factory=dict)


@dataclass
class MethodResult:
    panel: CharacteristicPanel
    model: str | None = None
    notes: dict = field(default_factory=dict)


MethodFn = Callable[[dict, MethodInput], MethodResult]
_METHODS: dict[str, MethodFn] = {}


def register_method(name: str) -> Callable[[MethodFn], MethodFn]:
    def deco(fn: MethodFn) -> MethodFn:
        _METHODS[name] = fn
        return fn

    return deco


def get_method(name: str) -> MethodFn:
    if name not in _METHODS:
        raise ValueError(f"unknown method {name!r}; known methods: {', '.join(sorted(_METHODS))}")
    return _METHODS[name]


def run_method(spec: dict, inp: MethodInput) -> MethodResult:
    return get_method(spec["method"])(spec.get("params", {}), inp)


def text_buckets(texts: list[TextRecord], period_ends: list[str]) -> dict[str, list[list[TextRecord]]]:
    """Per issuer, one list per grid index i holding text with event time in
    (month_end_time(period_ends[i-1]), month_end_time(period_ends[i])]; bucket 0 starts with its calendar month."""
    ends = [month_end_time(p) for p in period_ends]
    first = ends[0][:8] + "01T00:00:00Z"
    out: dict[str, list[list[TextRecord]]] = {}
    for t in texts:
        if t.company_id is None or t.event_time < first:
            continue
        i = bisect_left(ends, t.event_time)
        if i < len(ends):
            out.setdefault(t.company_id, [[] for _ in ends])[i].append(t)
    return out


def trainable_months(i: int) -> range:
    """Months whose label is known at grid index i: month j is labelled by the return at index j + 1."""
    return range(0, i)


@register_method("panel")
def _panel(params: dict, inp: MethodInput) -> MethodResult:
    name = params["name"]
    if name not in inp.panels:
        raise ValueError(f"missing panel {name!r}; available: {', '.join(sorted(inp.panels)) or 'none'}")
    model = params.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError(f"panel 'model' must be a string or null, got {model!r}")
    return MethodResult(inp.panels[name], model=model)


@register_method("price_momentum")
def _price_momentum(params: dict, inp: MethodInput) -> MethodResult:
    return MethodResult(momentum_panel(inp.prices, **params))


def run_recipe(
    recipe: Recipe, inp: MethodInput, *, registry: Registry, cutoffs: CutoffTable, data_version: str
) -> ExperimentRecord:
    result = run_method({"method": recipe.method, "params": recipe.params}, inp)
    if result.panel.period_ends != inp.prices.period_ends:
        raise ValueError(f"method {recipe.method!r} returned a panel on a different grid than the prices")
    cutoff = cutoffs.cutoff_for(result.model) if result.model else None
    experiment_id = experiment_id_for(recipe, data_version=data_version, model=result.model, cutoff=cutoff)
    # A re-run of a registered experiment is not a new trial (same rule as `arp signals evaluate`).
    n_trials = registry.trial_count(recipe) + (0 if registry.has(experiment_id) else 1)
    report = evaluate_signal(
        result.panel,
        inp.prices,
        sentiment_spec("signal", start=recipe.window_start, end=recipe.window_end),
        model=result.model,
        cutoffs=cutoffs,
        cost_bps=recipe.cost_bps,
        n_trials=n_trials,
        baselines={"price_momentum": momentum_panel(inp.prices), **inp.panels},
        forward_months=recipe.forward_months,
    )
    return registry.register(
        recipe, report, data_version=data_version, model=result.model, cutoff=cutoff, notes=result.notes
    )
