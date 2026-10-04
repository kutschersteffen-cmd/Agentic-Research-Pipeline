"""One release per document, publishing a run, and withdrawal that restores
the previous version (E73, E75)."""

from __future__ import annotations

from dataclasses import dataclass

from arp.api.auth import Principal
from arp.publish.candidates import Skip, run_candidates
from arp.publish.facts import (
    Fact,
    FactCandidate,
    FactEvent,
    FactKey,
    PublishStore,
    Release,
    VersionPlan,
    fact_key,
    plan_version,
    ts_now,
)
from arp.publish.gate import blob_key, lineage_error
from arp.schemas.common import new_id

SYSTEM = "system"


@dataclass
class PublishResult:
    releases: list[Release]
    reconfirmed: int
    blocked: list[dict]
    skipped: list[Skip]


class WithdrawalError(ValueError):
    pass


def _event(event_type: str, fact: Fact, now: str) -> FactEvent:
    return FactEvent(
        event_type=event_type, fact_id=fact.fact_id, issuer_key=fact.issuer_key, field_id=fact.field_id,
        period_end=fact.period_end, basis=fact.basis, release_id=fact.release_id, at=now,
    )


def split_by_gate(
    cands, blob_store, *, withdrawn_docs: set[str], content_store=None
) -> tuple[dict[tuple[str, str], list[FactCandidate]], list[dict]]:
    """Groups by (issuer_key, doc_id); a group is blocked whole by a withdrawn
    release or by the first lineage error among its citations."""
    blocked: list[dict] = []
    groups: dict[tuple[str, str], list[FactCandidate]] = {}
    for c in cands:
        if c.citation is None:
            blocked.append({"doc_id": None, "reason": "no_grounded_citation", "item_keys": [c.item_key]})
        else:
            groups.setdefault((c.issuer_key, c.citation.doc_id), []).append(c)
    passed = {}
    for (issuer_key, doc_id), group in groups.items():
        reason = "release_withdrawn" if doc_id in withdrawn_docs else next(
            filter(None, (lineage_error(c.citation, blob_store, content_store=content_store) for c in group)), None
        )
        if reason:
            blocked.append({"doc_id": doc_id, "reason": reason, "item_keys": [c.item_key for c in group]})
        else:
            passed[(issuer_key, doc_id)] = group
    return passed, blocked


def plan_release(
    group: list[FactCandidate], current: dict[FactKey, Fact], *, run_id, published_by, published_by_role,
    storage_uri: str, now: str,
) -> tuple[Release | None, list[VersionPlan], list[FactEvent]]:
    release_id = new_id("rel")
    plans = [plan_version(current.get(fact_key(c)), c, release_id=release_id, now=now) for c in group]
    inserts = [p.fact for p in plans if p.kind == "insert"]
    if not inserts:
        return None, plans, []
    first = group[0]
    release = Release(
        release_id=release_id, doc_id=first.citation.doc_id, content_key=first.citation.content_key,
        storage_uri=storage_uri, issuer_key=first.issuer_key, issuer_scheme=first.issuer_scheme, run_id=run_id,
        published_at=now, published_by=published_by, published_by_role=published_by_role,
    )
    return release, plans, [_event("restated" if f.restated else "published", f, now) for f in inserts]


def publish_run(
    store: PublishStore, run_store, run_id: str, *, principal: Principal | None, blob_store,
    content_store=None, now: str | None = None,
) -> PublishResult:
    now = now or ts_now()
    cands, skipped = run_candidates(run_store, run_id)
    seen: set[FactKey] = set()
    unique = []
    for c in cands:  # a repeated key would hit the version unique constraint on every retry
        if fact_key(c) in seen:
            skipped.append(Skip(c.item_key, "duplicate_key"))
        else:
            seen.add(fact_key(c))
            unique.append(c)
    cands = unique
    withdrawn_docs = {r.doc_id for r in store.list_releases(run_id=run_id) if r.withdrawn_at}
    groups, blocked = split_by_gate(cands, blob_store, withdrawn_docs=withdrawn_docs, content_store=content_store)
    result = PublishResult(releases=[], reconfirmed=0, blocked=blocked, skipped=list(skipped))
    for group in groups.values():
        current = store.current(fact_key(c) for c in group)
        release, plans, events = plan_release(
            group, current, run_id=run_id,
            published_by=principal.user_id if principal else SYSTEM,
            published_by_role=principal.role if principal else SYSTEM,
            storage_uri=blob_store.uri(blob_key(group[0].citation, content_store)), now=now,
        )
        result.skipped += [Skip(c.item_key, "older_than_published") for c, p in zip(group, plans, strict=True) if p.kind == "older"]
        result.reconfirmed += sum(p.kind == "reconfirm" for p in plans)
        store.save_release(release, [p for p in plans if p.kind != "older"], events)
        if release is not None:
            result.releases.append(release)
    return result


def plan_withdrawal(
    release: Release, versions: list[Fact], previous: dict[str, Fact], *, reason: str, withdrawn_by: str, now: str
) -> tuple[Release, list[Fact], list[Fact], list[FactEvent]]:
    if not reason.strip():
        raise WithdrawalError("a withdrawal needs a reason")
    if release.withdrawn_at:
        raise WithdrawalError("release already withdrawn")
    closes: list[Fact] = []
    restores: list[Fact] = []
    events: list[FactEvent] = []
    for v in versions:
        if v.valid_to is not None:
            continue  # already superseded: left as it is
        closed = v.model_copy(update={"valid_to": now})
        events.append(_event("withdrawn", closed, now))
        prev = previous.get(v.fact_id)
        if prev is not None:
            copy = prev.model_copy(update={
                "fact_id": new_id("fact"), "version": closed.version + 1, "valid_from": now, "valid_to": None,
                "superseded_by": None, "reconfirmed_at": None, "restored_from": prev.fact_id,
            })
            closed = closed.model_copy(update={"superseded_by": copy.fact_id})
            restores.append(copy)
            events.append(_event("restored", copy, now))
        closes.append(closed)
    updated = release.model_copy(update={"withdrawn_at": now, "withdrawal_reason": reason, "withdrawn_by": withdrawn_by})
    return updated, closes, restores, events


def withdraw(store, release_id: str, *, reason: str, principal: Principal, now: str | None = None) -> list[Fact]:
    release = store.get_release(release_id)
    if release is None:
        raise LookupError(f"unknown release {release_id}")
    releases: dict[str, Release | None] = {release_id: release}

    def withdrawn(f: Fact) -> bool:
        # the release being withdrawn counts too: its value must never come back
        if f.release_id not in releases:
            releases[f.release_id] = store.get_release(f.release_id)
        r = releases[f.release_id]
        return f.release_id == release_id or bool(r and r.withdrawn_at)

    versions = store.release_facts(release_id)
    previous: dict[str, Fact] = {}
    for f in versions:
        if f.valid_to is not None:
            continue
        prev = store.previous_version(f.restored_from or f.fact_id)
        while prev is not None and withdrawn(prev):
            prev = store.previous_version(prev.fact_id)
        if prev is not None:
            previous[f.fact_id] = prev
    now = now or ts_now()
    updated, closes, restores, events = plan_withdrawal(
        release, versions, previous, reason=reason, withdrawn_by=principal.user_id, now=now
    )
    store.save_withdrawal(updated, closes, restores, events)
    return restores
