from __future__ import annotations

from pathlib import Path

import typer

from arp.cli._shared import _portfolio_store, _run_store
from arp.config import get_settings
from arp.decision import sources as decision_sources
from arp.decision.compare import compare_results
from arp.decision.dataset import Dataset, dataset_from_file
from arp.decision.diffing import describe_changes
from arp.decision.mechanism import apply_mechanism, derive_mechanism
from arp.decision.profiling import profile_dataset
from arp.decision.roles import propose_roles
from arp.decision.sensitivity import tipping_points
from arp.schemas.decision import MechanismConfig
from arp.storage.decision_store import DecisionStore

decision_app = typer.Typer(
    help="Decision Mechanism: derive, tune and apply a scoring/tiering framework to any per-entity table. No LLM calls."
)


def _decision_store() -> DecisionStore:
    return DecisionStore(get_settings().frameworks_dir)


def _dataset(
    table: Path | None,
    dataset_id: str | None,
    source: str | None,
    run_id: str | None,
    as_of: str | None,
) -> Dataset:
    """One table, from wherever the caller has it: a file on disk, a stored
    dataset, or one of this system's own run results."""
    store = _decision_store()
    if table is not None:
        return store.save_dataset(dataset_from_file(table))
    if dataset_id:
        dataset = store.get_dataset(dataset_id)
        if dataset is None:
            typer.echo(f"Unknown dataset: {dataset_id}", err=True)
            raise typer.Exit(1)
        return dataset
    if source:
        run_store = _run_store()
        try:
            if source == "transition_plan_run":
                dataset = decision_sources.from_transition_plan_run(run_store, _require(run_id))
            elif source == "extraction_run":
                dataset = decision_sources.from_extraction_run(run_store, _require(run_id))
            elif source == "theme_run":
                dataset = decision_sources.from_theme_run(run_store, _require(run_id))
            elif source == "portfolio_snapshot":
                dataset = decision_sources.from_portfolio_snapshot(_portfolio_store(), as_of)
            else:
                typer.echo(f"Unknown source: {source}", err=True)
                raise typer.Exit(1)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        return store.save_dataset(dataset)
    typer.echo("Provide --table, --dataset or --source.", err=True)
    raise typer.Exit(1)


def _require(run_id: str | None) -> str:
    if not run_id:
        typer.echo("--run-id is required for this source.", err=True)
        raise typer.Exit(1)
    return run_id


def _config(dataset: Dataset, framework_id: str | None, version: int | None, framework_file: Path | None):
    if framework_file:
        return MechanismConfig.model_validate_json(framework_file.read_text()), []
    if framework_id:
        store = _decision_store()
        config = store.get(framework_id, version)
        if config is None:
            typer.echo(f"Unknown framework: {framework_id}", err=True)
            raise typer.Exit(1)
        return config, store.get_audit(framework_id, config.version)
    return derive_mechanism(dataset)


@decision_app.command("profile")
def decision_profile(
    table: Path = typer.Option(None, "--table", help="CSV/TSV/XLSX table, one row per entity."),
    dataset_id: str = typer.Option(None, "--dataset"),
    source: str = typer.Option(None, "--source", help="transition_plan_run | extraction_run | theme_run | portfolio_snapshot"),
    run_id: str = typer.Option(None, "--run-id"),
    as_of: str = typer.Option(None, "--as-of"),
) -> None:
    """Types every column from its values and proposes a job for it."""
    dataset = _dataset(table, dataset_id, source, run_id, as_of)
    profiles = profile_dataset(dataset)
    typer.echo(f"{dataset.dataset_id}\t{dataset.row_count} rows\t{len(dataset.columns)} columns")
    for proposal in propose_roles(profiles, dataset.columns):
        profile = profiles[proposal.column]
        flag = "  <-- check" if proposal.needs_check else ""
        typer.echo(
            f"  {proposal.column:42} {profile.type:12} cov {profile.coverage:5.0%}  "
            f"{proposal.role:10} {proposal.direction:6}{flag}"
        )


