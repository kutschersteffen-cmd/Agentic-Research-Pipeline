from __future__ import annotations

import json
from pathlib import Path

import typer

from arp.config import get_settings

index_app = typer.Typer(
    help="Equity index construction: compose screens/selection/weighting/constraints into a saved, versioned calibration and run reviews from it."
)


def _index_store():
    from arp.storage.index_store import IndexStore

    return IndexStore(get_settings().indices_dir)


def _index_universe(universe_file: Path | None):
    """The built-in demo universe unless a JSON file of IndexCandidate
    records is supplied, so every command below runs without a data feed."""
    from arp.index.mock_data import demo_universe
    from arp.schemas.index import IndexCandidate

    if universe_file is None:
        return demo_universe()
    rows = json.loads(Path(universe_file).read_text())
    return [IndexCandidate(**row) for row in rows]


def _index_risk_model(spec, universe, returns_file: Path | None):
    """Builds a risk model when the methodology needs one, from a supplied
    returns panel or the built-in demo panel."""
    from arp.index.mock_data import demo_risk_model
    from arp.index.risk import build_risk_model

    settings = spec.constraints.solver
    if settings.method not in ("min_tracking_error", "max_score") and settings.tracking_error_budget is None:
        return None
    if returns_file is not None:
        panel = json.loads(Path(returns_file).read_text())
        return build_risk_model(settings.risk_model, universe, panel)
    typer.echo("No --returns-file supplied; estimating the risk model from the built-in demo panel (illustrative only).")
    return demo_risk_model(universe, settings.risk_model)


def _load_spec(preset: str | None, spec_file: Path | None, solver_method: str | None = None):
    from arp.index.presets import build_preset
    from arp.schemas.index import ConstructionSpec

    if spec_file is not None:
        spec = ConstructionSpec.model_validate_json(Path(spec_file).read_text())
    elif preset is not None:
        spec = build_preset(preset)
    else:
        raise typer.BadParameter("Supply --preset or --spec-file.")
    if solver_method:
        from arp.index.optimize import available as optimizer_available

        if solver_method == "least_squares" and not optimizer_available():
            typer.echo('Note: cvxpy is not installed, so the run will fall back to the waterfall. pip install -e ".[optimize]"')
        spec.constraints.solver.method = solver_method  # type: ignore[assignment]
    return spec


@index_app.command("catalogue")
def index_catalogue() -> None:
    """Every rule type, its parameters and defaults, plus presets and screen bundles."""
    from arp.index.presets import rule_catalogue

    typer.echo(json.dumps(rule_catalogue(), indent=2))


@index_app.command("presets")
def index_presets() -> None:
    """List the named methodology presets."""
    from arp.index.presets import PRESETS

    for name, preset in sorted(PRESETS.items()):
        typer.echo(f"{name:24s} {preset['label']}")
        typer.echo(f"{'':24s} {preset['description']}")


@index_app.command("preview")
def index_preview(
    review_date: str = typer.Option(..., help="ISO date of the review."),
    preset: str = typer.Option(None, help="Named preset, e.g. eu_pab."),
    spec_file: Path = typer.Option(None, help="ConstructionSpec JSON, as saved from the UI."),
    universe_file: Path = typer.Option(None, help="IndexCandidate JSON list. Omit for the demo universe."),
    solver_method: str = typer.Option(None, help="Override the constraint method: waterfall | least_squares | min_tracking_error | max_score."),
    tracking_error_budget: float = typer.Option(None, help="Annualised ex-ante TE ceiling, e.g. 0.015. Needs a risk model."),
    score_field: str = typer.Option(None, help="method='max_score' only: the field to maximise."),
    max_constituents: int = typer.Option(None, help="Cardinality ceiling. Needs a mixed-integer solve."),
    min_constituents: int = typer.Option(None, help="Cardinality floor. Needs a mixed-integer solve."),
    enforce_min_weight: bool = typer.Option(False, help="Treat min_weight as 'held at the floor or not at all' instead of pruning."),
    returns_file: Path = typer.Option(None, help="JSON {period: {company_id: return}} for the risk model. Omit for the demo panel."),
    show: str = typer.Option("summary", help="summary | trace | constituents | json"),
) -> None:
    """Runs a review without persisting anything."""
    from arp.index.pipeline import run_review

    spec = _load_spec(preset, spec_file, solver_method)
    if tracking_error_budget:
        spec.constraints.solver.tracking_error_budget = tracking_error_budget
    if score_field:
        spec.constraints.solver.score_field = score_field
    if max_constituents:
        spec.constraints.max_constituents = max_constituents
    if min_constituents:
        spec.constraints.min_constituents = min_constituents
    if enforce_min_weight:
        spec.constraints.solver.enforce_semicontinuous = True
        if not spec.constraints.min_weight:
            typer.echo("Note: --enforce-min-weight has nothing to enforce -- this methodology sets no min_weight.")
    universe = _index_universe(universe_file)
    result = run_review(
        spec, universe, index_id="preview", review_date=review_date, risk_model=_index_risk_model(spec, universe, returns_file)
    )
    _echo_review(result, show)


