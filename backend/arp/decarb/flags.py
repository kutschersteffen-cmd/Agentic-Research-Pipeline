"""Construction of the seven greenwashing indicators from source records.

Implements the coding rules in Brown, Hsu & Manya (2026), *Red flags in green
promises*, npj Climate Action 5:19, Methods section. Their inputs are three
datasets, and the field names below follow their description of what they used:

  Net Zero Tracker  implementation plan, end target, end target status,
                    condition on the use of offsets, presence of interim
                    target, emission scope coverage, GHG coverage
  CDP               quantifiable reduction targets, target scope coverage,
                    target status, baseline and monitoring-year emissions
  LobbyMap          InfluenceMap performance band, A+ down to F

Every rule assigns 1 where the company fails the test and 0 where it passes,
matching their binary coding scheme.

Two things about this framework are easy to get wrong and are enforced here.

The indicators are **not** summed. The authors decline to build a composite
index, on the grounds that there is no agreed weighting approach, that any
weighting is "inherently subjective", and that binary occurrences with no
intensity dimension "could dilute their meaning" when combined. `redflags.py`
tests whether a composite is defensible on a given panel and, on their
published correlations, reports that it is not.

Missingness is **not** neutral. Several rules flag a company unless positive
evidence of compliance exists, so absent data produces a flag. That is the
authors' intent, since undisclosed offset policy is itself the thing being
measured, but it means a panel with poor coverage will show inflated
greenwashing rates. `assess` records which fields were missing so the
distinction between "failed" and "did not disclose" stays visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "LobbyBand",
    "NZTRecord",
    "CDPRecord",
    "FlagAssessment",
    "NET_ZERO_END_TARGETS",
    "has_climate_claim",
    "peta",
    "ambition",
    "assess",
]


class LobbyBand(str, Enum):
    """InfluenceMap LobbyMap performance bands, best to worst."""

    A_PLUS = "A+"
    A = "A"
    A_MINUS = "A-"
    B_PLUS = "B+"
    B = "B"
    B_MINUS = "B-"
    C_PLUS = "C+"
    C = "C"
    C_MINUS = "C-"
    D_PLUS = "D+"
    D = "D"
    D_MINUS = "D-"
    E = "E"
    F = "F"

    @property
    def rank(self) -> int:
        """0 is best. Used for the 'C or lower' threshold."""
        return list(LobbyBand).index(self)

    def is_negative(self) -> bool:
        """Brown, Hsu & Manya flag a rating of C or lower.

        C+ therefore passes; C does not.
        """
        return self.rank >= LobbyBand.C.rank


# End-target wordings that trigger the GHG-coverage test. Taken verbatim from
# the Methods: the discrepancy only counts as a red flag when the company is
# claiming one of these, because the claim is what the incomplete inventory
# contradicts.
NET_ZERO_END_TARGETS: frozenset[str] = frozenset(
    {
        "net zero",
        "net negative",
        "climate neutral",
        "climate positive",
        "zero emissions",
        "ghg neutral",
    }
)


@dataclass(slots=True)
class NZTRecord:
    """Net Zero Tracker fields.

    `None` means the field was not recorded, which several rules treat as a
    failure. That is deliberate; see the module docstring.
    """

    end_target: str | None = None
    end_target_status: str | None = None
    has_implementation_plan: bool | None = None
    has_interim_target: bool | None = None
    scope_coverage: str | None = None          # e.g. "scope 1+2+3", "partial scope 3", "scope 1+2"
    ghg_coverage: str | None = None            # e.g. "all ghgs", "co2 only", None if unspecified
    offsets_used: bool | None = None           # whether the pledge relies on offsets
    offsets_conditions: str | None = None      # stated conditions on offset use, if any

    def mentions_scope3(self) -> bool:
        """Full or partial Scope 3 coverage in the pledge."""
        if not self.scope_coverage:
            return False
        text = self.scope_coverage.lower()
        return "3" in text or "scope 3" in text or "value chain" in text


@dataclass(slots=True)
class CDPRecord:
    """CDP fields for one company's disclosed targets and emissions."""

    target_scopes: list[str] = field(default_factory=list)   # per target, e.g. ["scope 1+2", "scope 3"]
    target_years: list[int] = field(default_factory=list)
    target_status: list[str] = field(default_factory=list)
    base_year: int | None = None
    base_year_emissions: float | None = None
    reporting_year: int | None = None
    reporting_year_emissions: float | None = None
    target_year: int | None = None
    target_year_emissions: float | None = None

    def any_target_references_scope3(self) -> bool:
        return any("3" in s.lower() for s in self.target_scopes)

    def distinct_target_years(self) -> int:
        return len({y for y in self.target_years if y is not None})

    def has_quantifiable_target(self) -> bool:
        return bool(self.target_years) and self.target_year_emissions is not None


