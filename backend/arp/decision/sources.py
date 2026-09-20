from __future__ import annotations

import re
from collections import defaultdict

from arp.decision.dataset import Dataset, build_dataset
from arp.storage.run_store import RunStore

# Column names deliberately follow the conventions the role/direction
# dictionaries already recognise (`*_Coverage_pct`, `*_Intensity_*`,
# `*_Flag`, `*_Weight_*`), so role and direction inference works as well on
# a table built from an in-repo run as on an uploaded spreadsheet.

_EXPOSURE_SCALE = {"none": 0.0, "low": 25.0, "medium": 50.0, "high": 75.0, "very_high": 100.0}
_VERDICT_SCALE = {"include": 1, "borderline": 0, "exclude": 0}


def _matrix(columns: list[str], rows: list[list[str]]) -> list[list[str]]:
    return [columns] + rows


def from_transition_plan_run(run_store: RunStore, run_id: str) -> Dataset:
    """A transition-plan assessment run -> a scoreable table.

    The paper's completeness metric is a count, not a decision. This is
    what turns "42 of 64 indicators disclosed" into "Tier 2, engage on
    governance", which is what an investor actually does with it.
    """
    records = run_store.read_jsonl(run_store.results_path(run_id))
    if not records:
        raise ValueError(f"Transition plan run {run_id} has no results.")

    categories = sorted({b.get("category", "") for r in records for b in r.get("by_category", []) if b.get("category")})
    columns = [
        "Company",
        "Company_Id",
        "Sector",
        "Region",
        "Indicators_Disclosed_Count",
        "Walk_Disclosed_Count",
        "Talk_Disclosed_Count",
        "Walk_Share_pct",
        "Assessment_Confidence_pct",
        *[f"{c.title()}_Disclosure_pct" for c in categories],
        "Needs_Review_Flag",
    ]
    rows: list[list[str]] = []
    for record in records:
        by_category = {b.get("category"): b for b in record.get("by_category", [])}
        walk_total = record.get("walk_total_count") or 0
        walk_disclosed = record.get("walk_disclosed_count") or 0
        row = [
            str(record.get("name") or record.get("company_id") or ""),
            str(record.get("company_id") or ""),
            str(record.get("company_sector") or ""),
            str(record.get("company_location") or ""),
            str(record.get("disclosed_count") or 0),
            str(walk_disclosed),
            str(record.get("talk_disclosed_count") or 0),
            f"{(walk_disclosed / walk_total * 100):.1f}" if walk_total else "",
            f"{(record.get('overall_confidence') or 0.0) * 100:.1f}",
        ]
        for category in categories:
            breakdown = by_category.get(category) or {}
            total = breakdown.get("total_count") or 0
            row.append(f"{(breakdown.get('disclosed_count', 0) / total * 100):.1f}" if total else "")
        row.append("Yes" if record.get("needs_review") else "No")
        rows.append(row)

    dataset = build_dataset(
        f"Transition plan run {run_id}", _matrix(columns, rows), source="transition_plan_run", source_ref=run_id
    )
    # The paper's own confidence figure, carried per cell so a framework
    # asking for grounded coverage can act on it.
    confidence = [(float(r.get("overall_confidence") or 0.0)) for r in records]
    for column in ("Indicators_Disclosed_Count", "Walk_Disclosed_Count", "Talk_Disclosed_Count", "Walk_Share_pct"):
        dataset.confidence[column] = list(confidence)
    return dataset


def from_extraction_run(run_store: RunStore, run_id: str) -> Dataset:
    """An extraction run -> one row per company, one column per schema
    field, with each cell's confidence carried alongside it.

    This is the source that makes `require_grounded_coverage` worth having:
    an extracted value the verifier could not ground is present but not
    trustworthy, and a score built mostly on those should say so rather
    than read like any other score.
    """
    records = run_store.read_jsonl(run_store.results_path(run_id))
    if not records:
        raise ValueError(f"Extraction run {run_id} has no results.")

    field_names: list[str] = []
    for record in records:
        for field in record.get("fields", []):
            name = str(field.get("field_name") or field.get("field_id") or "")
            if name and name not in field_names:
                field_names.append(name)

    columns = ["Company", "Company_Id", "Extraction_Confidence_pct", *field_names, "Needs_Review_Flag"]
    rows: list[list[str]] = []
    confidence: dict[str, list[float | None]] = defaultdict(list)
    for record in records:
        by_name = {str(f.get("field_name") or f.get("field_id")): f for f in record.get("fields", [])}
        row = [
            str(record.get("name") or record.get("company_id") or ""),
            str(record.get("company_id") or ""),
            f"{(record.get('overall_confidence') or 0.0) * 100:.1f}",
        ]
        for name in field_names:
            field = by_name.get(name) or {}
            value = field.get("value")
            row.append("" if value is None else str(value))
            # An ungrounded citation is the reason confidence exists here:
            # the extractor's own certainty is not evidence.
            grounded = bool(field.get("grounded"))
            raw_confidence = field.get("confidence")
            confidence[name].append(float(raw_confidence) if raw_confidence is not None and grounded else (0.0 if name in by_name else None))
        row.append("Yes" if record.get("needs_review") else "No")
        rows.append(row)

    dataset = build_dataset(f"Extraction run {run_id}", _matrix(columns, rows), source="extraction_run", source_ref=run_id)
    dataset.confidence = {k: v for k, v in confidence.items()}
    return dataset


