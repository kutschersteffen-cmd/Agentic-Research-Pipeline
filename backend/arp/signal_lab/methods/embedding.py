from __future__ import annotations

import math

import numpy as np

from arp.replication.characteristics_data import CharacteristicPanel
from arp.signal_lab.methods.base import MethodInput, MethodResult, register_method, text_buckets, trainable_months
from arp.signal_lab.stats import _average_ranks

_DEFAULTS = {"alpha": 10.0, "min_train_months": 24}


def default_embedder(model_name: str = "BAAI/bge-small-en-v1.5"):
    """A fastembed-backed embedder; the import is here so the model stack loads only when asked for."""
    from fastembed import TextEmbedding

    class _FastEmbedder:
        name = model_name

        def __init__(self) -> None:
            self._model = TextEmbedding(model_name=model_name)

        def embed(self, texts: list[str]) -> np.ndarray:
            vecs = np.asarray(list(self._model.embed(texts)), dtype=float)
            return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

    return _FastEmbedder()


def ridge_predict(x: np.ndarray, y: np.ndarray, x_new: np.ndarray, *, alpha: float) -> np.ndarray:
    """Closed-form ridge on centred data, so the intercept (the training mean of y) is not penalised."""
    mx, my = x.mean(axis=0), y.mean()
    xc = x - mx
    beta = np.linalg.solve(xc.T @ xc + alpha * np.eye(x.shape[1]), xc.T @ (y - my))
    return (x_new - mx) @ beta + my


def _params(params: dict) -> tuple[float, int]:
    unknown = set(params) - set(_DEFAULTS)
    if unknown:
        raise ValueError(f"embedding_ridge got unknown params {sorted(unknown)}; expected {sorted(_DEFAULTS)}")
    alpha = params.get("alpha", _DEFAULTS["alpha"])
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or alpha <= 0:
        raise ValueError(f"embedding_ridge 'alpha' must be a number > 0, got {alpha!r}")
    min_train = params.get("min_train_months", _DEFAULTS["min_train_months"])
    if isinstance(min_train, bool) or not isinstance(min_train, int) or min_train < 1:
        raise ValueError(f"embedding_ridge 'min_train_months' must be an integer >= 1, got {min_train!r}")
    return float(alpha), min_train


@register_method("embedding_ridge")
def _embedding_ridge(params: dict, inp: MethodInput) -> MethodResult:
    alpha, min_train = _params(params)
    embedder = inp.resources.get("embedder")
    if embedder is None:
        raise ValueError("pass an embedder in resources['embedder']")

    ends = inp.prices.period_ends
    issuers = list(inp.prices.returns)
    buckets = text_buckets(inp.texts, ends)
    items = {r.item_id: f"{r.title} {r.body}".strip() for t in issuers for b in buckets.get(t, []) for r in b}
    vectors: dict[str, np.ndarray] = {}
    if items:
        ids = list(items)
        mat = np.asarray(embedder.embed([items[k] for k in ids]), dtype=float)
        if mat.ndim != 2 or mat.shape[0] != len(ids) or not np.isfinite(mat).all():
            raise ValueError(f"embedder returned an array of shape {mat.shape}, expected ({len(ids)}, dim) and finite")
        vectors = dict(zip(ids, mat, strict=True))

    # feature[t][j]: mean embedding of issuer t's month-j items, or None when it has no text that month.
    feature = {
        t: [np.mean([vectors[r.item_id] for r in b], axis=0) if b else None for b in buckets[t]]
        for t in issuers if t in buckets
    }
    # Month j's training rows: (feature, percentile rank of the return at j + 1 among the month's rows).
    rows: list[tuple[np.ndarray, np.ndarray]] = []
    for j in range(len(ends) - 1):
        pairs = [(feature[t][j], r) for t in feature if feature[t][j] is not None and (r := inp.prices.returns[t][j + 1]) is not None]
        if pairs:
            ranks = (_average_ranks(np.array([r for _, r in pairs])) + 1) / len(pairs)
            rows.append((np.array([f for f, _ in pairs]), ranks))
        else:
            rows.append((np.empty((0, 0)), np.empty(0)))

    values: dict[str, list[float | None]] = {t: [None] * len(ends) for t in issuers}
    for i in range(len(ends)):
        months = [rows[j] for j in trainable_months(i) if len(rows[j][1])]
        if len(months) < min_train:
            continue
        x = np.vstack([m[0] for m in months])
        y = np.concatenate([m[1] for m in months])
        todo = [t for t in feature if feature[t][i] is not None]
        if not todo:
            continue
        pred = ridge_predict(x, y, np.array([feature[t][i] for t in todo]), alpha=alpha)
        for t, p in zip(todo, pred, strict=True):
            values[t][i] = float(p)
    return MethodResult(CharacteristicPanel(list(ends), values, "embedding_ridge"), model=embedder.name)