@decision_app.command("derive")
def decision_derive(
    table: Path = typer.Option(None, "--table"),
    dataset_id: str = typer.Option(None, "--dataset"),
    source: str = typer.Option(None, "--source"),
    run_id: str = typer.Option(None, "--run-id"),
    as_of: str = typer.Option(None, "--as-of"),
    name: str = typer.Option(None, "--name", help="Framework name."),
    save: bool = typer.Option(False, "--save", help="Persist the derived framework as v1."),
    out: Path = typer.Option(None, "--out", help="Write the framework JSON here."),
) -> None:
    """Derives a scoring/tiering mechanism from a table, with the reason for every choice."""
    dataset = _dataset(table, dataset_id, source, run_id, as_of)
    config, audit = derive_mechanism(dataset, name=name)
    for entry in audit:
        flag = "  <-- check" if entry.needs_check else ""
        typer.echo(f"[{entry.stage}] {entry.item}: {entry.decision} -- {entry.why}{flag}")
    if save:
        _decision_store().save(config, audit)
        typer.echo(f"Saved {config.framework_id} v{config.version}")
    if out:
        out.write_text(config.model_dump_json(indent=2))
        typer.echo(f"Wrote {out}")


@decision_app.command("score")
def decision_score(
    table: Path = typer.Option(None, "--table"),
    dataset_id: str = typer.Option(None, "--dataset"),
    source: str = typer.Option(None, "--source"),
    run_id: str = typer.Option(None, "--run-id"),
    as_of: str = typer.Option(None, "--as-of"),
    framework_id: str = typer.Option(None, "--framework", help="Stored framework to apply; derived on the fly if omitted."),
    version: int = typer.Option(None, "--version"),
    framework_file: Path = typer.Option(None, "--framework-file"),
    limit: int = typer.Option(25, "--limit"),
    out: Path = typer.Option(None, "--out", help="Write the full result JSON here."),
) -> None:
    """Applies a mechanism and prints the ranked outcome."""
    dataset = _dataset(table, dataset_id, source, run_id, as_of)
    config, audit = _config(dataset, framework_id, version, framework_file)
    result = apply_mechanism(dataset, config, derivation_audit=audit)
    cuts = ", ".join(f"{c:.1f}" for c in result.effective_cuts)
    typer.echo(
        f"{result.scored_count} scored, {result.excluded_count} gated out, "
        f"{result.insufficient_count} insufficient; cuts {cuts} ({result.cuts_origin})"
    )
    for entity in sorted((e for e in result.entities if e.rank), key=lambda e: e.rank)[:limit]:
        band = f"[{entity.rank_min}-{entity.rank_max}]"
        notes = ("  " + "; ".join(entity.notes)) if entity.notes else ""
        typer.echo(f"{entity.rank:4}. {entity.name[:34]:34} {entity.score:6.2f}  {entity.tier_name or '':16} {band:8}{notes}")
    for entity in result.entities:
        if entity.status != "scored":
            typer.echo(f"      {entity.name[:34]:34} {entity.status:12} {'; '.join(entity.notes)}")
    if out:
        out.write_text(result.model_dump_json(indent=2))
        typer.echo(f"Wrote {out}")


@decision_app.command("sensitivity")
def decision_sensitivity(
    entity: list[str] = typer.Option(None, "--entity", help="Entity name/key to test; repeatable. Defaults to every scored entity."),
    table: Path = typer.Option(None, "--table"),
    dataset_id: str = typer.Option(None, "--dataset"),
    source: str = typer.Option(None, "--source"),
    run_id: str = typer.Option(None, "--run-id"),
    as_of: str = typer.Option(None, "--as-of"),
    framework_id: str = typer.Option(None, "--framework"),
    version: int = typer.Option(None, "--version"),
    framework_file: Path = typer.Option(None, "--framework-file"),
    steps: int = typer.Option(13, "--steps"),
) -> None:
    """How far a dimension's weight must move before a tier changes."""
    dataset = _dataset(table, dataset_id, source, run_id, as_of)
    config, _audit = _config(dataset, framework_id, version, framework_file)
    for row in tipping_points(dataset, config, entity_keys=list(entity) if entity else None, steps=steps):
        summary = (
            "robust across every weight tested"
            if row.min_delta_pct is None
            else f"flips after {row.min_delta_pct:+.1f}pp"
        )
        typer.echo(f"{row.name[:34]:34} tier {row.tier}  {summary}")
        for point in row.tipping_points:
            if point.delta_pct is not None:
                typer.echo(
                    f"    {point.dimension_name[:28]:28} {point.current_weight_pct:5.1f}% -> "
                    f"{point.flip_weight_pct:5.1f}% ({point.delta_pct:+.1f}pp) -> tier {point.new_tier}"
                )


