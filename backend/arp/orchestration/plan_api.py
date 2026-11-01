"""The closed set of step functions a plan script may call, with their typed inputs.

Adapters that start the real run types come with the executor (plan task 7); the checker, the dry run
and the planner prompt only need the input models.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Step(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UniverseBuild(_Step):
    theme: str
    region: str | None = None
    taxonomy_id: str | None = None


class DocumentDiscovery(_Step):
    universe_id: str
    doc_types: list[str] | None = None
    companies: list[str] | None = None


class Extraction(_Step):
    universe_id: str
    schema_id: str
    companies: list[str] | None = None


class FinancialsExtraction(_Step):
    universe_id: str
    companies: list[str] | None = None


class XbrlFacts(_Step):
    universe_id: str
    companies: list[str] | None = None
    market: str = "auto"


class DecisionScore(_Step):
    source_run_id: str
    framework_id: str | None = None


class IndexConstruct(_Step):
    decision_id: str
    methodology_id: str | None = None


class ReportRender(_Step):
    source_ids: list[str]
    template_id: str | None = None


STEPS: dict[str, type[_Step]] = {
    "universe_build": UniverseBuild,
    "document_discovery": DocumentDiscovery,
    "extraction": Extraction,
    "financials_extraction": FinancialsExtraction,
    "xbrl_facts": XbrlFacts,
    "decision_score": DecisionScore,
    "index_construct": IndexConstruct,
    "report_render": ReportRender,
}

# Fields a step result exposes to the script. Each company carries id, exposure, has_xbrl.
RESULT_FIELDS = ("id", "run_id", "companies")
BUILTINS = ("len", "min", "max", "sorted", "sum", "range")
