from __future__ import annotations

from dataclasses import dataclass

from arp.schemas.thematic import ActivityDefinition, ThemeDefinition

_USGS_2025 = "USGS 2025 List of Critical Minerals (Federal Register 2025-19813, published 2025-11-07)"
_IEA_CM = "IEA, The Role of Critical Minerals in Clean Energy Transitions"


@dataclass(frozen=True)
class CriticalMineral:
    """One bundled critical-mineral commodity and where it plausibly enters
    the ISIC Rev.4 value chain.

    `isic_codes` is this implementation's own categorization of where each
    commodity's mining/refining typically falls -- USGS and IEA publish
    commodity lists, not an ISIC crosswalk, so this mapping is not itself
    sourced from either body. `source` cites only the commodity's inclusion
    on the referenced list, not the ISIC association.
    """

    name: str
    isic_codes: tuple[str, ...]
    source: str
    notes: str


# A small, hand-curated subset centered on the electrification/battery
# value chain the bundled ICIO/EXIOBASE sample datasets already model
# (see sample_data/), not the full USGS 60-commodity list. Commodity
# inclusion verified against the current official list at time of writing;
# ISIC codes are this module's own categorization -- see CriticalMineral's
# docstring and docs/METHODOLOGY.md for the caveat this implies.
_CRITICAL_MINERALS: list[CriticalMineral] = [
    CriticalMineral(
        name="Lithium",
        isic_codes=("07", "20"),
        source=f"{_USGS_2025}; {_IEA_CM}",
        notes="Ore/brine extraction under ISIC 07 (Mining of metal ores); refining into "
        "battery-grade lithium carbonate/hydroxide under ISIC 20 (Manufacture of chemicals).",
    ),
    CriticalMineral(
        name="Cobalt",
        isic_codes=("07", "24"),
        source=f"{_USGS_2025}; {_IEA_CM}",
        notes="Mining under ISIC 07; refining into battery-grade cobalt compounds typically "
        "falls under ISIC 24 (Manufacture of basic metals).",
    ),
    CriticalMineral(
        name="Nickel",
        isic_codes=("07", "24"),
        source=f"{_USGS_2025}; {_IEA_CM}",
        notes="Ore mining under ISIC 07; smelting/refining to battery-grade nickel under ISIC 24.",
    ),
    CriticalMineral(
        name="Natural graphite",
        isic_codes=("07", "20"),
        source=f"{_USGS_2025}; {_IEA_CM}",
        notes="Mining under ISIC 07; purification/spheroidization into battery-grade anode "
        "material treated as a chemical-processing activity under ISIC 20.",
    ),
    CriticalMineral(
        name="Manganese",
        isic_codes=("07", "24"),
        source=_USGS_2025,
        notes="Ore mining under ISIC 07; refining into battery-grade manganese sulfate under ISIC 24.",
    ),
    CriticalMineral(
        name="Rare earth elements",
        isic_codes=("07", "20"),
        source=f"{_USGS_2025}; {_IEA_CM}",
        notes="Treated as one group (USGS lists individual lanthanides separately). Ore mining "
        "under ISIC 07; separation/refining under ISIC 20 -- essential for the permanent magnets "
        "used in EV motors and wind turbines.",
    ),
    CriticalMineral(
        name="Copper",
        isic_codes=("07", "24"),
        source=f"{_USGS_2025}; {_IEA_CM}",
        notes="Added to the USGS list in the 2025 revision (previously IEA-flagged only, not "
        "USGS-listed). Ore mining under ISIC 07; smelting/refining under ISIC 24 -- IEA "
        "identifies copper as a cornerstone of all electricity-related technologies.",
    ),
]


def list_critical_minerals() -> list[CriticalMineral]:
    return list(_CRITICAL_MINERALS)


def critical_isic_codes() -> set[str]:
    """Flattened set of every ISIC division appearing in the registry -- the
    join key used throughout the indirect-exposure subsystem. Coarse by
    construction: e.g. ISIC 07 also contains non-critical ore mining, so
    this is a "plausibly touches a critical-mineral supply chain" signal
    at the industry-division level, not a per-commodity certification.
    """
    return {code for mineral in _CRITICAL_MINERALS for code in mineral.isic_codes}


def is_critical_isic_code(isic_code: str) -> bool:
    return isic_code in critical_isic_codes()


def apply_criticality_overlay(theme: ThemeDefinition) -> ThemeDefinition:
    """Sets criticality_flag=True on every activity whose core_isic_codes
    intersects the bundled registry's ISIC set. Pure and deterministic, no
    LLM call -- intended to run as an explicit extra step immediately after
    classify_theme_core_sectors (which populates core_isic_codes), not
    folded into it, since this is a fixed-lookup concern independent of
    that LLM classification. An activity with no core_isic_codes yet is
    left unflagged rather than erroring.
    """
    critical_codes = critical_isic_codes()
    new_activities: list[ActivityDefinition] = [
        activity.model_copy(update={"criticality_flag": bool(critical_codes.intersection(activity.core_isic_codes))})
        for activity in theme.activities
    ]
    return theme.model_copy(update={"activities": new_activities})