def from_theme_run(run_store: RunStore, run_id: str) -> Dataset:
    """A thematic universe run -> one row per company, aggregated over the
    per-activity matches: how many activities it was included on, its best
    exposure estimate, and the adjudicator's mean confidence."""
    matches = run_store.read_jsonl(run_store.results_path(run_id))
    if not matches:
        raise ValueError(f"Theme run {run_id} has no results.")

    grouped: dict[str, list[dict]] = defaultdict(list)
    for match in matches:
        grouped[str(match.get("company_id") or match.get("name") or "")].append(match)

    columns = [
        "Company",
        "Company_Id",
        "Activities_Included_Count",
        "Best_Exposure_Score_0_100",
        "Mean_Exposure_Score_0_100",
        "Adjudicator_Confidence_pct",
        "Flagged_For_Review_Flag",
    ]
    rows: list[list[str]] = []
    for company_id, company_matches in grouped.items():
        included = [m for m in company_matches if str(m.get("verdict", "")).lower() == "include"]
        exposures = [_EXPOSURE_SCALE.get(str(m.get("exposure_estimate", "")).lower(), 0.0) for m in company_matches]
        confidences = [float(m.get("confidence") or 0.0) for m in company_matches]
        rows.append(
            [
                str(company_matches[0].get("name") or company_id),
                company_id,
                str(len(included)),
                f"{max(exposures):.1f}" if exposures else "",
                f"{(sum(exposures) / len(exposures)):.1f}" if exposures else "",
                f"{(sum(confidences) / len(confidences) * 100):.1f}" if confidences else "",
                "Yes" if any(m.get("flagged_for_review") for m in company_matches) else "No",
            ]
        )
    return build_dataset(f"Theme run {run_id}", _matrix(columns, rows), source="theme_run", source_ref=run_id)


def from_portfolio_snapshot(store, as_of: str | None = None, portfolio_ids: list[str] | None = None, field_ids: list[str] | None = None) -> Dataset:
    """Holdings as of one date, joined to whatever data-point observations
    exist for each issuer -- climate metrics included.

    `market_value_eur` becomes the size column, which is what makes the
    leverage ordering (position size x the gap to a perfect score) a real
    portfolio-weighted engagement priority list rather than a
    demonstration.
    """
    resolved = as_of or (store.all_snapshot_dates() or [None])[-1]
    if resolved is None:
        raise ValueError("No holdings snapshots available.")
    holdings = store.load_holdings_as_of(resolved, portfolio_ids)
    if not holdings:
        raise ValueError(f"No holdings as of {resolved}.")

    securities = {s.security_id: s for s in store.list_securities()}
    companies = {c.company_id: c for c in store.list_companies()}

    exposure: dict[str, float] = defaultdict(float)
    for holding in holdings:
        security = securities.get(holding.security_id)
        company_id = security.company_id if security else None
        if company_id:
            exposure[company_id] += holding.market_value_eur

    from arp.portfolio.climate.schemas import build_climate_schema

    fields = [f for f in build_climate_schema().fields if not field_ids or f.field_id in field_ids]
    observations: dict[str, dict[str, float]] = defaultdict(dict)
    for company_id in exposure:
        for field in fields:
            observation = store.latest_observation(company_id, field.field_id, as_of=resolved)
            if observation is not None and isinstance(observation.value, (int, float)):
                observations[company_id][field.field_id] = float(observation.value)

    used_fields = [f for f in fields if any(f.field_id in values for values in observations.values())]
    columns = ["Company", "Company_Id", "Sector", "Country", "Portfolio_Market_Value_EUR", *[_field_column(f) for f in used_fields]]
    rows: list[list[str]] = []
    for company_id, market_value in sorted(exposure.items(), key=lambda kv: -kv[1]):
        company = companies.get(company_id)
        row = [
            company.name if company else company_id,
            company_id,
            (company.sector if company else "") or "",
            (company.country if company else "") or "",
            f"{market_value:.2f}",
        ]
        for field in used_fields:
            value = observations.get(company_id, {}).get(field.field_id)
            row.append("" if value is None else f"{value:g}")
        rows.append(row)

    return build_dataset(
        f"Portfolio holdings as of {resolved}",
        _matrix(columns, rows),
        source="portfolio_snapshot",
        source_ref=",".join(portfolio_ids) if portfolio_ids else "all",
        as_of=resolved,
    )


