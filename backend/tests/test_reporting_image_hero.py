"""House-deck image primitive and hero slides (spec house-deck-image-slides, slice 2)."""

import base64
import io
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pptx import Presentation

from arp.api.deps import get_reporting_store
from arp.api.routers import reporting as reporting_router
from arp.reporting.browser import _page
from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.html_render import render_deck_html
from arp.reporting.render_model import VisualDataError, crop
from arp.schemas.reporting import Deck, Finding, LayoutInstructions, OutputFormat, ReportManifest, ReportRequest, SlideContent
from arp.schemas.visuals import ImageItem, ImageVisual, Points
from arp.storage.reporting_store import ReportingStore

PX = 9525


def _png(w, h, colour="#ff0000") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, "PNG")
    return buf.getvalue()


def _halves(w, h, a, b, vertical: bool) -> bytes:
    im = Image.new("RGB", (w, h), b)
    im.paste(Image.new("RGB", (w // 2, h) if vertical else (w, h // 2), a), (0, 0))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


FILES = {
    "quad": lambda: _halves(2000, 1000, "#ff0000", "#0000ff", vertical=True),
    "tall": lambda: _halves(1000, 2000, "#00ff00", "#000000", vertical=False),
    "small": lambda: _png(800, 400),
    "huge": lambda: _png(6000, 3000),
}


@pytest.fixture
def store(tmp_path) -> ReportingStore:
    return ReportingStore(tmp_path / "reports", tmp_path / "tpl")


def _hero_deck(store, image="quad", caption="", focus=None, alt="") -> tuple[str, Deck, dict]:
    m = ReportManifest(title="T", output_format=OutputFormat.HOUSE_DECK)
    rid = m.report_id
    store.save_manifest(m)
    entry = store.save_report_image(rid, image, FILES[image](), alt=alt, focus=focus)
    request = ReportRequest(title="T", qualitative_notes="n", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK), images=[entry])
    store.save_request(rid, request)
    deck = Deck(title="T", slides=[
        SlideContent(headline="First", visual=Points(points=["a", "b", "c"])),
        SlideContent(headline="Hero", visual=ImageVisual(variant="hero", images=[ImageItem(name=image, caption=caption)])),
    ])
    store.save_deck(rid, deck)
    return rid, deck, store.load_report_images(rid, request)


def _shapes(path, index=1) -> dict:
    return {sh.name: sh for sh in Presentation(str(path)).slides[index].shapes}


def _box(sh) -> list[float]:
    return [sh.left / PX, sh.top / PX, sh.width / PX, sh.height / PX]


def _crop(sh) -> list[float]:
    return [sh.crop_left, sh.crop_top, sh.crop_right, sh.crop_bottom]


def test_ac23_hero_fills_the_body_box_with_a_centre_crop(store, tmp_path):
    _, deck, images = _hero_deck(store)
    pic = _shapes(build_house_pptx(deck, [], tmp_path / "d.pptx", images=images))["image:1"]
    assert _box(pic) == pytest.approx([96, 328, 1728, 592], abs=1)
    assert _crop(pic) == pytest.approx([0, 0.1574, 0, 0.1574], abs=0.001)


@pytest.mark.parametrize(("image", "focus", "want"), [
    ("quad", [0.5, 0], [0, 0, 0, 0.3148]),  # AC-24
    ("tall", [0.5, 1], [0, 0.8287, 0, 0]),  # AC-25
])
def test_ac24_ac25_crop_follows_the_focus(store, tmp_path, image, focus, want):
    _, deck, images = _hero_deck(store, image=image, focus=focus)
    pic = _shapes(build_house_pptx(deck, [], tmp_path / "d.pptx", images=images))["image:1"]
    assert _crop(pic) == pytest.approx(want, abs=0.001)


def test_crop_cuts_the_width_of_a_wide_source():
    assert crop(4000, 1000, 1000, 1000, (0, 0.5)) == pytest.approx((0, 0, 0.75, 0))
    assert crop(4000, 1000, 1000, 1000) == pytest.approx((0.375, 0, 0.375, 0))


def test_ac26_caption_is_text_under_a_shorter_image(store, tmp_path):
    _, deck, images = _hero_deck(store, caption="Our landing page")
    shapes = _shapes(build_house_pptx(deck, [], tmp_path / "d.pptx", images=images))
    assert _box(shapes["image:1"])[3] == pytest.approx(544, abs=1)
    cap = shapes["image:1:caption"]
    assert _box(cap)[1] == pytest.approx(888, abs=1) and _box(cap)[3] == pytest.approx(32, abs=1)
    assert cap.has_text_frame and cap.text_frame.text == "Our landing page"
    assert cap.text_frame.paragraphs[0].runs[0].font.size.pt == pytest.approx(24 * 0.75)  # 24 px on the 20 in slide


async def test_ac27_ac28_ac30_html_matches_the_pptx(store, tmp_path):
    _, deck, images = _hero_deck(store, caption="Our landing page", focus=[0.5, 0], alt="Landing page")
    pptx = {n: _box(sh) for n, sh in _shapes(build_house_pptx(deck, [], tmp_path / "d.pptx", images=images)).items()}
    async with _page(render_deck_html(deck, [], images=images)) as page:
        got = await page.evaluate("""() => { const s = document.querySelectorAll('section.slide')[1], b = s.getBoundingClientRect();
            const box = n => { const r = s.querySelector(`[data-name="${n}"]`).getBoundingClientRect();
                               return [r.left - b.left, r.top - b.top, r.width, r.height]; };
            const img = s.querySelector('img[data-name="image:1"]'), cs = getComputedStyle(img);
            return {image: box('image:1'), caption: box('image:1:caption'), fit: cs.objectFit, pos: cs.objectPosition, alt: img.alt}; }""")
    assert got["image"] == pytest.approx(pptx["image:1"], abs=1)
    assert got["caption"] == pytest.approx(pptx["image:1:caption"], abs=1)
    assert (got["fit"], got["pos"], got["alt"]) == ("cover", "50% 0%", "Landing page")


def test_ac29_alt_text_and_ac33_full_source_embedded(store, tmp_path):
    _, deck, images = _hero_deck(store, alt="Landing page")
    pic = _shapes(build_house_pptx(deck, [], tmp_path / "d.pptx", images=images))["image:1"]
    assert pic._element.nvPicPr.cNvPr.get("descr") == "Landing page"
    assert Image.open(io.BytesIO(pic.image.blob)).size == (2000, 1000)


def test_alt_defaults_to_the_name(store, tmp_path):
    _, deck, images = _hero_deck(store, image="small")
    pic = _shapes(build_house_pptx(deck, [], tmp_path / "d.pptx", images=images))["image:1"]
    assert pic._element.nvPicPr.cNvPr.get("descr") == "small"


def test_huge_is_downscaled_in_both_outputs_and_kept_on_disk(store, tmp_path):
    rid, deck, images = _hero_deck(store, image="huge")
    out = build_house_pptx(deck.model_copy(update={"slides": [*deck.slides, deck.slides[1]]}), [], tmp_path / "d.pptx", images=images)
    prs = Presentation(str(out))
    pics = [sh for s in prs.slides for sh in s.shapes if sh.shape_type == 13]
    assert len(pics) == 2 and {Image.open(io.BytesIO(p.image.blob)).size for p in pics} == {(3840, 1920)}
    media = [p for p in prs.part.package.iter_parts() if p.partname.startswith("/ppt/media/")]
    assert len(media) == 1  # one copy, although the image is on two slides
    assert Image.open(store.report_image_path(rid, "huge")).size == (6000, 3000)
    html = render_deck_html(deck, [], images=images)
    src = re.search(r'data-name="image:1"[^>]* src="data:image/png;base64,([^"]+)"', html).group(1)
    assert Image.open(io.BytesIO(base64.b64decode(src))).size == (3840, 1920)


def test_unknown_image_is_a_data_error(store, tmp_path):
    _, deck, _ = _hero_deck(store)
    with pytest.raises(VisualDataError, match="unknown image 'quad'; registered: "):
        build_house_pptx(deck, [], tmp_path / "d.pptx", images={})


def test_hero_takes_exactly_one_image_and_no_points():
    with pytest.raises(ValueError, match="exactly 1 image"):
        ImageVisual(variant="hero", images=[ImageItem(name="a"), ImageItem(name="b")])
    with pytest.raises(ValueError, match="image 'a' appears twice"):
        ImageVisual(variant="gallery", images=[ImageItem(name="a", caption="x"), ImageItem(name="a", caption="y")])


@pytest.fixture
def client(store, fake_llm, monkeypatch) -> TestClient:
    monkeypatch.setattr(reporting_router, "get_llm_client", lambda: fake_llm({}))
    app = FastAPI()
    app.include_router(reporting_router.router)
    app.dependency_overrides[get_reporting_store] = lambda: store
    return TestClient(app)


@pytest.mark.parametrize(("image", "want"), [
    ("small", ["image 'small' is shown at 2.2× its pixels; use a larger image"]),  # AC-42
    ("quad", []),  # AC-44
])
def test_ac42_ac44_low_resolution_finding(store, client, image, want):
    rid, _, _ = _hero_deck(store, image=image)
    store.save_findings(rid, [Finding(slide=0, stage="lint", rule="other", message="kept"),
                              Finding(slide=1, stage="fit", rule="low_resolution", message="stale")])
    assert client.post(f"/api/reports/{rid}/render").status_code == 200
    found = client.get(f"/api/reports/{rid}/findings").json()["findings"]
    low = [f for f in found if f["rule"] == "low_resolution"]
    assert [f["message"] for f in low] == want
    assert all((f["stage"], f["slide"]) == ("fit", 1) for f in low)
    assert any(f["message"] == "kept" for f in found)
