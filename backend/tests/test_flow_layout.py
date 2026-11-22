"""layout_flows: vendored ELK, measured text, the fit ladder and `flow_too_big` (spec house-deck-flowchart-slides, slice 2)."""

import hashlib
import re
import tomllib
from pathlib import Path

import pytest

from arp.reporting import flow_layout
from arp.reporting.flow_layout import layout_flows
from arp.reporting.house_style import load_tokens
from arp.reporting.render_model import BODY
from arp.schemas.reporting import Deck, SlideContent
from arp.schemas.visuals import Flow, Points

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
F2 = "flowchart LR\n  s1[Step 1] --> s2[Step 2]\n" + "".join(f"  s{i} --> s{i + 1}[Step {i + 1}]\n" for i in range(2, 10))
F3 = "flowchart TB\n  a[Collect filings] --> b[Extract figures]\n  b --> c[Check citations]\n  c --> d[Store results]\n"
_WORDS = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven"]
F4 = "flowchart LR\n  hub[Hub]\n" + "".join(f"  hub --> t{i}[{w}]\n" for i, w in enumerate(_WORDS, 1))


def _deck(*texts: str) -> Deck:
    return Deck(title="Flows", slides=[SlideContent(headline=f"Flow F{k}", visual=Flow(mermaid=m)) for k, m in enumerate(texts, 1)])


async def _laid(*texts: str):
    return await layout_flows(_deck(*texts), load_tokens())


def _inside(b, x, y, w, h, tol=1.0):
    return b.x >= x - tol and b.y >= y - tol and b.x + b.w <= x + w + tol and b.y + b.h <= y + h + tol


@pytest.fixture(scope="module")
async def fdeck():
    return await _laid(F1, F2, F3, F4)


def test_vendored_elk_is_the_pinned_release_with_its_licence():
    d = Path(flow_layout.__file__).parent / "vendor" / "elkjs"
    assert hashlib.sha256((d / "elk.bundled.js").read_bytes()).hexdigest() == "b1032b7cfd2a57c54c6f0e8369d7665e19a579954f7cd20a6dae28f1912ea0d7"
    assert (d / "LICENSE.md").read_text().startswith("# Eclipse Public License - v 2.0")
    readme = (d / "README.md").read_text()
    assert "0.12.1" in readme and "EPL-2.0" in readme


async def test_every_flow_gets_a_layout_and_only_f4_is_too_big(fdeck):
    deck, findings = fdeck
    assert all(s.visual.layout is not None for s in deck.slides)
    assert [(f.slide, f.rule, f.stage) for f in findings] == [(3, "flow_too_big", "fit")]


async def test_layout_is_deterministic(fdeck):
    again, _ = await _laid(F1, F2, F3, F4)
    assert [s.visual.layout for s in again.slides] == [s.visual.layout for s in fdeck[0].slides]


async def test_no_flow_means_no_browser(monkeypatch):
    monkeypatch.setenv("ARP_CHROMIUM_PATH", "/nonexistent/chrome")
    deck = Deck(title="T", slides=[SlideContent(headline="h", visual=Points(points=["a", "b", "c"]))])
    out, findings = await layout_flows(deck, load_tokens())
    assert out == deck and findings == []


async def test_f1_fits_at_full_size_inside_the_area_less_the_legend(fdeck):
    lay = fdeck[0].slides[0].visual.layout
    assert (lay.type_step, lay.wrapped, lay.too_big) == (0, False, False)
    boxes = [s.box for s in lay.steps]
    for i, a in enumerate(boxes):
        assert _inside(a, BODY.x, BODY.y, BODY.w, BODY.h - 40)
        for b in boxes[i + 1:]:
            assert a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y


async def test_f1_arrows_are_orthogonal_and_start_and_end_on_borders(fdeck):
    flow = fdeck[0].slides[0].visual
    box = {s.id: s.box for s in flow.layout.steps}

    def on_border(p, b):
        x, y = p
        within = b.x - 1 <= x <= b.x + b.w + 1 and b.y - 1 <= y <= b.y + b.h + 1
        return within and min(abs(x - b.x), abs(x - b.x - b.w), abs(y - b.y), abs(y - b.y - b.h)) <= 1

    for arrow, lay in zip(flow.arrows, flow.layout.arrows, strict=True):
        pts = lay.points
        assert on_border(pts[0], box[arrow.source]) and on_border(pts[-1], box[arrow.target])
        for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False):
            assert abs(x1 - x2) <= 0.5 or abs(y1 - y2) <= 0.5
            for b in box.values():  # a segment never runs through a box's inside
                lo_x, hi_x, lo_y, hi_y = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)
                assert not (lo_x < b.x + b.w - 1 and hi_x > b.x + 1 and lo_y < b.y + b.h - 1 and hi_y > b.y + 1)


