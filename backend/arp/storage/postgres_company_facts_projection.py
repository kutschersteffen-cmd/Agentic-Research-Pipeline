"""Materializes each run's results.jsonl rows plus
orchestration/review_queue.py's decisions into CompanyFactModel
(arp/storage/postgres_models.py -- see that model's own docstring for
the full design). results.jsonl and review_decisions.jsonl/
review_queue.jsonl stay authoritative; this module only ever reads them
and writes derived, versioned rows.
"""

from __future__ import annotations

import logging

from arp.orchestration.review_queue import latest_decisions
from arp.schemas.common import now_iso
from arp.storage.postgres import get_engine
from arp.storage.postgres_projection_config import ProjectionConfig
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

# Maps a run's manifest.run_type to a human-readable fact_type. Falls
# back to the raw run_type string for anything not listed (see
# fact_candidates' fallback branch below) -- so a future run type never
# raises here, it just gets a less polished fact_type label.
_FACT_TYPE_BY_RUN_TYPE = {
    "extraction": "extraction_record",
    "financials": "financials_record",
    "theme": "theme_match",
    "proxy_voting": "voting_position",
}


def fact_candidates(run_type: str, row: dict) -> list[tuple[str, dict]]:
    """Pure: maps one results.jsonl row to (item_key, raw_value) pairs at
    the SAME granularity each pipeline's own queue_for_review call uses,
    so review decisions resolve against the right key. Verified against
    the actual call sites, not assumed from docstrings:

    - "theme" (arp/research/pipeline.py::execute_theme_run): the row is
      `{"company_matches": [<CompanyMatch dict>, ...], "_key": company_id}`
      (result_to_json builds this shape; there is no top-level
      company_id on the row itself). Reviewable unit is one match, keyed
      "{company_id}:{activity_id}" -- matches the key execute_theme_run's
      `review_items` queues: `f"{c.company_id}:{m.activity_id}"`.
    - "proxy_voting" (arp/voting/pipeline.py): the row is a CompanyBallot
      dict with a `votes: list[VoteRecord]`. Reviewable unit is one vote,
      keyed "{company_id}:{proposal_number}" -- matches
      `_item_key(company.company_id, vote.proposal.proposal_number)`.
    - everything else (extraction, financials, and any future run type
      not listed above): the whole row is the reviewable unit, keyed at
      company_id alone -- matches extraction/financials'
      `queue_for_review(run_store, run_id, company.company_id, ...)`
      exactly (their own item_key is the bare company_id, not a
      composite, despite review_queue.py's docstring example).
    """
    company_id = row.get("_key")
    if not company_id:
        return []
    if run_type == "theme":
        return [(f"{company_id}:{m['activity_id']}", m) for m in row.get("company_matches", []) if "activity_id" in m]
    if run_type == "proxy_voting":
        candidates = []
        for vote in row.get("votes", []):
            proposal_number = (vote.get("proposal") or {}).get("proposal_number")
            if proposal_number:
                candidates.append((f"{company_id}:{proposal_number}", vote))
        return candidates
    return [(company_id, row)]


def fact_confidence(value: dict) -> float | None:
    """The confidence CompanyFactModel.confidence records, or None when the
    run type has none. Verified against the row shapes fact_candidates
    produces: a CompanyMatch and an ExtractedField each carry `confidence`,
    an ExtractionRecord/CompanyFinancialsRecord carries
    `overall_confidence`, a VoteRecord carries neither (a policy
    recommendation is a judgment, not a scored extraction).

    The column was declared and documented from the start but never
    populated -- a caller reading this table saw NULL for every fact and
    had to go back to `payload` (or to results.jsonl) for the one number
    most likely to be filtered on.
    """
    for key in ("confidence", "overall_confidence"):
        candidate = value.get(key)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return float(candidate)
    return None


def fact_citations(value: dict) -> list | None:
    """The citation set behind a fact, or None when there is none. Kept as
    the raw citation dicts (JSONB) rather than a rendered string: a caller
    checking "is this fact grounded, and in which document" needs the
    doc_id/quote structure the pipelines already produce.

    A CompanyMatch cites at its own level; an ExtractionRecord cites per
    field, so its fields' citations are concatenated in field order --
    the whole record is one fact row at this table's granularity.
    """
    citations = value.get("citations")
    if isinstance(citations, list) and citations:
        return citations
    fields = value.get("fields")
    if isinstance(fields, list):
        collected = [c for field in fields if isinstance(field, dict) for c in (field.get("citations") or [])]
        if collected:
            return collected
    return None


