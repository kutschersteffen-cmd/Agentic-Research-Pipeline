from __future__ import annotations

from pydantic import BaseModel

from arp.replication.regime_analysis import RegimeStratifiedReport
from arp.replication.sanity_check import SanityCheckAssessment
from arp.schemas.strategy_replication import BacktestResult, ReplicationComparisonReport, StrategySpec
from arp.storage.run_store import RunStore


class ReplicationRunDetail(BaseModel):
    """Everything a completed `strategy_replication` run has produced so
    far, bundled into one response -- a replication run is one strategy's
    results (a spec + a couple of BacktestResults + a comparison report),
    small enough to return whole rather than paginating like the
    many-rows-per-company run types (theme/extraction) need to. Composition
    only: every field is an existing model, assembled by dispatching each
    `results.jsonl` row by its own `type` tag -- the same pattern
    `arp/cli/replication.py`'s `sanity-check`/`regime-report` commands
    already use to read a run's rows back.
    """

    run_id: str
    spec: StrategySpec
    in_sample: BacktestResult
    out_of_sample: BacktestResult | None = None
    comparison: ReplicationComparisonReport
    sanity_check: SanityCheckAssessment | None = None
    regime_report: RegimeStratifiedReport | None = None


def load_run_detail(run_store: RunStore, run_id: str) -> ReplicationRunDetail | None:
    """None if the run has no spec/in_sample/comparison row yet (doesn't
    exist, or hasn't finished the backtest step) -- sanity_check/
    regime_report are optional and simply omitted if not yet run."""
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    by_type: dict[str, dict] = {}
    for row in rows:
        by_type[row["type"]] = row  # last row of a given type wins (sanity_check/regime_report can be re-run)

    if "spec" not in by_type or "in_sample" not in by_type or "comparison" not in by_type:
        return None

    def _strip_type(row: dict) -> dict:
        return {k: v for k, v in row.items() if k != "type"}

    return ReplicationRunDetail(
        run_id=run_id,
        spec=StrategySpec.model_validate(_strip_type(by_type["spec"])),
        in_sample=BacktestResult.model_validate(_strip_type(by_type["in_sample"])),
        out_of_sample=BacktestResult.model_validate(_strip_type(by_type["out_of_sample"])) if "out_of_sample" in by_type else None,
        comparison=ReplicationComparisonReport.model_validate(_strip_type(by_type["comparison"])),
        sanity_check=SanityCheckAssessment.model_validate(_strip_type(by_type["sanity_check"])) if "sanity_check" in by_type else None,
        regime_report=RegimeStratifiedReport.model_validate(_strip_type(by_type["regime_report"])) if "regime_report" in by_type else None,
    )