@dataclass(slots=True)
class FlagAssessment:
    """Seven binary flags plus the provenance needed to interpret them."""

    firm_id: str
    made_climate_claim: bool
    flags: dict[str, bool]
    missing_inputs: list[str] = field(default_factory=list)
    peta: float | None = None
    ambition: float | None = None

    @property
    def n_flags(self) -> int:
        return sum(1 for v in self.flags.values() if v)

    @property
    def any_flag(self) -> bool:
        return self.n_flags > 0

    def explain(self) -> str:
        if not self.made_climate_claim:
            return f"{self.firm_id}: no climate claim, framework not applicable."
            
        raised = [k for k, v in self.flags.items() if v]
        note = f" (missing: {', '.join(self.missing_inputs)})" if self.missing_inputs else ""
        if not raised:
            return f"{self.firm_id}: no red flags{note}."
        return f"{self.firm_id}: {len(raised)} flag(s) - {', '.join(raised)}{note}."


def has_climate_claim(nzt: NZTRecord | None, cdp: CDPRecord | None) -> bool:
    """Whether the company made a claim the framework can be applied to.

    Their definition: the company appears on the Net Zero Tracker with any
    type of emission reduction pledge, or reports at least one emissions
    target for any scope. Companies with no claim are excluded, because
    greenwashing requires a claim to wash.
    """
    if nzt is not None and nzt.end_target:
        return True
    return bool(cdp is not None and cdp.target_scopes)


# --------------------------------------------------------------------------
# The seven rules
# --------------------------------------------------------------------------

def _no_interim_target(nzt: NZTRecord | None, cdp: CDPRecord | None) -> tuple[bool, str | None]:
    """Flag when no near-term interim milestone exists.

    Their fallback: where NZT has no data on interim targets, a company is
    credited with one if CDP shows at least two targets with different target
    years, which implies a near-term step ahead of the long-term goal.
    """
    if nzt is not None and nzt.has_interim_target is not None:
        return (not nzt.has_interim_target, None)
    if cdp is not None and cdp.distinct_target_years() >= 2:
        return (False, "nzt.has_interim_target")
    return (True, "nzt.has_interim_target")


def _no_implementation_plan(nzt: NZTRecord | None) -> tuple[bool, str | None]:
    """Flag when no published plan details how the target will be met."""
    if nzt is None or nzt.has_implementation_plan is None:
        return (True, "nzt.has_implementation_plan")
    return (not nzt.has_implementation_plan, None)


def _no_scope3_coverage(nzt: NZTRecord | None, cdp: CDPRecord | None) -> tuple[bool, str | None]:
    """Flag unless Scope 3 appears in the pledge or in any CDP target.

    Partial coverage counts as coverage, which is their explicit rule and
    makes this the most permissive of the seven tests. It is still the most
    commonly failed, at 70% of pledging companies.
    """
    if nzt is not None and nzt.mentions_scope3():
        return (False, None)
    if cdp is not None and cdp.any_target_references_scope3():
        return (False, None)
    missing = nzt is None or not nzt.scope_coverage
    return (True, "nzt.scope_coverage" if missing else None)


def _questionable_offsets(nzt: NZTRecord | None) -> tuple[bool, str | None]:
    """Flag on undisclosed offset intent, or on offset use without conditions.

    Note the asymmetry: a company that says nothing about offsets fails, and
    so does one that admits to using them without safeguards. Only an explicit
    conditional policy, or explicit non-use, passes.
    """
    if nzt is None or nzt.offsets_used is None:
        return (True, "nzt.offsets_used")
    if not nzt.offsets_used:
        return (False, None)
    return (not bool(nzt.offsets_conditions), None)


def _incomplete_ghg_coverage(nzt: NZTRecord | None) -> tuple[bool, str | None]:
    """Flag a neutrality claim backed by a CO2-only or unspecified inventory.

    This is the dimension most often misdescribed as being about *scopes*. It
    is about *gases*: a company claiming net zero or GHG neutrality while its
    inventory covers only carbon dioxide, or does not say which gases it
    covers, is claiming more than it measures.

    The test only bites when one of the neutrality wordings is claimed, so a
    company with a plain percentage-reduction target is not flagged here.
    """
    if nzt is None or not nzt.end_target:
        return (False, None)
    if nzt.end_target.strip().lower() not in NET_ZERO_END_TARGETS:
        return (False, None)
    coverage = (nzt.ghg_coverage or "").strip().lower()
    if not coverage:
        return (True, "nzt.ghg_coverage")
    return (coverage in {"co2", "co2 only", "carbon dioxide", "carbon dioxide only"}, None)


