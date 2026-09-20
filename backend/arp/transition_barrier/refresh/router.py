from __future__ import annotations

from dataclasses import dataclass

from arp.schemas.transition_barrier import AccessPattern, Region, RegistrySource
from arp.transition_barrier.dataset import load_source_registry
from arp.transition_barrier.refresh.eli import EliRef, parse_eli

# Only legal_regulatory_text is wired. The other five categories are listed
# here explicitly so the router reports "not automated" for them rather than
# silently returning nothing -- most of the six sources tagged
# structured_api_or_dashboard are dashboard front-ends, not documented APIs,
# and company_disclosure must stay discovery-and-triage only.
AUTOMATED_PATTERNS: frozenset[AccessPattern] = frozenset({AccessPattern.LEGAL_REGULATORY_TEXT})


@dataclass(frozen=True)
class RoutedSource:
    """A registry source paired with the reason it can or cannot be refreshed."""

    source: RegistrySource
    eli: EliRef | None
    reason: str
    # Which regional ratings this source is evidence about. An EU act says
    # nothing about the US or Chinese rating for the same criterion, so a
    # EUR-Lex source is scoped to the EU cell only -- checking it against all
    # three would manufacture two spurious findings per criterion.
    regions: tuple[Region, ...] = (Region.EUROPEAN_UNION,)

    @property
    def automatable(self) -> bool:
        return self.eli is not None


def route_sources(sources: list[RegistrySource] | None = None) -> list[RoutedSource]:
    """Classify every registry source by whether this slice can refresh it.

    Returns all 86, not just the automatable ones -- the point is an honest
    inventory of coverage, so a caller can see what is still manual.
    """
    routed: list[RoutedSource] = []
    for source in sources if sources is not None else load_source_registry():
        if source.access_pattern not in AUTOMATED_PATTERNS:
            routed.append(
                RoutedSource(
                    source=source,
                    eli=None,
                    reason=f"access_pattern '{source.access_pattern.value}' is not automated in this slice",
                )
            )
            continue
        eli = parse_eli(source.url or "")
        if eli is None:
            routed.append(RoutedSource(source=source, eli=None, reason="no parseable EUR-Lex ELI URI on this source"))
            continue
        routed.append(RoutedSource(source=source, eli=eli, reason="EUR-Lex ELI URI, refreshable"))
    return routed


def automatable_sources(sources: list[RegistrySource] | None = None) -> list[RoutedSource]:
    return [r for r in route_sources(sources) if r.automatable]


def coverage_summary(sources: list[RegistrySource] | None = None) -> dict[str, int]:
    """How much of the registry this slice actually covers -- the number to
    quote when asked "is the refresh pipeline done?".
    """
    routed = route_sources(sources)
    return {
        "total_sources": len(routed),
        "automatable": sum(1 for r in routed if r.automatable),
        "manual": sum(1 for r in routed if not r.automatable),
    }
