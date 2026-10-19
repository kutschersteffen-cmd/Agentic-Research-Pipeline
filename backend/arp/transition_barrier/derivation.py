"""Derivation runs: fetch and extract each requested cell's sources, derive the cell from its values, and queue
the result for review."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date

from arp.config import Settings
from arp.llm.base import LLMClient
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.transition_barrier import PrimarySource, Region
from arp.storage.run_store import RunStore
from arp.transition_barrier import RUN_TYPE, clock, fetching, store
from arp.transition_barrier.dataset import data_dir, load_criteria
from arp.transition_barrier.engine import Result, derive
from arp.transition_barrier.extraction import extract, fingerprint
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
    labels = {f["id"]: f["label"] for f in result.snapshot["facts"]}
    several = {f for f, n in Counter(e["fact"] for e in counted).items() if n > 1}
    return {
        "kind": kind, "current": current, "proposed": result.rating if kind in ("changed", "unchanged") else None,
        "values": [f"{e['shown']}, {e['document']}" for e in counted if e["fact"] in several] if kind == "conflict" else [],
        "result_key": key, "entered_by": sorted({e["entered_by"] for e in counted if e["entered_by"]}),
        "rule_book_version": result.rule_book_version,
        "not_counted": [
            f"{labels[e['fact']]} = {e['shown']} ({e['document']}): {e['reason']}"
            for e in result.values if not e["counted"] and e["document"]
        ],
    }


def _llms(settings: Settings) -> tuple[LLMClient, LLMClient]:
    return build_llm_client(settings), build_verifier_llm_client(settings)


async def _fetch_and_extract(cells: list[tuple[str, str]], run_id: str, settings: Settings, today: date) -> dict[str, list[str]]:
    """Fetches the run's registered sources once when refresh is on, then extracts every (cell, fact, latest
    document) with no stored extraction. Returns each source key's fetch notes."""
    notes: dict[str, list[str]] = {}
    if settings.transition_barrier_refresh_enabled:
        sources = {s.key: s for c in cells for s in cell_rules(*c)[1] if s.key}
        for key, source in sources.items():
            notes[key] = await fetching.fetch_sources([source], today)
    sectors = {c.code: c.sector for c in load_criteria()}
    todo = []
    for code, region in cells:
        rules, registry = cell_rules(code, region)
        docs = store.latest_source_documents([s.key for s in registry if s.key])
        for fact in (f for f in rules.facts if f.type):
            fp = fingerprint(fact)
            todo += [(code, region, fact, fp, d) for d in docs if store.extraction(code, region, fact.id, d["id"], fp) is None]
    if not todo:
        return notes
    llm, verifier = _llms(settings)
    conversions = load_rule_book(data_dir())[0].conversions
    limit = asyncio.Semaphore(4)

    async def one(code, region, fact, fp, doc):
        async with limit:
            got = await extract(
                fact, f"{sectors[code]}, {region}, {code}", doc, conversions, llm=llm, verifier_llm=verifier, settings=settings
            )
        store.add_extraction(code=code, region=region, fact=fact.id, doc_id=doc["id"], fingerprint=fp, result=got, run_id=run_id)

    await asyncio.gather(*(one(*t) for t in todo))
    return notes


def execute_derivation_run(run_store: RunStore, run_id: str, settings: Settings, *, today: date | None = None) -> None:
    """Fetches the sources (refresh on), extracts what isn't stored yet, then derives each cell in code."""
    jobs = JobManager(run_store)
    today = today or clock.today()
    version = load_rule_book(data_dir())[0].version
    book = Ratings(run_store)  # the run's own items are undecided, so no cell's rating changes during it
    try:
        cells = [(c["code"], c["region"]) for c in run_store.load_manifest(run_id).params["cells"]]
        fetched = asyncio.run(_fetch_and_extract(cells, run_id, settings, today))
        for code, region in cells:
            rules, registry = cell_rules(code, region)
            notes = [n for s in registry for n in fetched.get(s.key, [])] if settings.transition_barrier_refresh_enabled else [NOT_FETCHED]
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
