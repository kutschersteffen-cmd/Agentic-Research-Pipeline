from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from arp.schemas.common import new_id, now_iso

ColumnType = Literal["numeric", "ordinal", "boolean", "categorical", "identifier", "text"]
ColumnRole = Literal["label", "reference", "size", "gate", "criterion", "segment", "excluded"]
Direction = Literal["higher", "lower"]
NormMethod = Literal["percentile", "minmax", "zscore"]
MissingPolicy = Literal["renormalise", "neutral", "mean", "penalise"]
WeightPreset = Literal["balanced", "equal", "entropy", "manual"]
CutMode = Literal["quantile", "breaks", "absolute"]
GateOp = Literal["is", "isnot", "lt", "gt", "eq"]
GateOutcome = Literal["exclude", "demote", "flag"]
EntityStatus = Literal["scored", "excluded", "insufficient"]
AuditOrigin = Literal["derived", "human"]
ScoringMode = Literal["relative", "levels"]
RULE_NODE_TYPES = frozenset({"inputNode", "outputNode", "expressionNode", "decisionTableNode", "switchNode"})


def check_rule_graph(graph: dict[str, Any] | None) -> dict[str, Any] | None:
    """A rule graph arrives inline from the UI, so this is a trust boundary.
    Only declarative nodes are allowed: function nodes run JavaScript and
    decision nodes load other graphs, and formulas and conditions need
    neither."""
    if graph is None:
        return None
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not isinstance(graph.get("edges", []), list):
        raise ValueError("rule_graph must be a JDM graph with `nodes` and `edges` lists.")
    bad = sorted({str(n.get("type")) if isinstance(n, dict) else "?" for n in nodes if not isinstance(n, dict) or n.get("type") not in RULE_NODE_TYPES})
    if bad:
        raise ValueError(
            f"rule_graph node types not allowed: {', '.join(bad)}. "
            f"Use {', '.join(sorted(RULE_NODE_TYPES))} -- a framework holds formulas and conditions, not code."
        )
    return graph


class ColumnStats(BaseModel):
    """Quantile summary of a numeric/ordinal column. `true_share` is the
    boolean analogue -- both are what the UI's profile table renders and
    what `breaks` cut-point derivation works from."""

    count: int = 0
    min: float | None = None
    p5: float | None = None
    q1: float | None = None
    median: float | None = None
    q3: float | None = None
    p95: float | None = None
    max: float | None = None
    mean: float | None = None
    sd: float | None = None
    true_share: float | None = None


class ColumnProfile(BaseModel):
    """What a column *is*, derived from its values rather than its header.
    A header can lie (or be in another language); the values cannot."""

    name: str
    type: ColumnType
    coverage: float = Field(ge=0.0, le=1.0, description="Share of rows carrying a non-blank value.")
    unique: int = 0
    spread: bool = Field(default=False, description="False when every present value is identical -- no discriminating power.")
    decimal_comma: bool = Field(default=False, description="Numeric locale detected from the values (German/EU exports).")
    stats: ColumnStats | None = None
    levels: list[str] = Field(default_factory=list, description="Distinct values, for categorical/text columns (capped).")


class RoleProposal(BaseModel):
    """A proposed job and direction for one column, with the reason and --
    the field that matters -- whether the proposal is a guess worth
    checking. A wrong direction silently inverts a ranking, so an
    unconfident direction is surfaced rather than quietly applied."""

    column: str
    role: ColumnRole
    role_reason: str
    direction: Direction
    direction_reason: str
    needs_check: bool = False


class Dimension(BaseModel):
    """A group of criteria that measure the same underlying thing. The
    whole point of grouping is that a dimension's weight is shared by its
    members, so three ways of saying the same thing don't earn three
    times the weight."""

    id: str
    name: str
    weight: float = Field(default=1.0, ge=0.0)
    derived_from: list[str] = Field(default_factory=list, description="Columns the grouping was derived over.")


class Criterion(BaseModel):
    column: str
    dimension_id: str
    weight: float = Field(default=1.0, ge=0.0, description="Relative share of its dimension's weight. 0 parks it without deleting it.")
    enabled: bool = True
    direction: Direction = "higher"


class LevelRule(BaseModel):
    """One cell of a criterion's level grid: the level a company gets when
    `when` holds for its row. A ZEN expression over the table's columns
    (by name or slug), e.g. `target_coverage_pct >= 65 and net_zero_target`."""

    level: int
    when: str
    note: str = ""


