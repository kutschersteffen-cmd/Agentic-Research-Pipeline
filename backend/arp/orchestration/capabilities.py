"""The capability catalog: every function an agent may call, with its effect and lane (spec agent-panel-code-mode).

Plan lane (effect `run`): the step functions a plan script may call; `plan_api.STEPS`, the checker, the dry run and the
planner's stubs read them from here. Sandbox lane (effect `read`): the tools Ask ARP routes to, called directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Step(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UniverseBuild(_Step):
    taxonomy_id: str  # a ratified Taxonomy Library entry whose schema is released
    source: str  # the starting company universe: a CSV or JSON file path


class DocumentDiscovery(_Step):
    universe_run_id: str
    doc_types: list[str] | None = None
    companies: list[str] | None = None


class Extraction(_Step):
    universe_run_id: str
    schema_id: str
    companies: list[str] | None = None


class FinancialsExtraction(_Step):
    universe_run_id: str
    companies: list[str] | None = None


class XbrlFacts(_Step):
    universe_run_id: str
    companies: list[str] | None = None
    market: str = "auto"


class DecisionScore(_Step):
    source_run_id: str
    framework_id: str | None = None


class IndexConstruct(_Step):
    calibration_id: str  # an approved Index Construction calibration; the version in force on review_date is used
    candidates: str  # JSON file: the IndexCandidate list (prices, shares, sector, country, metrics)
    review_date: str  # YYYY-MM-DD
    index_id: str = "plan_index"
    decision_snapshot_ids: list[str] | None = None  # published Decision Studio results to join as fields


class ReportRender(_Step):
    source_ids: list[str]
    template_id: str | None = None


class IdentityResolution(_Step):
    universe_run_id: str
    companies: list[str] | None = None


class TnfdExtraction(_Step):
    universe_run_id: str
    as_of: str  # the reporting period every company is extracted for
    companies: list[str] | None = None


class BenchmarkSectorsArgs(_Step):
    benchmark_id: str | None = None


class TransitionPlanArgs(_Step):
    company: str | None = None


class PortfolioExposureArgs(_Step):
    question: str


class SmartSearchArgs(_Step):
    question: str


@dataclass(frozen=True)
class Capability:
    id: str
    summary: str
    effect: Literal["read", "run"]
    lane: Literal["plan", "sandbox"]
    input_model: type[BaseModel]
    output_note: str


def _run(id: str, summary: str, model: type[BaseModel]) -> Capability:
    return Capability(id, summary, "run", "plan", model, "Result: id, run_id, companies")


def _read(id: str, summary: str, model: type[BaseModel], output: str) -> Capability:
    return Capability(id, summary, "read", "sandbox", model, output)


CATALOG: list[Capability] = [
    _read("benchmark_sectors", "Sector weights of an uploaded benchmark index.", BenchmarkSectorsArgs,
          "BenchmarkCard"),
    _read("transition_plan", "A company's newest transition plan assessment.", TransitionPlanArgs,
          "TransitionPlanCard"),
    _read("portfolio_exposure", "Exposures, weights or counts over the portfolio holdings.", PortfolioExposureArgs,
          "the portfolio answer model"),
    _read("smart_search", "Open data issues, stored outputs and input feeds.", SmartSearchArgs, "SearchAnswer"),
    _run("universe_build", "Build a theme universe from a saved company universe.", UniverseBuild),
    _run("document_discovery", "Find and download each company's documents.", DocumentDiscovery),
    _run("extraction", "Extract a schema's fields from each company's documents.", Extraction),
    _run("financials_extraction", "Extract each company's financials.", FinancialsExtraction),
    _run("xbrl_facts", "Fetch each company's XBRL facts.", XbrlFacts),
    _run("decision_score", "Score a run with a ratified decision framework.", DecisionScore),
    _run("index_construct", "Preview an index review from a calibration.", IndexConstruct),
    _run("report_render", "Render a report from runs.", ReportRender),
    _run("identity_resolution", "Resolve each company's website, CIK and LEI.", IdentityResolution),
    _run("tnfd_extraction", "Extract each company's TNFD disclosures for one reporting period.", TnfdExtraction),
]
