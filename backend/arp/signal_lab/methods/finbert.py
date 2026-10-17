# FinBERT (ProsusAI/finbert) is CC BY-NC-SA 4.0, approved for internal research by the owner on 2026-10-16; no output or model derived from it is sold or distributed.
from __future__ import annotations

import math

from arp.replication.characteristics_data import CharacteristicPanel
from arp.signal_lab.methods.base import MethodInput, MethodResult, register_method, text_buckets

_MAX_TOKENS = 512
_NEEDS_EXTRA = "FinBERT needs the finbert extra: pip install 'arp[finbert]'"


def default_finbert(model_name: str = "ProsusAI/finbert"):
    """A Hugging Face pipeline scorer; the import is here so the model stack loads only when asked for."""
    try:
        from transformers import pipeline
    # A transformers install can import-fail with RuntimeError too (e.g. a torch/torchvision mismatch).
    except Exception as exc:
        raise ValueError(_NEEDS_EXTRA) from exc

    class _FinBert:
        name = model_name

        def __init__(self) -> None:
            self._pipe = pipeline(
                "text-classification", model=model_name, top_k=None, truncation=True, max_length=_MAX_TOKENS
            )

        def score(self, texts: list[str]) -> list[tuple[float, float, float]]:
            out = []
            for labels in self._pipe(texts):
                by_label = {d["label"].lower(): d["score"] for d in labels}
                missing = {"positive", "negative", "neutral"} - set(by_label)
                if missing:
                    raise ValueError(f"{model_name} did not return the labels {sorted(missing)}; got {sorted(by_label)}")
                out.append((by_label["positive"], by_label["negative"], by_label["neutral"]))
            return out

        def truncated(self, texts: list[str]) -> int:
            ids = self._pipe.tokenizer(texts, truncation=False)["input_ids"]
            return sum(len(x) > _MAX_TOKENS for x in ids)

    return _FinBert()


def _triples(raw, n: int) -> list[tuple[float, float, float]]:
    ok = isinstance(raw, (list, tuple)) and len(raw) == n
    if ok:
        for row in raw:
            ok = (
                isinstance(row, (list, tuple))
                and len(row) == 3
                and all(isinstance(p, (int, float)) and not isinstance(p, bool) and math.isfinite(p) and 0 <= p <= 1 for p in row)
            )
            if not ok:
                break
    if not ok:
        raise ValueError(f"FinBERT scorer must return {n} (positive, negative, neutral) triples of finite numbers in [0, 1]")
    return [tuple(map(float, row)) for row in raw]


@register_method("finbert")
def _finbert(params: dict, inp: MethodInput) -> MethodResult:
    if params:
        raise ValueError(f"finbert takes no params, got {sorted(params)}")
    scorer = inp.resources.get("finbert")
    if scorer is None:
        raise ValueError("pass a scorer in resources['finbert']")

    ends = inp.prices.period_ends
    issuers = list(inp.prices.returns)
    buckets = text_buckets(inp.texts, ends)
    # First 512 tokens only: the model truncates longer documents.
    items = {r.item_id: r.title + "\n\n" + r.body for t in issuers for b in buckets.get(t, []) for r in b}
    docs = list(items.values())
    scores: dict[str, float] = {}
    truncated = 0
    if docs:
        triples = _triples(scorer.score(docs), len(docs))
        scores = {k: pos - neg for k, (pos, neg, _) in zip(items, triples, strict=True)}
        if hasattr(scorer, "truncated"):
            truncated = int(scorer.truncated(docs))

    values: dict[str, list[float | None]] = {
        t: [sum(scores[r.item_id] for r in b) / len(b) if b else None for b in buckets[t]] if t in buckets else [None] * len(ends)
        for t in issuers
    }
    return MethodResult(CharacteristicPanel(list(ends), values, "finbert"), model=scorer.name, notes={"truncated": truncated})
