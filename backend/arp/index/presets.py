"""Named rule bundles and the machine-readable rule catalogue.

A preset is not a black box: it *expands* into the ordinary rules the UI
already shows, so a user can click "EU PAB exclusions", see all seven
resulting screens, and then edit or delete any of them. That keeps the
convenience of a template without hiding what the methodology actually is.

Thresholds carrying regulatory weight are sourced in
`docs/INDEX_METHODOLOGY_LANDSCAPE.md` section 5 and flagged there as needing
a primary-source check against the Official Journal before they are used
for a real published benchmark.
"""

from __future__ import annotations

from typing import Callable

from arp.schemas.index import (
    BaseWeighting,
    BestInClassCoverage,
    BucketTilt,
    CategoryScreen,
    ConstraintSet,
    ConstructionSpec,
    DecarbonisationTrajectory,
    FlagExclusionScreen,
    MetricThresholdScreen,
    MetricTilt,
    ScreenRule,
    SelectAll,
    TiltRule,
)


def _norms_and_weapons() -> list[ScreenRule]:
    return [
        FlagExclusionScreen(label="Norms-based exclusion (UNGC / OECD)", field="norms_violation"),
        FlagExclusionScreen(label="Controversial weapons", field="controversial_weapons"),
        MetricThresholdScreen(label="Tobacco production", field="tobacco_revenue_pct", max_value=0.0, missing="pass"),
    ]


def _fossil_exclusions() -> list[ScreenRule]:
    return [
        MetricThresholdScreen(label="Coal revenue > 1%", field="coal_revenue_pct", max_value=0.01),
        MetricThresholdScreen(label="Oil revenue > 10%", field="oil_revenue_pct", max_value=0.10),
        MetricThresholdScreen(label="Gas revenue > 50%", field="gas_revenue_pct", max_value=0.50),
        MetricThresholdScreen(
            label="High-intensity power generation > 50% (>100 gCO2e/kWh)",
            field="high_intensity_power_revenue_pct",
            max_value=0.50,
        ),
    ]


def eu_ctb_screens() -> list[ScreenRule]:
    """EU Climate Transition Benchmark: three exclusion categories only --
    controversial weapons, tobacco, and norms violators. Notably *no*
    fossil-fuel revenue exclusions, which is the main structural difference
    from a PAB."""
    return _norms_and_weapons()


def eu_pab_screens() -> list[ScreenRule]:
    """EU Paris-aligned Benchmark: the CTB set plus the fossil revenue
    thresholds."""
    return _norms_and_weapons() + _fossil_exclusions()


def liquidity_and_size_screens() -> list[ScreenRule]:
    return [
        MetricThresholdScreen(label="Minimum free-float market cap", field="float_mcap", min_value=500_000_000.0),
        MetricThresholdScreen(label="Minimum 3-month ADV", field="adv_3m", min_value=2_000_000.0),
    ]


def thematic_screens(min_relevance: float = 0.25) -> list[ScreenRule]:
    return [
        MetricThresholdScreen(label=f"Thematic relevance >= {min_relevance:.0%}", field="relevance", min_value=min_relevance),
        CategoryScreen(
            label="Classification sanity overlay",
            field="sector",
            deny=["Financials", "Real Estate"],
            missing="pass",
        ),
    ]


def esg_tilt() -> list[TiltRule]:
    """The MSCI ESG Universal shape: current score times trend, applied
    multiplicatively to the parent weight."""
    return [
        MetricTilt(label="ESG score tilt", field="esg_score", normalisation="max", floor=0.5, ceiling=1.5),
        MetricTilt(label="ESG trend tilt", field="esg_trend", normalisation="max", floor=0.8, ceiling=1.2),
    ]


