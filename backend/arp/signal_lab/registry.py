from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel

from arp.schemas.common import JobStatus, RunManifest, now_iso
from arp.signal_lab.cutoffs import CutoffTable
from arp.signal_lab.evidence import EvidenceReport
from arp.storage.run_store import RunStore

SIGNAL_REGISTRY_RUN_ID = "signal_registry"
MIN_POST_CUTOFF_IC_MONTHS = 12


class Recipe(BaseModel):
    category: Literal["sentiment_narrative", "earnings_call_tone", "fundamental", "price_momentum", "analyst_revisions"]
    method: str
    text_source: str | None
    params: dict
    universe: str
    window_start: str
    window_end: str
    forward_months: int = 1
    cost_bps: float = 10.0


class ExperimentRecord(BaseModel):
    experiment_id: str
    recipe: Recipe
    data_version: str
    model: str | None
    cutoff: str | None = None
    evidence: EvidenceReport
    created_at: str
    decision: Literal["none", "graduate", "shelve"] = "none"
    decided_by: str | None = None
    decided_at: str | None = None
    notes: dict = {}


def experiment_id_for(recipe: Recipe, *, data_version: str, model: str | None, cutoff: str | None) -> str:
    # The cutoff decides which months count as evidence, so a corrected cutoff must be a new experiment.
    canonical = json.dumps(
        [recipe.model_dump(mode="json"), data_version, model, cutoff], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class Registry:
    def __init__(self, store: RunStore) -> None:
        self.store = store

    def _rows(self) -> list[dict]:
        return self.store.read_results(SIGNAL_REGISTRY_RUN_ID)

    def register(
        self,
        recipe: Recipe,
        evidence: EvidenceReport,
        *,
        data_version: str,
        model: str | None,
        cutoff: str | None,
        notes: dict | None = None,
    ) -> ExperimentRecord:
        experiment_id = experiment_id_for(recipe, data_version=data_version, model=model, cutoff=cutoff)
        with self.store.lock(SIGNAL_REGISTRY_RUN_ID):
            if self.store.load_manifest(SIGNAL_REGISTRY_RUN_ID) is None:
                self.store.save_manifest(
                    RunManifest(run_id=SIGNAL_REGISTRY_RUN_ID, run_type="signal_registry", status=JobStatus.RUNNING)
                )
            record = ExperimentRecord(
                experiment_id=experiment_id,
                recipe=recipe,
                data_version=data_version,
                model=model,
                cutoff=cutoff,
                evidence=evidence,
                created_at=now_iso(),
                notes=notes or {},
            )
            # A repeat `_key` is a no-op, so re-registering neither duplicates the row nor adds a trial.
            self.store.append_result(
                SIGNAL_REGISTRY_RUN_ID,
                {"type": "experiment", "_key": f"experiment:{experiment_id}", **record.model_dump(mode="json")},
            )
            return next(r for r in self._list() if r.experiment_id == experiment_id)

    def _list(self) -> list[ExperimentRecord]:
        records: dict[str, ExperimentRecord] = {}
        for row in self._rows():
            if row["type"] == "experiment":
                records[row["experiment_id"]] = ExperimentRecord.model_validate(
                    {k: v for k, v in row.items() if k not in ("type", "_key")}
                )
            elif row["type"] == "decision":
                records[row["experiment_id"]] = records[row["experiment_id"]].model_copy(
                    update={
                        "decision": row["decision"],
                        "decided_by": row["decided_by"],
                        "decided_at": row["decided_at"],
                    }
                )
        return list(records.values())

    def list_experiments(self) -> list[ExperimentRecord]:
        return self._list()

    def has(self, experiment_id: str) -> bool:
        return any(r.experiment_id == experiment_id for r in self._list())

    def trial_count(self, recipe: Recipe) -> int:
        scope = (recipe.category, recipe.universe, recipe.window_start, recipe.window_end)
        return sum(
            (r.recipe.category, r.recipe.universe, r.recipe.window_start, r.recipe.window_end) == scope
            for r in self._list()
        )

    def decide(
        self,
        experiment_id: str,
        decision: Literal["graduate", "shelve"],
        *,
        approver: str,
        cutoffs: CutoffTable | None = None,
    ) -> ExperimentRecord:
        # Literal is only a type hint; the log is append-only, so a bad row could never be removed.
        if decision not in ("graduate", "shelve"):
            raise ValueError(f"decision must be 'graduate' or 'shelve', got {decision!r}")
        if not approver.strip():
            raise ValueError("an approver is required")
        with self.store.lock(SIGNAL_REGISTRY_RUN_ID):
            record = next((r for r in self._list() if r.experiment_id == experiment_id), None)
            if record is None:
                raise ValueError(f"unknown experiment {experiment_id!r}")
            if decision == "graduate":
                if cutoffs is None:
                    raise ValueError(f"cannot graduate {experiment_id}: a cutoff table is required to graduate")
                # Evidence split at a since-corrected cutoff may count leaked months as post-cutoff.
                if record.model is not None and cutoffs.cutoff_for(record.model) != record.cutoff:
                    raise ValueError(
                        f"cannot graduate {experiment_id}: the cutoff for model {record.model!r} changed since "
                        f"the experiment was evaluated ({record.cutoff} -> {cutoffs.cutoff_for(record.model)}); "
                        "re-run `arp signals evaluate`"
                    )
            if decision == "graduate" and not any(
                w.window == "post_cutoff" and w.ic.n >= MIN_POST_CUTOFF_IC_MONTHS for w in record.evidence.windows
            ):
                raise ValueError(
                    f"cannot graduate {experiment_id}: needs post-cutoff evidence with at least "
                    f"{MIN_POST_CUTOFF_IC_MONTHS} IC months"
                )
            n = sum(1 for r in self._rows() if r["type"] == "decision" and r["experiment_id"] == experiment_id)
            decided_at = now_iso()
            self.store.append_result(
                SIGNAL_REGISTRY_RUN_ID,
                {
                    "type": "decision",
                    "_key": f"decision:{experiment_id}:{n}",
                    "experiment_id": experiment_id,
                    "decision": decision,
                    "decided_by": approver,
                    "decided_at": decided_at,
                },
            )
            return record.model_copy(update={"decision": decision, "decided_by": approver, "decided_at": decided_at})