def _field_column(field) -> str:
    """A data-point field's column name, keeping the unit in the name where
    the dictionaries key off it (`_pct`, `_Intensity_`)."""
    base = field.name.replace(" ", "_").replace("/", "_")
    unit = (field.unit or "").strip().lower()
    if unit in ("%", "pct", "percent") and not base.lower().endswith("pct"):
        return f"{base}_pct"
    return base


# --- Sources whose entity is not a company ------------------------------
#
# Nothing in the engine assumes an entity is a company: it scores rows.
# A sector-and-region cell, a theme, and a strategy are all perfectly good
# entities, and the three adapters below are what make that concrete.

_RATING_SCALE = {"H": 100.0, "M": 50.0, "L": 0.0}
_CONFIDENCE_SCALE = {"high": 1.0, "medium": 0.6, "low": 0.2}


def from_transition_barrier(region: str | None = None, sectors: list[str] | None = None) -> Dataset:
    """The barrier matrix -> one row per sector x region.

    The columns are named for **feasibility**, not for barriers, and that is
    deliberate rather than stylistic: `Rating.HIGH` in this dataset means the
    transition is *more* feasible -- fewer barriers -- so a column called
    `..._Barrier_...` would be read by direction inference as
    lower-is-better and would invert the entire ranking while every number
    on screen still looked correct.
    """
    from arp.transition_barrier.dataset import load_scores
    from arp.transition_barrier.staleness import staleness_days

    rows_in = [s for s in load_scores() if (region is None or s.region.value == region) and (sectors is None or s.sector in sectors)]
    if not rows_in:
        raise ValueError("No barrier scores match that sector/region filter.")

    pillars = sorted({s.category.value for s in rows_in})
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for score in rows_in:
        grouped[(score.sector, score.region.value)].append(score)

    columns = [
        "Assessment",
        "Sector",
        "Region",
        *[f"{_slug_title(p)}_Feasibility_0_100" for p in pillars],
        "Assessment_Confidence_pct",
        "Evidence_Staleness_Days",
        "Criteria_Rated_Count",
    ]
    rows: list[list[str]] = []
    confidence: dict[str, list[float | None]] = defaultdict(list)
    for (sector, region_value), cells in sorted(grouped.items()):
        row = [f"{sector} - {region_value}", sector, region_value]
        for pillar in pillars:
            members = [c for c in cells if c.category.value == pillar]
            column = f"{_slug_title(pillar)}_Feasibility_0_100"
            if members:
                row.append(f"{sum(_RATING_SCALE[m.rating.value] for m in members) / len(members):.1f}")
                confidence[column].append(sum(_CONFIDENCE_SCALE.get(m.confidence.value, 0.2) for m in members) / len(members))
            else:
                row.append("")
                confidence[column].append(None)
        confidences = [_CONFIDENCE_SCALE.get(c.confidence.value, 0.2) for c in cells]
        row.append(f"{sum(confidences) / len(confidences) * 100:.1f}")
        row.append(str(max(staleness_days(c) for c in cells)))
        row.append(str(len(cells)))
        rows.append(row)

    dataset = build_dataset(
        f"Transition barrier matrix{f' ({region})' if region else ''}",
        _matrix(columns, rows),
        source="transition_barrier",
        source_ref=region or "all regions",
    )
    dataset.confidence = dict(confidence)
    return dataset


def _slug_title(pillar: str) -> str:
    """"Demand & Economics" -> "Demand_Economics". Runs of separators collapse
    to one underscore, so the column name stays readable and the keyword
    dictionaries still tokenise it."""
    return re.sub(r"_+", "_", "".join(ch if ch.isalnum() else "_" for ch in pillar)).strip("_")


