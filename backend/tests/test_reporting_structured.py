import pytest

from arp.reporting.structured import parse_deltas, parse_flow, parse_meters, parse_quadrants, parse_tree, tree_svg


def test_parse_flow_marks_preferred_boxes():
    stages = parse_flow(["Retrieve :: 8 passages", "Answer :: *Yes/No/NA :: quotes"])
    assert [s.title for s in stages] == ["Retrieve", "Answer"]
    assert stages[1].boxes == [("Yes/No/NA", True), ("quotes", False)]


@pytest.mark.parametrize("items", [["Only one :: box"], ["No boxes", "Two :: b"], ["A :: 1 :: 2 :: 3 :: 4", "B :: b"]])
def test_parse_flow_rejects_bad_items(items):
    with pytest.raises(ValueError, match="flow"):
        parse_flow(items)


def test_parse_meters():
    assert parse_meters(["Disclosure :: 54%", "Science :: 46.5 %"]) == [("Disclosure", 54.0), ("Science", 46.5)]


@pytest.mark.parametrize("item", ["Disclosure 54%", "Disclosure :: lots", "Disclosure :: 140%"])
def test_parse_meters_rejects_bad_items(item):
    with pytest.raises(ValueError, match="meter"):
        parse_meters([item])


def test_parse_quadrants():
    q = parse_quadrants([f"T{i} :: sub :: text :: {s}" for i, s in enumerate(["low", "high", "mid", "neutral"])])
    assert q[1] == ("T1", "sub", "text", "high")


@pytest.mark.parametrize("items", [["A :: b :: c :: high"] * 3, ["A :: b :: c :: teal"] * 4, ["A :: b :: high"] * 4])
def test_parse_quadrants_rejects_bad_items(items):
    with pytest.raises(ValueError, match="quadrant"):
        parse_quadrants(items)


def test_parse_deltas():
    assert parse_deltas(["+11 :: points ahead", "−1 :: point"]) == [("+11", "points ahead"), ("−1", "point")]


@pytest.mark.parametrize("item", ["eleven :: points", "+11"])
def test_parse_deltas_rejects_bad_items(item):
    with pytest.raises(ValueError, match="delta"):
        parse_deltas([item])


_TREE = ["q1 :: Quote found? :: q2 :: bad", "q2 :: Verifier agrees? :: ok :: flag",
         "ok :: =Accepted :: high", "flag :: =Flagged :: low", "bad :: =Review queue :: mid"]


def test_parse_tree_builds_yes_no_branches():
    root = parse_tree(_TREE)
    assert root.text == "Quote found?" and root.yes.text == "Verifier agrees?" and root.no.status == "mid"
    assert root.yes.yes.outcome and root.yes.yes.text == "Accepted"


def _chain(depth):
    items = [f"q{i} :: Q{i}? :: q{i + 1} :: o{i}" for i in range(depth)]
    return items + [f"q{depth} :: =End :: high"] + [f"o{i} :: =Out {i} :: low" for i in range(depth)]


def test_parse_tree_depth_limit():
    assert parse_tree(_chain(4))
    with pytest.raises(ValueError, match="deeper than 4"):
        parse_tree(_chain(5))


@pytest.mark.parametrize("items, msg", [
    (["q1 :: Q? :: q2 :: nope", "q2 :: =A :: high"], "unknown node 'nope'"),
    (["q1 :: Q? :: q1 :: a", "a :: =A :: high"], "reached twice"),
    (["q1 :: Q? :: a :: b", "a :: =A :: blue", "b :: =B :: low"], "status"),
    (["q1 :: Q? :: a :: b", "a :: =A :: high", "b :: =B :: low", "c :: =C :: low"], "never reached"),
])
def test_parse_tree_rejects_bad_trees(items, msg):
    with pytest.raises(ValueError, match=msg):
        parse_tree(items)


def test_tree_svg_draws_boxes_connectors_and_labels():
    svg = tree_svg(parse_tree(_TREE), 1728, 543)
    assert svg.count("<rect") == 5 and svg.count(">Yes<") == 2 and svg.count(">No<") == 2
    assert "var(--status-high)" in svg and "#" not in svg.replace("&#", "")  # colours come from the tokens only


def test_tree_svg_rejects_text_that_does_not_fit():
    with pytest.raises(ValueError, match="too long"):
        tree_svg(parse_tree(["q1 :: " + "word " * 40 + ":: a :: b", "a :: =A :: high", "b :: =B :: low"]), 1728, 543)
