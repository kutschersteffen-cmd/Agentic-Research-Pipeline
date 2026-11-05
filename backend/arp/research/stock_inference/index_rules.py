"""Layer 1: stated index rules -- extracted from methodology documents, mapped onto a draft ConstructionSpec.

Every number in a mapped rule is parsed here from the rule's grounded quote (the document's own text), never
taken from the model."""

from __future__ import annotations

import logging
import re

from arp.research.authority_taxonomy.checklist import INDEX_RULES_CHECKLIST
from arp.research.authority_taxonomy.extract import StatedRule, extract_source
from arp.research.stock_inference.schemas import IndexRule, IndexRules
from arp.schemas.common import SourceDocument
from arp.schemas.index import CategoryScreen, ConstructionSpec, MetricThresholdScreen, TopN

log = logging.getLogger(__name__)

_GICS_SECTORS = ["Energy", "Materials", "Industrials", "Consumer Discretionary", "Consumer Staples", "Health Care",
                 "Financials", "Information Technology", "Communication Services", "Utilities", "Real Estate"]
_CURRENCY = {"$": "USD", "us$": "USD", "€": "EUR", "£": "GBP"}
_SCALE = {"thousand": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9}
_MONEY = re.compile(r"(USD|EUR|GBP|CHF|JPY|US\$|\$|€|£)\s*(\d[\d,]*(?:\.\d+)?)(?:\s*(thousand|million|mn|m|billion|bn|b)\b)?", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|per\s?cent\b)", re.I)
_FREQUENCY = [(r"semi[\s-]?annual|half[\s-]?year|twice a year|bi[\s-]?annual", "semi_annual"),
              (r"quarter", "quarterly"), (r"\bmonthly\b|every month", "monthly"),
              (r"\bannual|\byearly\b|once a year", "annual")]


def _money(q: str) -> tuple[float, str] | None:
    m = _MONEY.search(q)
    if not m:
        return None
    cur = m.group(1)
    return float(m.group(2).replace(",", "")) * _SCALE.get((m.group(3) or "").lower(), 1), _CURRENCY.get(cur.lower(), cur.upper())


def _pct(q: str) -> float | None:
    m = _PCT.search(q)
    return float(m.group(1)) / 100 if m else None


def _has(pattern: str, q: str) -> bool:
    return re.search(pattern, q, re.I) is not None


def _match(q: str):
    """The one recognised form of a rule: (target, value, currency) or None. First form wins."""
    money, pct = _money(q), _pct(q)
    if _has(r"5\s*/\s*10\s*/\s*40", q):
        return "ucits", True, None
    if money and _has(r"market\s+capitali[sz]ation", q):
        return "float_mcap", money[0], money[1]
    if money and _has(r"daily\s+trad(?:ed|ing)\s+value|\badtv\b|daily\s+turnover", q):
        return "adv_3m", money[0], money[1]
    if pct is not None and _has(r"\b(?:revenue|revenues|sales|exposure|turnover)\b", q):
        return "relevance", pct, None
    if pct and pct <= 1 and _has(r"\bexceed|\bcap(?:ped|s)?\b|\bmaximum\b|\bmore than\b|\blimited to\b", q):
        return "single_name_cap", pct, None
    if _has(r"exclu", q):
        found = sorted((m.start(), s) for s in _GICS_SECTORS if (m := re.search(rf"\b{s}\b", q, re.I)))
        if found:
            return "sector", [s for _, s in found], None
    n = re.search(r"\b(\d+)\s+(?:largest\s+|biggest\s+|top\s+)?(?:[a-z-]+\s+)?(?:companies|constituents|stocks|securities|issuers)\b", q, re.I)
    if n and int(n.group(1)) > 0 and not _has(r"at least|minimum|maximum|up to|no more than|fewer than|more than", q):
        return "top_n", int(n.group(1)), None
    if _has(r"equal(?:ly)?[\s-]+weight", q):
        return "scheme", "equal", None
    if _has(r"market[\s-]+capitali[sz]ation[\s-]+weight|weighted\s+(?:by|according to|in proportion to)\s+(?:their\s+)?"
            r"(?:free[\s-]+float(?:[\s-]+adjusted)?\s+)?market\s+capitali[sz]ation", q):
        return "scheme", "free_float_mcap", None
    if _has(r"review|rebalanc|reconstitut", q):
        for pattern, freq in _FREQUENCY:
            if _has(pattern, q):
                return "frequency", freq, None
    return None


_SINGLE = {"ucits": "constraints.ucits_5_10_40", "single_name_cap": "constraints.single_name_cap",
           "top_n": "selection.n", "scheme": "base_weighting.scheme", "frequency": "calendar.review_frequency"}


def map_rules(rules: list[StatedRule]) -> IndexRules:
    """Rules in document order -> the draft spec; a field no rule sets keeps ConstructionSpec's default."""
    spec, currency, out = ConstructionSpec(), None, []
    for r in rules:
        hit, path = _match(r.quote), None
        if hit:
            target, value, cur = hit
            if target in ("float_mcap", "adv_3m", "relevance"):
                path = f"screens[{len(spec.screens)}].min_value"
                spec.screens.append(MetricThresholdScreen(field=target, min_value=value, label=r.text))
                currency = currency or cur
            elif target == "sector":
                path = f"screens[{len(spec.screens)}].deny"
                spec.screens.append(CategoryScreen(field="sector", deny=value, label=r.text))
            elif _SINGLE[target] not in {x.mapped_to for x in out}:  # a later rule for a set field stays unmapped
                path = _SINGLE[target]
                if target == "ucits":
                    spec.constraints.ucits_5_10_40 = True
                elif target == "single_name_cap":
                    spec.constraints.single_name_cap = value
                elif target == "top_n":
                    score = "float_mcap" if _has(r"largest|biggest|market\s+capitali[sz]ation", r.quote) else "relevance"
                    spec.selection = TopN(n=value, score_field=score, label=r.text)
                elif target == "scheme":
                    spec.base_weighting.scheme = value
                else:
                    spec.calendar.review_frequency = value
        out.append(IndexRule(text=r.text, quote=r.quote, source=r.source, mapped_to=path))
    if currency:
        spec.index_currency = currency
    return IndexRules(currency=currency, construction_spec=ConstructionSpec.model_validate(spec.model_dump()), rules=out)


async def stated_index_rules(docs: list[SourceDocument], theme_name: str, llm) -> tuple[IndexRules, str | None]:
    """Layer 1 over the methodology documents: (index rules, the stated theme or None).

    Per document: the default authority checklist for the stated theme, then one call per index-rules item. Each
    call stands alone, so one bad model reply loses only that item."""
    rules: list[StatedRule] = []
    stated = None
    for doc in docs:
        src, text = doc.source_url or doc.title, doc.full_text or ""
        try:
            ext = await extract_source(src, text, theme_name=theme_name, scope="", value_chain=False, llm=llm)
            stated = stated or ext.theme_description or None
        except Exception:
            log.warning("Stated-theme extraction failed for %s", src, exc_info=True)
        found = []
        for item in INDEX_RULES_CHECKLIST:
            try:
                ext = await extract_source(src, text, theme_name=theme_name, scope="", value_chain=False, llm=llm,
                                           checklist=[item])
                found += ext.rules
            except Exception:
                log.warning("Index-rules item %s failed for %s", item.key, src, exc_info=True)
        # document order: position of the quote in the text; a quote seen twice is one rule
        unique = {r.quote: r for r in reversed(found)}
        rules += sorted(unique.values(), key=lambda r: text.find(r.quote))
    return map_rules(rules), stated