def resolve_fact(item_key: str, raw_value: dict, decisions: dict[str, dict], queued_item_keys: set[str]) -> tuple[dict, str, str | None]:
    """Pure: determines a fact candidate's materialized (value, status,
    reviewer) from this run's latest_decisions() map and the set of
    item_keys ever queued for review (read from review_queue.jsonl) --
    the same signal each pipeline's own queue_for_review call already
    recorded, so "was this ever flagged for review" doesn't need to be
    re-derived from run-type-specific confidence/threshold fields that
    don't exist uniformly across extraction/theme/voting.

    - a recorded "approve" -> the raw value, status "approved".
    - a recorded "edit" -> the edited_value, status "edited".
    - a recorded "reject" -> still returned (never silently dropped),
      status "rejected", so a rejected fact is visibly rejected rather
      than absent.
    - queued for review but no decision recorded yet -> status
      "pending_review": a fact row is still materialized (so a caller
      can see a draft is pending), but its value is provisional.
    - never queued at all -> status "auto_approved", matching this
      system's existing implicit-trust-unless-flagged behavior.
    """
    decision = decisions.get(item_key)
    if decision is not None:
        outcome = decision.get("decision")
        reviewer = decision.get("reviewer")
        if outcome == "approve":
            return raw_value, "approved", reviewer
        if outcome == "edit":
            return decision.get("edited_value") or raw_value, "edited", reviewer
        return raw_value, "rejected", reviewer
    if item_key in queued_item_keys:
        return raw_value, "pending_review", None
    return raw_value, "auto_approved", None


def materialize_run(dsn: str, run_store: RunStore, run_id: str) -> int:
    """One DB transaction for this run: for each fact candidate, finds
    the current row (is_current=True) for (company_id, fact_key, as_of=""),
    if any; no-ops if the new value/status is identical to the current
    row (avoids version churn on an unchanged re-sync); otherwise closes
    the old row (valid_to/is_current/superseded_by_id) and inserts a new
    current one. Returns the number of facts changed (inserted new or
    superseded an existing one).

    `confidence` and `citations` are populated from the fact value where
    the run type has them (see fact_confidence/fact_citations).

    `as_of` is left as "" uniformly for now (a point-in-time fact) --
    none of the four verified run types expose a reliable fiscal-period
    field at this generic, run-type-agnostic layer; a per-period `as_of`
    is a natural refinement once that's needed.
    """
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        return 0
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    decisions = latest_decisions(run_store, run_id)
    queued_item_keys = {r["item_key"] for r in run_store.read_jsonl(run_store.review_queue_path(run_id)) if "item_key" in r}
    fact_type = _FACT_TYPE_BY_RUN_TYPE.get(manifest.run_type, manifest.run_type)

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from arp.storage.postgres_models import CompanyFactModel

    candidates = [
        (item_key, raw_value)
        for row in rows
        for item_key, raw_value in fact_candidates(manifest.run_type, row)
    ]
    if not candidates:
        return 0

    engine = get_engine(dsn)
    changed = 0
    with Session(engine) as session:
        # One query for every fact this run touches, rather than one
        # SELECT per candidate: a theme run over a few hundred companies
        # produces thousands of candidates, and this materialization runs
        # inline on RunStore.save_manifest (see run_store.py's projection
        # hook), so the round-trips were on the critical path of finishing
        # a run.
        current_by_key = {
            fact.fact_key: fact
            for fact in session.scalars(
                select(CompanyFactModel).where(
                    CompanyFactModel.fact_key.in_([item_key for item_key, _ in candidates]),
                    CompanyFactModel.as_of == "",
                    CompanyFactModel.is_current.is_(True),
                )
            ).all()
        }
        for item_key, raw_value in candidates:
            company_id = item_key.split(":", 1)[0]
            value, status, reviewer = resolve_fact(item_key, raw_value, decisions, queued_item_keys)
            current = current_by_key.get(item_key)
            if current is not None and current.value == value and current.status == status:
                continue

            now = now_iso()
            new_fact = CompanyFactModel(
                company_id=company_id,
                fact_key=item_key,
                as_of="",
                fact_type=fact_type,
                value=value,
                status=status,
                confidence=fact_confidence(value),
                citations=fact_citations(value),
                source_run_id=run_id,
                reviewer=reviewer,
                valid_from=now,
                valid_to=None,
                is_current=True,
            )
            session.add(new_fact)
            session.flush()  # assigns new_fact.id before it's referenced below
            if current is not None:
                current.valid_to = now
                current.is_current = False
                current.superseded_by_id = new_fact.id
            current_by_key[item_key] = new_fact
            changed += 1
        session.commit()
    return changed


def materialize_all(dsn: str, run_store: RunStore, *, since: str | None = None) -> int:
    """Backfills every run (optionally only those updated after `since`,
    an ISO timestamp) -- used by `arp db reindex company-facts`."""
    total = 0
    for manifest in run_store.list_runs():
        if since is not None and manifest.updated_at <= since:
            continue
        total += materialize_run(dsn, run_store, manifest.run_id)
    return total


def materialize_run_if_enabled(config: ProjectionConfig, run_store: RunStore, run_id: str) -> None:
    """Best-effort: called from RunStore.save_manifest on a terminal
    status. Any failure is logged and swallowed -- never blocks the real
    (file-based) write it's attached to."""
    if not config.company_facts_enabled:
        return
    try:
        materialize_run(config.postgres_dsn, run_store, run_id)
    except Exception:
        logger.warning("Postgres company-facts materialization failed for run_id=%s", run_id, exc_info=True)
