"""The steps of each extraction profile, as the node editor shows them.

The shape is read from the compiled per-item LangGraph itself, so the
diagram cannot drift from what runs. Around it sit the two company-level
steps every profile shares: the company record the items are assembled
into, and the rules step (arp.orchestration.batch_runner).

`StepSettings` are the per-run knobs a node exposes; a run started with
some applies them over the app's settings (see `apply`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.config import Settings

ExtractionProfile = Literal["custom", "financials", "tnfd", "transition_plan"]


class StepSettings(BaseModel):
    """Per-run overrides; a field left out keeps the app's setting."""

    pre_identity_enabled: bool | None = None
    pre_content_search_enabled: bool | None = None
    pre_document_mgmt_enabled: bool | None = None
    pre_parse_index_enabled: bool | None = None
    hybrid_retrieval_enabled: bool | None = None
    xbrl_facts_enabled: bool | None = None
    llm_model: str | None = Field(default=None, min_length=1)
    llm_verifier_model: str | None = Field(default=None, min_length=1)
    grounding_fuzzy_threshold: float | None = Field(default=None, ge=0.5, le=1.0)
    confidence_review_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_max_chunks: int | None = Field(default=None, ge=1, le=50)
    rerank_enabled: bool | None = None
    extraction_group_size: int | None = Field(default=None, ge=0, le=20)
    vision_fallback_enabled: bool | None = None

    def apply(self, settings: Settings) -> Settings:
        return settings.model_copy(update=self.model_dump(exclude_none=True))

    @classmethod
    def effective(cls, settings: Settings) -> StepSettings:
        return cls(**{k: getattr(settings, k) for k in cls.model_fields})


SETTING_INFO: dict[str, dict] = {
    "pre_identity_enabled": {"label": "Run this step", "type": "bool", "help": "Resolves the company's website and SEC CIK (at most one LLM call) and uses them if the match is clear."},
    "pre_content_search_enabled": {"label": "Run this step", "type": "bool", "help": "Finds the homepage (from the website, or a web search) and crawls it for report links."},
    "pre_document_mgmt_enabled": {"label": "Run this step", "type": "bool", "help": "Downloads what content search found, records new and changed documents, and counts what the company has."},
    "pre_parse_index_enabled": {"label": "Run this step", "type": "bool", "help": "Parses every document once and caches the text, so each item's evidence step reads it back."},
    "hybrid_retrieval_enabled": {"label": "Hybrid search", "type": "bool", "help": "Ranks evidence by BM25 and local embeddings together; off is BM25 only."},
    "xbrl_facts_enabled": {"label": "SEC XBRL facts first", "type": "bool", "help": "Values EDGAR filers tag in SEC's structured data (CapEx and R&D totals, and any field with XBRL tags) come from it, not the LLM."},
    "llm_model": {"label": "Extractor model", "type": "model", "help": "Drafts each answer with quotes from the evidence."},
    "llm_verifier_model": {"label": "Verifier model", "type": "model", "help": "Checks the draft; keep it different from the extractor so the two don't share blind spots."},
    "grounding_fuzzy_threshold": {"label": "Quote match threshold", "type": "number", "min": 0.5, "max": 1.0, "step": 0.01, "help": "How closely a quote must match its source to count as grounded."},
    "confidence_review_threshold": {"label": "Review below confidence", "type": "number", "min": 0.0, "max": 1.0, "step": 0.05, "help": "Answers under this confidence go to the review queue."},
    "evidence_max_chunks": {"label": "Evidence passages", "type": "number", "min": 1, "max": 50, "step": 1, "help": "How many ranked passages each field's extractor sees."},
    "rerank_enabled": {"label": "Re-rank evidence", "type": "bool", "help": "A cross-encoder re-scores the top passages before the best go to the extractor."},
    "extraction_group_size": {"label": "Fields per call", "type": "number", "min": 0, "max": 20, "step": 1, "help": "Extract this many non-high-risk fields in one call over their shared evidence; each is still verified on its own. 0 or 1: one call per field."},
    "vision_fallback_enabled": {"label": "Page image check", "type": "bool", "help": "A value whose quote is not found in the text is read off the PDF page image; a match clears the not-grounded flag on non-high-risk fields."},
}