@index_app.command("run")
def index_run(
    index_id: str = typer.Option(..., help="The index this review belongs to."),
    review_date: str = typer.Option(..., help="ISO date of the review."),
    calibration_id: str = typer.Option(None, help="Run the calibration version in force on the review date."),
    preset: str = typer.Option(None),
    spec_file: Path = typer.Option(None),
    universe_file: Path = typer.Option(None),
    solver_method: str = typer.Option(None, help="Override the constraint method."),
    returns_file: Path = typer.Option(None, help="JSON {period: {company_id: return}} for the risk model."),
    show: str = typer.Option("summary"),
) -> None:
    """Runs a review and persists it, chaining state from the previous one."""
    from arp.index.pipeline import run_review

    store = _index_store()
    calibration_version = None
    if calibration_id:
        calibration = store.resolve_for_date(calibration_id, review_date)
        if calibration is None:
            raise typer.BadParameter(f"No version of {calibration_id} is in force on {review_date}.")
        spec, calibration_version = calibration.spec, calibration.version
        typer.echo(f"Using calibration {calibration.name} v{calibration.version} (effective {calibration.effective_from}).")
        if solver_method:
            spec.constraints.solver.method = solver_method  # type: ignore[assignment]
            typer.echo(f"Overriding the constraint method to '{solver_method}' for this run only.")
    else:
        spec = _load_spec(preset, spec_file, solver_method)

    prior = store.latest_state_before(index_id, review_date)
    if prior is not None:
        typer.echo(f"Chaining from the {prior.review_date} review (carry {prior.shortfall_carry:.4%}).")
    universe = _index_universe(universe_file)
    result = run_review(
        spec,
        universe,
        index_id=index_id,
        review_date=review_date,
        prior_state=prior,
        calibration_id=calibration_id,
        calibration_version=calibration_version,
        risk_model=_index_risk_model(spec, universe, returns_file),
    )
    store.save_review(result)
    _echo_review(result, show)


@index_app.command("calibration-save")
def index_calibration_save(
    name: str = typer.Option(..., help="Display name."),
    effective_from: str = typer.Option(..., help="ISO date: the first review date this version governs."),
    preset: str = typer.Option(None),
    spec_file: Path = typer.Option(None),
    solver_method: str = typer.Option(None, help="waterfall | least_squares."),
    calibration_id: str = typer.Option(None, help="Supply to add a new version to an existing calibration."),
    notes: str = typer.Option(""),
    approved_by: str = typer.Option("", help="Comma-separated committee minute references."),
) -> None:
    """Saves a construction spec as a new calibration, or a new version of one."""
    store = _index_store()
    spec = _load_spec(preset, spec_file, solver_method)
    approvals = [a.strip() for a in approved_by.split(",") if a.strip()]
    if calibration_id:
        calibration = store.new_calibration_version(
            calibration_id, spec, effective_from=effective_from, notes=notes, approved_by=approvals
        )
    else:
        calibration = store.create_calibration(name, spec, effective_from=effective_from, notes=notes, approved_by=approvals)
    typer.echo(f"{calibration.calibration_id} v{calibration.version}  effective {calibration.effective_from}  hash {calibration.config_hash[:12]}")


