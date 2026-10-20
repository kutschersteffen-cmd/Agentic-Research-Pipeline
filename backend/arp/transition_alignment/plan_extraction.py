"""Part A list extraction: one model call per transition plan document returns its actions and assumed prices;
each stated value becomes one row, grounded and typed as any other field's (rulings P3, P5, P6)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.config import Settings
from arp.extraction.extractor_agent import PeriodValue, format_evidence
from arp.extraction.field_graph import field_evidence, merge_evidence
from arp.grounding import ground_citations
from arp.llm.base import LLMClient, LLMUsage
from arp.normalise.value import typed_value
from arp.presets.transition_plan_actions import ACTION_FIELDS
from arp.schemas.common import Citation, CompanyRef, DocumentChunk, ProvenanceInfo, SourceDocument
from arp.schemas.datapoints import ExtractedField, FieldDefinition
from arp.schemas.review import ReasonCode
from arp.transition_alignment.action_check import sector_actions

ASSUMPTION_FIELD = {"carbon_price": "ta_assumed_carbon_price", "h2_cost": "ta_assumed_h2_cost"}


class Cited(BaseModel):
    value: str | float | None = None
    unit: str | None = None
    quote: str = Field(default="", description="Verbatim substring of the evidence this value is read from.")
    page: int | None = None


class ActionDraft(BaseModel):
    text: Cited
    action_id: Cited | None = None
    status: Cited | None = None
    year: Cited | None = None
    region: Cited | None = None
    ghg_saving: Cited | None = None
    capex_needed: Cited | None = None
    capex_allocated: Cited | None = None


class AssumptionDraft(BaseModel):
    kind: Literal["carbon_price", "h2_cost"]
    value: float
    unit: str
    region: str | None = None
    year: int | None = None
    quote: str
    page: int | None = None


class PlanDraft(BaseModel):
    actions: list[ActionDraft] = Field(default_factory=list)
    assumptions: list[AssumptionDraft] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


_SYSTEM = """\
You read a company's transition plan and list its decarbonisation actions and the prices it assumes.
Rules:
- An action is one specific measure, technology or asset. Vague intentions ("we will reduce emissions") are not actions.
- List actions in the order the plan states them. For each value give the value as printed, its unit where it
  has one, the page, and a `quote` that is an EXACT, VERBATIM substring of the evidence it is read from.
- Leave a value out when the plan does not state it. NEVER estimate, infer or compute a value.
- action_id: exactly one id from the allowed list, or "other" if none fits.
- status: "implemented" (in operation) or "planned". region: "European Union", "United States", "China" or "other".
- ghg_saving unit: "tCO2e/yr", "MtCO2e/yr" or "%". Capex: the number as printed with its unit, e.g. 1500 and
  "EUR million"; never convert.
- assumptions: an assumed carbon price (kind carbon_price, unit "<currency>/tCO2") or hydrogen cost (kind h2_cost,
  unit "<currency>/kg H2"), with the region and year it applies to if stated."""


def plan_evidence(fields: list[FieldDefinition], document: SourceDocument, settings: Settings) -> list[DocumentChunk]:
    """The document's passages for the list fields: keyword retrieval, hybrid off (P6)."""
    keyword = settings.model_copy(update={"hybrid_retrieval_enabled": False})
    return merge_evidence([field_evidence(f, [document], keyword) for f in fields], settings.evidence_max_chunks * 2)


def _cite(c: Cited, document: SourceDocument) -> Citation:
    return Citation(doc_id=document.doc_id, doc_type=document.doc_type, quote=c.quote, location=f"p. {c.page}" if c.page else None)


def _row(field: FieldDefinition, c: Cited, document: SourceDocument, passages: dict, fuzzy: float, confidence: float,
         *, basis: str, period_end: str | None, provenance: ProvenanceInfo) -> ExtractedField:
    pv = PeriodValue(value=c.value, unit_text=c.unit, citations=[_cite(c, document)])
    tv = typed_value(field, pv, fiscal_year_end=None)
    cites = ground_citations(pv.citations, {document.doc_id: document}, fuzzy, passages=passages)
    grounded = all(x.grounded for x in cites)
    # the same reason and note the aggregator gives an ungrounded value
    reasons = ([] if grounded else [ReasonCode.NOT_GROUNDED]) + tv.reasons + [ReasonCode.UNVERIFIED_LIST_ITEM]
    notes = ([] if grounded else ["One or more citations failed the programmatic grounding check."]) + tv.notes
    return ExtractedField(
        field_id=field.field_id, field_name=field.name, value=tv.value, citations=cites, confidence=confidence,
        extractor_confidence=confidence, grounded=grounded, verifier_notes=" ".join(notes) or None,
        review_reasons=reasons, value_state=tv.value_state, unit=tv.unit, canonical_value=tv.canonical_value,
        canonical_unit=tv.canonical_unit, scale_applied=tv.scale_applied, period_end=period_end, basis=basis,
        provenance=provenance, method="extracted",
    )


async def extract_plan(
    company: CompanyRef, sector: str | None, document: SourceDocument, chunks: list[DocumentChunk], llm: LLMClient,
    *, fields: list[FieldDefinition], fuzzy_threshold: float, schema_version: str = "",
) -> tuple[list[ExtractedField], LLMUsage]:
    """One row per stated value of `fields` (the list fields still to extract). An action's rows share basis
    `action:<doc_id>:<page>:<n>`; an assumption has `region:<Region>` or `region:any`, period_end 31 Dec of its year."""
    ids = [*(f"{a['id']} ({a['label']})" for a in sector_actions(sector)), "other"]
    prompt = (f"Company: {company.name}\nAllowed action ids: {', '.join(ids)}\n\n"
              f"Evidence:\n{format_evidence(chunks)}")
    draft, usage = await llm.complete_structured(system=_SYSTEM, prompt=prompt, output_model=PlanDraft)
    by_id = {f.field_id: f for f in fields}
    passages = {c.chunk_id: c for c in chunks}
    provenance = {fid: ProvenanceInfo(provider=usage.provider, extractor_model=usage.model,
                                      extractor_prompt_version=usage.prompt_version, schema_version=schema_version,
                                      field_version=f.version) for fid, f in by_id.items()}

    def row(fid: str, c: Cited, basis: str, period_end: str | None = None) -> ExtractedField:
        return _row(by_id[fid], c, document, passages, fuzzy_threshold, draft.confidence,
                    basis=basis, period_end=period_end, provenance=provenance[fid])

    out: list[ExtractedField] = []
    on_page: dict[int | None, int] = {}
    for a in draft.actions:
        cites = ground_citations([_cite(a.text, document)], {document.doc_id: document}, fuzzy_threshold, passages=passages)
        page = next((c.page for c in cites if c.grounded), None) or a.text.page
        on_page[page] = on_page.get(page, 0) + 1
        basis = f"action:{document.doc_id}:{page}:{on_page[page]}"
        values = zip(ACTION_FIELDS, (a.text, a.action_id, a.status, a.year, a.region, a.ghg_saving, a.capex_needed,
                                     a.capex_allocated), strict=True)
        out += [row(fid, c, basis) for fid, c in values if fid in by_id and c is not None and c.value is not None]
    for s in draft.assumptions:
        fid = ASSUMPTION_FIELD[s.kind]
        if fid in by_id:
            c = Cited(value=s.value, unit=s.unit, quote=s.quote, page=s.page)
            out.append(row(fid, c, f"region:{s.region or 'any'}", f"{s.year}-12-31" if s.year else None))
    return out, usage
