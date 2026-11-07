from __future__ import annotations

import csv
import random
from pathlib import Path

from arp.research.stock_inference.schemas import InferStock, Selection
from arp.research.taxonomy_sources.etf_holdings import load_holdings_with_weights
from arp.universe import load_company_universe

MAX_STOCKS = 30
WEIGHT_CUTOFF = 0.8


def _is_universe(path: Path) -> bool:
    if path.suffix.lower() == ".json":
        return True
    with path.open(newline="", encoding="utf-8-sig") as f:
        return "company_id" in [h.strip() for h in next(csv.reader(f), [])]


def load_stocks(path: Path) -> tuple[list[InferStock], float | None]:
    """Stocks file -> (stocks, total_weight). total_weight is None for unweighted input."""
    path = Path(path)
    if _is_universe(path):
        stocks = [
            InferStock(
                company_id=c.company_id, name=c.name, ticker=c.ticker, isin=c.isin, lei=c.lei, cik=c.cik,
                codes={k: v for k, v in (("isic", c.isic_code), ("nace_rev2.1" if c.nace_rev == "2.1" else "nace", c.nace_code),
                                         ("gics", c.gics_code)) if v},
            )
            for c in load_company_universe(path)
        ]
        return stocks, None
    merged: dict[str, InferStock] = {}
    for h in load_holdings_with_weights(path):
        cid = h.ticker.strip()
        if cid in merged:
            prev = merged[cid]
            weight = None if prev.weight is None and h.weight is None else (prev.weight or 0.0) + (h.weight or 0.0)
            merged[cid] = prev.model_copy(update={"weight": weight})
        else:
            merged[cid] = InferStock(
                company_id=cid, name=h.name or cid, ticker=h.ticker.strip(), weight=h.weight,
                isin=h.isin, sedol=h.sedol, lei=h.lei, cik=h.cik,
            )
    stocks = list(merged.values())
    if all(s.weight is None for s in stocks):
        return stocks, None
    return stocks, sum(s.weight or 0.0 for s in stocks)


def select(stocks: list[InferStock], total_weight: float | None) -> tuple[list[InferStock], Selection]:
    if total_weight is not None:
        ordered = sorted(stocks, key=lambda s: (-(s.weight or 0.0), s.company_id))
        picked: list[InferStock] = []
        running, reason = 0.0, "all"
        for s in ordered:
            picked.append(s)
            running += s.weight or 0.0
            if running >= WEIGHT_CUTOFF * total_weight - 1e-9:  # float sums such as 0.7999... reach 80 %
                reason = "weight_80"
                break
            if len(picked) == MAX_STOCKS:
                reason = "cap_30"
                break
        return picked, Selection(method="weighted", cutoff_reason=reason, total_weight=total_weight)
    ordered = sorted(stocks, key=lambda s: s.company_id)
    if len(ordered) > MAX_STOCKS:
        return sorted(random.Random(0).sample(ordered, MAX_STOCKS), key=lambda s: s.company_id), Selection(method="sample", cutoff_reason="sample")
    return ordered, Selection(method="sample", cutoff_reason="all")
