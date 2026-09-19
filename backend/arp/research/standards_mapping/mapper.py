from __future__ import annotations

import csv
import io
from pathlib import Path

from arp.config import Settings
from arp.llm.base import LLMClient, LLMUsage
from arp.research.indirect_exposure.core_sectors import classify_theme_core_sectors
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.standards_mapping.crosswalk import CrosswalkTable, load_crosswalk
from arp.research.standards_mapping.gics import GicsReferenceEntry, classify_gics, load_gics_reference
from arp.schemas.standards import ActivityStandardsMapping
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition

_SAMPLE_DIR = Path(__file__).parent / "sample_data"
_SAMPLE_FILES = {
    "nace": "isic_nace_sample.csv",
    "naics": "isic_naics_sample.csv",
    "sic": "isic_sic_sample.csv",
    "gics": "gics_reference_sample.csv",
}


def _resolve_table_path(explicit: Path | None, standard: str, use_sample: bool) -> Path | None:
    """Each of the four standards resolves independently: a real configured
    path always wins; the bundled sample is only used when explicitly
    requested. A standard with neither is simply skipped (empty result for
    that standard), rather than failing the whole mapping -- e.g. a real
    NACE table but no GICS license is a perfectly normal deployment."""
    if explicit:
        return explicit
    if use_sample:
        return _SAMPLE_DIR / _SAMPLE_FILES[standard]
    return None


async def map_activity_standards(
    activity: ActivityDefinition,
    nace_table: CrosswalkTable,
    naics_table: CrosswalkTable,
    sic_table: CrosswalkTable,
    gics_reference: list[GicsReferenceEntry],
    llm: LLMClient,
) -> tuple[ActivityStandardsMapping, LLMUsage]:
    nace, nace_unmapped = nace_table.lookup_many(activity.core_isic_codes)
    naics, naics_unmapped = naics_table.lookup_many(activity.core_isic_codes)
    sic, sic_unmapped = sic_table.lookup_many(activity.core_isic_codes)
    gics, usage = await classify_gics(activity, gics_reference, llm)

    # Genuinely unmapped only if every loaded crosswalk missed it -- a code
    # absent from an unconfigured/empty table isn't a real gap.
    unmapped_sets = [set(u) for u, loaded in ((nace_unmapped, nace_table), (naics_unmapped, naics_table), (sic_unmapped, sic_table)) if loaded]
    unmapped = [c for c in activity.core_isic_codes if all(c in s for s in unmapped_sets)] if unmapped_sets else []

    mapping = ActivityStandardsMapping(nace_codes=nace, naics_codes=naics, sic_codes=sic, gics=gics, unmapped_isic_codes=unmapped)
    return mapping, usage


async def map_theme_to_standards(
    theme: ThemeDefinition,
    settings: Settings,
    llm: LLMClient,
    *,
    use_sample_icio: bool = False,
    use_sample_exiobase: bool = False,
    use_sample_standards: bool = False,
) -> tuple[ThemeDefinition, LLMUsage]:
    """Populates standards_mapping (NACE/NAICS/SIC/GICS) on every activity
    in the theme.

    Activities without core_isic_codes are classified against ISIC first
    (reusing the indirect-exposure tier's classifier) since ISIC is the
    join key the NACE/NAICS/SIC crosswalks key off of; this step is
    skipped, not fatal, if no input-output model is configured/sampled --
    GICS still classifies directly from the activity's own description
    either way, and NACE/NAICS/SIC simply come back empty for those
    activities.
    """
    total_usage = LLMUsage()
    model = resolve_indirect_exposure_model(settings, use_sample_icio=use_sample_icio, use_sample_exiobase=use_sample_exiobase)
    if model is not None:
        theme, isic_usage = await classify_theme_core_sectors(theme, model, llm)
        total_usage = LLMUsage(input_tokens=isic_usage.input_tokens, output_tokens=isic_usage.output_tokens)

    nace_path = _resolve_table_path(settings.nace_crosswalk_path, "nace", use_sample_standards)
    naics_path = _resolve_table_path(settings.naics_crosswalk_path, "naics", use_sample_standards)
    sic_path = _resolve_table_path(settings.sic_crosswalk_path, "sic", use_sample_standards)
    gics_path = _resolve_table_path(settings.gics_reference_path, "gics", use_sample_standards)

    nace_table = load_crosswalk(nace_path) if nace_path else CrosswalkTable.empty()
    naics_table = load_crosswalk(naics_path) if naics_path else CrosswalkTable.empty()
    sic_table = load_crosswalk(sic_path) if sic_path else CrosswalkTable.empty()
    gics_reference = load_gics_reference(gics_path) if gics_path else []

    new_activities: list[ActivityDefinition] = []
    for activity in theme.activities:
        mapping, usage = await map_activity_standards(activity, nace_table, naics_table, sic_table, gics_reference, llm)
        total_usage = LLMUsage(
            input_tokens=total_usage.input_tokens + usage.input_tokens,
            output_tokens=total_usage.output_tokens + usage.output_tokens,
        )
        new_activities.append(activity.model_copy(update={"standards_mapping": mapping}))
    return theme.model_copy(update={"activities": new_activities}), total_usage


def format_standards_csv(theme: ThemeDefinition) -> str:
    """Flattens each activity's standards_mapping into one CSV row -- the
    exportable deliverable, shared by the CLI and API so the two surfaces
    can't drift on column layout."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["activity_id", "activity_name", "isic_codes", "nace_codes", "naics_codes", "sic_codes", "gics_codes", "gics_labels", "gics_rationale", "unmapped_isic_codes"]
    )
    for activity in theme.activities:
        mapping = activity.standards_mapping
        if mapping is None:
            writer.writerow([activity.activity_id, activity.name, ";".join(activity.core_isic_codes), "", "", "", "", "", "", ""])
            continue
        writer.writerow(
            [
                activity.activity_id,
                activity.name,
                ";".join(activity.core_isic_codes),
                ";".join(m.code for m in mapping.nace_codes),
                ";".join(m.code for m in mapping.naics_codes),
                ";".join(m.code for m in mapping.sic_codes),
                ";".join(m.code for m in mapping.gics),
                ";".join(m.label for m in mapping.gics),
                " | ".join(m.rationale for m in mapping.gics if m.rationale),
                ";".join(mapping.unmapped_isic_codes),
            ]
        )
    return buf.getvalue()
