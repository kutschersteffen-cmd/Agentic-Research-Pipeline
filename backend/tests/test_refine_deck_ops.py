from arp.refine.deck_ops import apply_deck_ops
from arp.schemas.reporting import ChartSpec, ColumnKind, DatasetColumn, Deck, QuantitativeDataset, SlideContent

DS = QuantitativeDataset(
    dataset_id="d1", name="D", columns=[DatasetColumn(name="cat", kind=ColumnKind.CATEGORY), DatasetColumn(name="v")],
    rows=[{"cat": "a", "v": 5}, {"cat": "b", "v": 8}],
)
ONE_ROW = QuantitativeDataset(dataset_id="d2", name="E", columns=DS.columns, rows=[{"cat": "a", "v": 5}])


def _deck(n=3, chart_dataset="d1", chart_type="line"):
    slides = [SlideContent(headline=f"S{i}", layout="bullets", variant="three", slots={"items": ["x"]}) for i in range(1, n + 1)]
    slides[1] = SlideContent(
        headline="S2", layout="two_column", variant="text_chart", slots={"text": "old"},
        chart=ChartSpec(dataset_id=chart_dataset, chart_type=chart_type, category_column="cat", value_columns=["v"]),
    )
    return Deck(title="T", slides=slides)


def _ops(deck, ops, ds=(DS, ONE_ROW), findings=""):
    return apply_deck_ops(deck, ops, list(ds), findings)


def test_set_text():
    deck = _deck()
    out, res = _ops(deck, [{"op": "set_text", "slide": 2, "slot": "text", "text": "Net zero by 2040"}])
    assert out.slides[1].slots["text"] == "Net zero by 2040" and deck.slides[1].slots["text"] == "old"
    assert res["changed"] == [2] and res["not_changed"] == []


def test_unknown_slot_skipped_others_apply():
    out, res = _ops(_deck(), [{"op": "set_text", "slide": 2, "slot": "sidebar", "text": "x"}, {"op": "set_headline", "slide": 2, "text": "New"}])
    assert out.slides[1].headline == "New"
    assert res["not_changed"] == [{"id": 2, "reason": "no such slot"}] and res["changed"] == [2]


def test_unknown_variant():
    deck = _deck()
    out, res = _ops(deck, [{"op": "set_variant", "slide": 2, "variant": "nonexistent"}])
    assert out == deck and res == {"changed": [], "not_changed": [{"id": 2, "reason": "no such variant"}], "check_figures": []}


def test_set_variant_ok():
    out, res = _ops(_deck(), [{"op": "set_variant", "slide": 2, "variant": "text_text"}])
    assert out.slides[1].variant == "text_text" and res["changed"] == [2]


def test_set_chart_type_keeps_columns():
    out, res = _ops(_deck(), [{"op": "set_chart_type", "slide": 2, "chart_type": "column"}])
    c = out.slides[1].chart
    assert (c.chart_type, c.dataset_id, c.category_column, c.value_columns) == ("column", "d1", "cat", ["v"]) and res["changed"] == [2]


def test_move_then_delete_start_positions():
    out, res = _ops(_deck(4), [{"op": "move_slide", "slide": 4, "to": 1}, {"op": "delete_slide", "slide": 3}])
    assert [s.headline for s in out.slides] == ["S4", "S1", "S2"]
    assert res["changed"] == [1] and res["not_changed"] == []  # S4 moved; S3 deleted is reported nowhere


def test_move_to_is_live_position():
    out, _ = _ops(_deck(4), [{"op": "move_slide", "slide": 1, "to": 4}, {"op": "delete_slide", "slide": 2}])
    assert [s.headline for s in out.slides] == ["S3", "S4", "S1"]


def test_unbacked_figure_flagged_but_applied():
    out, res = _ops(_deck(), [{"op": "set_text", "slide": 2, "slot": "text", "text": "Emissions fell 73%"}])
    assert out.slides[1].slots["text"] == "Emissions fell 73%" and res["check_figures"] == [2]


def test_backed_figures_not_flagged():
    deck = _deck()
    deck.slides[1].slots["text"] = "up 12"
    _, res = _ops(deck, [{"op": "set_text", "slide": 2, "slot": "text", "text": "12 then 8 and 1,200 and 4.5"}], findings="1200 4.5")
    assert res["check_figures"] == []


def test_chart_type_that_does_not_fit():
    out, res = _ops(_deck(chart_dataset="d2"), [{"op": "set_chart_type", "slide": 2, "chart_type": "heatmap"}])
    assert out.slides[1].chart.chart_type == "line"
    assert res["not_changed"] == [{"id": 2, "reason": "chart type does not fit the data"}] and res["changed"] == []


def test_slide_out_of_range():
    _, res = _ops(_deck(), [{"op": "set_headline", "slide": 9, "text": "x"}, {"op": "delete_slide", "slide": 0}])
    assert res["not_changed"] == [{"id": 9, "reason": "no such slide"}, {"id": 0, "reason": "no such slide"}]


def test_set_text_without_slot():
    _, res = _ops(_deck(), [{"op": "set_text", "slide": 2, "text": "x"}, {"op": "set_variant", "slide": 2}, {"op": "set_headline", "slide": 2}])
    assert [r["reason"] for r in res["not_changed"]] == ["no such slot", "no such variant", "no text"]


def test_malformed_fields_are_skips():
    _, res = _ops(_deck(), [
        {"op": "set_variant", "slide": 2, "variant": ["x"]}, {"op": "set_chart_type", "slide": 2, "chart_type": {}},
        {"op": "set_text", "slide": 2, "slot": "text", "text": ["a"]}, {"op": "set_text", "slide": 1, "slot": "items", "text": "a"},
        {"op": "set_headline", "slide": 1, "text": ["a"]},
    ])
    assert [r["reason"] for r in res["not_changed"]] == ["no such variant", "chart type does not fit the data", "no text", "no text", "no text"]
    assert res["changed"] == []


def test_list_slot_takes_list():
    out, _ = _ops(_deck(), [{"op": "set_text", "slide": 1, "slot": "items", "text": ["a", "b"]}])
    assert out.slides[0].slots["items"] == ["a", "b"]


def test_bad_position_and_unknown_op_in_op_order():
    _, res = _ops(_deck(), [{"op": "frobnicate", "slide": 1}, {"op": "move_slide", "slide": 1, "to": 9}, {"op": "set_headline", "slide": 7, "text": "x"}])
    assert res["not_changed"] == [{"id": 1, "reason": "unknown op"}, {"id": 1, "reason": "no such position"}, {"id": 7, "reason": "no such slide"}]
