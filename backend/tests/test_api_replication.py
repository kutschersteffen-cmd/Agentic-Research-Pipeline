import csv
import random

import pytest
from fastapi import HTTPException

from arp.api.routers.replication import (
    ApproveSpecRequest,
    BacktestRequest,
    CreateSpecRequest,
    ReviseSpecRequest,
    approve_spec_draft,
    create_spec_draft,
    get_replication_run,
    get_spec_draft,
    revise_spec_draft,
    run_backtest_from_spec,
    trigger_regime_report,
    trigger_sanity_check,
    update_spec_draft,
)
from arp.replication.spec_extractor_agent import StrategySpecDraft
from arp.replication.spec_revision import _current_revision_draft
from arp.replication.spec_verifier_agent import SpecVerifierOutput
from arp.schemas.strategy_replication import RebalanceFrequency, ReportedPerformance, SignalType, StrategySpec, WeightingScheme
from arp.storage.run_store import RunStore

_PAPER_TEXT = (
    "We form decile portfolios based on the prior 6-month formation period return and hold them "
    "for 6 months. NYSE ordinary common shares, sample period 1965 to 1989."
)


def _draft() -> StrategySpecDraft:
    return StrategySpecDraft(
        paper_title="Test momentum paper",
        strategy_name="6-6 momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="NYSE ordinary common shares",
        formation_period_months=6,
        holding_period_months=6,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        num_portfolios=4,
        long_leg_portfolio=1,
        short_leg_portfolio=4,
        weighting=WeightingScheme.EQUAL,
        sample_period_start="1965-01-01",
        sample_period_end="1969-12-31",
        reported_performance=ReportedPerformance(),
        citations=[],
        confidence=0.9,
    )


async def _drafted_spec_run_id(run_store, fake_llm) -> str:
    llm = fake_llm({"StrategySpecDraft": [_draft()], "SpecVerifierOutput": [SpecVerifierOutput(agrees=True, confidence=0.85, notes="ok")]})
    result = await create_spec_draft(
        CreateSpecRequest(paper_citation="Test (2020)", paper_text=_PAPER_TEXT),
        run_store=run_store, llm=llm, verifier_llm=llm, settings=_settings(),
    )
    return result["spec_run_id"]


def _settings():
    from arp.config import get_settings

    return get_settings()


def _run_store(tmp_path) -> RunStore:
    return RunStore(tmp_path / "runs")


async def test_create_spec_draft_is_unapproved(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)

    state = get_spec_draft(spec_run_id, run_store=run_store)
    assert state["approved"] is False
    assert state["spec"]["strategy_name"] == "6-6 momentum"
    assert state["history"] == []


def test_get_spec_draft_404_for_unknown_id(tmp_path):
    run_store = _run_store(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        get_spec_draft("nope", run_store=run_store)
    assert exc_info.value.status_code == 404


async def test_approve_then_edit_unapproves(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)

    approved = approve_spec_draft(spec_run_id, ApproveSpecRequest(reviewer="alice"), run_store=run_store)
    assert approved["approved"] is True

    current_state = get_spec_draft(spec_run_id, run_store=run_store)
    edited_spec = StrategySpec.model_validate(current_state["spec"])
    edited_spec.holding_period_months = 12
    result = update_spec_draft(spec_run_id, edited_spec, run_store=run_store)

    assert result["approved"] is False  # editing after approval un-approves
    assert result["spec"]["holding_period_months"] == 12


async def test_revise_via_instruction_records_history_entry(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    current = StrategySpec.model_validate(get_spec_draft(spec_run_id, run_store=run_store)["spec"])

    revised_draft = _current_revision_draft(current).model_copy(update={"rebalance_frequency": RebalanceFrequency.QUARTERLY})
    llm = fake_llm({"StrategySpecRevisionDraft": [revised_draft]})
    result = await revise_spec_draft(spec_run_id, ReviseSpecRequest(instruction="use quarterly rebalancing"), run_store=run_store, llm=llm)

    assert result["spec"]["rebalance_frequency"] == "quarterly"
    assert result["approved"] is False
    history = get_spec_draft(spec_run_id, run_store=run_store)["history"]
    assert len(history) == 1
    assert history[0]["comment"] == "use quarterly rebalancing"


async def test_backtest_rejected_without_approval(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)

    with pytest.raises(HTTPException) as exc_info:
        run_backtest_from_spec(
            spec_run_id, BacktestRequest(tickers=["T0"], prices_ref="unused.csv"), run_store=run_store
        )
    assert exc_info.value.status_code == 403


def _write_price_csv(path, n_months=48, seed=11):
    rng = random.Random(seed)
    tickers = [f"T{i}" for i in range(15)]
    dates = []
    year, month = 1965, 1
    for _ in range(n_months):
        dates.append(f"{year}-{month:02d}-01")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    prices = {t: [100.0] for t in tickers}
    for t in tickers:
        for _ in range(n_months - 1):
            prices[t].append(prices[t][-1] * (1 + rng.gauss(0.01, 0.05)))
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", *tickers])
        for i, d in enumerate(dates):
            writer.writerow([d, *(round(prices[t][i], 4) for t in tickers)])
    return tickers


async def test_full_flow_backtest_then_results_then_regime_report(tmp_path, fake_llm):
    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    approve_spec_draft(spec_run_id, ApproveSpecRequest(), run_store=run_store)

    prices_path = tmp_path / "prices.csv"
    tickers = _write_price_csv(prices_path)

    result = run_backtest_from_spec(
        spec_run_id,
        BacktestRequest(tickers=tickers, prices_ref=str(prices_path), out_of_sample_start=None, out_of_sample_end=None),
        run_store=run_store,
    )
    run_id = result["run_id"]

    detail = get_replication_run(run_id, run_store=run_store)
    assert detail.spec.strategy_name == "6-6 momentum"
    assert detail.regime_report is None
    assert detail.sanity_check is None

    regime = trigger_regime_report(run_id, run_store=run_store)
    assert "buckets" in regime

    detail_after = get_replication_run(run_id, run_store=run_store)
    assert detail_after.regime_report is not None


def test_get_replication_run_404_for_unknown_run(tmp_path):
    run_store = _run_store(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        get_replication_run("nope", run_store=run_store)
    assert exc_info.value.status_code == 404


async def test_trigger_sanity_check_appends_and_is_returned_on_next_fetch(tmp_path, fake_llm):
    from arp.replication.sanity_check import SanityCheckAssessment

    run_store = _run_store(tmp_path)
    spec_run_id = await _drafted_spec_run_id(run_store, fake_llm)
    approve_spec_draft(spec_run_id, ApproveSpecRequest(), run_store=run_store)
    prices_path = tmp_path / "prices.csv"
    tickers = _write_price_csv(prices_path)
    result = run_backtest_from_spec(spec_run_id, BacktestRequest(tickers=tickers, prices_ref=str(prices_path)), run_store=run_store)
    run_id = result["run_id"]

    assessment = SanityCheckAssessment(plausible=True, findings=[], summary="Looks fine.")
    llm = fake_llm({"SanityCheckAssessment": [assessment]})
    response = await trigger_sanity_check(run_id, run_store=run_store, llm=llm)
    assert response["plausible"] is True

    detail = get_replication_run(run_id, run_store=run_store)
    assert detail.sanity_check is not None
    assert detail.sanity_check.summary == "Looks fine."
