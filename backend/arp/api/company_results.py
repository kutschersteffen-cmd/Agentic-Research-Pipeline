from __future__ import annotations

from arp.storage.run_store import RunStore

# Shared by extraction.py/financials.py (per-company results) and runs.py
# (the company picker) -- the company-centric complement to a single run's
# own results.jsonl, which is already scoped to a run, not a company.


def list_company_results(run_store: RunStore, run_type: str, company_id: str) -> list[dict]:
    """Every result row for one company across every run of the given type,
    newest run first (list_runs' order)."""
    manifests = run_store.list_runs(run_type)
    matches: list[dict] = []
    for manifest in manifests:
        for row in run_store.read_results(manifest.run_id):
            if row.get("company_id") == company_id:
                matches.append(row)
    return matches


def list_known_companies(run_store: RunStore, run_type: str) -> list[dict]:
    """Every distinct company_id seen across every run of this type, with
    the most recently seen name/ticker -- powers a company picker for the
    "extracted info by company" view without needing a separate company
    directory store. Oldest-run-first iteration so a later run's name/
    ticker (e.g. after a universe correction) wins over an earlier one's."""
    seen: dict[str, dict] = {}
    manifests = reversed(run_store.list_runs(run_type))
    for manifest in manifests:
        for row in run_store.read_results(manifest.run_id):
            company_id = row.get("company_id")
            if not company_id:
                continue
            seen[company_id] = {"company_id": company_id, "name": row.get("name"), "ticker": row.get("ticker")}
    return sorted(seen.values(), key=lambda c: c["company_id"])
