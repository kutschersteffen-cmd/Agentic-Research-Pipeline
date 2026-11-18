"""Mermaid flowchart subset → `Flow` (spec house-deck-flowchart-slides, slice 1)."""

import pytest
from pydantic import ValidationError

from arp.reporting.mermaid_flow import MermaidError, parse_mermaid
from arp.schemas.reporting import SlideContent
from arp.schemas.visuals import Flow, FlowArrow, FlowStep

F1 = """flowchart LR
  %% sample review flow
  q2["Q2 results<br>ESEF filings"]:::team
  screen["Screen debt"]:::team
  engage["Engage boards"]:::steward
  plan{"Plan credible?"}:::steward
  add["Add position"]:::team
  log[("Decision log")]:::steward
  q2 --> screen
  screen -->|over 5.5x| engage
  engage --> plan
  plan -->|yes| add
  plan -- no --> log
  classDef team fill:#fff
  classDef steward fill:#eee
  class log stored
  class plan emphasis
"""


def test_f1_steps_actors_and_classes():
    flow = parse_mermaid(F1)
    assert flow.direction == "LR"
    assert [s.id for s in flow.steps] == ["q2", "screen", "engage", "plan", "add", "log"]
    assert [s.kind for s in flow.steps] == ["step", "step", "step", "decision", "step", "data"]
    assert flow.actors == ["team", "steward"]
    assert [s.actor for s in flow.steps] == ["team", "team", "steward", "steward", "team", "steward"]
    assert [s.stored for s in flow.steps] == [False] * 5 + [True]
    assert flow.emphasis == "plan"
    assert (flow.steps[0].label, flow.steps[0].tag) == ("Q2 results", "ESEF filings")
    assert flow.layout is None


def test_f1_arrows_in_order():
    flow = parse_mermaid(F1)
    assert [(a.source, a.target, a.label) for a in flow.arrows] == [
        ("q2", "screen", ""), ("screen", "engage", "over 5.5x"), ("engage", "plan", ""),
        ("plan", "add", "yes"), ("plan", "log", "no")]


def test_td_chain_labels_default_to_ids():
    flow = parse_mermaid("flowchart TD\n  a --> b --> c")
    assert flow.direction == "TB"
    assert [(s.id, s.label) for s in flow.steps] == [("a", "a"), ("b", "b"), ("c", "c")]
    assert [(a.source, a.target) for a in flow.arrows] == [("a", "b"), ("b", "c")]


def test_text_given_later_and_other_accepted_forms():
    flow = parse_mermaid("graph LR;\n  a --> b;\n  b[Later]\n  %%{init: {}}%%\n\n  c([Round]) --> d(Soft)\n  b --> c")
    assert [(s.id, s.label, s.kind) for s in flow.steps] == [
        ("a", "a", "step"), ("b", "Later", "step"), ("c", "Round", "step"), ("d", "Soft", "step")]
    flow = parse_mermaid("flowchart LR\n  a[One<br/>Tag A] --> b[Two<br />Tag B]")
    assert [(s.label, s.tag) for s in flow.steps] == [("One", "Tag A"), ("Two", "Tag B")]


HEADER_ERRORS = [
    ("sequenceDiagram\n  a->>b: hi", "line 1: only flowcharts are supported, not sequenceDiagram"),
    ("hello\n  a --> b", 'line 1: start with "flowchart LR" or "flowchart TB"'),
    ("flowchart\n  a --> b", 'line 1: start with "flowchart LR" or "flowchart TB"'),
    ("\n%% hi\nflowchart BT\n  a --> b", "line 3: direction BT is not supported; use LR or TB"),
    ("flowchart RL\n  a --> b", "line 1: direction RL is not supported; use LR or TB"),
    ("---\ntitle: x\n---\nflowchart LR", "line 1: front matter is not supported"),
]

