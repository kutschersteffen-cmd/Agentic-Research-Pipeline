from arp.research.authority_taxonomy.extract import StatedRule
from arp.research.stock_inference.index_rules import map_rules
from arp.schemas.index import CategoryScreen, ConstructionSpec, MetricThresholdScreen, TopN


def _rule(quote, kind="eligibility"):
    return StatedRule(kind=kind, text=quote, quote=quote, source="m.txt")


def _default(spec, *exclude):
    """Every field but `exclude` equals ConstructionSpec()'s default (rule ids are random per instance)."""
    keep = set(ConstructionSpec.model_fields) - set(exclude)
    a, b = (x.model_dump(include=keep, exclude={"selection": {"rule_id"}}) for x in (spec, ConstructionSpec()))
    return a == b


def test_ac42_min_float_mcap():
    q = "Companies must have a minimum free-float market capitalisation of USD 500 million."
    out = map_rules([_rule(q)])
    spec = ConstructionSpec.model_validate(out.construction_spec.model_dump())
    s = spec.screens[0]
    assert isinstance(s, MetricThresholdScreen) and s.field == "float_mcap" and s.min_value == 500_000_000
    assert spec.index_currency == "USD" and out.currency == "USD"
    assert [(r.quote, r.source, r.mapped_to) for r in out.rules] == [(q, "m.txt", "screens[0].min_value")]
    assert _default(spec, "screens", "index_currency")


def test_ac43_single_name_cap():
    out = map_rules([_rule("No constituent may exceed 8 % of the index.", "caps")])
    assert out.construction_spec.constraints.single_name_cap == 0.08
    assert out.rules[0].mapped_to == "constraints.single_name_cap"
    assert _default(out.construction_spec, "constraints")
    assert out.currency is None


def test_ac44_semi_annual_not_annual():
    out = map_rules([_rule("The index is reviewed semi-annually.", "rebalance")])
    assert out.construction_spec.calendar.review_frequency == "semi_annual"
    assert out.rules[0].mapped_to == "calendar.review_frequency"


def test_review_frequency_forms():
    for text, want in [("Reviewed quarterly.", "quarterly"), ("The index is reviewed annually.", "annual"),
                       ("Rebalanced monthly.", "monthly"), ("Reviewed twice a year.", "semi_annual")]:
        assert map_rules([_rule(text)]).construction_spec.calendar.review_frequency == want, text


def test_ac45_unrecognised_rule_kept_unmapped():
    q = "The index committee may exclude any company at its discretion."
    out = map_rules([_rule(q)])
    assert [(r.text, r.quote, r.mapped_to) for r in out.rules] == [(q, q, None)]
    assert _default(out.construction_spec)


def test_adv_and_currency_from_first_monetary_rule():
    out = map_rules([
        _rule("A minimum three-month average daily traded value of EUR 2.5 million is required."),
        _rule("A minimum market capitalisation of USD 1 billion."),
    ])
    s0, s1 = out.construction_spec.screens
    assert (s0.field, s0.min_value, s1.field, s1.min_value) == ("adv_3m", 2_500_000, "float_mcap", 1_000_000_000)
    assert out.currency == out.construction_spec.index_currency == "EUR"
    assert [r.mapped_to for r in out.rules] == ["screens[0].min_value", "screens[1].min_value"]


def test_revenue_share_needs_a_number():
    out = map_rules([_rule("Companies must derive at least 50% of revenue from hydrogen."),
                     _rule("Companies must derive significant revenue from hydrogen.")])
    s = out.construction_spec.screens[0]
    assert (s.field, s.min_value) == ("relevance", 0.5)
    assert [r.mapped_to for r in out.rules] == ["screens[0].min_value", None]


def test_sector_exclusion():
    out = map_rules([_rule("Companies in the Financials and Real Estate sectors are excluded.")])
    s = out.construction_spec.screens[0]
    assert isinstance(s, CategoryScreen) and s.field == "sector" and s.deny == ["Financials", "Real Estate"]
    assert out.rules[0].mapped_to == "screens[0].deny"


def test_top_n_and_weighting_and_ucits():
    out = map_rules([
        _rule("The index selects the 25 largest companies by market capitalisation.", "selection"),
        _rule("Constituents are equally weighted.", "weighting"),
        _rule("Weights are capped according to the 5/10/40 rule.", "caps"),
    ])
    spec = out.construction_spec
    assert isinstance(spec.selection, TopN) and spec.selection.n == 25 and spec.selection.score_field == "float_mcap"
    assert spec.base_weighting.scheme == "equal"
    assert spec.constraints.ucits_5_10_40 is True
    assert [r.mapped_to for r in out.rules] == ["selection.n", "base_weighting.scheme", "constraints.ucits_5_10_40"]
    assert spec.screens == []


def test_market_cap_weighting():
    out = map_rules([_rule("The index is weighted by free-float market capitalisation.", "weighting")])
    assert out.construction_spec.base_weighting.scheme == "free_float_mcap"
    assert out.construction_spec.screens == []
    assert out.rules[0].mapped_to == "base_weighting.scheme"


def test_second_rule_for_same_field_unmapped():  # Review Focus 4
    out = map_rules([_rule("No constituent may exceed 8 % of the index.", "caps"),
                     _rule("No single stock may exceed 10 % of the index.", "caps")])
    assert out.construction_spec.constraints.single_name_cap == 0.08
    assert [r.mapped_to for r in out.rules] == ["constraints.single_name_cap", None]


def test_no_rules():
    out = map_rules([])
    assert out.rules == [] and out.currency is None
    assert _default(out.construction_spec)


def test_impossible_numbers_stay_unmapped():
    out = map_rules([_rule("No constituent may exceed 150 % of the index.", "caps"),
                     _rule("The index comprises 0 constituents.", "selection")])
    assert [r.mapped_to for r in out.rules] == [None, None]
    assert _default(out.construction_spec)
