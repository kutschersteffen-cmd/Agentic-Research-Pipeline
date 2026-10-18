"""Derivation runs: derive each requested cell from its stored facts and queue the result for review."""

from __future__ import annotations

from collections import Counter
from datetime import date

from arp.config import Settings
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.transition_barrier import PrimarySource, Region
from arp.storage.run_store import RunStore
from arp.transition_barrier import RUN_TYPE, clock, store
from arp.transition_barrier.dataset import data_dir, load_criteria
from arp.transition_barrier.engine import Result, derive
from arp.transition_barrier.ratings import Ratings, item_key
from arp.transition_barrier.rule_book import CriterionRules, load_rule_book

NOT_FETCHED = "Sources not fetched: refresh is disabled"


class UnknownCell(LookupError):
    def __init__(self, code: str, region: str) -> None:
        super().__init__(f"Unknown cell {code} / {region}")


def cell_rules(code: str, region: str) -> tuple[CriterionRules, list[PrimarySource]]:
    """The criterion's rules and registered sources, or UnknownCell for a cell that doesn't exist."""
    criterion = next((c for c in load_criteria() if c.code == code), None)
    if criterion is None or region not in {r.value for r in Region}:
        raise UnknownCell(code, region)
    return load_rule_book(data_dir())[0].criteria[code], criterion.primary_sources


def create_derivation_run(run_store: RunStore, cells: list[tuple[str, str]]) -> str:
    cells = list(dict.fromkeys(cells))
    for code, region in cells:
        cell_rules(code, region)
    params = {"cells": [{"code": c, "region": r} for c, r in cells]}
    return JobManager(run_store).create_run(RUN_TYPE, params, company_count=len(cells)).run_id


def _payload(result: Result, current: str, key: str) -> dict:
    kind = result.rating if result.rating in ("not_rated", "conflict") else "unchanged" if result.rating == current else "changed"
    counted = [e for e in result.values if e["counted"] and e["document"]]
    several = {f for f, n in Counter(e["fact"] for e in counted).items() if n > 1}
    return {
        "kind": kind, "current": current, "proposed": result.rating if kind in ("changed", "unchanged") else None,
        "values": [f"{e['shown']}, {e['document']}" for e in counted if e["fact"] in several] if kind == "conflict" else [],
        "result_key": key, "entered_by": sorted({e["entered_by"] for e in counted if e["entered_by"]}),
        "rule_book_version": result.rule_book_version,
    }


def execute_derivation_run(run_store: RunStore, run_id: str, settings: Settings, *, today: date | None = None) -> None:
    """Pure code and database reads: no model is called and no source is fetched."""
    jobs = JobManager(run_store)
    today = today or clock.today()
    notes = [] if settings.transition_barrier_refresh_enabled else [NOT_FETCHED]
    version = load_rule_book(data_dir())[0].version
    book = Ratings(run_store)  # the run's own items are undecided, so no cell's rating changes during it
    try:
        for cell in run_store.load_manifest(run_id).params["cells"]:
            code, region = cell["code"], cell["region"]
            rules, registry = cell_rules(code, region)
            result = derive(
                rules, region, store.cell_values(code, region, rules, registry, today),
                rule_book_version=version, run_id=run_id, snapshot=rules.model_dump(mode="json"), notes=notes,
            )
            key = item_key(code, region)
            run_store.append_result(run_id, {"_key": key, **result.model_dump(mode="json")})
            payload = _payload(result, book.cell(code, region).rating.value, key)
            queue_for_review(run_store, run_id, key, {"code": code, "region": region, **payload})
            jobs.record_progress(run_id, completed_delta=1, review_delta=1)
    except Exception as exc:
        jobs.finish_run(run_id, error=str(exc))
        raise
    jobs.finish_run(run_id)
