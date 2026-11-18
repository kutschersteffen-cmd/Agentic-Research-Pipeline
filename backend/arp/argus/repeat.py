"""Step 3's repeat rule: per company, compare the chosen schema version and the kept files' contents with that
company's latest run (spec, The repeat rule). Computed on every read, never stored."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from arp.api.auth import Principal
from arp.argus.documents import FlowFile
from arp.argus.flows import ArgusFlow, SchemaChoice
from arp.argus.rows import _prior_runs
from arp.ingestion.registry import read_only_documents
from arp.schemas.common import RunManifest
from arp.storage.run_store import RunStore


class RepeatRow(BaseModel):
    company_id: str
    kind: Literal["same", "added"]
    added: int  # files added since the earlier run, for `added`
    run_id: str
    date: str
    approved: int
    waiting: int


def chosen_version(choice: SchemaChoice | None) -> str | None:
    """As runs record it: `<schema_id>:v<n>` for a schema, the run type for a fixed profile."""
    if choice is None:
        return None
    return choice.profile if choice.kind == "profile" else f"{choice.schema_id}:v{choice.version}"


def run_version(m: RunManifest) -> str:
    return str(m.params.get("schema_version")) if m.run_type == "extraction" else m.run_type


def classify(chosen: str | None, earlier_version: str | None, earlier: set[str], now: set[str]) -> tuple[str | None, int]:
    """`same` (same version, same file contents), `added` (same version, files only added since) or None."""
    if chosen is None or earlier_version != chosen or not earlier:  # no record of what the earlier run read
        return None, 0
    if earlier == now:
        return "same", 0
    if earlier < now:
        return "added", len(now - earlier)
    return None, 0


def kept_content(files: list[FlowFile]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in files:
        if f.state == "kept" and f.content_key:
            out.setdefault(f.company_id, set()).add(f.content_key)
    return out


def repeat_rows(flow: ArgusFlow, files: list[FlowFile], last_runs: dict[str, str], *, run_store: RunStore,
                principal: Principal) -> list[RepeatRow]:
    """`last_runs`: company id -> its newest extraction-like run (as step 1 finds it)."""
    chosen = chosen_version(flow.schema_choice)
    kept = kept_content(files)
    if chosen is None or not kept:
        return []
    prior = _prior_runs(run_store, {c: r for c, r in last_runs.items() if c in kept}, principal)
    out = []
    for cid, now in kept.items():
        run_id = last_runs.get(cid)
        m = run_store.load_manifest(run_id) if run_id else None
        if m is None or m.params.get("trial") or cid not in prior:  # a trial stored no facts: nothing was extracted before
            continue
        recorded = read_only_documents(run_store.run_dir(run_id))  # runs started from Argus record their files
        earlier = recorded.get(cid, set()) if recorded is not None else {
            d["content_key"] for row in run_store.read_results(run_id) if row.get("company_id") == cid
            for d in row.get("documents") or [] if d.get("content_key")}
        kind, added = classify(chosen, run_version(m), earlier, now)
        if kind:
            p = prior[cid]
            out.append(RepeatRow(company_id=cid, kind=kind, added=added, run_id=run_id, date=p.date,
                                 approved=p.approved, waiting=p.waiting))
    return out
