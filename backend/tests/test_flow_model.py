"""The model part of flow slides: storyline and slide fill offer `flow`, retry then fallback, `layout_flows` in
`build_house_deck`, and later stages leave flows alone (spec house-deck-flowchart-slides, slice 5)."""

from arp.reporting.house_pipeline import build_house_deck
from arp.reporting.lint import lint_deck
from arp.reporting.slide_fill import SlotRewrite, fill_slide
from arp.reporting.storyline import draft_storyline
from arp.reporting.visual_qa import QAResult
from arp.schemas.reporting import (
    Deck,
    LayoutInstructions,
    OutputFormat,
    ReportRequest,
    SlideContent,
    Storyline,
    StorylineSlide,
)
from arp.schemas.visuals import Flow, NextAction
from arp.storage.reporting_store import ReportingStore
from tests.test_flow_layout import F1, F4

_REQ = ReportRequest(title="T", qualitative_notes="Review flow.", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK))
_SLIDE = StorylineSlide(headline="Weak plans go to the decision log", purpose="Show the review path", rationale="A process", visual="flow")
_BAD = "flowchart LR\n  a --> b\n  subgraph s"
_CLOSING = [NextAction(text="Approve the plan"), NextAction(text="Brief the board")]


class _Recording:
    """Answers each call from `answers` in order (a dict becomes the output model), records the system prompts."""

    def __init__(self, *answers, rewrite: str | None = None):
        self.answers, self.rewrite = list(answers), rewrite
        self.calls, self.systems, self.prompts = [], [], []

    async def complete_structured(self, *, system, prompt, output_model, **kw):
        from arp.llm.base import LLMUsage

        self.calls.append(output_model.__name__)
        self.systems.append(system)
        self.prompts.append(prompt)
        if output_model is QAResult:
            out = QAResult(edits=[])
        elif output_model is SlotRewrite:
            out = SlotRewrite(text=self.rewrite or prompt)
        else:
            out = output_model.model_validate({"headline": "x", "visual": {"type": "flow", "mermaid": self.answers.pop(0)}})
        return out, LLMUsage(input_tokens=1, output_tokens=1)


def _labels(flow: Flow) -> list[str]:
    return [s.label for s in flow.steps] + [a.label for a in flow.arrows]


async def test_ac36_storyline_offers_flow(fake_llm):
    llm = fake_llm({"Storyline": [Storyline(title="T", slides=[StorylineSlide(headline="h", purpose="p", visual="flow")], closing=_CLOSING)]})
    await draft_storyline(ReportRequest(title="T", qualitative_notes="n"), llm)
    assert "kpi_row, chart, comparison_table, two_column, points, flow" in llm.prompts[0]
    assert "- flow: a process or decision path of 2 to 12 steps, written as Mermaid flowchart text." in llm.prompts[0]


async def test_ac37_fill_flow_one_call():
    llm = _Recording(F1)
    slide, findings, _ = await fill_slide(_SLIDE, 1, _REQ, llm)
    assert len(llm.calls) == 1 and findings == []
    assert all(w in llm.systems[0] for w in ("flowchart LR", "flowchart TB", "classDef", "<br>", "-->|", "stored", "emphasis"))
    assert slide.visual.type == "flow" and len(slide.visual.steps) == 6 and slide.visual.layout is None
    assert slide.headline == _SLIDE.headline


async def test_ac37b_prompt_has_answer_schema_only():
    llm = _Recording(F1)
    await fill_slide(_SLIDE, 1, _REQ, llm)
    for word in ('"layout"', '"steps"', '"arrows"', "FlowLayout"):
        assert word not in llm.systems[0]
    assert '"mermaid"' in llm.systems[0]


async def test_ac38_parse_error_retried_once():
    llm = _Recording(_BAD, F1)
    slide, findings, _ = await fill_slide(_SLIDE, 1, _REQ, llm)
    assert len(llm.calls) == 2 and "line 3: subgraph is not supported" in llm.prompts[1]
    assert slide.visual.type == "flow" and len(slide.visual.steps) == 6 and findings == []


async def test_ac39_second_failure_falls_back_to_points():
    llm = _Recording(_BAD, _BAD)
    slide, findings, _ = await fill_slide(_SLIDE, 1, _REQ, llm)
    assert len(llm.calls) == 2 and slide.visual.type == "points"
    assert [f.rule for f in findings] == ["bad_reference"] and "subgraph is not supported" in findings[0].message


def _store(tmp_path) -> ReportingStore:
    return ReportingStore(tmp_path / "reports", tmp_path / "templates")


async def _build(tmp_path, mermaid: str, rewrite: str | None = None):
    store = _store(tmp_path)
    deck, findings = await build_house_deck("r1", _REQ, Storyline(title="Flows", slides=[_SLIDE], closing=_CLOSING), _Recording(mermaid, rewrite=rewrite), store)
    flow = next(s for s in store.load_deck("r1").slides if s.visual.type == "flow")
    return store, flow, findings


async def test_ac40_build_lays_out_flows(tmp_path):
    store, slide, _ = await _build(tmp_path, F1)
    assert slide.visual.layout is not None and slide.visual.mermaid == F1
    assert [s.label for s in slide.visual.steps] == [s.label for s in Flow(mermaid=F1).steps]
    assert b"group:plan" in b"".join(_pptx_parts(store.output_path("r1", "output.pptx")))


def _pptx_parts(path) -> list[bytes]:
    import zipfile

    with zipfile.ZipFile(path) as z:
        return [z.read(n) for n in z.namelist() if n.startswith("ppt/slides/slide")]


async def test_ac40b_lint_skips_flow_references():
    flow = Flow(mermaid=F1)
    deck = Deck(title="T", slides=[SlideContent(headline="h", visual=flow)])
    slots = {f.slot for f in lint_deck(deck, _REQ)}
    texts = [f"visual.steps.{n}.{k}" for n in range(6) for k in ("label", "tag")] + [f"visual.arrows.{n}.label" for n in range(5)]
    assert slots <= {"headline", *texts}
    assert "visual.arrows.1.label" in slots  # 5.5x is not in the notes: arrow labels are linted as text


async def test_ac40c_rewrites_never_touch_flows(tmp_path):
    _, slide, _ = await _build(tmp_path, F1, rewrite="REWRITTEN")
    assert _labels(slide.visual) == _labels(Flow(mermaid=F1))


async def test_ac40d_too_big_flow_flagged(tmp_path):
    _, slide, findings = await _build(tmp_path, F4)
    assert slide.needs_review and [f.rule for f in findings].count("flow_too_big") == 1


async def test_too_big_flow_flagged_once(tmp_path):
    _, _, findings = await _build(tmp_path, F4)
    flow = [(f.rule, f.slot) for f in findings if f.slide == 1]
    assert flow == [("flow_too_big", "visual")]  # the fit ladder adds no overflow findings and no second needs_review