def _negative_lobbying(band: LobbyBand | str | None) -> tuple[bool, str | None]:
    """Flag a LobbyMap performance band of C or lower.

    Companies absent from LobbyMap are *not* flagged. Their sample covers 600
    companies on this indicator against 4,131 overall, so treating absence as
    failure would manufacture the flag for the majority.
    """
    if band is None:
        return (False, "lobbymap.band")
    if isinstance(band, str):
        try:
            band = LobbyBand(band.strip().upper())
        except ValueError:
            return (False, "lobbymap.band")
    return (band.is_negative(), None)


def peta(cdp: CDPRecord | None) -> float | None:
    """Pro-rated emissions target achievement.

    Ratio of the reduction achieved to the reduction required on a linear
    trajectory from base year to target year:

        achieved = E_base - E_reporting
        required = (E_base - E_target) * (reporting_year - base_year)
                                       / (target_year - base_year)
        peta     = achieved / required

    A value of 1 means exactly on the straight-line path; below 1 is behind.

    The published equations (2) and (3) are typeset with sign and
    normalisation conventions that do not reconcile as printed: taken
    literally, "achieved" is negative for a firm that cut emissions while
    "required" is positive, and the stated on-track test could never hold.
    This implements the reading that makes the measure behave as described,
    with the time term as a fraction of the target period rather than an
    absolute count of years.
    """
    if cdp is None:
        return None
    needed = (cdp.base_year, cdp.base_year_emissions, cdp.reporting_year,
              cdp.reporting_year_emissions, cdp.target_year, cdp.target_year_emissions)
    if any(v is None for v in needed):
        return None
    span = cdp.target_year - cdp.base_year
    if span <= 0:
        return None
    elapsed = (cdp.reporting_year - cdp.base_year) / span
    if elapsed <= 0:
        return None
    required = (cdp.base_year_emissions - cdp.target_year_emissions) * elapsed
    if required == 0:
        return None
    achieved = cdp.base_year_emissions - cdp.reporting_year_emissions
    return achieved / required


def ambition(cdp: CDPRecord | None, *, as_of_year: int | None = None) -> float | None:
    """Annualised percentage reduction implied by the target, their equation (4).

        ambition = -100 * (1 / remaining maturity in years)
                        * (E_target - E_base) / E_base

    Positive values mean a commitment to cut. Used by the authors as a
    determinant in the regressions rather than as a flag.
    """
    if cdp is None or cdp.base_year_emissions in (None, 0) or cdp.target_year_emissions is None:
        return None
    if cdp.target_year is None:
        return None
    reference = as_of_year if as_of_year is not None else cdp.reporting_year or cdp.base_year
    if reference is None:
        return None
    remaining = cdp.target_year - reference
    if remaining <= 0:
        return None
    change = (cdp.target_year_emissions - cdp.base_year_emissions) / cdp.base_year_emissions
    return -100.0 * change / remaining


def _off_track(cdp: CDPRecord | None) -> tuple[bool, str | None]:
    """Flag when pro-rated target achievement is below 1."""
    value = peta(cdp)
    if value is None:
        return (False, "cdp.peta_inputs")
    return (value < 1.0, None)


def assess(
    firm_id: str,
    *,
    nzt: NZTRecord | None = None,
    cdp: CDPRecord | None = None,
    lobby_band: LobbyBand | str | None = None,
) -> FlagAssessment:
    """Apply all seven rules to one company.

    Returns a `FlagAssessment` whose `flags` dict keys match
    `arp.decarb.schemas.RED_FLAGS`, so it drops straight into the analysis in
    `redflags.py`.

    Companies with no climate claim come back with every flag False and
    `made_climate_claim` False. They are not "clean"; the framework simply
    does not apply, and including them in a prevalence denominator would
    understate the incidence the authors report.
    """
    claim = has_climate_claim(nzt, cdp)
    if not claim:
        return FlagAssessment(firm_id, False, {k: False for k in _RULE_ORDER}, [])

    results: dict[str, bool] = {}
    missing: list[str] = []
    for name, flagged, absent in (
        ("no_interim_targets", *_no_interim_target(nzt, cdp)),
        ("no_implementation_plan", *_no_implementation_plan(nzt)),
        ("no_scope3_coverage", *_no_scope3_coverage(nzt, cdp)),
        ("questionable_offsets", *_questionable_offsets(nzt)),
        ("incomplete_ghg_coverage", *_incomplete_ghg_coverage(nzt)),
        ("misaligned_lobbying", *_negative_lobbying(lobby_band)),
        ("off_track_vs_target", *_off_track(cdp)),
    ):
        results[name] = flagged
        if absent:
            missing.append(absent)

    return FlagAssessment(
        firm_id=firm_id,
        made_climate_claim=True,
        flags=results,
        missing_inputs=missing,
        peta=peta(cdp),
        ambition=ambition(cdp),
    )


_RULE_ORDER = (
    "no_scope3_coverage",
    "questionable_offsets",
    "no_interim_targets",
    "off_track_vs_target",
    "no_implementation_plan",
    "incomplete_ghg_coverage",
    "misaligned_lobbying",
)
