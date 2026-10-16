from __future__ import annotations

import re

from arp.replication.characteristics_data import CharacteristicPanel
from arp.signal_lab.methods.base import MethodInput, MethodResult, register_method, text_buckets

_MODES = ("intensity", "change")
_MIN_PRIOR = 3


def _term_pattern(terms: list[str]) -> re.Pattern[str]:
    # Whitespace inside a phrase matches any run of whitespace.
    parts = [r"\b" + r"\s+".join(re.escape(w) for w in t.split()) + r"\b" for t in terms]
    return re.compile("|".join(parts), re.IGNORECASE)


@register_method("narrative_attention")
def _narrative_attention(params: dict, inp: MethodInput) -> MethodResult:
    terms = [t.strip() for t in params.get("terms") or [] if t.strip()]
    if not terms:
        raise ValueError("narrative_attention needs a non-empty 'terms' list")
    mode = params.get("mode", "intensity")
    if mode not in _MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {', '.join(_MODES)}")
    lookback = params.get("lookback_months", 12)
    pattern = _term_pattern(terms)
    ends = inp.prices.period_ends
    buckets = text_buckets(inp.texts, ends)

    values: dict[str, list[float | None]] = {}
    for issuer in inp.prices.returns:
        months = buckets.get(issuer, [[] for _ in ends])
        intensity: list[float | None] = [
            float(sum(1 for t in months[i] if pattern.search(t.title) or pattern.search(t.body)))
            if any(months[max(0, i - lookback) : i + 1])
            else None
            for i in range(len(ends))
        ]
        if mode == "intensity":
            values[issuer] = intensity
            continue
        out: list[float | None] = []
        for i, x in enumerate(intensity):
            prior = [v for v in intensity[max(0, i - lookback) : i] if v is not None]
            out.append(x - sum(prior) / len(prior) if x is not None and len(prior) >= _MIN_PRIOR else None)
        values[issuer] = out
    return MethodResult(CharacteristicPanel(list(ends), values, f"narrative_attention_{mode}"))
