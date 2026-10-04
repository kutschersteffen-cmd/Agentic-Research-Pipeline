"""Decided values from earlier extraction runs (E37): the prior-period checks compare against these."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from arp.orchestration.review_queue import effective_decisions
from arp.schemas.review import field_item_key, held_item_key, period_key
from arp.storage.run_store import RunStore


@dataclass(frozen=True)
class PriorValue:
    value: str | float | bool | None
    canonical_value: float | None
    run_id: str
    decided_by: Literal["human", "system"]


class RunHistory:
    def __init__(self) -> None:
        self._decided: dict[str, PriorValue] = {}
        self._rejected: dict[str, PriorValue] = {}  # item_key -> value a human rejected, until a human approves/edits
        self._periods: dict[str, set[str]] = {}
        self._company_rows: dict[str, list[dict]] = {}
        self._company_run: dict[str, str] = {}
        self._company_rejected: dict[str, set[str]] = {}  # company -> field ids a human rejected in its last run
        self._released: set[tuple[str, str]] = set()  # (company_id, content_key) of held documents a human approved

    @classmethod
    def load(cls, run_store: RunStore, *, exclude_run_id: str | None = None) -> RunHistory:
        # ponytail: full scan of past extraction runs per run; index by item_key if run count makes this slow
        h = cls()
        runs = [
            m for m in run_store.list_runs("extraction")
            if m.run_id != exclude_run_id and not m.params.get("trial")
        ]
        for m in sorted(runs, key=lambda m: m.created_at):  # later runs overwrite earlier ones
            h._add_run(run_store, m.run_id)
        return h

    def _add_run(self, run_store: RunStore, run_id: str) -> None:
        # Same decision view as the facts projection: an edit counts only once co-signed.
        decisions = effective_decisions(run_store, run_id, cosign_required={"edit"})
        queued = {r["item_key"] for r in run_store.read_jsonl(run_store.review_queue_path(run_id)) if "item_key" in r}
        rejected = {k for k, d in decisions.items() if d.get("decision") == "reject"}
        for row in run_store.read_jsonl(run_store.results_path(run_id)):
            issuer = row.get("issuer_key", "")
            self._company_rows[row.get("company_id", "")] = row.get("fields", [])
            self._company_run[row.get("company_id", "")] = run_id
            self._company_rejected[row.get("company_id", "")] = {
                f["field_id"] for f in row.get("fields", []) if field_item_key(issuer, f["field_id"], period_key(f)) in rejected
            }
            company = row.get("company_id", "")
            for d in row.get("held_documents", []):
                ck = d.get("content_key")
                if not ck:
                    continue  # legacy held dict: nothing to key a release on
                if (decisions.get(held_item_key(company, d["doc_id"])) or {}).get("decision") == "approve":
                    self._released.add((company, ck))
                else:  # a later reject or new round withdraws an earlier release
                    self._released.discard((company, ck))
            for f in row.get("fields", []):
                key = field_item_key(issuer, f["field_id"], period_key(f))
                kind = (decisions.get(key) or {}).get("decision")
                if kind == "reject":
                    self._rejected[key] = PriorValue(f.get("value"), f.get("canonical_value"), run_id, "human")
                elif kind in ("approve", "edit", "correct"):
                    self._rejected.pop(key, None)
                prior = _decided_value(f, decisions.get(key), key in queued, run_id)
                if prior is not None:
                    self._decided[key] = prior
                    self._periods.setdefault(issuer, set()).add(period_key(f))

    def released_documents(self) -> set[tuple[str, str]]:
        return set(self._released)

    def last_decided(self, item_key: str) -> PriorValue | None:
        return self._decided.get(item_key)

    def last_rejected_value(self, item_key: str) -> PriorValue | None:
        return self._rejected.get(item_key)

    def last_rows(self, company_id: str, field_id: str) -> list[dict]:
        return [f for f in self._company_rows.get(company_id, []) if f["field_id"] == field_id]

    def last_rejected(self, company_id: str, field_id: str) -> bool:
        """A human rejected one of this field's rows in the run `last_rows` comes from."""
        return field_id in self._company_rejected.get(company_id, set())

    def last_run_id(self, company_id: str) -> str | None:
        return self._company_run.get(company_id)

    def recorded_periods(self, issuer_key: str) -> set[str]:
        return set(self._periods.get(issuer_key, ()))


def _decided_value(f: dict, decision: dict | None, queued: bool, run_id: str) -> PriorValue | None:
    if decision is not None:
        kind = decision.get("decision")
        if kind == "approve":
            return PriorValue(f.get("value"), f.get("canonical_value"), run_id, "human")
        if kind in ("edit", "correct"):
            edit = decision.get("edited_value") or {}
            return PriorValue(edit.get("value", f.get("value")), edit.get("canonical_value"), run_id, "human")
        return None  # reject
    route = f.get("route")
    if route == "auto_accept" or (route is None and not queued):
        return PriorValue(f.get("value"), f.get("canonical_value"), run_id, "system")
    return None