# Run modes: one choice that fills the step settings above. Every mode keeps the safety rules (grounding,
# blind verification of high-risk fields, review routing); the extractor and verifier are always different
# models, and Cheap and Max pair a Claude with a Gemini model so the two don't share blind spots.
MODES: dict[str, StepSettings] = {
    "cheap": StepSettings(
        llm_model="gemini-3.8-flash", llm_verifier_model="claude-sonnet-5-5", extraction_group_size=5,
        evidence_max_chunks=8, rerank_enabled=False, vision_fallback_enabled=False, confidence_review_threshold=0.5,
    ),
    "normal": StepSettings(
        llm_model="claude-sonnet-5-5", llm_verifier_model="claude-opus-5-5", extraction_group_size=0,
        evidence_max_chunks=12, vision_fallback_enabled=False, confidence_review_threshold=0.6,
    ),
    "max": StepSettings(
        llm_model="claude-opus-5-5", llm_verifier_model="gemini-4-argon", extraction_group_size=0,
        evidence_max_chunks=20, rerank_enabled=True, vision_fallback_enabled=True, confidence_review_threshold=0.8,
    ),
}

STEP_INFO: dict[str, dict[str, str]] = {
    "start": {"label": "Start", "about": ""},
    "identity": {"label": "Identity", "about": "Resolves who the company is: its website and SEC CIK, from what is known, an EDGAR lookup, or a web search the model adjudicates."},
    "content_search": {"label": "Content search", "about": "Finds the company's homepage and crawls it for sustainability and annual reports, listing candidate URLs."},
    "document_mgmt": {"label": "Document management", "about": "Downloads the found documents into the company's folder, records which are new or changed, and takes stock of its documents."},
    "parse_index": {"label": "Parse & index", "about": "Parses every document (PDF, DOCX, HTML) once and splits it into chunks for evidence ranking."},
    "try_tagged": {"label": "Tagged data first", "about": "A field with XBRL tags takes the filer's own tagged value for each planned year, with no LLM call; otherwise the item goes on to find evidence."},
    "gather_evidence": {"label": "Find evidence", "about": "Fetches the company's documents, splits them into chunks and ranks the chunks against the item's keywords."},
    "finalize_no_evidence": {"label": "No evidence", "about": "Nothing matched: recorded as not disclosed, with no LLM call and no review."},
    "extract": {"label": "Extract", "about": "The extractor model drafts the value, quoting the evidence it used."},
    "answer": {"label": "Answer", "about": "The extractor model answers the indicator Yes/No, quoting the evidence it used."},
    "verify": {"label": "Verify", "about": "A second model checks the draft against the same evidence."},
    "adjudicate": {"label": "Adjudicate", "about": "Only when the verifier disagrees: the verifier model settles the value from the evidence; unsettled or uncited, the item goes to review."},
    "finalize_answer_error": {"label": "Answer failed", "about": "The model never returned a valid answer; recorded as failed and flagged for review."},
    "aggregate": {"label": "Ground & score", "about": "Every quote is re-matched against its source; ungrounded or low-confidence answers go to review."},
    "company": {"label": "Company record", "about": "The company's items are assembled into one record and saved to the run."},
    "rules": {"label": "Rules step", "about": "Once every company is done, the attached Decision Studio framework scores and tiers the run."},
}