@index_app.command("calibration-list")
def index_calibration_list() -> None:
    """Lists saved calibrations at their latest version."""
    for calibration in _index_store().list_calibrations():
        typer.echo(
            f"{calibration.calibration_id}  v{calibration.version}  {calibration.name}  "
            f"effective {calibration.effective_from}  hash {calibration.config_hash[:12]}"
        )


@index_app.command("calibration-show")
def index_calibration_show(
    calibration_id: str = typer.Argument(...),
    version: int = typer.Option(None, help="Omit for the latest version."),
    as_of: str = typer.Option(None, help="Resolve the version in force on this review date instead."),
) -> None:
    """Prints a calibration, or its whole version history."""
    store = _index_store()
    calibration = store.resolve_for_date(calibration_id, as_of) if as_of else store.get_calibration(calibration_id, version)
    if calibration is None:
        raise typer.BadParameter(f"No calibration {calibration_id}" + (f" in force on {as_of}" if as_of else ""))
    typer.echo(calibration.model_dump_json(indent=2))


@index_app.command("calibration-history")
def index_calibration_history(calibration_id: str = typer.Argument(...)) -> None:
    """Every version of a calibration, with the window each one governs."""
    for calibration in _index_store().list_calibration_versions(calibration_id):
        window = f"{calibration.effective_from} -> {calibration.effective_to or 'open'}"
        typer.echo(f"v{calibration.version:<3d} {window:<26s} hash {calibration.config_hash[:12]}  {calibration.notes}")


def _echo_review(result, show: str) -> None:
    if show == "json":
        typer.echo(result.model_dump_json(indent=2))
        return
    d = result.diagnostics
    typer.echo(f"\n{result.index_id} @ {result.review_date}   config {result.config_hash[:12]}")
    typer.echo(f"  universe {d.universe_size} -> eligible {d.eligible_size} -> selected {d.selected_size} -> final {d.final_size}")
    constraint_stage = next((s for s in result.trace if s.stage == "constraints"), None)
    if constraint_stage is not None:
        typer.echo(f"  constraints: {constraint_stage.label}")
    if d.integer_constraints:
        typer.echo(f"  mixed-integer solve: {d.final_size} constituents held")
    if d.tracking_error is not None:
        typer.echo(f"  ex-ante tracking error {d.tracking_error:.4%} (annualised, vs the eligible universe)")
    typer.echo(f"  max weight {d.max_weight:.4%}   effective N {d.effective_n:.1f}" + (f"   turnover {d.one_way_turnover:.2%}" if d.one_way_turnover is not None else ""))
    for field, value in sorted(d.weighted_metrics.items()):
        universe_value = d.universe_weighted_metrics.get(field)
        if universe_value is None or abs(universe_value) < 1e-9:
            continue
        # Signed as "the index value relative to the universe": a 50%
        # intensity cut reads -50%, which is the direction people expect.
        typer.echo(f"  {field}: index {value:.4f} vs universe {universe_value:.4f}  ({value / universe_value - 1:+.2%})")
    if result.state.required_metric_value is not None:
        typer.echo(
            f"  trajectory: target {result.state.required_metric_value:.4f}, achieved {result.state.achieved_metric_value:.4f}, "
            f"binding {result.state.binding_constraint}, carry {result.state.shortfall_carry:.4%}"
        )
    for exception in result.exceptions:
        typer.echo(f"  ! {exception}")
    if show == "trace":
        typer.echo("")
        for stage in result.trace:
            typer.echo(f"  {stage.stage:<12s} {stage.label:<46s} {stage.candidates_in:>4d} -> {stage.candidates_out:<4d} {stage.detail}")
    if show == "constituents":
        typer.echo("")
        for constituent in sorted(result.constituents, key=lambda c: -c.weight):
            typer.echo(f"  {constituent.company_id:<10s} {constituent.name:<28s} {constituent.weight:>8.4%}  shares {constituent.index_shares:>14.4f}")


