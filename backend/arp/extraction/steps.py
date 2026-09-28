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

    hybrid_retrieval_enabled: bool | None = None
    xbrl_facts_enabled: bool | None = None
    llm_model: str | None = Field(default=None, min_length=1)
    llm_verifier_model: str | None = Field(default=None, min_length=1)
    grounding_fuzzy_threshold: float | None = Field(default=None, ge=0.5, le=1.0)
    confidence_review_threshold: float | None = Field(default=None, ge=0.0, le=1.0)

    def apply(self, settings: Settings) -> Settings:
        return settings.model_copy(update=self.model_dump(exclude_none=True))

    @classmethod
    def effective(cls, settings: Settings) -> StepSettings:
        return cls(**{k: getattr(settings, k) for k in cls.model_fields})


SETTING_INFO: dict[str, dict] = {
    "hybrid_retrieval_enabled": {"label": "Hybrid search", "type": "bool", "help": "Ranks evidence by BM25 and local embeddings together; off is BM25 only."},
    "xbrl_facts_enabled": {"label": "SEC XBRL facts first", "type": "bool", "help": "EDGAR filers' CapEx and R&D totals come from SEC's structured data, not the LLM."},
    "llm_model": {"label": "Extractor model", "type": "model", "help": "Drafts each answer with quotes from the evidence."},
    "llm_verifier_model": {"label": "Verifier model", "type": "model", "help": "Checks the draft; keep it different from the extractor so the two don't share blind spots."},
    "grounding_fuzzy_threshold": {"label": "Quote match threshold", "type": "number", "min": 0.5, "max": 1.0, "step": 0.01, "help": "How closely a quote must match its source to count as grounded."},
    "confidence_review_threshold": {"label": "Review below confidence", "type": "number", "min": 0.0, "max": 1.0, "step": 0.05, "help": "Answers under this confidence go to the review queue."},
}

STEP_INFO: dict[str, dict[str, str]] = {
    "gather_evidence": {"label": "Find evidence", "about": "Fetches the company's documents, splits them into chunks and ranks the chunks against the item's keywords."},
    "finalize_no_evidence": {"label": "No evidence", "about": "Nothing matched: recorded as not disclosed, with no LLM call and no review."},
    "extract": {"label": "Extract", "about": "The extractor model drafts the value, quoting the evidence it used."},
    "answer": {"label": "Answer", "about": "The extractor model answers the indicator Yes/No, quoting the evidence it used."},
    "verify": {"label": "Verify", "about": "A second model checks the draft against the same evidence."},
    "finalize_answer_error": {"label": "Answer failed", "about": "The model never returned a valid answer; recorded as failed and flagged for review."},
    "aggregate": {"label": "Ground & score", "about": "Every quote is re-matched against its source; ungrounded or low-confidence answers go to review."},
    "company": {"label": "Company record", "about": "The company's items are assembled into one record and saved to the run."},
    "rules": {"label": "Rules step", "about": "Once every company is done, the attached Decision Studio framework scores and tiers the run."},
}

_REVIEW = ["grounding_fuzzy_threshold", "confidence_review_threshold"]
PROFILES: dict[str, dict] = {
    "custom": {"item": "each field of each company", "settings": {
        "gather_evidence": ["hybrid_retrieval_enabled"], "extract": ["llm_model"], "verify": ["llm_verifier_model"], "aggregate": _REVIEW}},
    "financials": {"item": "each company", "settings": {
        "gather_evidence": ["hybrid_retrieval_enabled", "xbrl_facts_enabled"], "extract": ["llm_model"], "verify": ["llm_verifier_model"], "aggregate": _REVIEW}},
    "tnfd": {"item": "each company", "settings": {
        "gather_evidence": ["hybrid_retrieval_enabled"], "extract": ["llm_model"], "verify": ["llm_verifier_model"], "aggregate": _REVIEW}},
    "transition_plan": {"item": "each indicator of each company", "settings": {
        "gather_evidence": ["hybrid_retrieval_enabled"], "answer": ["llm_model"], "verify": ["llm_verifier_model"], "aggregate": ["grounding_fuzzy_threshold"]}},
}


def _graph(profile: str):
    if profile == "custom":
        from arp.extraction.field_graph import _COMPILED_GRAPH
    elif profile == "financials":
        from arp.extraction.financials_graph import _COMPILED_GRAPH
    elif profile == "tnfd":
        from arp.extraction.tnfd_graph import _COMPILED_GRAPH
    else:
        from arp.transition_plan.indicator_graph import _COMPILED_GRAPH
    return _COMPILED_GRAPH.get_graph()


def pipeline_shape(profile: str, settings: Settings) -> dict:
    """Nodes and edges for the diagram. `__start__` becomes the per-item
    entry and `__end__` the company record, followed by the rules step."""
    graph = _graph(profile)
    rename = {"__start__": "item", "__end__": "company"}
    node_settings = PROFILES[profile]["settings"]
    nodes = [
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
    edges = [{"source": rename.get(e.source, e.source), "target": rename.get(e.target, e.target), "conditional": e.conditional} for e in graph.edges]
    edges.append({"source": "company", "target": "rules", "conditional": False})
    return {
        "profile": profile,
        "nodes": nodes,
        "edges": edges,
        "setting_info": SETTING_INFO,
        "defaults": StepSettings.effective(settings).model_dump(),
    }


def restart_overrides(step: str) -> dict:
    """The settings a restart from `step` runs with: caches are skipped from
    that step on, so it and every later step recompute while the earlier
    ones replay. Grounding and the company record need nothing skipped --
    they rerun on every run from the (cached) model answers."""
    if step in ("item", "gather_evidence"):
        return {"document_cache_enabled": False, "llm_cache_refresh": True}
    if step in ("extract", "answer"):
        return {"llm_cache_refresh": True}
    if step == "verify":
        return {"llm_verifier_cache_refresh": True}
    return {}