class LevelCriterion(BaseModel):
    """A criterion scored on the framework's fixed scale, from the company's
    own data only. Rules are tried in order and the first that holds sets
    the level; a row none of them fits gets `otherwise`, or no level at all
    (missing, which the sufficiency gate then counts)."""

    id: str = Field(default_factory=lambda: new_id("crit"))
    name: str
    dimension_id: str = Field(description="The cluster this criterion belongs to.")
    weight: float = Field(default=1.0, ge=0.0, description="Relative share of its cluster's weight.")
    enabled: bool = True
    rules: list[LevelRule] = Field(default_factory=list)
    otherwise: int | None = None
    otherwise_on_blank: bool = Field(
        default=True,
        description="Whether `otherwise` also applies when a rule could not be decided because a value it reads is "
        "blank. False leaves such a row without a level, so missing data counts against coverage instead of earning "
        "the default; a value that is there but fits no rule still gets `otherwise`.",
    )
    hint: str = Field(default="", description="What the criterion asks, shown to reviewers next to the level.")


class GateRule(BaseModel):
    """A rule evaluated *before* the score exists. A knockout is a
    decision, not a deduction -- an excluded entity never reaches the
    average, where a strong score elsewhere could dilute it."""

    id: str = Field(default_factory=lambda: new_id("gate"))
    column: str
    op: GateOp = "is"
    value: str = "Yes"
    outcome: GateOutcome = "demote"


class VetoRule(BaseModel):
    """A floor under every dimension: one strong dimension shouldn't carry
    an entity that fails elsewhere. Applied only to dimensions measured by
    `min_criteria` or more criteria, so a single yes/no answer cannot
    demote an entity on its own."""

    enabled: bool = True
    min_score: float = Field(default=30.0, ge=0.0, le=100.0)
    min_criteria: int = Field(default=2, ge=1)


class TierDefinition(BaseModel):
    rank: int = Field(ge=1, description="1 is the best band.")
    name: str
    action: str = ""


class MechanismConfig(BaseModel):
    """The versioned, ratifiable artefact: everything needed to turn a
    table into a decision, and nothing about any particular table's
    contents. Derivation and application are separate (see
    arp.decision.mechanism) precisely so a ratified config can be applied
    to next quarter's data unchanged.
    """

    framework_id: str = Field(default_factory=lambda: new_id("fw"))
    version: int = 1
    name: str = "Untitled framework"
    notes: str = ""
    ratified: bool = False
    ratified_at: str | None = None
    ratified_by: str | None = None
    created_at: str = Field(default_factory=now_iso)

    mode: ScoringMode = Field(
        default="relative",
        description="relative: each criterion is normalised against the other entities in the table. levels: each "
        "criterion gets a level on a fixed scale from rules over the entity's own data, and cluster and total scores "
        "are weighted averages on that scale -- an entity's score does not move when its peers change.",
    )
    level_min: int = Field(default=1, description="levels mode: the lowest level on the scale.")
    level_max: int = Field(default=7, description="levels mode: the highest level on the scale.")
    level_criteria: list[LevelCriterion] = Field(
        default_factory=list, description="levels mode: the criteria, each with its level grid. Clusters are `dimensions`."
    )

    norm: NormMethod = "percentile"
    winsor_pct: float = Field(default=5.0, ge=0.0, le=20.0)
    missing: MissingPolicy = "renormalise"
    weighting: WeightPreset = "balanced"
    min_coverage_pct: float = Field(default=60.0, ge=0.0, le=100.0)

    normalise_within: str | None = Field(
        default=None,
        description="Column whose levels form peer cohorts. When set, every criterion is normalised inside its "
        "cohort instead of across the whole table -- an emissions-intensity percentile computed across utilities "
        "and software companies together is close to meaningless, and whole-table normalisation is the default "
        "that produces it.",
    )
    min_cohort_size: int = Field(
        default=5,
        ge=2,
        description="Cohorts smaller than this fall back to whole-table normalisation: a percentile rank over "
        "three peers is noise dressed as a score.",
    )

    require_grounded_coverage: bool = Field(
        default=False,
        description="When the dataset carries per-cell confidence (any table built from an extraction run does), "
        "the sufficiency gate keys off grounded weight covered rather than plain weight covered -- so a score "
        "resting on unverified values is routed to review instead of published.",
    )
    grounded_confidence_min: float = Field(default=0.8, ge=0.0, le=1.0)

    dimensions: list[Dimension] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)
    gates: list[GateRule] = Field(default_factory=list)

    cut_mode: CutMode = "quantile"
    pinned_cuts: list[float] | None = Field(
        default=None,
        description="Explicit cut-points that survive a re-run against different data. The prototype wrote derived "
        "cuts back into the saved config on every recompute, so a 'saved' framework silently carried whatever "
        "dataset was last loaded; pinned and derived are separate here for exactly that reason.",
    )
    veto: VetoRule = Field(default_factory=VetoRule)
    # No default actions: whether Tier 1 (the highest scores) is the one to
    # act on depends on how the criteria are set up, which only a person knows.
    tiers: list[TierDefinition] = Field(default_factory=lambda: [TierDefinition(rank=r, name=f"Tier {r}") for r in range(1, 5)])

    label_column: str | None = None
    size_column: str | None = None
    segment_column: str | None = None

    source_columns: list[str] = Field(
        default_factory=list,
        description="The columns of the table this framework was derived on. A column the framework uses that is "
        "not in here came from its rule graph, so a template is checked against another table (or an extraction "
        "schema before its run exists) only for the columns that table has to supply. See arp.decision.templates.",
    )

    cluster_threshold: float = Field(
        default=0.72,
        ge=0.0,
        le=1.0,
        description="Rank-correlation floor for grouping two criteria into one dimension, under complete linkage. "
        "A framework field rather than a constant because it is a judgement call -- but two frameworks with "
        "different thresholds are not directly comparable, which the audit log says explicitly.",
    )

    rule_graph: dict[str, Any] | None = Field(
        default=None,
        description="A GoRules JSON Decision Model evaluated once per row before scoring. Every output key that is "
        "not already a column becomes a calculated column -- a formula (capex / revenue * 100) or an AND/OR "
        "condition -- which criteria and gates then use like any other column. See arp.decision.rules.",
    )

    tier_graph: dict[str, Any] | None = Field(
        default=None,
        description="A GoRules JSON Decision Model evaluated per scored entity after the score band is drawn. When set "
        "it replaces the gates and the dimension floor: it sees the entity's band, score, rank, coverage and columns "
        "and must output `tier` (1..number of tiers), optionally `exclude` and `note`. See arp.decision.rules.",
    )

    @field_validator("rule_graph", "tier_graph")
    @classmethod
    def _declarative_rules_only(cls, graph: dict[str, Any] | None) -> dict[str, Any] | None:
        return check_rule_graph(graph)

    @model_validator(mode="after")
    def _levels_on_the_scale(self) -> MechanismConfig:
        """A level grid is a trust boundary like a rule graph: it arrives inline
        from the UI or a template file. Levels must sit on the scale and every
        condition must parse, so a typo is refused on save rather than
        quietly matching nothing on every row."""
        if self.level_min >= self.level_max:
            raise ValueError("level_min must be below level_max.")
        import zen

        for criterion in self.level_criteria:
            levels = [r.level for r in criterion.rules] + ([criterion.otherwise] if criterion.otherwise is not None else [])
            off = [lv for lv in levels if not self.level_min <= lv <= self.level_max]
            if off:
                raise ValueError(f"{criterion.name}: levels {off} are outside {self.level_min}-{self.level_max}.")
            for rule in criterion.rules:
                # An empty condition is a rule not written yet: it is skipped, not refused.
                error = zen.validate_expression(rule.when) if rule.when.strip() else None
                if error:
                    raise ValueError(f"{criterion.name}, level {rule.level}: {error.get('source', error)}")
        return self