def from_emerging_themes_run(run_store: RunStore, run_id: str) -> Dataset:
    """An Emerging Themes run -> one row per candidate theme.

    Read through `load_candidates_with_status`, not off results.jsonl, so a
    theme an analyst has already rejected or disconfirmed arrives with that
    status rather than as a live candidate -- the promote/reject log is
    append-only and folding it in is the only way to see current state.
    """
    from arp.emerging_themes.pipeline import load_candidates_with_status

    candidates = load_candidates_with_status(run_store, run_id)
    if not candidates:
        raise ValueError(f"Emerging themes run {run_id} has no candidates.")

    columns = [
        "Theme",
        "Theme_Id",
        "Signal_Velocity",
        "Breadth_pct",
        "Persistence_Periods",
        "Novelty_pct",
        "Action_Score_pct",
        "Materiality_pct",
        "Contradiction_pct",
        "Companies_Count",
        "Grounded_Sources_pct",
        "Status",
        "Disconfirmed_Flag",
    ]
    rows: list[list[str]] = []
    for candidate in candidates:
        sources = candidate.corroborating_sources
        grounded = [s for s in sources if s.grounded]
        rows.append(
            [
                candidate.theme_name,
                candidate.theme_id,
                f"{candidate.signal_velocity:.3f}",
                f"{candidate.breadth * 100:.1f}",
                str(candidate.persistence),
                f"{candidate.novelty * 100:.1f}",
                f"{candidate.action_score * 100:.1f}",
                f"{candidate.materiality * 100:.1f}",
                f"{candidate.contradiction * 100:.1f}",
                str(len(candidate.candidate_sectors_companies)),
                f"{len(grounded) / len(sources) * 100:.1f}" if sources else "",
                candidate.status.value,
                # A disconfirmed theme's transmission mechanism has been
                # invalidated by material counter-evidence. That is a
                # knockout, not a deduction -- it belongs in the tree.
                "Yes" if candidate.status.value == "disconfirmed" else "No",
            ]
        )

    dataset = build_dataset(
        f"Emerging themes run {run_id}", _matrix(columns, rows), source="emerging_themes_run", source_ref=run_id
    )
    scores = [float(c.confidence_score) for c in candidates]
    for column in ("Signal_Velocity", "Breadth_pct", "Novelty_pct", "Action_Score_pct", "Materiality_pct"):
        dataset.confidence[column] = list(scores)
    return dataset


def from_replication_runs(run_store: RunStore, run_ids: list[str] | None = None) -> Dataset:
    """Strategy replication runs -> one row per replicated strategy.

    One run replicates one spec, so a table worth ranking spans runs: the
    question this answers is which of the strategies we replicated actually
    deserve capital, and a single run cannot answer it.

    `Out_Of_Sample_Persistence_pp` carries the sign the engine needs
    (higher = held up better) and is deliberately not called a "gap": `gap`
    is in the lower-is-better dictionary, and a column named that way would
    be scored upside-down.
    """
    if run_ids is None:
        run_ids = [m.run_id for m in run_store.list_runs(run_type="strategy_replication")]
    if not run_ids:
        raise ValueError("No strategy_replication runs found.")

    columns = [
        "Strategy",
        "Spec_Id",
        "Run_Id",
        "Verdict",
        "In_Sample_Sharpe",
        "Out_Of_Sample_Sharpe",
        "In_Sample_Annualized_Return_pct",
        "Out_Of_Sample_Annualized_Return_pct",
        "Out_Of_Sample_Persistence_pp",
        "Max_Drawdown_pct",
        "Deflated_Sharpe_Ratio",
        "Universe_Size",
        "Monthly_Turnover_pct",
        "Data_Warnings_Count",
        "Not_Replicated_Flag",
    ]
    rows: list[list[str]] = []
    for run_id in run_ids:
        records = run_store.read_jsonl(run_store.results_path(run_id))
        report = next((r for r in records if r.get("type") == "comparison"), None)
        if report is None:
            continue
        spec = next((r for r in records if r.get("type") == "spec"), {})
        in_sample = report.get("in_sample") or {}
        out_of_sample = report.get("out_of_sample") or {}
        in_leg = (in_sample.get("long_short") or {})
        out_leg = (out_of_sample.get("long_short") or {})
        deflated = (report.get("deflated_sharpe") or {}).get("deflated_sharpe_ratio")
        verdict = str(report.get("verdict") or "")
        rows.append(
            [
                str(spec.get("strategy_name") or report.get("spec_id") or run_id),
                str(report.get("spec_id") or ""),
                run_id,
                verdict,
                _num(in_leg.get("sharpe_ratio")),
                _num(out_leg.get("sharpe_ratio")),
                _num(in_leg.get("annualized_return_pct")),
                _num(out_leg.get("annualized_return_pct")),
                _num(report.get("out_of_sample_return_gap_pp")),
                _num(in_leg.get("max_drawdown_pct")),
                _num(deflated),
                str(in_sample.get("universe_size") or ""),
                _num(in_sample.get("monthly_turnover_pct")),
                str(len(in_sample.get("warnings") or [])),
                # Wrong sign, indistinguishable from zero, or not enough
                # data: none of those is a low score to be averaged against
                # a good Sharpe elsewhere.
                "Yes" if verdict in ("not_replicated", "insufficient_data") else "No",
            ]
        )

    if not rows:
        raise ValueError("None of those runs carry a completed replication comparison.")
    return build_dataset(
        "Strategy replication runs", _matrix(columns, rows), source="replication_runs", source_ref=",".join(run_ids)
    )


def _num(value) -> str:
    return "" if value is None else f"{float(value):g}"