PRESETS: dict[str, dict] = {
    "exclusion_only": {
        "label": "Exclusion only (ESG Screened / ESG-X shape)",
        "description": "Parent index minus norms violators, controversial weapons and tobacco. Parent weights, renormalised. The cheapest credible ESG index.",
        "build": lambda: ConstructionSpec(
            screens=liquidity_and_size_screens() + eu_ctb_screens(),
            selection=SelectAll(label="No selection step"),
            base_weighting=BaseWeighting(scheme="free_float_mcap"),
            constraints=ConstraintSet(single_name_cap=0.10),
        ),
    },
    "esg_tilt": {
        "label": "ESG tilt (ESG Universal shape)",
        "description": "Minimal exclusions, then a closed-form score x trend tilt on parent market-cap weights. No solver, no risk model.",
        "build": lambda: ConstructionSpec(
            screens=liquidity_and_size_screens() + eu_ctb_screens(),
            selection=SelectAll(label="No selection step"),
            base_weighting=BaseWeighting(scheme="free_float_mcap"),
            tilts=esg_tilt(),
            constraints=ConstraintSet(single_name_cap=0.08),
        ),
    },
    "best_in_class": {
        "label": "Best-in-class (ESG Leaders shape)",
        "description": "Rank by ESG score within sector, select down to 50% of each sector's float market cap, with a 10% buffer to damp turnover.",
        "build": lambda: ConstructionSpec(
            screens=liquidity_and_size_screens() + eu_ctb_screens(),
            selection=BestInClassCoverage(
                label="Top 50% of each sector by float market cap",
                score_field="esg_score",
                group_by="sector",
                target_pct=0.5,
                basis="float_mcap",
                buffer_pct=0.10,
            ),
            base_weighting=BaseWeighting(scheme="free_float_mcap"),
            constraints=ConstraintSet(single_name_cap=0.08),
        ),
    },
    "climate_category_tilt": {
        "label": "Climate category tilt (Climate Change CTB shape)",
        "description": "Tilt between and within low-carbon-transition categories, with the multiplier floored so a tilt cannot silently become an exclusion.",
        "build": lambda: ConstructionSpec(
            screens=liquidity_and_size_screens() + eu_ctb_screens(),
            selection=SelectAll(label="No selection step"),
            base_weighting=BaseWeighting(scheme="free_float_mcap"),
            tilts=[
                BucketTilt(
                    label="Low-carbon transition category",
                    field="lct_category",
                    multipliers={"solutions": 1.6, "neutral": 1.0, "operational_transition": 0.8, "product_transition": 0.7, "asset_stranding": 0.5},
                    default_multiplier=1.0,
                ),
                MetricTilt(label="LCT score, normalised within category", field="lct_score", normalisation="group_max", group_by="lct_category", floor=0.5, ceiling=1.5),
            ],
            constraints=ConstraintSet(single_name_cap=0.08),
        ),
    },
    "eu_ctb": {
        "label": "EU Climate Transition Benchmark",
        "description": "CTB exclusions, 30% intensity reduction versus the investable universe, and a 7% year-on-year trajectory from a fixed base.",
        "build": lambda: ConstructionSpec(
            screens=liquidity_and_size_screens() + eu_ctb_screens(),
            selection=SelectAll(label="No selection step"),
            base_weighting=BaseWeighting(scheme="free_float_mcap"),
            constraints=ConstraintSet(single_name_cap=0.05, ucits_5_10_40=True),
            trajectory=DecarbonisationTrajectory(enabled=True, metric_field="ghg_intensity", annual_reduction_rate=0.07, universe_reduction_pct=0.30),
        ),
    },
    "eu_pab": {
        "label": "EU Paris-aligned Benchmark",
        "description": "PAB exclusions including the fossil revenue thresholds, 50% intensity reduction versus the investable universe, and the 7% trajectory.",
        "build": lambda: ConstructionSpec(
            screens=liquidity_and_size_screens() + eu_pab_screens(),
            selection=SelectAll(label="No selection step"),
            base_weighting=BaseWeighting(scheme="free_float_mcap"),
            constraints=ConstraintSet(single_name_cap=0.05, ucits_5_10_40=True),
            trajectory=DecarbonisationTrajectory(enabled=True, metric_field="ghg_intensity", annual_reduction_rate=0.07, universe_reduction_pct=0.50),
        ),
    },
    "thematic_pure_play": {
        "label": "Thematic, relevance-weighted",
        "description": "Relevance >= 25% with a classification sanity overlay, weighted by relevance x market cap and capped at 5% per issuer.",
        "build": lambda: ConstructionSpec(
            screens=liquidity_and_size_screens() + thematic_screens() + _norms_and_weapons(),
            selection=SelectAll(label="No selection step"),
            base_weighting=BaseWeighting(scheme="free_float_mcap"),
            tilts=[MetricTilt(label="Thematic relevance", field="relevance", normalisation="none", floor=0.25, ceiling=1.0)],
            constraints=ConstraintSet(single_name_cap=0.05),
        ),
    },
}


