"""Data Hub's issues list: every open data problem the tool already knows about, in one place. Read-only: it gathers
what the feeds, the security master and the extraction checks have recorded; nothing is re-run or guessed.

- feed: a feed behind schedule or whose last load failed (from the feed overview)
- security_master: a held security the master does not map to exactly one issuer
- check: a failing check (warn or block) on the latest extracted value of a field, not yet decided by a reviewer
"""

from __future__ import annotations

from datetime import date

from arp.holdings import security_master
from arp.orchestration.review_queue import effective_decisions
from arp.portfolio import feeds
from arp.review.items import cosign_rule
from arp.schemas.review import field_item_key, period_key
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore

FEED_LABEL = {"security_master": "Security master", "holdings": "Portfolio holdings", "index": "Index constituents",
              "esg": "ESG data", "news": "News"}


def _feed_issues(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        name = f"{FEED_LABEL[r['feed']]} · {r['source_id']}"
        failed = r["last_load"] is not None and r["last_load"]["status"] == "failed"
        if failed:
            out.append({"source": "feed", "severity": "block", "title": f"{name}: last load failed",
                        "detail": r["last_load"]["detail"], "subject": r["source_id"], "ref": f"feed:{r['feed']}:{r['source_id']}"})
        if r["stale"]:
            out.append({"source": "feed", "severity": "warn", "title": f"{name}: behind",
                        "detail": r["detail"], "subject": r["source_id"], "ref": f"feed:{r['feed']}:{r['source_id']}"})
    return out


def _unmatched_issues(store, idmap: IdentifierMapStore) -> list[dict]:
    return [{
        "source": "security_master", "severity": "block", "title": f"{r['isin'] or r['security_id']}: {r['reason']}",
        "detail": f"held by {r['holder_id']} ({r['kind']}) as of {r['as_of']}" + (f"; candidates {', '.join(r['candidates'])}" if r["candidates"] else ""),
        "subject": r["isin"] or r["security_id"], "ref": f"security:{r['kind']}:{r['holder_id']}:{r['security_id']}",
    } for r in security_master.unmatched(store, idmap)]


def _check_issues(run_store: RunStore) -> list[dict]:
    """Newest run first, so each (issuer, field, period) is judged on its latest extracted value only."""
    runs = sorted((m for m in run_store.list_runs("extraction") if not m.params.get("trial")), key=lambda m: m.created_at, reverse=True)
    seen: set[str] = set()
    out = []
    for m in runs:
        decisions = effective_decisions(run_store, m.run_id, cosign_required=cosign_rule("extraction"))
        for row in run_store.read_jsonl(run_store.results_path(m.run_id)):
            for f in row.get("fields", []):
                key = field_item_key(row.get("issuer_key", ""), f["field_id"], period_key(f))
                if key in seen:
                    continue
                seen.add(key)
                if decisions.get(key):  # a reviewer decided this value: the finding is handled
                    continue
                for c in f.get("checks", []):
                    if c.get("outcome") == "fail" and c.get("severity") in ("warn", "block"):
                        out.append({
                            "source": "check", "severity": c["severity"],
                            "title": f"{row.get('name') or row.get('company_id')} · {f['field_id']}: {c['check_id']}",
                            "detail": c.get("detail", ""), "subject": row.get("name") or row.get("company_id") or "",
                            "ref": f"check:{m.run_id}:{key}:{c['check_id']}", "run_id": m.run_id,
                        })
    return out


SEVERITY_ORDER = {"block": 0, "warn": 1, "info": 2}
# Within a severity the foundations come first: a check finding may only be a symptom of a stale feed or unmatched security.
SOURCE_ORDER = {"feed": 0, "security_master": 1, "check": 2}


def open_issues(store, idmap: IdentifierMapStore, run_store: RunStore, today: date) -> list[dict]:
    issues = _feed_issues(feeds.overview(store, idmap, today)) + _unmatched_issues(store, idmap) + _check_issues(run_store)
    return sorted(issues, key=lambda i: (SEVERITY_ORDER[i["severity"]], SOURCE_ORDER[i["source"]], i["title"]))
