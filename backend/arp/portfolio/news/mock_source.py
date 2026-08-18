from __future__ import annotations

from arp.portfolio.news.source import NewsSource
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import NewsItem

# Illustrative articles for the demo dataset only -- not real reporting.
# company_id -> [(headline, excerpt, source_url, published_at)]
_ARTICLES: dict[str, list[tuple[str, str, str, str]]] = {
    "totalenergies": [
        (
            "Regulator opens probe into TotalEnergies refinery emissions reporting",
            "The regulator said it would examine whether TotalEnergies understated methane leakage at two "
            "European refineries in its most recent sustainability disclosures.",
            "https://example-news.invalid/totalenergies-methane-probe",
            "2026-05-14",
        ),
        (
            "TotalEnergies expands offshore wind pipeline in the North Sea",
            "The company announced a new offshore wind development agreement, part of its stated plan to grow "
            "low-carbon generation capacity through 2030.",
            "https://example-news.invalid/totalenergies-offshore-wind",
            "2026-02-03",
        ),
    ],
    "shell": [
        (
            "Court orders Shell to accelerate emissions-reduction timeline",
            "A court ruling found Shell's current climate transition plan insufficient and ordered a faster "
            "timeline for Scope 1 and 2 emissions cuts.",
            "https://example-news.invalid/shell-court-ruling",
            "2026-06-02",
        ),
    ],
    "orsted": [
        (
            "Orsted reaches milestone on offshore wind portfolio buildout",
            "Orsted confirmed its offshore wind capacity additions are on track against its published "
            "decarbonization roadmap for the year.",
            "https://example-news.invalid/orsted-milestone",
            "2026-03-11",
        ),
    ],
    "iberdrola": [
        (
            "Iberdrola cited among leaders in grid decarbonization investment",
            "An industry review named Iberdrola among the top European utilities by capital committed to grid "
            "modernization supporting renewable integration.",
            "https://example-news.invalid/iberdrola-grid-investment",
            "2026-04-22",
        ),
    ],
    "bmw": [
        (
            "BMW supplier flagged in NGO report on battery mineral sourcing",
            "An NGO report named a tier-2 battery materials supplier to BMW as failing to meet its own "
            "responsible-sourcing commitments; BMW said it was reviewing the findings.",
            "https://example-news.invalid/bmw-supplier-ngo-report",
            "2026-07-01",
        ),
    ],
}


class MockNewsSource(NewsSource):
    """Stands in for a real news vendor/API (decision 4's news feed
    requirement). Company-specific articles are already tagged to a
    `company_id` here -- a real connector would need its own entity
    resolution step first, matching how `entity_resolution.py` handles
    securities.
    """

    name = "mock_news"

    def __init__(self, articles: dict[str, list[tuple[str, str, str, str]]] | None = None) -> None:
        self._articles = articles if articles is not None else _ARTICLES

    async def fetch(self, company: CompanyRef, since: str | None = None) -> list[NewsItem]:
        rows = self._articles.get(company.company_id, [])
        items = [
            NewsItem(company_id=company.company_id, headline=headline, excerpt=excerpt, source_url=url, published_at=published_at)
            for headline, excerpt, url, published_at in rows
        ]
        if since:
            items = [i for i in items if i.published_at >= since]
        return items