def build_preset(name: str) -> ConstructionSpec:
    preset = PRESETS.get(name)
    if preset is None:
        raise ValueError(f"Unknown preset: {name!r}. Known: {', '.join(sorted(PRESETS))}")
    builder: Callable[[], ConstructionSpec] = preset["build"]
    return builder()


SCREEN_BUNDLES: dict[str, Callable[[], list[ScreenRule]]] = {
    "eu_ctb_exclusions": eu_ctb_screens,
    "eu_pab_exclusions": eu_pab_screens,
    "size_and_liquidity": liquidity_and_size_screens,
    "thematic": thematic_screens,
}


def _optimizer_available() -> bool:
    from arp.index.optimize import available

    return available()


def rule_catalogue() -> dict:
    """Machine-readable description of every rule type, its parameters and
    defaults -- the single source the UI builds its pickers from, so a new
    rule type appears in the UI without a frontend change."""
    return {
        "screens": [
            {
                "type": "metric_threshold",
                "label": "Metric threshold",
                "help": "Keep companies whose numeric field sits inside the bounds. Covers size and liquidity floors, relevance thresholds, and every revenue-involvement exclusion.",
                "params": [
                    {"name": "field", "kind": "metric_field", "required": True},
                    {"name": "min_value", "kind": "number", "required": False},
                    {"name": "max_value", "kind": "number", "required": False},
                    {"name": "missing", "kind": "enum", "options": ["block", "fail", "pass"], "default": "block"},
                ],
            },
            {
                "type": "flag_exclusion",
                "label": "Flag exclusion",
                "help": "Exclude companies whose boolean field is set -- norms violations, controversial weapons, controversy flags.",
                "params": [
                    {"name": "field", "kind": "flag_field", "required": True},
                    {"name": "exclude_when", "kind": "boolean", "default": True},
                    {"name": "missing", "kind": "enum", "options": ["block", "fail", "pass"], "default": "block"},
                ],
            },
            {
                "type": "category_screen",
                "label": "Category allow / deny",
                "help": "Allow-list or deny-list on a categorical field. The allow-list form is the classification sanity overlay for NLP-derived thematic scores.",
                "params": [
                    {"name": "field", "kind": "category_field", "required": True},
                    {"name": "allow", "kind": "category_values", "required": False},
                    {"name": "deny", "kind": "category_values", "required": False},
                    {"name": "missing", "kind": "enum", "options": ["block", "fail", "pass"], "default": "block"},
                ],
            },
        ],
        "selection": [
            {"type": "select_all", "label": "No selection step", "help": "Everything surviving the screens is in.", "params": []},
            {
                "type": "best_in_class_coverage",
                "label": "Best-in-class to a coverage target",
                "help": "Rank within a group, select until coverage reaches the target -- by float market cap or by count. One rule covers the MSCI ESG Leaders, MSCI Climate Action and STOXX ESG Broad Market variants.",
                "params": [
                    {"name": "score_field", "kind": "metric_field", "required": True},
                    {"name": "group_by", "kind": "category_field", "default": "sector"},
                    {"name": "target_pct", "kind": "fraction", "default": 0.5},
                    {"name": "basis", "kind": "enum", "options": ["float_mcap", "count"], "default": "float_mcap"},
                    {"name": "buffer_pct", "kind": "fraction", "default": 0.0},
                    {"name": "higher_is_better", "kind": "boolean", "default": True},
                ],
            },
            {
                "type": "absolute_threshold",
                "label": "Absolute threshold",
                "help": "Select everything clearing a bar, optionally per group (the ISS Prime shape). Can empty a group, so the fallback is declared up front.",
                "params": [
                    {"name": "score_field", "kind": "metric_field", "required": True},
                    {"name": "threshold", "kind": "number", "required": True},
                    {"name": "group_by", "kind": "category_field", "default": "sector"},
                    {"name": "on_empty_group", "kind": "enum", "options": ["leave_empty", "fallback_relative", "block"], "default": "leave_empty"},
                    {"name": "fallback_target_pct", "kind": "fraction", "default": 0.25},
                ],
            },
            {
                "type": "top_n",
                "label": "Top N",
                "help": "Fixed-size index: the N best by score, with deterministic tie-breaking.",
                "params": [
                    {"name": "score_field", "kind": "metric_field", "required": True},
                    {"name": "n", "kind": "integer", "required": True},
                    {"name": "group_by", "kind": "category_field", "default": "none"},
                ],
            },
        ],
        "base_weighting": [
            {"scheme": "free_float_mcap", "label": "Free-float market cap", "needs_field": False},
            {"scheme": "equal", "label": "Equal weight", "needs_field": False},
            {"scheme": "metric", "label": "Weight by metric", "needs_field": True},
            {"scheme": "inverse_metric", "label": "Market cap / metric", "needs_field": True},
        ],
        "tilts": [
            {
                "type": "metric_tilt",
                "label": "Metric tilt",
                "help": "Multiply the base weight by a bounded function of a numeric field. Floor and ceiling are mandatory: an unbounded tilt silently becomes an exclusion.",
                "params": [
                    {"name": "field", "kind": "metric_field", "required": True},
                    {"name": "normalisation", "kind": "enum", "options": ["none", "max", "group_max", "rank_percentile", "zscore"], "default": "max"},
                    {"name": "group_by", "kind": "category_field", "default": "none"},
                    {"name": "floor", "kind": "number", "default": 0.5},
                    {"name": "ceiling", "kind": "number", "default": 2.0},
                    {"name": "higher_is_better", "kind": "boolean", "default": True},
                ],
            },
            {
                "type": "bucket_tilt",
                "label": "Category multiplier table",
                "help": "A fixed factor per category value -- the most auditable tilt there is, because the whole rule is a table a committee can read.",
                "params": [
                    {"name": "field", "kind": "category_field", "required": True},
                    {"name": "multipliers", "kind": "multiplier_table", "required": True},
                    {"name": "default_multiplier", "kind": "number", "default": 1.0},
                ],
            },
        ],
        "constraints": [
            {"name": "single_name_cap", "kind": "fraction", "help": "Maximum weight per issuer, applied by the deterministic waterfall."},
            {"name": "group_caps", "kind": "group_cap_list", "help": "Maximum aggregate weight per sector / country / any categorical dimension."},
            {"name": "ucits_5_10_40", "kind": "boolean", "help": "No issuer above 10%, and issuers above 5% summing to at most 40%."},
            {"name": "min_weight", "kind": "fraction", "help": "Constituents below this are dropped and their weight redistributed."},
        ],
        "constraint_solver": {
            "help": (
                "How the constraint set is satisfied. The waterfall needs nothing installed and is byte-identical "
                "everywhere, but applies the constraints in sequence. The least-squares projection solves them "
                "simultaneously and returns the closest feasible portfolio to what the rules asked for; it needs the "
                "optional `optimize` extra and falls back to the waterfall, with an exception recorded, if the solver "
                "fails or its answer does not pass our own constraint check."
            ),
            "params": [
                {"name": "method", "kind": "enum", "options": ["waterfall", "least_squares"], "default": "waterfall"},
                {"name": "solver", "kind": "enum", "options": ["CLARABEL", "OSQP", "SCS"], "default": "CLARABEL", "help": "Pinned per calibration: a solver swap can move the last digits, so it is a methodology change."},
                {"name": "verify_tolerance", "kind": "number", "default": 1e-7, "help": "Every constraint is re-checked in plain Python at this tolerance; the solver's own status is never taken as proof."},
                {"name": "fallback_to_waterfall", "kind": "boolean", "default": True},
                {
                    "name": "tracking_error_budget",
                    "kind": "fraction",
                    "default": None,
                    "help": "Annualised ex-ante tracking error ceiling versus the benchmark, e.g. 0.015 for 1.5%. Needs a risk model. Where it conflicts with a decarbonisation target, the budget binds and the shortfall is carried.",
                },
                {"name": "score_field", "kind": "metric_field", "default": None, "help": "method='max_score' only: the field whose index-weighted value is maximised."},
                {"name": "min_risk_coverage", "kind": "fraction", "default": 0.98, "help": "Minimum share of index weight the risk model must cover before a budget is trusted."},
            ],
            "methods": [
                {"name": "waterfall", "label": "Deterministic waterfall", "needs_solver": False, "needs_risk_model": False},
                {"name": "least_squares", "label": "Least-squares projection", "needs_solver": True, "needs_risk_model": False},
                {"name": "min_tracking_error", "label": "Minimum tracking error", "needs_solver": True, "needs_risk_model": True},
                {"name": "max_score", "label": "Maximise a score under a TE budget", "needs_solver": True, "needs_risk_model": True},
            ],
            "risk_model": {
                "help": "The covariance behind a tracking-error budget. The estimators need only a returns panel; 'supplied' is the licensed path, where a vendor factor model is handed to the engine directly.",
                "params": [
                    {"name": "source", "kind": "enum", "options": ["ledoit_wolf", "sample", "factor", "supplied"], "default": "ledoit_wolf"},
                    {"name": "lookback_periods", "kind": "integer", "default": 260},
                    {"name": "min_observations", "kind": "integer", "default": 60},
                    {"name": "periods_per_year", "kind": "number", "default": 252.0, "help": "252 daily, 52 weekly, 12 monthly."},
                    {"name": "factor_fields", "kind": "field_list", "default": [], "help": "source='factor' only."},
                ],
            },
            "available": _optimizer_available(),
        },
        "trajectory": {
            "help": "The path-dependent layer. Two reductions bind at once: the trajectory decays geometrically from a fixed base, the universe-relative floor moves with the investable universe. Whichever is tighter binds, and the engine records which.",
            "params": [
                {"name": "enabled", "kind": "boolean", "default": False},
                {"name": "metric_field", "kind": "metric_field", "default": "ghg_intensity"},
                {"name": "annual_reduction_rate", "kind": "fraction", "default": 0.07},
                {"name": "universe_reduction_pct", "kind": "fraction", "default": None, "help": "0.30 for an EU CTB, 0.50 for an EU PAB."},
                {"name": "base_date", "kind": "date", "default": None, "help": "Empty means the first review becomes the base."},
                {"name": "compensate_missed_targets", "kind": "boolean", "default": True, "help": "Article 8: a missed year is owed and tightens the next target."},
            ],
        },
        "presets": [
            {"name": name, "label": preset["label"], "description": preset["description"]}
            for name, preset in sorted(PRESETS.items())
        ],
        "screen_bundles": [
            {"name": "eu_pab_exclusions", "label": "EU PAB exclusions", "description": "Norms, controversial weapons, tobacco, plus the coal / oil / gas / high-intensity-power revenue thresholds."},
            {"name": "eu_ctb_exclusions", "label": "EU CTB exclusions", "description": "Norms, controversial weapons and tobacco only -- a CTB carries no fossil revenue exclusions."},
            {"name": "size_and_liquidity", "label": "Size & liquidity floors", "description": "Minimum free-float market cap and 3-month average daily value."},
            {"name": "thematic", "label": "Thematic relevance", "description": "Relevance threshold plus a classification sanity overlay."},
        ],
    }
