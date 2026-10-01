from arp.reporting.visual_qa import QAEdit, QAResult, visual_qa
from arp.schemas.reporting import Deck, ReportRequest, SlideContent

_REQ = ReportRequest(title="T", qualitative_notes="")


def _deck(n=2):
    title = SlideContent(headline="T", layout="title", variant="plain", slots={"title": "T", "subtitle": "S"})
    body = SlideContent(headline="Headline", layout="bullets", variant="three", slots={"items": ["a", "b", "c"]})
    return Deck(title="T", slides=[title, *[body] * (n - 1)])


def _pngs(tmp_path, n):
    paths = [tmp_path / f"page-{k:03d}.png" for k in range(1, n + 1)]
    for k, p in enumerate(paths):
        p.write_bytes(b"png%d" % k)
    return paths


async def test_qa_sends_one_png_per_slide_in_one_call(tmp_path, fake_llm):
    llm = fake_llm({"QAResult": [QAResult(edits=[])]})
    deck, findings = await visual_qa(_deck(3), _pngs(tmp_path, 3), _REQ, llm)
    assert llm.calls == ["QAResult"] and len(llm.images[0]) == 3 and llm.images[0][2] == b"png2"
    assert findings == [] and deck == _deck(3)


async def test_qa_ignores_headline_edits_and_invalid_variants(tmp_path, fake_llm):
    edits = [
        QAEdit(slide=1, slot="headline", text="New", reason="r"),
        QAEdit(slide=0, slot="title", text="New", reason="r"),
        QAEdit(slide=1, variant="nope", reason="r"),
        QAEdit(slide=1, slot="nope", text="x", reason="r"),
        QAEdit(slide=9, variant="five", reason="r"),
    ]
    llm = fake_llm({"QAResult": [QAResult(edits=edits)]})
    deck, findings = await visual_qa(_deck(), _pngs(tmp_path, 2), _REQ, llm)
    assert deck == _deck()
    assert [f.rule for f in findings] == ["invalid_edit"] * 5


async def test_qa_runs_exactly_once(tmp_path, fake_llm):
    edit = QAEdit(slide=1, variant="five", slot="items", text=["Revenue grew 37%", "b"], reason="lone bullet")
    llm = fake_llm({"QAResult": [QAResult(edits=[edit])]})
    deck, findings = await visual_qa(_deck(), _pngs(tmp_path, 2), _REQ, llm)
    assert llm.calls.count("QAResult") == 1
    assert deck.slides[1].variant == "five" and deck.slides[1].slots["items"] == ["Revenue grew 37%", "b"]
    assert any(f.rule == "applied" and f.message == "lone bullet" for f in findings)
    assert any(f.stage == "lint" and f.rule == "number_not_in_source" for f in findings)  # QA text is re-linted


async def test_qa_truncates_and_survives_failure(tmp_path, fake_llm):
    llm = fake_llm({})  # no QAResult scripted: the call raises
    deck, findings = await visual_qa(_deck(22), _pngs(tmp_path, 22), _REQ, llm)
    assert len(llm.images[0]) == 20 and deck == _deck(22)
    assert [f.rule for f in findings] == ["qa_truncated", "qa_failed"]
