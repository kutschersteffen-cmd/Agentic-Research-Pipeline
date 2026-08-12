from __future__ import annotations

import csv
from pathlib import Path

from arp.llm.base import LLMClient, LLMUsage
from arp.research.taxonomy_sources.corpus_synthesis import synthesize_activities_from_corpus
from arp.schemas.common import CompanyRef
from arp.schemas.taxonomy_sources import CorpusSnippet, CorpusSourceType, HoldingRow
from arp.schemas.thematic import ThemeDefinition

# Column names accepted per field, in priority order -- fund providers'
# holdings exports aren't standardized, so a few common variants are
# checked rather than requiring one exact header set.
_NAME_COLUMNS = ("name", "company", "holding", "security")
_TICKER_COLUMNS = ("ticker", "symbol")
_SECTOR_COLUMNS = ("sector", "industry", "gics_sector", "sub_industry")
_DESCRIPTION_COLUMNS = ("description", "business_description", "notes")
_WEIGHT_COLUMNS = ("weight", "weight (%)", "weighting", "% of net assets", "portfolio weight")


def _first_present(row: dict, columns: tuple[str, ...]) -> str | None:
    for col in columns:
        for key in row:
            if key.strip().lower() == col:
                value = row[key].strip()
                if value:
                    return value
    return None


def _parse_weight(raw: str | None) -> float | None:
    """Normalizes a weight cell to a 0-1 fraction.

    Handles three real-world formats: an explicit percent sign in the
    cell ("12.5%"), a bare number under a percent-labeled header with no
    sign in the cell itself (by far the most common export format --
    "Weight (%)" column, "12.5" value), and an already-fractional value
    ("0.125"). A bare value > 1 is assumed to be a percent needing /100,
    since no single holding is ever >100% of a fund.
    """
    if not raw:
        return None
    has_percent_sign = "%" in raw
    cleaned = raw.strip().rstrip("%")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value / 100 if (has_percent_sign or value > 1) else value


def _parse_holdings_rows(path: Path) -> list[dict]:
    """Shared CSV parsing for any fund/index holdings export -- every
    other function in this module is a projection of these normalized
    rows, so there's exactly one place that has to know about column-name
    variants across fund providers.
    """
    rows: list[dict] = []
    with path.open(newline="") as f:
        for raw_row in csv.DictReader(f):
            name = _first_present(raw_row, _NAME_COLUMNS)
            ticker = _first_present(raw_row, _TICKER_COLUMNS)
            sector = _first_present(raw_row, _SECTOR_COLUMNS)
            description = _first_present(raw_row, _DESCRIPTION_COLUMNS)
            weight = _parse_weight(_first_present(raw_row, _WEIGHT_COLUMNS))
            if not (name or ticker):
                continue
            rows.append({"ticker": ticker, "name": name, "sector": sector, "description": description, "weight": weight})
    return rows


def load_holdings_corpus(path: Path) -> list[CorpusSnippet]:
    """Loads a user-supplied fund/index holdings export into corpus
    snippets for bottom-up taxonomy synthesis.

    Fetching holdings automatically from a fund provider's site isn't
    attempted here: provider sites vary widely in format and several
    financial-data domains are unreachable from this environment, so a
    user-supplied export -- what `discover_thematic_funds` points the user
    toward downloading -- is the robust path.
    """
    corpus: list[CorpusSnippet] = []
    for row in _parse_holdings_rows(path):
        parts = [p for p in (row["name"], row["sector"], row["description"]) if p]
        if not parts:
            continue
        corpus.append(
            CorpusSnippet(text=" -- ".join(parts), source_type=CorpusSourceType.ETF_HOLDINGS, source_ref=row["ticker"] or row["name"] or "unknown")
        )
    return corpus


def load_universe_from_holdings(path: Path) -> list[CompanyRef]:
    """Projects a holdings export into a company universe -- the Universe
    Builder's path for constructing a universe from an index/sector fund's
    constituents instead of a hand-written list, reusing the exact same
    CSV parsing as the ETF-holdings taxonomy derivation method.
    """
    companies: list[CompanyRef] = []
    seen_ids: set[str] = set()
    for row in _parse_holdings_rows(path):
        company_id = row["ticker"] or row["name"]
        if not company_id or company_id in seen_ids:
            continue
        seen_ids.add(company_id)
        companies.append(CompanyRef(company_id=company_id, name=row["name"] or company_id, ticker=row["ticker"], sector=row["sector"]))
    return companies


def load_holdings_with_weights(path: Path) -> list[HoldingRow]:
    """Projects a holdings export into weighted rows for overlap
    computation (arp/research/taxonomy_sources/overlap.py)."""
    holdings: list[HoldingRow] = []
    for row in _parse_holdings_rows(path):
        ticker = row["ticker"] or row["name"]
        if not ticker:
            continue
        holdings.append(HoldingRow(ticker=ticker, name=row["name"], weight=row["weight"], sector=row["sector"]))
    return holdings


async def build_theme_from_holdings(
    theme_name: str, theme_description: str, holdings_path: Path, llm: LLMClient
) -> tuple[ThemeDefinition, str, LLMUsage]:
    corpus = load_holdings_corpus(holdings_path)
    if not corpus:
        raise ValueError(f"No usable rows found in holdings file: {holdings_path}")

    activities, assessment, usage = await synthesize_activities_from_corpus(theme_name, theme_description, corpus, llm)
    theme = ThemeDefinition(name=theme_name, description=theme_description, activities=activities)
    notes = f"Derived from {len(corpus)} fund holding(s) in {holdings_path.name}. {assessment}"
    return theme, notes, usage