class AuditEntry(BaseModel):
    """One line of the derivation trail. `origin` is what lets a reviewer
    answer the question this whole layer exists to answer: which rules
    came from the data, and which came from a person."""

    stage: str
    item: str
    decision: str
    why: str
    needs_check: bool = False
    origin: AuditOrigin = "derived"
    at: str = Field(default_factory=now_iso)
    by: str | None = None


class LevelOverride(BaseModel):
    """A reviewer setting one criterion's level for one entity by hand, in
    levels mode. The rules' own level stays on the result beside it
    (CriterionContribution.overridden_from), and the override is audited."""

    entity_key: str = Field(min_length=1)
    criterion_id: str = Field(min_length=1)
    level: int
    reason: str = Field(min_length=3, description="Why the rules' level is wrong for this entity; shown to anyone reading the score.")
    reviewer: str = Field(min_length=1)
    at: str = Field(default_factory=now_iso)


class CriterionContribution(BaseModel):
    column: str
    normalised: float | None = None
    weight: float = 0.0
    contribution: float = 0.0
    imputed: bool = False
    low_confidence: bool = False
    # Levels mode: which criterion this is, and, when a reviewer overrode
    # it, the level the rules gave and the override itself.
    criterion_id: str | None = None
    overridden_from: float | None = None
    override: LevelOverride | None = None


class EntityDecision(BaseModel):
    entity_key: str
    name: str
    segment: str | None = None
    cohort: str | None = None

    score: float | None = None
    coverage: float = 0.0
    grounded_coverage: float | None = None

    status: EntityStatus = "scored"
    tier: int | None = None
    tier_name: str | None = None
    tier_action: str | None = None
    notes: list[str] = Field(default_factory=list)

    rank: int | None = None
    rank_min: int | None = None
    rank_max: int | None = None

    size: float | None = None
    leverage: float | None = Field(
        default=None,
        description="size * (100 - score) / 100 -- position size times the gap to a perfect score. The ordering a "
        "stewardship team actually wants: where does engagement move the most.",
    )
    leverage_rank: int | None = None

    dimension_scores: dict[str, float | None] = Field(default_factory=dict)
    contributions: list[CriterionContribution] = Field(default_factory=list)


