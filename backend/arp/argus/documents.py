"""Argus step 2: the flow's files, each with its check and its keep/remove state."""

from __future__ import annotations

from typing import Literal

from arp.argus.flows import ArgusFlow, FlowFile

PASSED = "✓ name, year"


def check_text(f: FlowFile, reporting_year: int) -> str | None:
    """What is wrong with the file, first problem only; None when it passed. Computed on every read, so a changed reporting year re-checks."""
    if f.duplicate_of:
        return f"Duplicate of {f.duplicate_of}, skipped"
    if f.company_match in ("none", "no_text"):
        return "Company not found in document"
    if f.year is None:
        return "Year unclear"
    if f.year != reporting_year:
        return f"Year {f.year}, expected {reporting_year}"
    return None


class FlowFileView(FlowFile):
    check: str
    passed: bool
    state: Literal["kept", "removed"] | None


def file_views(flow: ArgusFlow, discovered: list[FlowFile]) -> list[FlowFileView]:
    """Uploads, then discovered files, one per key. A passing file is kept until someone removes it; a failing one waits for a person."""
    views, seen = [], set()
    for f in [*flow.uploads, *discovered]:
        if f.key in seen:
            continue
        seen.add(f.key)
        problem = check_text(f, flow.reporting_year)
        state = flow.decisions.get(f.key) if not f.duplicate_of else None
        if state is None and problem is None:
            state = "kept"
        views.append(FlowFileView(**f.model_dump(), check=problem or PASSED, passed=problem is None, state=state))
    return views
