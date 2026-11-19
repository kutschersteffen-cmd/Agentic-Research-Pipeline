from __future__ import annotations

from arp.config import Settings
from arp.llm.base import LLMClient
from arp.research.authority_taxonomy.extract import SourceExtraction
from arp.research.authority_taxonomy.matching import match_activities
from arp.research.indirect_exposure import nace
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.standards_mapping.mapper import map_theme_to_standards
from arp.schemas.authority_taxonomy import SectorCode, merge_key
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition

_TOP_UPSTREAM = 5


def _isic(sector: str) -> list[str]:
    """Sector -> ISIC section letter + division via NACE (spec decision 5): Production of electricity by wind -> D35,
    the form authority sources cite."""
    divisions = sorted({i[:2] for n in nace.sector_nace2_codes(sector) for i in nace.nace2_to_isic4(n)})
    return [f"{nace.isic4_section(d)}{d}" for d in divisions if nace.isic4_section(d)]


def _upstream(model: LeontiefModel, sector: str) -> list[str]:
    """Top-5 supplier industries as ISIC codes: sectors ranked by the sector's total-requirements column, skipping
    sectors sharing its nodes, then converted; codes repeated or among the sector's own are skipped."""
    own = set(model.code_nodes.get(sector, []).tolist())
    if not own:
        return []
    column = model.leontief_inverse[:, sorted(own)].sum(axis=1)
    scored = [
        (float(column[nodes].sum()), c)
        for c, nodes in model.code_nodes.items()
        if len(nodes) and nace.sector_nace2_codes(c) and not own & set(nodes.tolist())
    ]
    out, skip = [], set(_isic(sector))
    for _, c in sorted(scored, key=lambda s: (-s[0], s[1])):
        for code in _isic(c):
            if code not in skip and len(out) < _TOP_UPSTREAM:
                out.append(code)
                skip.add(code)
        if len(out) == _TOP_UPSTREAM:
            break
    return out


def _merge(kept: list, new: list, key, cites: bool = True) -> None:
    """Appends items of `new` whose key is unseen; for a seen key, unions the citations."""
    for item in new:
        match = next((k for k in kept if key(k) == key(item)), None)
        if match is None:
            kept.append(item)
        elif cites:
            match.citations += [c for c in item.citations if c not in match.citations]


def _fold(kept: ActivityDefinition, act: ActivityDefinition) -> None:
    kept.citations += act.citations
    kept.out_of_scope_citations += act.out_of_scope_citations
    for crit in act.criteria:
        if crit.text not in {k.text for k in kept.criteria}:
            kept.criteria.append(crit)
    kept.seed_keywords += [k for k in act.seed_keywords if k not in kept.seed_keywords]
    for code in act.sector_codes:
        _add(kept.sector_codes, code)


def _add(codes: list[SectorCode], new: SectorCode) -> None:
    if not any((c.system, c.code) == (new.system, new.code) for c in codes):
        codes.append(new)


async def consolidate(
    extractions: list[SourceExtraction],
    *,
    theme_name: str,
    scope: str,
    value_chain: bool,
    settings: Settings,
    llm: LLMClient,
    value_chain_model: LeontiefModel | None,
) -> tuple[ThemeDefinition, str]:
    """Merges per-source activities source by source with match_activities, then attaches sector codes:
    source codes, map_theme_to_standards codes, and on value_chain the top-5 EXIOBASE upstream industries."""
    kept_acts: list[ActivityDefinition] = []
    for ext in extractions:
        new: list[ActivityDefinition] = []
        for act in ext.activities:
            act = act.model_copy(update={"sector_codes": act.sector_codes + ext.sector_codes}, deep=True)
            codes = act.sector_codes
            act.sector_codes = []
            _merge(act.sector_codes, codes, lambda c: (c.system, c.code, c.origin), cites=False)
            same = next((n for n in new if merge_key(n.name) == merge_key(act.name)), None)
            if same is None:
                new.append(act)
            else:  # same merge key within one source: merge before matching, no model call
                _fold(same, act)
        matched = {m.right: kept_acts[m.left] for m in await match_activities(kept_acts, new, scope=scope, llm=llm)}
        for j, act in enumerate(new):
            kept = matched.get(j)
            if kept is None:
                kept_acts.append(act)
                continue
            _fold(kept, act)

    techs, defs, thresholds = [], [], []
    for e in extractions:
        _merge(techs, [t.model_copy(deep=True) for t in e.technologies], lambda t: merge_key(t.name))
        _merge(defs, [d.model_copy(deep=True) for d in e.definitions], lambda d: merge_key(d.term))
        _merge(thresholds, [t.model_copy(deep=True) for t in e.thresholds], lambda t: t.citations[0].quote if t.citations else t.text)

    theme = ThemeDefinition(
        name=theme_name,
        description=next((e.theme_description for e in extractions if e.theme_description), ""),
        scope=scope,
        activities=kept_acts,
        technologies=techs,
        definitions=defs,
        thresholds=thresholds,
        checklist_report={e.url: e.report for e in extractions},
    )
    theme, _usage = await map_theme_to_standards(theme, settings, llm)

    notes: list[str] = []
    if value_chain and value_chain_model is None:
        notes.append("no IO model: sector codes not widened with EXIOBASE upstream industries")
    for act in theme.activities:
        for isic in (i for sector in act.core_sectors for i in _isic(sector)):
            _add(act.sector_codes, SectorCode(system="ISIC", code=isic, origin="map_standards"))
        if m := act.standards_mapping:
            for system, matches in (("NACE", m.nace_codes), ("NAICS", m.naics_codes), ("SIC", m.sic_codes), ("GICS", m.gics)):
                for match in matches:
                    _add(act.sector_codes, SectorCode(system=system, code=match.code, origin="map_standards"))
        if value_chain and value_chain_model is not None:
            for isic in (u for sector in act.core_sectors for u in _upstream(value_chain_model, sector)):
                _add(act.sector_codes, SectorCode(system="ISIC", code=isic, origin="exiobase"))
    return theme, "\n".join(notes)