LINE3_ERRORS = [
    ("subgraph s", "subgraph is not supported"),
    ("style a fill:#fff", "style is not supported"),
    ("linkStyle 0 stroke:#000", "linkStyle is not supported"),
    ('click a "https://x.y"', "click links are not supported"),
    ("c((Round))", "shape (( is not supported; use [ ], { } or [( )]"),
    ("c>Flag]", "shape > is not supported; use [ ], { } or [( )]"),
    ("c{{Hex}}", "shape {{ is not supported; use [ ], { } or [( )]"),
    ("c[/Lean/]", "shape [/ is not supported; use [ ], { } or [( )]"),
    ("c[\\Lean\\]", "shape [\\ is not supported; use [ ], { } or [( )]"),
    ("c[[Sub]]", "shape [[ is not supported; use [ ], { } or [( )]"),
    ("c@{ shape: rect }", "shape @{ is not supported; use [ ], { } or [( )]"),
    ("a --- c", "arrow --- is not supported; use -->"),
    ("a ==> c", "arrow ==> is not supported; use -->"),
    ("a -.-> c", "arrow -.-> is not supported; use -->"),
    ("a <--> c", "arrow <--> is not supported; use -->"),
    ("a --o c", "arrow --o is not supported; use -->"),
    ("a --x c", "arrow --x is not supported; use -->"),
    ("a ~~~ c", "arrow ~~~ is not supported; use -->"),
    ("a & c --> d", "& is not supported; write one arrow per pair"),
    ('c["One<br>Two<br>Three"]', "step c has more than one <br>; write the label, then one tech tag"),
    ("?? what", 'cannot read "?? what"'),
]


@pytest.mark.parametrize(("text", "message"), HEADER_ERRORS)
def test_header_errors(text, message):
    with pytest.raises(MermaidError) as e:
        parse_mermaid(text)
    assert str(e.value) == message


@pytest.mark.parametrize(("line", "message"), LINE3_ERRORS)
def test_line_errors(line, message):
    with pytest.raises(MermaidError) as e:
        parse_mermaid(f"flowchart LR\n  a --> b\n  {line}\n")
    assert str(e.value) == f"line 3: {message}"


def test_defined_twice():
    with pytest.raises(MermaidError) as e:
        parse_mermaid("flowchart LR\n  a[First] --> b\n  a[Again]")
    assert str(e.value) == "line 3: step a is defined twice"


def test_first_line_error_wins_over_limits():
    with pytest.raises(MermaidError) as e:
        parse_mermaid("flowchart LR\n  a --> a\n  style a fill:#fff\n  subgraph s")
    assert str(e.value) == "line 3: style is not supported"


def _chain(n: int) -> str:
    return "flowchart LR\n" + "\n".join(f"  s{i} --> s{i + 1}" for i in range(1, n))


def _fan(n: int) -> str:  # n arrows over 2 + n steps would break the step limit; use a dense graph instead
    pairs = [(i, j) for i in range(1, 8) for j in range(1, 8) if i != j][:n]
    return "flowchart LR\n" + "\n".join(f"  s{i} --> s{j}" for i, j in pairs)


LIMIT_ERRORS = [
    (_chain(13), "flow has 13 steps; at most 12"),
    ("flowchart LR\n  a[Alone]", "flow has 1 step; at least 2"),
    ("flowchart LR", "flow has 0 steps; at least 2"),
    ("flowchart LR\n  a:::p1 --> b:::p2\n  c:::p3 --> d:::p4\n  e:::p5 --> a", "flow has 5 actors; at most 4"),
    (_fan(21), "flow has 21 arrows; at most 20"),
    ("flowchart LR\n  a[one two three four five six] --> b", "step a: label has 6 words; at most 5"),
    ("flowchart LR\n  a[Start<br>" + "x" * 25 + "] --> b", "step a: tag has 25 characters; at most 24"),
    ("flowchart LR\n  a -->|one two three four| b", "arrow a→b: label has 4 words; at most 3"),
    ("flowchart LR\n  a --> b\n  b --> b", "arrow b→b: a step cannot point to itself"),
    ("flowchart LR\n  a --> b\n  a --> b", "arrow a→b appears twice"),
    ("flowchart LR\n  a:::team --> b:::team\n  class a ops", "step a is in 2 actors; at most 1"),
    ("flowchart LR\n  a:::team --> b", "step b has no actor; give every step an actor or none"),
    ("flowchart LR\n  a --> b\n  class a,b emphasis", "only one step can have class emphasis"),
    ("flowchart LR\n  a --> b\n  class zz team", "class names unknown step zz"),
    ("flowchart LR\n  a:::team --> b:::team\n  class zz team", "class names unknown step zz"),
]


