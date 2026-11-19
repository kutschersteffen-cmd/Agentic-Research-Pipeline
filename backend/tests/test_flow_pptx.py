"""Flow slides in PowerPoint: steps as groups, LR arrows as glued connectors, and `arp report flow`
(spec house-deck-flowchart-slides, slice 4)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.oxml.ns import qn
from typer.testing import CliRunner

from arp.cli.reporting import reporting_app
from arp.reporting.flow_layout import layout_flows
from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import load_tokens
from arp.reporting.sheet import sheet_deck
from arp.schemas.reporting import Deck, SlideContent
from arp.schemas.visuals import Flow
from tests.test_flow_layout import F1, F3, F4

TOKENS = load_tokens()


@pytest.fixture(scope="module")
async def fdeck():
    deck = Deck(title="Flows", slides=[SlideContent(headline=f"Flow F{k}", visual=Flow(mermaid=m)) for k, m in ((1, F1), (3, F3))])
    deck, _ = await layout_flows(deck, TOKENS)
    return deck


@pytest.fixture(scope="module")
def slides(fdeck, tmp_path_factory):
    return Presentation(str(build_house_pptx(fdeck, [], tmp_path_factory.mktemp("pptx") / "f.pptx"))).slides


def _by_name(slide) -> dict:
    """Every shape on the slide by name, group children included."""
    out = {}
    for sh in slide.shapes:
        out[sh.name] = sh
        if sh.shape_type == 6:  # MSO_SHAPE_TYPE.GROUP
            out |= {c.name: c for c in sh.shapes}
    return out


def test_ac27_each_step_is_a_group_in_slide_coordinates(fdeck, slides):
    top = {sh.name: sh for sh in slides[0].shapes}
    flow = fdeck.slides[0].visual
    for step in flow.steps:
        group = top[f"group:{step.id}"]
        children = [c.name for c in group.shapes]
        want = [f"step:{step.id}", f"step:{step.id}:label"] + [f"step:{step.id}:tag"] * bool(step.tag.strip())
        assert children == want + [f"step:{step.id}:stored"] * step.stored, step.id
        xfrm = group._element.grpSpPr.find(qn("a:xfrm"))
        off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
        ch_off, ch_ext = xfrm.find(qn("a:chOff")), xfrm.find(qn("a:chExt"))
        assert (off.get("x"), off.get("y"), ext.get("cx"), ext.get("cy")) == (
            ch_off.get("x"), ch_off.get("y"), ch_ext.get("cx"), ch_ext.get("cy"))
    assert {n for n in top if n.startswith("step:")} == set()  # no step part outside its group


def test_ac28_ac29_lr_arrows_are_glued_connectors(fdeck, slides):
    shapes, flow = _by_name(slides[0]), fdeck.slides[0].visual
    for n, (arrow, lay) in enumerate(zip(flow.arrows, flow.layout.arrows, strict=True), start=1):
        el = shapes[f"arrow:{n}"]._element
        assert len(lay.points) in (2, 4), n  # F1's LR routes: straight or one step up/down
        assert el.tag == qn("p:cxnSp"), n
        assert el.spPr.prstGeom.get("prst") == ("straightConnector1" if len(lay.points) == 2 else "bentConnector3"), n
        assert el.spPr.find(qn("a:ln")).find(qn("a:tailEnd")) is not None
        cnv = el.nvCxnSpPr.cNvCxnSpPr
        st, end = cnv.find(qn("a:stCxn")), cnv.find(qn("a:endCxn"))
        assert (int(st.get("id")), st.get("idx")) == (shapes[f"step:{arrow.source}"].shape_id, "3"), n
        assert (int(end.get("id")), end.get("idx")) == (shapes[f"step:{arrow.target}"].shape_id, "1"), n


def test_bent_connector_matches_its_route(fdeck, slides):
    shapes, flow = _by_name(slides[0]), fdeck.slides[0].visual
    bent = [(n, lay.points) for n, lay in enumerate(flow.layout.arrows, start=1) if len(lay.points) == 4]
    assert bent, "F1 has a bent arrow"
    for n, (p0, p1, _, p3) in bent:
        sh = shapes[f"arrow:{n}"]
        assert (sh.begin_x / 9525, sh.begin_y / 9525, sh.end_x / 9525, sh.end_y / 9525) == pytest.approx((*p0, *p3), abs=1)
        assert (sh._element.spPr.find(qn("a:xfrm")).get("flipV") == "1") == (p3[1] < p0[1])
        gd = sh._element.spPr.prstGeom.find(qn("a:avLst")).find(qn("a:gd"))
        assert gd.get("name") == "adj1"
        assert int(gd.get("fmla").removeprefix("val ")) == pytest.approx((p1[0] - p0[0]) / (p3[0] - p0[0]) * 100000, abs=1)


def test_ac30_tb_arrows_stay_freeform(slides):
    shapes = _by_name(slides[1])
    arrows = [sh for name, sh in shapes.items() if name.startswith("arrow:") and not name.endswith(":label")]
    assert arrows and all(sh._element.tag == qn("p:sp") for sh in arrows)
    assert not slides[1]._element.findall(".//" + qn("p:cxnSp"))
    assert {sh.name for sh in slides[1].shapes if sh.name.startswith("group:")} == {f"group:{s}" for s in "abcd"}


def test_sheet_deck_has_no_groups_or_connectors(tmp_path):
    deck, data, _ = sheet_deck()
    for slide in Presentation(str(build_house_pptx(deck, data, tmp_path / "s.pptx"))).slides:
        assert not slide._element.findall(".//" + qn("p:cxnSp"))
        assert not [sh.name for sh in slide.shapes if sh.name.startswith("group:")]


def _flow_cli(tmp_path: Path, monkeypatch, text: str, name: str = "f1.mmd"):
    """`arp report flow NAME --out d` in this process (so coverage sees it), from `tmp_path`."""
    (tmp_path / name).write_text(text)
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(reporting_app, ["flow", name, "--out", "d"]), tmp_path / "d"


def test_ac31_report_flow_writes_three_files(tmp_path, monkeypatch):
    run, d = _flow_cli(tmp_path, monkeypatch, F1)
    assert (run.exit_code, run.stdout) == (0, "Wrote flow.pptx, flow.pdf, flow.png to d\n"), run.output
    with Image.open(d / "flow.png") as im:
        assert im.size == (1920, 1080)
    prs = Presentation(str(d / "flow.pptx"))
    assert len(prs.slides) == 1 and "group:q2" in {sh.name for sh in prs.slides[0].shapes}
    assert (d / "flow.pdf").stat().st_size > 0


def test_ac31_report_flow_needs_no_database(tmp_path):
    (tmp_path / "f3.mmd").write_text(F3)
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARP_POSTGRES")}
    run = subprocess.run([sys.executable, "-m", "arp", "report", "flow", "f3.mmd", "--out", "d"], cwd=tmp_path, env=env,
                         capture_output=True, text=True)
    assert (run.returncode, run.stdout) == (0, "Wrote flow.pptx, flow.pdf, flow.png to d\n"), run.stderr


def test_ac32_parse_error_writes_nothing(tmp_path, monkeypatch):
    run, d = _flow_cli(tmp_path, monkeypatch, "flowchart LR\n  a --> b\n  subgraph s\n", "bad.mmd")
    assert (run.exit_code, run.stderr) == (1, "line 3: subgraph is not supported\n")
    assert not d.exists()


def test_ac33_too_big_still_writes_and_warns(tmp_path, monkeypatch):
    run, d = _flow_cli(tmp_path, monkeypatch, F4, "f4.mmd")
    assert run.exit_code == 0, run.output
    assert all((d / f).exists() for f in ("flow.pptx", "flow.pdf", "flow.png"))
    assert len([ln for ln in run.stderr.splitlines() if ln.startswith("flow_too_big: laid out ")]) == 1