class TierSummary(BaseModel):
    rank: int
    name: str
    action: str = ""
    count: int = 0
    size_total: float | None = None


class HistogramBin(BaseModel):
    lower: float
    upper: float
    count: int


class DecisionResult(BaseModel):
    """The output of applying one framework version to one dataset."""

    framework_id: str
    framework_version: int
    dataset_id: str | None = None
    computed_at: str = Field(default_factory=now_iso)

    norm: NormMethod = "percentile"
    effective_cuts: list[float] = Field(default_factory=list)
    cuts_origin: CutMode = "quantile"
    effective_weights: dict[str, float] = Field(default_factory=dict)

    entities: list[EntityDecision] = Field(default_factory=list)
    tier_summary: list[TierSummary] = Field(default_factory=list)
    histogram: list[HistogramBin] = Field(default_factory=list)
    scored_count: int = 0
    excluded_count: int = 0
    insufficient_count: int = 0
    audit: list[AuditEntry] = Field(default_factory=list)
    tier_inputs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="What a tier graph sees for the first rows (band, score, rank, columns...) -- the browser "
        "evaluates the tier graph against these while it is being edited.",
    )


class TippingPoint(BaseModel):
    """How far one dimension's weight must move before an entity changes
    tier. Converts 'the framework says Tier 1' into 'the framework says
    Tier 1, and it takes a 14-point weight change to say otherwise'."""

    dimension_id: str
    dimension_name: str
    current_weight_pct: float
    flip_weight_pct: float | None = None
    delta_pct: float | None = None
    new_tier: int | None = None
    robust: bool = Field(default=True, description="True when no weight in the searched range changes the tier.")


class EntitySensitivity(BaseModel):
    entity_key: str
    name: str
    tier: int | None = None
    score: float | None = None
    tipping_points: list[TippingPoint] = Field(default_factory=list)
    min_delta_pct: float | None = Field(default=None, description="The smallest weight change that flips the tier.")


class EntityMovement(BaseModel):
    entity_key: str
    name: str
    tier_before: int | None = None
    tier_after: int | None = None
    tier_delta: int | None = Field(default=None, description="Negative is an improvement: a lower tier number is better.")
    score_before: float | None = None
    score_after: float | None = None
    score_delta: float | None = None
    rank_before: int | None = None
    rank_after: int | None = None
    rank_delta: int | None = None
    status_before: EntityStatus | None = None
    status_after: EntityStatus | None = None
    drivers: list[str] = Field(default_factory=list, description="Criteria whose contribution moved most, largest first.")


class DecisionComparison(BaseModel):
    """The same framework applied to two snapshots. This is the question
    the stewardship module exists to answer -- did anything actually move
    -- and it is only meaningful with the framework version pinned, which
    is why both are recorded here."""

    framework_id: str
    framework_version: int
    label_before: str
    label_after: str
    improved: int = 0
    worsened: int = 0
    unchanged: int = 0
    entered: int = 0
    left: int = 0
    movements: list[EntityMovement] = Field(default_factory=list)
    comparable: bool = True
    incomparable_reason: str | None = None
    caveat: str | None = Field(
        default=None,
        description="A limitation of the comparison that does not invalidate it -- chiefly that a rank-based "
        "normalisation can only show movement relative to the field, never absolute improvement.",
    )
    cut_points: list[float] = Field(default_factory=list, description="The cut-points the later snapshot was tiered on.")
    cuts_moved: str | None = Field(
        default=None,
        description="Set when the two snapshots were tiered on different cut-points, so a tier can change on an "
        "unchanged score. The studio and CLI hold the earlier snapshot's cuts, which leaves this empty.",
    )


class PublishedRow(BaseModel):
    entity_id: str
    name: str
    score: float | None = None
    tier: int | None = None
    tier_name: str | None = None
    rank: int | None = None
    rank_min: int | None = None
    rank_max: int | None = None
    status: EntityStatus = "scored"


class PublishedDecision(BaseModel):
    """A ratified framework's result on one dataset, frozen and signed so
    other functions can read it. Stewardship coverage rules and index
    construction see it as company fields (`decision.<framework_id>.tier`
    etc.); neither ever reads a live, re-scorable result."""

    snapshot_id: str = Field(default_factory=lambda: new_id("pub"))
    framework_id: str
    framework_version: int
    framework_name: str
    dataset_id: str
    dataset_name: str
    as_of: str | None = None
    id_column: str
    published_by: str
    published_at: str = Field(default_factory=now_iso)
    note: str = ""
    rows: list[PublishedRow] = Field(default_factory=list)
