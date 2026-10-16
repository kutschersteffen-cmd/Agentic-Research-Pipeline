from __future__ import annotations

import math

import numpy as np

from arp.replication.characteristics_data import CharacteristicPanel
from arp.signal_lab.methods.base import MethodInput, MethodResult, register_method, text_buckets

_MODES = ("intensity", "share", "change")
_DEFAULTS = {
    "top_n": 1, "min_similarity": 0.3, "refit_months": 12, "min_train_months": 12, "mode": "intensity",
    "lookback_months": 12,
}
_MIN_PRIOR = 3
_TOP_WORDS = 5
_MISSING_EXTRA = "topic attention needs the topics extra: pip install 'arp[topics]'"


def default_topic_model(embedder, seed: int = 42, min_topic_size: int = 10):
    """A factory of BERTopic models with a fixed-seed UMAP; the imports are here so the stack loads only when asked for."""
    try:
        from bertopic import BERTopic
        from bertopic.backend import BaseEmbedder
        from umap import UMAP
    except ImportError as e:
        raise ValueError(_MISSING_EXTRA) from e

    class _Backend(BaseEmbedder):
        # find_topics embeds the query with the model's own embedding_model, so it must be the caller's embedder.
        def embed(self, documents, verbose=False):
            return np.asarray(embedder.embed(list(documents)), dtype=float)

    def factory():
        umap = UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=seed)
        return BERTopic(embedding_model=_Backend(), umap_model=umap, min_topic_size=min_topic_size)

    return factory


def _int(params: dict, key: str, low: int) -> int:
    v = params.get(key, _DEFAULTS[key])
    if isinstance(v, bool) or not isinstance(v, int) or v < low:
        raise ValueError(f"topic_attention {key!r} must be an integer >= {low}, got {v!r}")
    return v


def _params(params: dict) -> dict:
    unknown = set(params) - set(_DEFAULTS) - {"query"}
    if unknown:
        raise ValueError(f"topic_attention got unknown params {sorted(unknown)}; expected {sorted([*_DEFAULTS, 'query'])}")
    query = params.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("topic_attention needs a non-empty 'query' string")
    sim = params.get("min_similarity", _DEFAULTS["min_similarity"])
    if isinstance(sim, bool) or not isinstance(sim, (int, float)) or not math.isfinite(sim):
        raise ValueError(f"topic_attention 'min_similarity' must be a finite number, got {sim!r}")
    mode = params.get("mode", _DEFAULTS["mode"])
    if mode not in _MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {', '.join(_MODES)}")
    return {
        "query": query.strip(), "min_similarity": float(sim), "mode": mode,
        "top_n": _int(params, "top_n", 1), "refit_months": _int(params, "refit_months", 1),
        "min_train_months": _int(params, "min_train_months", 1), "lookback": _int(params, "lookback_months", 0),
    }


def _target_topics(model, p: dict) -> list[tuple[int, float]]:
    # BERTopic ranks its outlier topic -1 among the results, so ask for one extra, drop it, then keep top_n.
    ids, sims = model.find_topics(p["query"], p["top_n"] + 1)
    ranked = [(int(t), float(s)) for t, s in zip(ids, sims, strict=True) if int(t) != -1][: p["top_n"]]
    return [(t, s) for t, s in ranked if s >= p["min_similarity"]]


def _top_words(model, topic_id: int) -> list[str]:
    get = getattr(model, "get_topic", None)
    return [w for w, _ in (get(topic_id) or [])[:_TOP_WORDS]] if get else []


