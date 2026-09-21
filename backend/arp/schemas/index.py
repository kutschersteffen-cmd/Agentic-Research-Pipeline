"""Schemas for index construction.

The shape of this module follows one idea: an index methodology is a
*composition of named rules*, not a bespoke script. Every stage of the
construction stack (screens -> selection -> weighting -> tilts ->
constraints -> trajectory) is a list or a choice of typed rules, so the UI
can offer them as pickable, combinable options and the whole composition
can be saved, versioned and diffed as one `IndexCalibration`.

See `docs/INDEX_METHODOLOGY_LANDSCAPE.md` for the survey of MSCI / ISS
STOXX / Solactive methodologies these rule types are distilled from, and
`docs/EQUITY_INDEX_CONSTRUCTION_PLAN.md` for where this sits in the build.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from arp.schemas.common import new_id, now_iso

# --------------------------------------------------------------------------
# Input: what the engine sees for one company on one selection date
# --------------------------------------------------------------------------

MissingPolicy = Literal["block", "fail", "pass"]
"""What a rule does when the field it tests is absent for a company.

`block` is the default everywhere and is the plan's "fail loud on data
quality" principle made operational: a missing free-float figure stops the
run rather than silently defaulting. `fail` (treat as screened out) and
`pass` (treat as eligible) are deliberate, recorded choices -- each one
shows up in the calibration diff and on the review's exception list.
"""


class IndexCandidate(BaseModel):
    """One company as the index engine sees it on one selection date.

    Numeric, boolean and categorical attributes are kept in three separate
    maps rather than as fixed fields so a methodology can screen or tilt on
    any data point the pipeline produces (ESG score, GHG intensity,
    thematic relevance, coal revenue share, LCT category, ISS Prime status)
    without a schema change -- and so the UI can offer exactly the fields
    that are actually populated.
    """

    company_id: str
    name: str
    sector: str | None = None
    country: str | None = None
    currency: str = "EUR"
    price: float = Field(gt=0, description="Close on the weight reference date, in `currency`.")
    fx_rate: float = Field(default=1.0, gt=0, description="To the index currency, on the weight reference date.")
    shares_outstanding: float = Field(gt=0)
    free_float_factor: float = Field(default=1.0, ge=0.0, le=1.0)
    metrics: dict[str, float] = Field(default_factory=dict, description='Numeric attributes, e.g. {"esg_score": 7.1, "ghg_intensity": 84.0}.')
    flags: dict[str, bool] = Field(default_factory=dict, description='Boolean attributes, e.g. {"norms_violation": False}.')
    categories: dict[str, str] = Field(default_factory=dict, description='Categorical attributes, e.g. {"lct_category": "solutions"}.')

    @property
    def float_mcap(self) -> float:
        """Free-float market cap in the index currency."""
        return self.price * self.shares_outstanding * self.free_float_factor * self.fx_rate

    def group_value(self, dimension: str) -> str:
        """Resolves a grouping dimension to a label, for group-wise
        selection, capping and tilt normalisation. Falls back to the
        categories map so a methodology can group on any classification the
        data carries, not only sector/country."""
        if dimension == "sector":
            return self.sector or "unclassified"
        if dimension == "country":
            return self.country or "unclassified"
        if dimension in ("none", "", "index"):
            return "__all__"
        return self.categories.get(dimension, "unclassified")


# --------------------------------------------------------------------------
# Stage 2 -- screens (ordered, composable, each one independently auditable)
# --------------------------------------------------------------------------


class _Rule(BaseModel):
    rule_id: str = Field(default_factory=lambda: new_id("rule"))
    label: str = Field(default="", description="Free-text name shown in the UI and on the committee pack.")
    enabled: bool = True


class MetricThresholdScreen(_Rule):
    """Keep companies whose numeric field sits inside [min_value, max_value].

    Covers size and liquidity floors, thematic relevance thresholds, and
    every revenue-involvement exclusion (a coal exclusion is
    `max_value=0.01` on a `coal_revenue_pct` field), which is why there is
    no separate involvement rule type.
    """

    type: Literal["metric_threshold"] = "metric_threshold"
    field: str
    min_value: float | None = None
    max_value: float | None = None
    missing: MissingPolicy = "block"

    @model_validator(mode="after")
    def _at_least_one_bound(self) -> MetricThresholdScreen:
        if self.min_value is None and self.max_value is None:
            raise ValueError("metric_threshold needs at least one of min_value / max_value")
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError("metric_threshold: min_value must not exceed max_value")
        return self


class FlagExclusionScreen(_Rule):
    """Exclude companies whose boolean field equals `exclude_when` --
    norms-based screens, controversial weapons, controversy flags."""

    type: Literal["flag_exclusion"] = "flag_exclusion"
    field: str
    exclude_when: bool = True
    missing: MissingPolicy = "block"


class CategoryScreen(_Rule):
    """Allow-list and/or deny-list on a categorical field. The allow-list
    form is the classification sanity overlay that stops an NLP-derived
    thematic score putting an unrelated industry in the index."""

    type: Literal["category_screen"] = "category_screen"
    field: str
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)
    missing: MissingPolicy = "block"

    @model_validator(mode="after")
    def _at_least_one_list(self) -> CategoryScreen:
        if not self.allow and not self.deny:
            raise ValueError("category_screen needs a non-empty allow or deny list")
        return self


ScreenRule = Annotated[
    MetricThresholdScreen | FlagExclusionScreen | CategoryScreen,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------
# Stage 3 -- selection (exactly one)
# --------------------------------------------------------------------------


class SelectAll(_Rule):
    """No selection step: everything that survives the screens is in. This
    is what an exclusion-only index (MSCI ESG Screened, STOXX ESG-X) uses."""

    type: Literal["select_all"] = "select_all"


class BestInClassCoverage(_Rule):
    """Rank within a group, then select down the ranking until coverage
    reaches `target_pct` of the group -- measured either by float market
    cap or by constituent count.

    One rule covers three published variants: MSCI ESG Leaders (50% of
    sector float cap), STOXX ESG Broad Market (80% of industry *count*) and
    MSCI Climate Action (50% of sector count). `buffer_pct` is the
    hysteresis band that keeps an incumbent in when its group is already
    within tolerance of the target, which is what stops the index churning
    at every review.
    """

    type: Literal["best_in_class_coverage"] = "best_in_class_coverage"
    score_field: str
    group_by: str = "sector"
    target_pct: float = Field(default=0.5, gt=0.0, le=1.0)
    basis: Literal["float_mcap", "count"] = "float_mcap"
    buffer_pct: float = Field(default=0.0, ge=0.0, lt=1.0, description="Tolerance around target_pct; incumbents inside the band are retained.")
    higher_is_better: bool = True
    missing: MissingPolicy = "block"


class AbsoluteThreshold(_Rule):
    """Select every company whose score clears a threshold -- optionally a
    different threshold per group, as ISS Prime status uses (C+ for most
    industries, B- for high-risk ones).

    Unlike a relative rule, an absolute one can leave a group empty, so the
    fallback is explicit rather than discovered in production.
    """

    type: Literal["absolute_threshold"] = "absolute_threshold"
    score_field: str
    threshold: float
    group_by: str = "sector"
    group_thresholds: dict[str, float] = Field(default_factory=dict, description="Per-group override of `threshold`.")
    higher_is_better: bool = True
    on_empty_group: Literal["leave_empty", "fallback_relative", "block"] = "leave_empty"
    fallback_target_pct: float = Field(default=0.25, gt=0.0, le=1.0, description="Coverage target used when on_empty_group='fallback_relative'.")
    missing: MissingPolicy = "block"


class TopN(_Rule):
    """Fixed-size index: the N best by score, ties broken by float market
    cap then company_id so the result is order-independent."""

    type: Literal["top_n"] = "top_n"
    score_field: str
    n: int = Field(gt=0)
    group_by: str = "none"
    higher_is_better: bool = True
    missing: MissingPolicy = "block"


SelectionRule = Annotated[
    SelectAll | BestInClassCoverage | AbsoluteThreshold | TopN,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------
# Stage 4 -- base weighting and tilts
# --------------------------------------------------------------------------


class BaseWeighting(BaseModel):
    """The starting weight before any tilt or constraint."""

    scheme: Literal["free_float_mcap", "equal", "metric", "inverse_metric"] = "free_float_mcap"
    field: str | None = Field(default=None, description="Required for the metric / inverse_metric schemes.")
    floor: float = Field(default=1e-9, gt=0, description="Applied to the metric before inversion, so a near-zero value cannot dominate.")

    @model_validator(mode="after")
    def _field_required(self) -> BaseWeighting:
        if self.scheme in ("metric", "inverse_metric") and not self.field:
            raise ValueError(f"BaseWeighting.scheme='{self.scheme}' requires `field`")
        return self


class MetricTilt(_Rule):
    """Multiply the base weight by a function of a numeric field.

    This is the closed-form over/underweight rule behind MSCI ESG Universal
    (`rating x trend x parent weight`), MSCI Climate Change (LCT score,
    normalised within its category) and MSCI-style thematic weighting
    (relevance x market cap).

    `floor` and `ceiling` are mandatory and defaulted deliberately: an
    unbounded tilt silently becomes an exclusion, which is a methodology
    change nobody approved.
    """

    type: Literal["metric_tilt"] = "metric_tilt"
    field: str
    normalisation: Literal["none", "max", "group_max", "rank_percentile", "zscore"] = "max"
    group_by: str = "none"
    floor: float = Field(default=0.5, gt=0.0)
    ceiling: float = Field(default=2.0, gt=0.0)
    higher_is_better: bool = True
    missing: MissingPolicy = "block"

    @model_validator(mode="after")
    def _bounds_ordered(self) -> MetricTilt:
        if self.floor > self.ceiling:
            raise ValueError("MetricTilt: floor must not exceed ceiling")
        return self


class BucketTilt(_Rule):
    """Multiply the base weight by a fixed factor per category value -- the
    most auditable tilt there is, because the whole rule is a table a
    committee can read."""

    type: Literal["bucket_tilt"] = "bucket_tilt"
    field: str
    multipliers: dict[str, float] = Field(default_factory=dict)
    default_multiplier: float = Field(default=1.0, gt=0.0)
    missing: MissingPolicy = "pass"

    @model_validator(mode="after")
    def _positive_multipliers(self) -> BucketTilt:
        for key, value in self.multipliers.items():
            if value <= 0:
                raise ValueError(f"BucketTilt multiplier for {key!r} must be > 0")
        return self


TiltRule = Annotated[MetricTilt | BucketTilt, Field(discriminator="type")]


# --------------------------------------------------------------------------
# Stage 5 -- constraints
# --------------------------------------------------------------------------


class GroupCap(BaseModel):
    dimension: str = "sector"
    max_weight: float = Field(gt=0.0, le=1.0)
    label: str = ""


class RiskModelSpec(BaseModel):
    """How the covariance behind a tracking-error budget is obtained.

    The estimators need only a returns panel; `supplied` is the licensed
    path, where a vendor factor model is handed to the engine directly.
    Nothing downstream distinguishes them, so the licence is a
    data-sourcing decision rather than an engineering one.
    """

    source: Literal["ledoit_wolf", "sample", "factor", "supplied"] = "ledoit_wolf"
    lookback_periods: int = Field(default=260, gt=0, description="Most recent periods used; earlier ones are dropped.")
    min_observations: int = Field(default=60, gt=1, description="Below this the model is refused rather than estimated badly.")
    periods_per_year: float = Field(default=252.0, gt=0, description="Annualisation factor: 252 for daily, 52 weekly, 12 monthly.")
    factor_fields: list[str] = Field(
        default_factory=list,
        description="source='factor' only. Numeric fields are standardised cross-sectionally; categorical fields become dummies.",
    )


class ConstraintSolver(BaseModel):
    """How the constraint set is satisfied.

    `waterfall` is the default and needs nothing installed: pin every
    breach at its cap, redistribute pro-rata, repeat. It is byte-identical
    everywhere and satisfies the constraints, but applies them in sequence
    and makes no claim about how far it moves the weights to do so.

    `least_squares` solves `min ||w - b||^2` over the whole constraint set
    as one convex programme (see `arp/index/optimize.py`), so every
    constraint binds simultaneously and the result is the *closest*
    feasible portfolio to what the methodology asked for. It needs the
    optional `optimize` extra, and the solver choice is part of the
    calibration precisely because it can move the last digits.

    `min_tracking_error` minimises ex-ante tracking error against the
    benchmark subject to the same constraints, and `max_score` maximises an
    index-weighted score subject to a tracking-error budget. Both need a
    risk model as well as the solver -- which is a data licence or an
    estimator, and the reason they sit behind `tracking_error_budget` and
    `risk_model` rather than being the default.
    """

    method: Literal["waterfall", "least_squares", "min_tracking_error", "max_score"] = "waterfall"
    solver: Literal["CLARABEL", "OSQP", "SCS"] = Field(
        default="CLARABEL", description="Pinned per calibration: a solver swap is a methodology change, not an implementation detail."
    )
    verify_tolerance: float = Field(
        default=1e-7,
        gt=0.0,
        description="Every constraint is re-checked in plain Python at this tolerance after the solve; a solver's own 'optimal' status is never taken as proof.",
    )
    fallback_to_waterfall: bool = Field(
        default=True,
        description="On solver failure or a failed verification, fall back to the waterfall and record an exception rather than failing the review.",
    )
    tracking_error_budget: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "PRECEDENCE: where a tracking-error budget and a decarbonisation target cannot both hold, the budget "
            "binds and the target is recorded as missed with its shortfall carried forward. A risk limit is treated "
            "as the harder of the two; a methodology that wants the opposite must widen the budget explicitly. "
            "Annualised ex-ante tracking error ceiling versus the benchmark, e.g. 0.015 for 1.5%. Needs a risk model. "
            "Applies as a constraint to every method except min_tracking_error, which minimises it instead."
        ),
    )
    score_field: str | None = Field(
        default=None, description="method='max_score' only: the numeric field whose index-weighted value is maximised."
    )
    risk_model: RiskModelSpec = Field(default_factory=RiskModelSpec)
    enforce_semicontinuous: bool = Field(
        default=False,
        description=(
            "Treat min_weight as the disjunction it really is -- a name is held at or above it, or not at all -- "
            "instead of pruning the smallest names. Needs integer variables."
        ),
    )
    mip_solver: Literal["SCIP", "HIGHS", "GUROBI", "MOSEK", "CPLEX"] = Field(
        default="SCIP",
        description="Backend for the integer problem. SCIP is the free one; the rest need a commercial licence. Pinned per calibration.",
    )
    mip_gap: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Optimality gap the integer solve must close. Left at 0 deliberately: any positive gap means the solver may "
            "return any incumbent within it, and which one it returns varies by version and machine."
        ),
    )
    mip_time_limit_seconds: float | None = Field(
        default=120.0,
        gt=0.0,
        description=(
            "Wall-clock ceiling on the integer solve. A truncated solve raises rather than returning its incumbent, so "
            "a slow machine produces a recorded failure instead of a different index."
        ),
    )
    tie_break_epsilon: float = Field(
        default=1e-8,
        ge=0.0,
        description=(
            "Integer problems routinely have several holdings that score identically, and which one a solver returns is "
            "arbitrary. A vanishing penalty on a fixed name ordering makes the choice a rule instead. Set 0 to disable."
        ),
    )
    min_risk_coverage: float = Field(
        default=0.98,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum share of index weight the risk model must cover before a tracking-error budget is trusted. "
            "Below it the budget is an understatement dressed up as a control, so the review says so."
        ),
    )

    @model_validator(mode="after")
    def _coherent(self) -> ConstraintSolver:
        if self.method == "max_score" and not self.score_field:
            raise ValueError("method='max_score' requires score_field")
        if self.method == "max_score" and self.tracking_error_budget is None:
            raise ValueError("method='max_score' requires tracking_error_budget -- an unbounded maximisation is not an index")
        if self.tracking_error_budget is not None and self.solver == "OSQP":
            # A tracking-error ceiling is a second-order cone constraint and
            # OSQP solves quadratic programmes with linear constraints only.
            # Caught here so a calibration cannot be saved in a state that
            # would fail opaquely inside the solver at review time.
            raise ValueError(
                "solver='OSQP' cannot express a tracking-error budget (a second-order cone constraint); "
                "use CLARABEL or SCS"
            )
        return self


class ConstraintSet(BaseModel):
    """Satisfied by the deterministic waterfall by default; optionally by a
    least-squares projection -- see `solver` and `arp/index/capping.py`."""

    single_name_cap: float | None = Field(default=None, gt=0.0, le=1.0)
    group_caps: list[GroupCap] = Field(default_factory=list)
    ucits_5_10_40: bool = Field(default=False, description="No issuer above 10%, and issuers above 5% summing to at most 40%.")
    min_weight: float | None = Field(
        default=None,
        ge=0.0,
        lt=1.0,
        description=(
            "Minimum weight for a held constituent. By default this is a prune-and-redistribute heuristic: names below "
            "the threshold are dropped. Set solver.enforce_semicontinuous to make it the real constraint "
            "(w = 0 or w >= min_weight), which needs integer variables."
        ),
    )
    max_constituents: int | None = Field(
        default=None, gt=0, description="Cardinality ceiling. Needs integer variables -- see solver.mip_solver."
    )
    min_constituents: int | None = Field(
        default=None, gt=0, description="Cardinality floor, e.g. a diversification commitment. Needs integer variables."
    )
    max_iterations: int = Field(default=200, gt=0)
    solver: ConstraintSolver = Field(default_factory=ConstraintSolver)


# --------------------------------------------------------------------------
# Stage 5b -- the path-dependent layer
# --------------------------------------------------------------------------


class DecarbonisationTrajectory(BaseModel):
    """The EU PAB/CTB-shaped constraint, and the only part of the stack
    whose result depends on prior reviews.

    Two reductions bind at once and one of them moves: `annual_reduction_rate`
    decays geometrically from a *fixed base*, while
    `universe_reduction_pct` is measured against the investable universe as
    it stands at *this* review. The engine takes whichever is tighter and
    records which one bound.

    `compensate_missed_targets` implements Article 8 of Regulation (EU)
    2020/1818: a year in which the target was missed is owed, and the
    shortfall is carried into the next review's target.
    """

    enabled: bool = False
    metric_field: str = "ghg_intensity"
    annual_reduction_rate: float = Field(default=0.07, ge=0.0, lt=1.0)
    base_date: str | None = Field(default=None, description="ISO date. None means the first review becomes the base.")
    universe_reduction_pct: float | None = Field(default=None, ge=0.0, lt=1.0, description="0.30 for an EU CTB, 0.50 for an EU PAB.")
    compensate_missed_targets: bool = True
    max_tilt_strength: float = Field(default=50.0, gt=0.0, description="Bisection bound on the exponential tilt that meets the target.")
    tolerance: float = Field(default=1e-6, gt=0.0)
    missing: MissingPolicy = "block"


class CalendarSpec(BaseModel):
    review_frequency: Literal["monthly", "quarterly", "semi_annual", "annual"] = "quarterly"
    selection_lag_days: int = Field(default=5, ge=0, description="Trading days between the selection date and the announcement.")
    base_level: float = Field(default=100.0, gt=0)


class RoundingPolicy(BaseModel):
    """Fixed precision applied at defined points, never incidentally through
    formatting -- one of the determinism requirements in the build plan."""

    weight_decimals: int = Field(default=10, ge=2, le=15)
    shares_decimals: int = Field(default=6, ge=0, le=12)
    level_decimals: int = Field(default=6, ge=2, le=12)


# --------------------------------------------------------------------------
# The composition, and the calibration that stores it
# --------------------------------------------------------------------------


class ConstructionSpec(BaseModel):
    """A complete, executable index methodology: the ordered composition of
    every rule above. This is the object the UI edits."""

    index_currency: str = "EUR"
    screens: list[ScreenRule] = Field(default_factory=list, description="Applied in order. Order matters and is part of the methodology.")
    selection: SelectionRule = Field(default_factory=SelectAll)
    base_weighting: BaseWeighting = Field(default_factory=BaseWeighting)
    tilts: list[TiltRule] = Field(default_factory=list, description="Applied in order, multiplicatively, onto the base weight.")
    constraints: ConstraintSet = Field(default_factory=ConstraintSet)
    trajectory: DecarbonisationTrajectory = Field(default_factory=DecarbonisationTrajectory)
    calendar: CalendarSpec = Field(default_factory=CalendarSpec)
    rounding: RoundingPolicy = Field(default_factory=RoundingPolicy)

    def content_hash(self) -> str:
        """SHA-256 over the resolved spec with rule ids and labels stripped.

        Two calibrations that differ only in a rule's generated id or its
        display label produce identical indices, so they hash identically --
        which makes the hash answer "would this change the numbers?" rather
        than "did anything at all change?".
        """
        payload = self.model_dump(mode="json")

        def strip(node: object) -> object:
            if isinstance(node, dict):
                return {k: strip(v) for k, v in sorted(node.items()) if k not in ("rule_id", "label")}
            if isinstance(node, list):
                return [strip(v) for v in node]
            return node

        return hashlib.sha256(json.dumps(strip(payload), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class IndexCalibration(BaseModel):
    """A saved, versioned, effective-dated construction spec.

    Versions are append-only, exactly like the taxonomy library: editing a
    calibration creates a new version rather than overwriting history, and
    `effective_from` means the engine resolves the version *in force on the
    review date* rather than the latest one -- otherwise today's parameters
    silently rewrite past reviews.
    """

    calibration_id: str = Field(default_factory=lambda: new_id("cal"))
    name: str
    version: int = 1
    based_on_version: int | None = None
    effective_from: str = Field(description="ISO date. The first review date this version governs.")
    effective_to: str | None = None
    approved_by: list[str] = Field(default_factory=list, description="Committee minute references, e.g. 'IC-2026-06-11'.")
    notes: str = ""
    created_at: str = Field(default_factory=now_iso)
    spec: ConstructionSpec

    @property
    def config_hash(self) -> str:
        return self.spec.content_hash()


# --------------------------------------------------------------------------
# Output: a review, its trace, and the state it carries forward
# --------------------------------------------------------------------------


class StageTrace(BaseModel):
    """One line of the construction funnel -- what a rule did, in numbers.

    This is simultaneously the UI's funnel view, the committee's evidence
    pack, and the input-data audit trail.
    """

    stage: str
    rule_type: str
    label: str
    candidates_in: int
    candidates_out: int
    dropped_sample: list[str] = Field(default_factory=list, description="Up to 10 company_ids dropped here, for spot-checking.")
    detail: dict[str, float | str | int] = Field(default_factory=dict)


class Constituent(BaseModel):
    company_id: str
    name: str
    sector: str | None = None
    country: str | None = None
    weight: float
    base_weight: float = Field(description="Before tilts, capping and the trajectory.")
    tilt_multiplier: float = 1.0
    capping_factor: float = Field(default=1.0, description="Final weight / weight before constraints, for this name.")
    price: float
    fx_rate: float = 1.0
    index_shares: float = 0.0
    metrics: dict[str, float] = Field(default_factory=dict)


class IndexState(BaseModel):
    """What this review must remember for the next one.

    The existence of this object is the whole reason a path-dependent
    methodology is more than a config flag: a review is
    `f(data, spec, state[t-1])`, not `f(data, spec)`.
    """

    index_id: str
    review_date: str
    base_date: str | None = None
    base_metric_value: float | None = Field(default=None, description="Weighted-average metric at the base date -- the anchor of the trajectory.")
    required_metric_value: float | None = None
    achieved_metric_value: float | None = None
    universe_metric_value: float | None = None
    shortfall_carry: float = Field(default=0.0, ge=0.0, description="Fractional shortfall owed to the next review under Article 8.")
    binding_constraint: Literal["none", "trajectory", "universe_relative"] = "none"
    divisor: float | None = None
    index_level: float | None = None
    prior_weights: dict[str, float] = Field(
        default_factory=dict, description="Target weights set at this review, before any price drift."
    )
    prior_members: list[str] = Field(default_factory=list)
    prior_index_shares: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Index shares fixed at this review. With prior_prices these let the next review reconstruct the *drifted* "
            "weights it is actually trading away from, which is what turnover has to be measured against."
        ),
    )
    prior_prices: dict[str, float] = Field(
        default_factory=dict,
        description="Price x FX in index currency at this review, so a name absent from the next universe carries its last price.",
    )


class ReviewDiagnostics(BaseModel):
    universe_size: int
    eligible_size: int
    selected_size: int
    final_size: int
    weighted_metrics: dict[str, float] = Field(default_factory=dict, description="Index-weighted average of every numeric field present.")
    universe_weighted_metrics: dict[str, float] = Field(default_factory=dict)
    effective_n: float = Field(description="1 / sum of squared weights -- concentration in intuitive units.")
    max_weight: float
    one_way_turnover: float | None = Field(default=None, description="Half the sum of absolute weight changes vs. the previous review.")
    capping_iterations: int = 0
    trajectory_iterations: int = 0
    tracking_error: float | None = Field(
        default=None, description="Annualised ex-ante tracking error versus the benchmark, when a risk model was supplied."
    )
    integer_constraints: bool = Field(default=False, description="Whether the weighting step used a mixed-integer programme.")


class ReviewResult(BaseModel):
    index_id: str
    review_date: str
    calibration_id: str | None = None
    calibration_version: int | None = None
    config_hash: str
    constituents: list[Constituent] = Field(default_factory=list)
    diagnostics: ReviewDiagnostics
    trace: list[StageTrace] = Field(default_factory=list)
    state: IndexState
    exceptions: list[str] = Field(default_factory=list, description="Every rule relaxation or data-quality override applied, in order.")
    created_at: str = Field(default_factory=now_iso)


class IndexLevelPoint(BaseModel):
    date: str
    level: float
    divisor: float
    market_cap: float
    constituents_priced: int
