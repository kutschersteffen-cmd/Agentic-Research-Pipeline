from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from arp.replication.backtest_engine import run_backtest
from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.schemas.strategy_replication import StrategySpec

_DEFAULT_CASES_PATH = Path(__file__).parent / "data" / "golden_set_cases.json"


class GoldenPanelData(BaseModel):
    """Plain-data (JSON-serializable) stand-in for PricePanel, since
    PricePanel is a dataclass rather than a pydantic model."""

    period_ends: list[str]
    returns: dict[str, list[float | None]]

    def to_price_panel(self) -> PricePanel:
        return PricePanel(period_ends=self.period_ends, returns=self.returns, source="golden_set")


class GoldenCharacteristicData(BaseModel):
    period_ends: list[str]
    values: dict[str, list[float | None]]

    def to_characteristic_panel(self) -> CharacteristicPanel:
        return CharacteristicPanel(period_ends=self.period_ends, values=self.values, source="golden_set")


class BacktestGoldenCase(BaseModel):
    """One fixed (spec, price panel, characteristics) input with a known-
    correct expected result -- the "behavioural equivalence test" this
    codebase's own precision-control conventions call for (see
    arp/golden_set/ for the LLM-extraction analog, which compares against
    a human-verified answer; here, since the backtest engine is fully
    deterministic, "known-correct" means captured from a reviewed run and
    guarded against silent drift, the same spirit as a snapshot test).

    Run this (`arp replicate golden-set`) before a signals.py/
    backtest_engine.py/rebalance.py/metrics.py change ships -- a silent
    behavior change here would not necessarily fail any single unit test's
    narrow assertion.
    """

    case_id: str
    description: str = Field(description="What this case is designed to catch, or which real construction it mirrors.")
    spec: StrategySpec
    panel: GoldenPanelData
    characteristics: dict[str, GoldenCharacteristicData] = Field(default_factory=dict)
    period_start: str
    period_end: str
    expected_long_short_annualized_return_pct: float | None = None
    expected_num_periods: int | None = None
    tolerance_pct: float = Field(default=0.01, description="Absolute tolerance for the annualized-return comparison, in percentage points.")


class GoldenCaseResult(BaseModel):
    case_id: str
    description: str
    passed: bool
    expected_annualized_return_pct: float | None
    actual_annualized_return_pct: float | None
    expected_num_periods: int | None
    actual_num_periods: int
    detail: str = ""


class GoldenSetReport(BaseModel):
    total: int
    passed: int
    failed_case_ids: list[str] = Field(default_factory=list)
    results: list[GoldenCaseResult] = Field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return self.passed == self.total


def run_golden_case(case: BacktestGoldenCase) -> GoldenCaseResult:
    panel = case.panel.to_price_panel()
    characteristics = {name: c.to_characteristic_panel() for name, c in case.characteristics.items()} or None
    result = run_backtest(
        case.spec,
        panel,
        period_label="golden",
        period_start=case.period_start,
        period_end=case.period_end,
        characteristics=characteristics,
    )
    actual_return = result.long_short.annualized_return_pct
    actual_periods = len(result.periods)

    problems: list[str] = []
    if case.expected_long_short_annualized_return_pct is not None:
        expected = case.expected_long_short_annualized_return_pct
        if actual_return is None or abs(actual_return - expected) > case.tolerance_pct:
            problems.append(f"annualized_return_pct expected {expected}, got {actual_return}")
    if case.expected_num_periods is not None and actual_periods != case.expected_num_periods:
        problems.append(f"num_periods expected {case.expected_num_periods}, got {actual_periods}")

    return GoldenCaseResult(
        case_id=case.case_id,
        description=case.description,
        passed=not problems,
        expected_annualized_return_pct=case.expected_long_short_annualized_return_pct,
        actual_annualized_return_pct=actual_return,
        expected_num_periods=case.expected_num_periods,
        actual_num_periods=actual_periods,
        detail="; ".join(problems),
    )


def run_golden_set(cases: list[BacktestGoldenCase]) -> GoldenSetReport:
    results = [run_golden_case(c) for c in cases]
    failed = [r.case_id for r in results if not r.passed]
    return GoldenSetReport(total=len(results), passed=len(results) - len(failed), failed_case_ids=failed, results=results)


def load_bundled_cases(path: Path | None = None) -> list[BacktestGoldenCase]:
    rows = json.loads((path or _DEFAULT_CASES_PATH).read_text())
    return [BacktestGoldenCase.model_validate(row) for row in rows]
