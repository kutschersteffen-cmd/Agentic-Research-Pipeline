from arp.discovery.site_finder import SearchResult
from arp.research.taxonomy_sources.discovery import discover_authority_sources, discover_thematic_funds
from arp.schemas.taxonomy_sources import SourceCandidateType


async def test_discover_authority_sources_returns_candidates(fake_search):
    search = fake_search(
        {
            "official taxonomy classification": [SearchResult(title="IEA Electrification Taxonomy", url="https://iea.org/taxonomy")],
            "IEA definition taxonomy": [SearchResult(title="IEA Electrification Taxonomy", url="https://iea.org/taxonomy")],
        }
    )
    candidates = await discover_authority_sources("Electrification", search)
    assert len(candidates) == 1  # deduped by URL across the two matching queries
    assert candidates[0].source_type == SourceCandidateType.AUTHORITY
    assert candidates[0].url == "https://iea.org/taxonomy"


async def test_discover_thematic_funds_returns_candidates(fake_search):
    search = fake_search(
        {
            "ETF": [SearchResult(title="iShares Electrification ETF", url="https://ishares.com/elec-etf")],
        }
    )
    candidates = await discover_thematic_funds("Electrification", search)
    assert len(candidates) == 1
    assert candidates[0].source_type == SourceCandidateType.THEMATIC_FUND
    assert candidates[0].name == "iShares Electrification ETF"


async def test_discovery_survives_a_failing_query(fake_search):
    class _FlakySearch:
        def __init__(self):
            self.calls = 0

        async def search(self, query, max_results=5):
            self.calls += 1
            if "IEA" in query:
                raise RuntimeError("search backend unavailable")
            return [SearchResult(title="Some source", url="https://example.com/x")]

    candidates = await discover_authority_sources("Electrification", _FlakySearch())
    assert len(candidates) >= 1  # the failing query didn't blank the whole result


async def test_max_candidates_is_respected(fake_search):
    many_results = [SearchResult(title=f"Source {i}", url=f"https://example.com/{i}") for i in range(20)]
    search = fake_search({"official taxonomy": many_results})
    candidates = await discover_authority_sources("Electrification", search, max_candidates=3)
    assert len(candidates) == 3
