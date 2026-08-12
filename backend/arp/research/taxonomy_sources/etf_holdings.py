from __future__ import annotations

import csv
from pathlib import Path

from arp.llm.base import LLMClient, LLMUsage
from arp.research.taxonomy_sources.corpus_synthesis import synthesize_activities_from_corpus
from arp.schemas.taxonomy_sources import CorpusSnippet, CorpusSourceType
from arp.schemas.thematic import ThemeDefinition

# Column names accepted per field, in priority order -- fund providers'
# holdings exports aren't standardized, so a few common variants are
# checked rather than requiring one exact header set.
_NAME_COLUMNS = ("name", "company", "holding", "security")
_TICKER_COLUMNS = ("ticker", "symbol")
_SECTOR_COLUMNS = ("sector", "industry", "gics_sector", "sub_industry")
_DESCRIPTION_COLUMNS = ("description", "business_description", "notes")


def _first_present(row: dict, columns: tuple[str, ...]) -> str | None:
    for col in columns:
        for key in row:
            if key.strip().lower() == col:
                value = row[key].strip()
                if value:
                    return value
    return None


def load_holdings_corpus(path: Path) -> list[CorpusSnippet]:
    """Loads a user-supplied fund/index holdings export (any CSV with some
    recognizable subset of name/ticker/sector/description columns -- these
    aren't standardized across fund providers, so no single official
    format is assumed) into corpus snippets for bottom-up synthesis.

    Fetching holdings automatically from a fund provider's site isn't
    attempted here: provider sites vary widely in format and several
    financial-data domains are unreachable from this environment, so a
    user-supplied export -- what `discover_thematic_funds` points the user
    toward downloading -- is the robust path.
    """
    corpus: list[CorpusSnippet] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            name = _first_present(row, _NAME_COLUMNS)
            ticker = _first_present(row, _TICKER_COLUMNS)
            sector = _first_present(row, _SECTOR_COLUMNS)
            description = _first_present(row, _DESCRIPTION_COLUMNS)
            parts = [p for p in (name, sector, description) if p]
            if not parts:
                continue
            corpus.append(
                CorpusSnippet(text=" -- ".join(parts), source_type=CorpusSourceType.ETF_HOLDINGS, source_ref=ticker or name or "unknown")
            )
    return corpus


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
