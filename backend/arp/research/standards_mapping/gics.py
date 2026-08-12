from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.standards import GicsMatch
from arp.schemas.thematic import ActivityDefinition

_SYSTEM_PROMPT = """\
You classify a thematic investment activity against a fixed list of GICS \
(Global Industry Classification Standard) entries spanning all four levels \
of the hierarchy -- sector, industry group, industry, and sub-industry \
(each entry's level is given in parentheses).

Prefer the most specific level that genuinely fits: pick a sub-industry \
when the activity clearly matches one, and only fall back to a broader \
industry/industry group/sector match when no sub-industry (or industry) \
is specific enough to be accurate. Do not select both a sub-industry and \
its parent industry/industry group/sector for the same match -- pick the \
single most specific applicable level.

Select only entries that are a direct, primary match for the activity as \
described -- not merely economically adjacent or a plausible customer/
supplier. Most activities match exactly one entry; select more than one \
only when the activity plainly spans multiple distinct GICS categories. \
If nothing in the list is a good match, return an empty list rather than \
picking the closest-sounding one. For every entry you select, give a \
one-sentence rationale grounded in the activity's own in-scope \
description."""


@dataclass
class GicsReferenceEntry:
    code: str
    label: str
    level: str


class _GicsSelection(BaseModel):
    code: str
    rationale: str


class _GicsSelectionList(BaseModel):
    matches: list[_GicsSelection] = Field(default_factory=list)


def load_gics_reference(path: Path) -> list[GicsReferenceEntry]:
    entries: list[GicsReferenceEntry] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            entries.append(GicsReferenceEntry(code=row["code"].strip(), label=row["label"].strip(), level=row.get("level", "").strip()))
    return entries


def _format_reference_list(reference: list[GicsReferenceEntry]) -> str:
    return "\n".join(f"{e.code} ({e.level}): {e.label}" for e in reference)


async def classify_gics(
    activity: ActivityDefinition, reference: list[GicsReferenceEntry], llm: LLMClient
) -> tuple[list[GicsMatch], LLMUsage]:
    """Classifies one activity against a fixed GICS reference list -- there
    is no public official ISIC->GICS correspondence table (unlike NACE/
    NAICS/SIC), so this is a closed-list LLM judgment call, the same
    pattern as `indirect_exposure/core_sectors.py::classify_core_sectors`:
    a rationale per match, and any code the model returns that isn't
    actually in the reference list is dropped rather than trusted.
    """
    if not reference:
        return [], LLMUsage()

    prompt = (
        f"Activity: {activity.name}\n"
        f"In scope: {activity.in_scope_description}\n"
        f"Out of scope: {activity.out_of_scope_description}\n\n"
        f"Available GICS entries:\n{_format_reference_list(reference)}"
    )
    draft, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_GicsSelectionList)

    by_code = {e.code: e for e in reference}
    matches: list[GicsMatch] = []
    for selection in draft.matches:
        entry = by_code.get(selection.code)
        if entry is None:
            continue
        matches.append(GicsMatch(code=entry.code, label=entry.label, rationale=selection.rationale))
    return matches, usage