@decision_app.command("compare")
def decision_compare(
    before: str = typer.Option(..., "--before", help="Dataset id, or a path to a table."),
    after: str = typer.Option(..., "--after", help="Dataset id, or a path to a table."),
    framework_id: str = typer.Option(None, "--framework"),
    version: int = typer.Option(None, "--version"),
    framework_file: Path = typer.Option(None, "--framework-file"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Applies one framework to two snapshots and reports what moved."""
    store = _decision_store()

    def _resolve(ref: str) -> Dataset:
        if Path(ref).exists():
            return store.save_dataset(dataset_from_file(Path(ref)))
        dataset = store.get_dataset(ref)
        if dataset is None:
            typer.echo(f"Unknown dataset: {ref}", err=True)
            raise typer.Exit(1)
        return dataset

    ds_before, ds_after = _resolve(before), _resolve(after)
    config, _audit = _config(ds_after, framework_id, version, framework_file)
    comparison = compare_results(
        apply_mechanism(ds_before, config),
        apply_mechanism(ds_after, config),
        label_before=ds_before.as_of or ds_before.name,
        label_after=ds_after.as_of or ds_after.name,
    )
    if not comparison.comparable:
        typer.echo(f"WARNING: {comparison.incomparable_reason}", err=True)
    if comparison.caveat:
        typer.echo(f"NOTE: {comparison.caveat}", err=True)
    typer.echo(
        f"{comparison.label_before} -> {comparison.label_after}: {comparison.improved} improved, "
        f"{comparison.worsened} worsened, {comparison.unchanged} unchanged, "
        f"{comparison.entered} new, {comparison.left} gone"
    )
    for movement in comparison.movements[:limit]:
        if not movement.tier_delta and not movement.score_delta:
            continue
        drivers = ("  " + ", ".join(movement.drivers)) if movement.drivers else ""
        typer.echo(
            f"  {movement.name[:32]:32} tier {movement.tier_before} -> {movement.tier_after}  "
            f"score {movement.score_delta:+.1f}{drivers}"
        )


@decision_app.command("list")
def decision_list() -> None:
    for config in _decision_store().list_frameworks():
        status = "ratified" if config.ratified else "draft"
        typer.echo(f"{config.framework_id}\tv{config.version}\t{status}\t{len(config.criteria)} criteria\t{config.name}")


@decision_app.command("show")
def decision_show(framework_id: str, version: int = typer.Option(None)) -> None:
    config = _decision_store().get(framework_id, version)
    if config is None:
        typer.echo("Not found", err=True)
        raise typer.Exit(1)
    typer.echo(config.model_dump_json(indent=2))


@decision_app.command("audit")
def decision_audit(framework_id: str, version: int = typer.Option(None)) -> None:
    """The derivation and edit trail for one framework version -- which rules
    came from the data, and which came from a person."""
    for entry in _decision_store().get_audit(framework_id, version):
        origin = "you" if entry.origin == "human" else "data"
        flag = "  <-- check" if entry.needs_check else ""
        typer.echo(f"[{origin}] [{entry.stage}] {entry.item}: {entry.decision} -- {entry.why}{flag}")


@decision_app.command("new-version")
def decision_new_version(
    framework_id: str,
    framework_file: Path = typer.Option(..., "--framework-file", help="Edited MechanismConfig JSON."),
    by: str = typer.Option(None, "--by", help="Who made the edits, recorded in the audit trail."),
) -> None:
    store = _decision_store()
    edited = MechanismConfig.model_validate_json(framework_file.read_text())
    previous = store.get(framework_id)
    if previous is None:
        typer.echo(f"Unknown framework: {framework_id}", err=True)
        raise typer.Exit(1)
    audit = list(store.get_audit(framework_id, previous.version)) + describe_changes(previous, edited, by=by)
    saved = store.new_version(edited.model_copy(update={"framework_id": framework_id}), audit)
    typer.echo(f"Created {saved.framework_id} v{saved.version}")


@decision_app.command("ratify")
def decision_ratify(framework_id: str, version: int = typer.Option(None)) -> None:
    try:
        config = _decision_store().ratify(framework_id, version)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Ratified {config.framework_id} v{config.version}")
