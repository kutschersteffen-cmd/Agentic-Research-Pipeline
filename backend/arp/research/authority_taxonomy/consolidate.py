from __future__ import annotations

from arp.config import Settings
from arp.llm.base import LLMClient
from arp.research.authority_taxonomy.extract import SourceExtraction
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.standards_mapping.mapper import map_theme_to_standards
from arp.schemas.authority_taxonomy import SectorCode, merge_key
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition

_TOP_UPSTREAM = 5


def _isic(model: LeontiefModel | None, code: str) -> str:
    """ICIO code -> ISIC section letter + first division (D -> D35), the form authority sources cite."""
    divisions = model.isic_divisions.get(code) if model else None
    return f"{code[0]}{divisions[0]}" if divisions else code


def _upstream(model: LeontiefModel, code: str) -> list[str]:
    """Top supplier codes by the code's total-requirements column, skipping codes sharing its nodes."""
    own = set(model.code_nodes.get(code, []).tolist())
    if not own:
        return []
    column = model.leontief_inverse[:, sorted(own)].sum(axis=1)
    scored = [
        (float(column[nodes].sum()), c)
        for c, nodes in model.code_nodes.items()
        if len(nodes) and model.isic_divisions.get(c) and not own & set(nodes.tolist())
    ]
    return [c for _, c in sorted(scored, key=lambda s: (-s[0], s[1]))[:_TOP_UPSTREAM]]


def _merge(kept: list, new: list, key, cites: bool = True) -> None:
    """Appends items of `new` whose key is unseen; for a seen key, unions the citations."""
    for item in new:
        match = next((k for k in kept if key(k) == key(item)), None)
        if match is None:
            kept.append(item)
        elif cites:
            match.citations += [c for c in item.citations if c not in match.citations]


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
    """Merges per-source activities by merge_key (deterministic), then attaches sector codes:
    source codes, map_theme_to_standards codes, and on value_chain the top-5 EXIOBASE upstream industries."""
    groups: dict[str, ActivityDefinition] = {}
    for ext in extractions:
        for act in ext.activities:
            act = act.model_copy(update={"sector_codes": act.sector_codes + ext.sector_codes}, deep=True)
            codes = act.sector_codes
            act.sector_codes = []
            _merge(act.sector_codes, codes, lambda c: (c.system, c.code, c.origin), cites=False)
            kept = groups.setdefault(merge_key(act.name), act)
            if kept is act:
                continue
            kept.citations += act.citations
            kept.out_of_scope_citations += act.out_of_scope_citations
            for crit in act.criteria:
                if crit.text not in {k.text for k in kept.criteria}:
                    kept.criteria.append(crit)
            kept.seed_keywords += [k for k in act.seed_keywords if k not in kept.seed_keywords]
            for code in act.sector_codes:
                _add(kept.sector_codes, code)

    techs, defs, thresholds = [], [], []
    for e in extractions:
        _merge(techs, [t.model_copy(deep=True) for t in e.technologies], lambda t: merge_key(t.name))
        _merge(defs, [d.model_copy(deep=True) for d in e.definitions], lambda d: merge_key(d.term))
        _merge(thresholds, [t.model_copy(deep=True) for t in e.thresholds], lambda t: t.citations[0].quote if t.citations else t.text)

    theme = ThemeDefinition(
        name=theme_name,
        description=next((e.theme_description for e in extractions if e.theme_description), ""),
        scope=scope,
        activities=list(groups.values()),
        technologies=techs,
        definitions=defs,
        thresholds=thresholds,
        checklist_report={e.url: e.report for e in extractions},
    )
    theme, _usage = await map_theme_to_standards(theme, settings, llm)

    io = value_chain_model  # labels map_standards' ICIO codes as ISIC; loaded only when there are codes to label
    if io is None and any(a.core_isic_codes for a in theme.activities):
        io = resolve_indirect_exposure_model(settings)
    notes: list[str] = []
    if value_chain and value_chain_model is None:
        notes.append("no IO model: sector codes not widened with EXIOBASE upstream industries")
    for act in theme.activities:
        for isic in act.core_isic_codes:
            _add(act.sector_codes, SectorCode(system="ISIC", code=_isic(io, isic), origin="map_standards"))
        if m := act.standards_mapping:
            for system, matches in (("NACE", m.nace_codes), ("NAICS", m.naics_codes), ("SIC", m.sic_codes), ("GICS", m.gics)):
                for match in matches:
                    _add(act.sector_codes, SectorCode(system=system, code=match.code, origin="map_standards"))
        if value_chain and value_chain_model is not None:
            for isic in act.core_isic_codes:
                for up in _upstream(value_chain_model, isic):
                    _add(act.sector_codes, SectorCode(system="ISIC", code=_isic(value_chain_model, up), origin="exiobase"))
    return theme, "\n".join(notes)
