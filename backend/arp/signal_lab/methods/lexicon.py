from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

from arp.replication.characteristics_data import CharacteristicPanel
from arp.signal_lab.methods.base import MethodInput, MethodResult, register_method, text_buckets, trainable_months
from arp.signal_lab.stats import _average_ranks

_TOKEN = re.compile(r"[^\W\d_]{3,}")
_GRID = np.arange(1, 1000) / 1000
_DEFAULTS = {"alpha_plus": 0.05, "alpha_minus": 0.05, "kappa": 20, "lam": 1.0, "min_train_months": 24}
_TOP = 20


def _number(params: dict, key: str, lo: float, hi: float | None = None) -> float:
    v = params.get(key, _DEFAULTS[key])
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < lo or (hi is not None and v > hi):
        bound = f"in [{lo}, {hi}]" if hi is not None else f">= {lo}"
        raise ValueError(f"sestm {key!r} must be a number {bound}, got {v!r}")
    return float(v)


def _integer(params: dict, key: str) -> int:
    v = params.get(key, _DEFAULTS[key])
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise ValueError(f"sestm {key!r} must be an integer >= 1, got {v!r}")
    return v


def screen(
    docs: list[Counter[str]], positive: list[bool], *, alpha_plus: float, alpha_minus: float, kappa: int
) -> dict[str, float]:
    """Step 1: the charged words, each mapped to the share f_w of the documents containing it that are positive."""
    k: Counter[str] = Counter()
    k_pos: Counter[str] = Counter()
    for d, up in zip(docs, positive, strict=True):
        k.update(d.keys())
        if up:
            k_pos.update(d.keys())
    out = {}
    for w, n in k.items():
        f = k_pos[w] / n
        if n >= kappa and (f >= 0.5 + alpha_plus or f <= 0.5 - alpha_minus):
            out[w] = f
    return out


def topics(docs: list[Counter[str]], returns: list[float], charged: list[str]) -> np.ndarray | None:
    """Step 2: the |S| x 2 matrix [O+, O-], or None when the regression or a column is degenerate."""
    if not charged:
        return None
    p_hat = (_average_ranks(np.asarray(returns, dtype=float)) + 1) / len(returns)
    index = {w: n for n, w in enumerate(charged)}
    rows, ps = [], []
    for d, p in zip(docs, p_hat, strict=True):
        hits = {index[w]: c for w, c in d.items() if w in index}
        if hits:
            h = np.zeros(len(charged))
            h[list(hits)] = list(hits.values())
            rows.append(h / h.sum())
            ps.append(p)
    if not rows:
        return None
    w = np.array([ps, [1 - p for p in ps]])
    wwt = w @ w.T
    if np.linalg.matrix_rank(wwt) < 2:
        return None
    o = np.clip(np.array(rows).T @ w.T @ np.linalg.inv(wwt), 0, None)
    sums = o.sum(axis=0)
    return None if (sums == 0).any() else o / sums


def score(docs: list[Counter[str]], charged: list[str], o: np.ndarray, lam: float) -> list[float | None]:
    """Step 3: each document's penalised maximum-likelihood tone on the 0.001 grid; None without charged words."""
    if not docs:
        return []
    d = np.array([[doc.get(w, 0) for w in charged] for doc in docs], dtype=float)
    s = d.sum(axis=1)
    log_mix = np.log(np.clip(np.outer(_GRID, o[:, 0]) + np.outer(1 - _GRID, o[:, 1]), 1e-12, None))
    with np.errstate(invalid="ignore", divide="ignore"):
        objective = (d @ log_mix.T) / s[:, None] + lam * np.log(_GRID * (1 - _GRID))
    best = _GRID[np.argmax(objective, axis=1)]
    return [float(p) if n > 0 else None for p, n in zip(best, s, strict=True)]


@register_method("sestm")
def _sestm(params: dict, inp: MethodInput) -> MethodResult:
    unknown = set(params) - set(_DEFAULTS)
    if unknown:
        raise ValueError(f"sestm got unknown params {sorted(unknown)}; expected {sorted(_DEFAULTS)}")
    alpha_plus = _number(params, "alpha_plus", 0.0, 0.5)
    alpha_minus = _number(params, "alpha_minus", 0.0, 0.5)
    kappa = _integer(params, "kappa")
    lam = _number(params, "lam", 0.0)
    min_train = _integer(params, "min_train_months")

    ends = inp.prices.period_ends
    buckets = text_buckets(inp.texts, ends)
    issuers = list(inp.prices.returns)
    docs = {
        t: [[Counter(_TOKEN.findall(f"{r.title} {r.body}".lower())) for r in b] for b in buckets[t]]
        for t in issuers if t in buckets
    }
    # Month j's labelled documents: (counts, return at j + 1, above that month's cross-sectional median).
    labelled: list[list[tuple[Counter[str], float, bool]]] = []
    for j in range(len(ends) - 1):
        rets = {t: r for t in docs if docs[t][j] and (r := inp.prices.returns[t][j + 1]) is not None}
        med = float(np.median(list(rets.values()))) if rets else 0.0
        labelled.append([(d, r, r > med) for t, r in rets.items() for d in docs[t][j]])

    values: dict[str, list[float | None]] = {t: [None] * len(ends) for t in issuers}
    without_model: list[str] = []
    last_charged: dict[str, float] | None = None
    # shortcut: full refit per month, slow on multi-year corpora; upgrade to incremental counts when a real corpus is used
    for i in range(len(ends)):
        months = [labelled[j] for j in trainable_months(i) if labelled[j]]
        if len(months) < min_train:
            continue
        train = [x for m in months for x in m]
        charged_f = screen(
            [x[0] for x in train], [x[2] for x in train], alpha_plus=alpha_plus, alpha_minus=alpha_minus, kappa=kappa
        )
        last_charged = charged_f
        charged = sorted(charged_f)
        o = topics([x[0] for x in train], [x[1] for x in train], charged)
        if o is None:
            without_model.append(ends[i])
            continue
        for t in docs:
            scored = [p for p in score(docs[t][i], charged, o, lam) if p is not None]
            values[t][i] = sum(scored) / len(scored) if scored else None

    notes: dict = {"months_without_model": without_model}
    if last_charged is not None:
        notes["charged_set_size"] = len(last_charged)
        notes["most_positive_words"] = sorted(
            (w for w, f in last_charged.items() if f > 0.5), key=lambda w: (-last_charged[w], w)
        )[:_TOP]
        notes["most_negative_words"] = sorted(
            (w for w, f in last_charged.items() if f < 0.5), key=lambda w: (last_charged[w], w)
        )[:_TOP]
    return MethodResult(CharacteristicPanel(list(ends), values, "sestm"), notes=notes)
