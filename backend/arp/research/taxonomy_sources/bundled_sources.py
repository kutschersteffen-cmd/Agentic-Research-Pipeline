from __future__ import annotations

from arp.schemas.taxonomy_sources import SourceCandidate, SourceCandidateType

# A small, hand-curated registry of stable, canonical authority-source URLs
# -- verified reachable, real documents at time of writing, not invented or
# LLM-guessed. This supplies trustworthy *starting points* for
# derivation_method=authority_source, the same discovery/authority.py
# candidate shape produced by live web search (discovery.py) -- it does not
# pre-parse or embed any taxonomy content of its own. Whichever URL the
# user actually selects still goes through the normal fetch + grounded LLM
# extraction pipeline (authority_extraction.py), so this module's job is
# narrowly "point at a real, official document," not "assert what it says."
#
# Deliberately small and reviewed by hand rather than scraped/generated,
# since a wrong or dead link here would undermine the whole point of
# offering "pre-vetted" alternatives to a live search.
_BUNDLED_SOURCES: list[dict[str, str]] = [
    {
        "category": "eu_taxonomy",
        "name": "EU Taxonomy Climate Delegated Act -- Commission Delegated Regulation (EU) 2021/2139",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=celex:32021R2139",
        "snippet": (
            "Official EUR-Lex text of the Delegated Regulation establishing technical screening criteria for "
            "determining which economic activities substantially contribute to climate change mitigation or "
            "adaptation under EU Taxonomy Regulation (EU) 2020/852, including the Annex I/II activity lists."
        ),
    },
    {
        "category": "eu_taxonomy",
        "name": "EU Taxonomy for Sustainable Activities -- European Commission",
        "url": "https://finance.ec.europa.eu/sustainable-finance/tools-and-standards/eu-taxonomy-sustainable-activities_en",
        "snippet": (
            "European Commission's official hub for the EU Taxonomy Regulation and its delegated acts, including "
            "the EU Taxonomy Compass tool for browsing activities and technical screening criteria by sector."
        ),
    },
    {
        "category": "nace",
        "name": "NACE -- Statistical Classification of Economic Activities in the EU (Eurostat)",
        "url": "https://ec.europa.eu/eurostat/web/nace",
        "snippet": "Eurostat's official overview page for the NACE Rev. 2 industry classification used across EU statistics and regulation.",
    },
    {
        "category": "nace",
        "name": "NACE Rev. 2 -- Structure and Explanatory Notes (Eurostat)",
        "url": "https://ec.europa.eu/eurostat/documents/3859598/5902521/KS-RA-07-015-EN.PDF",
        "snippet": "Eurostat's full published NACE Rev. 2 structure document: every section/division/group/class code with explanatory notes.",
    },
    {
        "category": "iea",
        "name": "IEA Technology Roadmaps (International Energy Agency)",
        "url": "https://www.iea.org/reports/technology-roadmaps",
        "snippet": (
            "IEA's series of sector-by-sector technology roadmaps for low-carbon energy technologies -- a "
            "definitional reference for emerging/critical technologies within a theme, licensed CC BY 4.0."
        ),
    },
    {
        "category": "ipcc",
        "name": "IPCC AR6 Working Group III -- Mitigation of Climate Change",
        "url": "https://www.ipcc.ch/report/ar6/wg3/",
        "snippet": (
            "IPCC Sixth Assessment Report, Working Group III contribution: the authoritative scientific "
            "assessment of climate-change mitigation options and technologies, organized by sector."
        ),
    },
]


def list_bundled_authority_sources(category: str | None = None) -> list[SourceCandidate]:
    """Bundled alternative to discover_authority_sources' live web search --
    same SourceCandidate shape, so the caller (and the frontend) can treat
    bundled and discovered candidates identically. authority_score=1.0
    marks these as pre-vetted rather than LLM-ranked.
    """
    return [
        SourceCandidate(
            source_type=SourceCandidateType.AUTHORITY,
            name=item["name"],
            url=item["url"],
            snippet=item["snippet"],
            authority_score=1.0,
            authority_reasoning="Canonical, official source -- pre-vetted and bundled rather than discovered via search.",
        )
        for item in _BUNDLED_SOURCES
        if category is None or item["category"] == category
    ]


def bundled_source_categories() -> list[str]:
    return sorted({item["category"] for item in _BUNDLED_SOURCES})
