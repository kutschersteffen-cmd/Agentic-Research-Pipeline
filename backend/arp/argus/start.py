"""Step 3's start: one run on exactly the files kept in step 2, minus the companies the user skipped."""

from __future__ import annotations

from arp.argus.documents import FlowFile, expected_year
from arp.argus.flows import ArgusFlow
from arp.argus.repeat import RepeatRow, kept_content
from arp.extraction.steps import StepSettings
from arp.schemas.datapoints import DataPointSchema


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
    # a Skip counts only for a company the warning lists now; an earlier choice may be stale
    skipped = {r.company_id for r in repeats if r.kind == "same" and flow.repeat.get(r.company_id) == "skip"}
    companies = [c for c in flow.companies if c.company_id in kept and c.company_id not in skipped]
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
