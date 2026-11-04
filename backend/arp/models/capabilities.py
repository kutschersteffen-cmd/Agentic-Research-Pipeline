"""Public capabilities: cache -> arp-models (cloud) -> local fallback. embed and rerank skip the cache."""
from collections.abc import Callable

import numpy as np

from arp.compute import client
from arp.models import local
from arp.models.cache import cached
from arp.models.registry import entry, model_header, provenance


def classify(texts: list[str], labels: list[str],
             hypothesis: str = "This text is about {}.") -> tuple[list[dict[str, float]], dict]:
    e = entry("nli")
    labs = sorted(set(labels))
    where = ["cloud"] if client.models_configured() else ["local"]

    def compute(ts):
        if where[0] == "cloud":
            r = client.classify_scores(ts, labs, hypothesis, model_header(e))
            if r is not None:
                return r
            where[0] = "local"
        return local.nli_scores(e, ts, labs, hypothesis)

    res = cached(e, texts, (*labs, hypothesis), compute) if texts else []
    return res, provenance(e, where[0])


def tag(model_key: str, texts: list[str]) -> tuple[list[dict], dict]:
    e = entry(model_key)
    if e.capability != "tag":
        raise ValueError(f"{model_key!r} is a {e.capability} model, not a tag model")
    where = ["cloud"] if client.models_configured() else ["local"]

    def compute(ts):
        if where[0] == "cloud":
            r = client.tag_result(model_key, ts, model_header(e))
            if r is not None:
                return r
            where[0] = "local"
        return local.tag_scores(e, ts)

    res = cached(e, texts, None, compute) if texts else []
    return res, provenance(e, where[0])


def spans(texts: list[str], labels: list[str], threshold: float = 0.5) -> tuple[list[list[dict]], dict]:
    e = entry("gliner")
    labs = sorted(set(labels))
    where = ["cloud"] if client.models_configured() else ["local"]

    def compute(ts):
        if where[0] == "cloud":
            r = client.spans_result(ts, labs, threshold, model_header(e))
            if r is not None:
                return r
            where[0] = "local"
        return local.span_scores(e, ts, labs, threshold)

    res = cached(e, texts, (*labs, str(threshold)), compute) if texts else []
    # a span whose offsets do not select its own text is dropped, from the cache as well
    res = [[sp for sp in found if t[sp["start"]:sp["end"]] == sp["text"]] for t, found in zip(texts, res, strict=True)]
    return res, provenance(e, where[0])


def embed(texts: list[str], load: Callable | None = None) -> tuple[np.ndarray, dict]:
    """(n, dim) float32 vectors, all from the cloud or all local. `load` overrides the local model getter."""
    e = entry("embed")
    try:
        remote = client.embed(texts) if texts else None
    except Exception:  # noqa: BLE001 - the client never raises; whatever does, the local model still answers
        remote = None
    if remote is not None and np.shape(remote) == (len(texts), e.dim):  # never another model's vectors
        return np.asarray(remote, dtype=np.float32), provenance(e, "cloud")
    model = load() if load else local.text_embedding(e.hf_id)
    return np.asarray(list(model.embed(texts)), dtype=np.float32), provenance(e, "local")


def rerank(query: str, texts: list[str],
           score: Callable[[str, list[str]], list[float]] | None = None) -> tuple[list[float] | None, dict]:
    """Cross-encoder scores, one per text. With the cloud configured, None on failure: the slow local
    model is never its fallback. Local errors propagate. `score` overrides the local scorer."""
    e = entry("rerank")
    if client.models_configured():
        return client.rerank_scores(query, texts), provenance(e, "cloud")
    if score is None:
        return [float(s) for s in local.cross_encoder(e.hf_id).rerank(query, texts)], provenance(e, "local")
    return score(query, texts), provenance(e, "local")
