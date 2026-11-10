"""Step 3's start: one run on exactly the files kept in step 2, minus the companies the user skipped."""

from __future__ import annotations

from arp.argus.documents import FlowFile, expected_year
from arp.argus.flows import ArgusFlow
from arp.argus.repeat import RepeatRow, kept_content
from arp.extraction.steps import StepSettings
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import DataPointSchema


class KeptDocuments:
    """A document registry that hands a listed company only its kept documents (by content key); every other
    company, and everything but `fetch_all`, is the wrapped registry's."""

    def __init__(self, inner, only: dict[str, set[str]]) -> None:
        self.inner, self.only = inner, only

    async def fetch_all(self, company: CompanyRef, doc_types: list[DocType] | None = None) -> list[SourceDocument]:
        docs = await self.inner.fetch_all(company, doc_types)
        keep = self.only.get(company.company_id)
        return docs if keep is None else [d for d in docs if d.content_key in keep]

    def __getattr__(self, name):
        return getattr(self.inner, name)


class StartError(ValueError):
    pass


def start_request(
    flow: ArgusFlow, files: list[FlowFile], repeats: list[RepeatRow], schema: DataPointSchema | None,
) -> tuple[dict, dict[str, set[str]]]:
    """The `StartRequest` body for the flow, and the kept content keys per company in it (`only`)."""
    choice = flow.schema_choice
    if choice is None:
        raise StartError("Choose what to extract first.")
    if any(r.kind == "same" and r.company_id not in flow.repeat for r in repeats):
        raise StartError("Choose Skip, keep earlier results or Run again for every company listed.")
    kept = kept_content(files)
    companies = [c for c in flow.companies if c.company_id in kept and flow.repeat.get(c.company_id) != "skip"]
    if not companies:
        raise StartError("Keep at least one file in step 2.")
    s = flow.settings
    body: dict = {
        "mode": s.mode, "batch": s.batch,
        "decision_framework_id": s.decision_framework_id, "decision_framework_version": s.decision_framework_version,
        "step_settings": StepSettings(evidence_max_chunks=s.evidence_passages) if s.evidence_passages else None,
    }
    if choice.kind == "profile":
        body |= {"profile": choice.profile, "as_of": f"FY{expected_year(flow)}" if choice.profile == "tnfd" else None}
    else:
        trial = not schema.release_flag  # a draft runs as a trial on one company and writes no facts
        companies = companies[:1] if trial else companies
        body |= {"profile": "custom", "datapoint_schema": schema, "trial": trial}
    return {**body, "companies": companies}, {c.company_id: kept[c.company_id] for c in companies}