@pytest.mark.parametrize(("text", "message"), LIMIT_ERRORS)
def test_limit_errors(text, message):
    with pytest.raises(MermaidError) as e:
        parse_mermaid(text)
    assert str(e.value) == message


def test_twelve_steps_and_trimmed_labels_are_fine():
    flow = parse_mermaid(_chain(12) + '\n  s1["  one two three four five  "]')
    assert len(flow.steps) == 12
    assert flow.steps[0].label == "one two three four five"


def test_slide_content_parses_mermaid():
    slide = SlideContent(headline="x", visual={"type": "flow", "mermaid": F1})
    assert slide.visual.type == "flow"
    assert len(slide.visual.steps) == 6
    assert slide.visual.layout is None
    assert slide.visual.mermaid == F1


def test_mermaid_replaces_given_fields():
    flow = Flow.model_validate({"type": "flow", "mermaid": "flowchart TB\n  a --> b", "direction": "LR",
                                "steps": [{"id": "x", "label": "X"}]})
    assert flow.direction == "TB"
    assert [s.id for s in flow.steps] == ["a", "b"]


def test_parse_error_is_a_validation_error():
    with pytest.raises(ValidationError) as e:
        SlideContent.model_validate({"headline": "x", "visual": {"type": "flow", "mermaid": "flowchart LR\n  a --> b\n  subgraph s"}})
    assert "line 3: subgraph is not supported" in str(e.value)


def _steps(*ids, **kw):
    return [FlowStep(id=i, label=i.upper(), **kw) for i in ids]


@pytest.mark.parametrize("fields", [
    {"steps": _steps("a", "b"), "arrows": [FlowArrow(source="a", target="zz")]},
    {"steps": _steps("a", "a")},
    {"steps": _steps("a", "b"), "arrows": [FlowArrow(source="a", target="a")]},
    {"steps": _steps("a", "b"), "arrows": [FlowArrow(source="a", target="b")] * 2},
    {"steps": _steps("a", "b", actor="team"), "actors": []},
    {"steps": [FlowStep(id="a", label="A", actor="team"), FlowStep(id="b", label="B")], "actors": ["team"]},
    {"steps": _steps("a", "b"), "emphasis": "zz"},
    {"steps": _steps("a")},
    {"steps": _steps(*[f"s{i}" for i in range(13)])},
    {"steps": _steps("a", "b"), "actors": ["p1", "p2", "p3", "p4", "p5"]},
])
def test_field_built_flow_is_checked(fields):
    with pytest.raises(ValidationError):
        Flow.model_validate(fields)


def test_field_built_flow_validates():
    flow = Flow(steps=_steps("a", "b", actor="team"), actors=["team"], arrows=[FlowArrow(source="a", target="b")],
                emphasis="b")
    assert flow.mermaid == "" and flow.direction == "LR"


@pytest.mark.parametrize("step", [{"id": "1a", "label": "A"}, {"id": "a", "label": "  "},
                                  {"id": "a", "label": "one two three four five six"}, {"id": "a" * 33, "label": "A"}])
def test_step_fields_are_checked(step):
    with pytest.raises(ValidationError):
        FlowStep.model_validate(step)