_REVIEW = ["grounding_fuzzy_threshold", "confidence_review_threshold"]
PROFILES: dict[str, dict] = {
    "custom": {"item": "each field of each company", "settings": {
        "try_tagged": ["xbrl_facts_enabled"], "gather_evidence": ["hybrid_retrieval_enabled", "evidence_max_chunks", "rerank_enabled"],
        "extract": ["llm_model", "extraction_group_size"], "verify": ["llm_verifier_model"], "adjudicate": ["llm_verifier_model"],
        "aggregate": [*_REVIEW, "vision_fallback_enabled"]}},
    "financials": {"item": "each company", "settings": {
        "gather_evidence": ["hybrid_retrieval_enabled", "xbrl_facts_enabled"], "extract": ["llm_model"], "verify": ["llm_verifier_model"], "aggregate": _REVIEW}},
    "tnfd": {"item": "each company", "settings": {
        "gather_evidence": ["hybrid_retrieval_enabled"], "extract": ["llm_model"], "verify": ["llm_verifier_model"], "aggregate": _REVIEW}},
}
PROFILES["transition_plan"] = PROFILES["custom"]  # the preset runs the field pipeline


def _graph(profile: str):
    if profile in ("custom", "transition_plan"):
        from arp.extraction.field_graph import _COMPILED_GRAPH
    elif profile == "financials":
        from arp.extraction.financials_graph import _COMPILED_GRAPH
    else:
        from arp.extraction.tnfd_graph import _COMPILED_GRAPH
    return _COMPILED_GRAPH.get_graph()


PRE_STEPS = ("identity", "content_search", "document_mgmt", "parse_index")


def pipeline_shape(profile: str, settings: Settings) -> dict:
    """Nodes and edges for the diagram: the start, the optional steps before
    extraction, then the per-item graph -- `__start__` becomes the per-item
    entry and `__end__` the company record -- and the rules step."""
    graph = _graph(profile)
    rename = {"__start__": "item", "__end__": "company"}
    node_settings = PROFILES[profile]["settings"]
    pre = [
        {"id": step, **STEP_INFO[step], "per_item": False, "settings": [f"pre_{step}_enabled"], "optional": True}
        for step in PRE_STEPS
    ]
    nodes = [{"id": "start", **STEP_INFO["start"], "per_item": False, "settings": []}, *pre] + [
        {
            "id": rename.get(n, n),
            "label": f"For {PROFILES[profile]['item']}" if n == "__start__" else STEP_INFO.get(rename.get(n, n), {}).get("label", n),
            "about": "" if n == "__start__" else STEP_INFO.get(rename.get(n, n), {}).get("about", ""),
            "per_item": n != "__end__",
            "settings": node_settings.get(n, []),
        }
        for n in graph.nodes
    ]
    nodes.append({"id": "rules", **STEP_INFO["rules"], "per_item": False, "settings": []})
    chain = ["start", *PRE_STEPS, "item"]
    edges = [{"source": a, "target": b, "conditional": False} for a, b in zip(chain, chain[1:], strict=False)]
    edges += [{"source": rename.get(e.source, e.source), "target": rename.get(e.target, e.target), "conditional": e.conditional} for e in graph.edges]
    edges.append({"source": "company", "target": "rules", "conditional": False})
    return {
        "profile": "custom" if profile == "transition_plan" else profile,  # the same body as custom's
        "nodes": nodes,
        "edges": edges,
        "setting_info": SETTING_INFO,
        "defaults": StepSettings.effective(settings).model_dump(),
        "modes": {name: m.model_dump(exclude_none=True) for name, m in MODES.items()},
    }


def restart_overrides(step: str) -> dict:
    """The settings a restart from `step` runs with: caches are skipped from
    that step on, so it and every later step recompute while the earlier
    ones replay. Grounding and the company record need nothing skipped --
    they rerun on every run from the (cached) model answers."""
    if step in ("start", *PRE_STEPS, "item", "try_tagged", "gather_evidence"):
        return {"document_cache_enabled": False, "llm_cache_refresh": True}
    if step in ("extract", "answer"):
        return {"llm_cache_refresh": True}
    if step in ("verify", "adjudicate"):
        return {"llm_verifier_cache_refresh": True}
    return {}