async def test_f1_steps_run_left_to_right(fdeck):
    flow = fdeck[0].slides[0].visual
    box = {s.id: s.box for s in flow.layout.steps}
    for a in flow.arrows:
        assert box[a.target].x > box[a.source].x + box[a.source].w


async def test_f1_is_centred_in_the_area(fdeck):
    lay = fdeck[0].slides[0].visual.layout
    xs, ys = [], []
    for s in lay.steps:
        xs += [s.box.x, s.box.x + s.box.w]
        ys += [s.box.y, s.box.y + s.box.h]
    for a in lay.arrows:
        xs += [p[0] for p in a.points]
        ys += [p[1] for p in a.points]
        if a.label_box:
            xs += [a.label_box.x, a.label_box.x + a.label_box.w]
            ys += [a.label_box.y, a.label_box.y + a.label_box.h]
    assert abs((min(xs) + max(xs)) / 2 - (BODY.x + BODY.w / 2)) <= 1
    assert abs((min(ys) + max(ys)) / 2 - (BODY.y + (BODY.h - 40) / 2)) <= 1
    assert abs(lay.width - (max(xs) - min(xs))) <= 1 and abs(lay.height - (max(ys) - min(ys))) <= 1


async def test_long_lr_chain_wraps_at_full_size(fdeck):
    lay = fdeck[0].slides[1].visual.layout
    assert (lay.type_step, lay.wrapped, lay.too_big) == (0, True, False)
    assert len({round(s.box.y) for s in lay.steps}) >= 2
    assert all(_inside(s.box, BODY.x, BODY.y, BODY.w, BODY.h) for s in lay.steps)


async def test_tb_never_wraps_so_a_long_chain_is_too_big():
    deck, findings = await _laid(F2.replace("flowchart LR", "flowchart TB"))
    assert deck.slides[0].visual.layout.wrapped is False
    assert [f.rule for f in findings] == ["flow_too_big"]


async def test_tb_steps_run_top_to_bottom(fdeck):
    lay = fdeck[0].slides[2].visual.layout
    assert lay.type_step == 0
    for a, b in zip(lay.steps, lay.steps[1:], strict=False):
        assert b.box.y > a.box.y + a.box.h


async def test_too_big_flags_the_slide_with_the_size_it_needed(fdeck):
    deck, findings = fdeck
    slide, [f] = deck.slides[3], [f for f in findings if f.slide == 3]
    assert slide.needs_review and slide.visual.layout.too_big and slide.visual.layout.type_step == 1
    assert f.rule == "flow_too_big" and f.stage == "fit"
    assert re.fullmatch(r"laid out \d+×\d+ px at 24 px text; the body has 1728×592 px; merge steps", f.message)


async def test_legend_band_shrinks_the_area_in_the_message():
    _, [f] = await _laid(F4 + "  class hub,t1,t2,t3,t4,t5,t6,t7,t8,t9,t10,t11 team\n")
    assert f.message.endswith("the body has 1728×552 px; merge steps")


async def test_long_label_breaks_into_two_balanced_lines():
    words = {"Aaaa": 100, "Bbbb Cccc Dddd": 300, "Aaaa Bbbb": 200, "Cccc Dddd": 200, "Aaaa Bbbb Cccc": 300, "Dddd": 100,
             "Aaaa Bbbb Cccc Dddd": 400}
    assert flow_layout._label_lines("Aaaa Bbbb Cccc Dddd", words.__getitem__) == ["Aaaa Bbbb", "Cccc Dddd"]
    assert flow_layout._label_lines("Aaaa Bbbb", words.__getitem__) == ["Aaaa Bbbb"]


async def test_needs_no_node(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    project = tomllib.loads((Path(flow_layout.__file__).parents[2] / "pyproject.toml").read_text())["project"]
    deps = [d.lower() for d in project["dependencies"] + sum(project["optional-dependencies"].values(), [])]
    assert not [d for d in deps if any(k in d for k in ("elkjs", "nodejs", "npm"))]
    deck, _ = await _laid(F1)
    assert deck.slides[0].visual.layout is not None