@register_method("topic_attention")
def _topic_attention(params: dict, inp: MethodInput) -> MethodResult:
    """Count items per issuer-month in the topics matching a query, refitting walk-forward.

    `change` compares intensities across refits, whose target topics may differ.
    """
    p = _params(params)
    embedder, factory = inp.resources.get("embedder"), inp.resources.get("topic_model")
    if embedder is None:
        raise ValueError("pass an embedder in resources['embedder']")
    if factory is None:
        raise ValueError("pass a topic model factory in resources['topic_model']")

    ends = inp.prices.period_ends
    n = len(ends)
    issuers = list(inp.prices.returns)
    buckets = {t: b for t, b in text_buckets(inp.texts, ends).items() if t in inp.prices.returns}
    empty = [[] for _ in ends]
    docs = {r.item_id: f"{r.title} {r.body}".strip() for b in buckets.values() for m in b for r in m}
    vectors: dict[str, np.ndarray] = {}
    if docs:
        ids = list(docs)
        mat = np.asarray(embedder.embed([docs[k] for k in ids]), dtype=float)
        if mat.ndim != 2 or mat.shape[0] != len(ids) or not np.isfinite(mat).all():
            raise ValueError(f"embedder returned an array of shape {mat.shape}, expected ({len(ids)}, dim) and finite")
        vectors = dict(zip(ids, mat, strict=True))

    def month_items(m: int):
        return [r for t in issuers for r in buckets.get(t, empty)[m]]

    # counts[t][m]: items in a target topic; None where the month has no model or the model has no target topic.
    counts: dict[str, list[int | None]] = {t: [None] * n for t in issuers}
    refits = list(range(p["min_train_months"] - 1, n, p["refit_months"]))
    notes_refits: list[dict] = []
    without_topic = 0
    failed: list[dict] = []
    for k, r in enumerate(refits):
        # Point in time: the model sees only buckets <= r, i.e. text published by month_end_time(period_ends[r]).
        train = [x for m in range(r + 1) for x in month_items(m)]
        found: list[tuple[int, float]] = []
        model = None
        if train:
            model = factory()
            try:
                model.fit([docs[x.item_id] for x in train], np.array([vectors[x.item_id] for x in train]))
            except Exception as e:  # noqa: BLE001  tiny training sets can make UMAP/HDBSCAN fail; that refit's months stay None
                failed.append({"refit_index": r, "period_end": ends[r], "error": type(e).__name__})
                continue
            found = _target_topics(model, p)
        notes_refits.append({
            "refit_index": r, "period_end": ends[r],
            "topics": [{"id": t, "similarity": s, "top_words": _top_words(model, t)} for t, s in found],
        })
        if not found:
            without_topic += 1
            continue
        target = {t for t, _ in found}
        last = refits[k + 1] if k + 1 < len(refits) else n
        for m in range(r, last):
            items = month_items(m)
            for t in issuers:
                counts[t][m] = 0
            if items:
                assigned, _ = model.transform([docs[x.item_id] for x in items], np.array([vectors[x.item_id] for x in items]))
                for x, topic in zip(items, assigned, strict=True):
                    if int(topic) in target:
                        counts[x.company_id][m] += 1

    lookback = p["lookback"]
    values: dict[str, list[float | None]] = {}
    for t in issuers:
        months = buckets.get(t, empty)
        sizes = [len(b) for b in months]
        # No item anywhere in the window is "no data", not zero attention.
        has_data = [any(sizes[max(0, i - lookback) : i + 1]) for i in range(n)]
        intensity: list[float | None] = [
            float(counts[t][i]) if counts[t][i] is not None and has_data[i] else None for i in range(n)
        ]
        if p["mode"] == "intensity":
            values[t] = intensity
        elif p["mode"] == "share":
            # No items this month leaves no denominator.
            values[t] = [x / sizes[i] if x is not None and sizes[i] else None for i, x in enumerate(intensity)]
        else:
            out: list[float | None] = []
            for i, x in enumerate(intensity):
                prior = [v for v in intensity[max(0, i - lookback) : i] if v is not None]
                out.append(x - sum(prior) / len(prior) if x is not None and len(prior) >= _MIN_PRIOR else None)
            values[t] = out
    notes = {"refits": notes_refits, "refits_without_topic": without_topic, "refits_failed": failed}
    return MethodResult(CharacteristicPanel(list(ends), values, f"topic_attention_{p['mode']}"), model=embedder.name, notes=notes)
