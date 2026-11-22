"""House-deck image slides: split, gallery and the cover image (spec house-deck-image-slides, slice 3)."""

import io

import pytest
from PIL import Image
from pptx import Presentation

from arp.reporting.browser import _page
from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.house_style import load_tokens
from arp.reporting.html_render import render_deck_html
from arp.reporting.render_model import palette
from arp.schemas.reporting import Deck, LayoutInstructions, OutputFormat, ReportManifest, ReportRequest, SlideContent
from arp.schemas.visuals import Cover, Figure, ImageItem, ImageVisual, Points
from arp.storage.reporting_store import ReportingStore
from tests.test_reporting_image_hero import FILES, _box

POINTS = ["one two three four five", "six seven eight nine ten", "eleven twelve thirteen fourteen fifteen"]
CAPS = {"quad": "Red and blue", "tall": "Green over black", "quad2": "Same as first", "small": "Small red tile", "huge": "Very large red"}


@pytest.fixture
def store(tmp_path) -> ReportingStore:
    return ReportingStore(tmp_path / "reports", tmp_path / "tpl")


def _items(names):
    return [ImageItem(name=n, caption=CAPS[n]) for n in names]


def _image_deck(store, **split) -> tuple[str, Deck, dict]:
    m = ReportManifest(title="T", output_format=OutputFormat.HOUSE_DECK)
    rid = m.report_id
    store.save_manifest(m)
    entries = [store.save_report_image(rid, n, FILES["quad" if n == "quad2" else n]()) for n in ("quad", "tall", "quad2", "small", "huge")]
    request = ReportRequest(title="T", qualitative_notes="n", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK), images=entries)
    store.save_request(rid, request)
    deck = Deck(title="T", slides=[
        SlideContent(headline="First", visual=Points(points=["a", "b", "c"])),
        SlideContent(headline="Hero", visual=ImageVisual(variant="hero", images=[ImageItem(name="quad")])),
        SlideContent(headline="Split", visual=ImageVisual(variant="split", images=[ImageItem(name="quad")], points=POINTS, **split)),
        SlideContent(headline="Four", visual=ImageVisual(variant="gallery", images=_items(["quad", "tall", "quad2", "small"]))),
        SlideContent(headline="Five", visual=ImageVisual(variant="gallery", images=_items(["quad", "tall", "quad2", "small", "huge"]))),
    ])
    store.save_deck(rid, deck)
    return rid, deck, store.load_report_images(rid, request)


def _slides(path):
    return [{sh.name: sh for sh in s.shapes} for s in Presentation(str(path)).slides]


def _build(store, tmp_path, **split):
    rid, deck, images = _image_deck(store, **split)
    return rid, _slides(build_house_pptx(deck, [], tmp_path / "d.pptx", images=images))


def test_ac34_split_left(store, tmp_path):
    _, slides = _build(store, tmp_path)
    s = slides[2]
    assert _box(s["image:1"]) == pytest.approx([96, 328, 1000, 592], abs=1)
    for n in (1, 2, 3):
        x, _, w, _ = _box(s[f"points:row:{n}"])
        assert x >= 1160 - 1 and x + w <= 1824 + 1


def test_ac35_split_right(store, tmp_path):
    _, slides = _build(store, tmp_path, side="right")
    s = slides[2]
    assert _box(s["image:1"])[0] == pytest.approx(824, abs=1)
    x, _, w, _ = _box(s["points:row:1"])
    assert x >= 96 - 1 and x + w <= 760 + 1


def test_ac36_emphasised_point_is_bold(store, tmp_path):
    _, slides = _build(store, tmp_path, emphasis=1)
    bold = [all(r.font.bold for p in slides[2][f"points:row:{n}"].text_frame.paragraphs for r in p.runs) for n in (1, 2, 3)]
    assert bold == [False, True, False]


def test_ac31_ac32_text_stays_text_and_alt_defaults_to_the_name(store, tmp_path):
    _, slides = _build(store, tmp_path)
    for n, name in enumerate(["quad", "tall", "quad2", "small"], start=1):
        cap = slides[3][f"image:{n}:caption"]
        assert cap.has_text_frame and cap.text_frame.text == CAPS[name]
    for n in (1, 2, 3):
        assert slides[2][f"points:row:{n}"].has_text_frame and slides[2][f"points:row:{n}"].text_frame.text == POINTS[n - 1]
    assert sum(sh.shape_type == 13 for sh in slides[2].values()) == 1
    assert slides[3]["image:4"]._element.nvPicPr.cNvPr.get("descr") == "small"


def test_ac37_gallery_of_four(store, tmp_path):
    _, slides = _build(store, tmp_path)
    s = slides[3]
    for n, (x, y) in enumerate([(96, 328), (976, 328), (96, 640), (976, 640)], start=1):
        assert _box(s[f"image:{n}"]) == pytest.approx([x, y, 848, 232], abs=1)
        assert _box(s[f"image:{n}:caption"])[1] == pytest.approx(y + 232 + 16, abs=1)


def test_ac38_gallery_of_five_centres_the_short_row(store, tmp_path):
    _, slides = _build(store, tmp_path)
    s = slides[4]
    want = [(96, 328), (682.67, 328), (1269.33, 328), (389.33, 640), (976, 640)]
    for n, (x, y) in enumerate(want, start=1):
        bx, by, bw, _ = _box(s[f"image:{n}"])
        assert (bx, by, bw) == pytest.approx((x, y, 554.67), abs=1)


def test_ac39_ac40_one_media_part_per_image_and_huge_downscaled(store, tmp_path):
    rid, deck, images = _image_deck(store)
    prs = Presentation(str(build_house_pptx(deck, [], tmp_path / "d.pptx", images=images)))
    media = [p for p in prs.part.package.iter_parts() if p.partname.startswith("/ppt/media/")]
    sizes = sorted(Image.open(io.BytesIO(p.blob)).size for p in media)
    assert sizes == sorted([(2000, 1000), (1000, 2000), (800, 400), (3840, 1920)])
    assert Image.open(store.report_image_path(rid, "huge")).size == (6000, 3000)


async def test_ac27_ac41_html_matches_the_pptx(store, tmp_path):
    _, deck, images = _image_deck(store)
    slides = _slides(build_house_pptx(deck, [], tmp_path / "d.pptx", images=images))
    async with _page(render_deck_html(deck, [], images=images)) as page:
        got = await page.evaluate("""() => [...document.querySelectorAll('section.slide')].map(s => {
            const b = s.getBoundingClientRect(), out = {};
            for (const el of s.querySelectorAll('[data-name^="image:"]')) {
                const r = el.getBoundingClientRect();
                out[el.dataset.name] = [r.left - b.left, r.top - b.top, r.width, r.height, el.naturalWidth || 0];
            }
            return out; })""")
    names = 0
    for html, pptx in zip(got, slides, strict=True):
        for name, box in html.items():
            assert box[:4] == pytest.approx(_box(pptx[name]), abs=1), name
            names += 1
    assert names == 1 + 1 + 8 + 10
    assert got[4]["image:5"][4] == 3840


def _cover(store, tmp_path, cover_image="quad", **cover) -> dict:
    _, _, images = _image_deck(store)
    deck = Deck(title="T", slides=[SlideContent(headline="T", visual=Cover(title="Title", **cover))])
    return _slides(build_house_pptx(deck, [], tmp_path / "c.pptx", images=images, cover_image=cover_image))[0]


FULL = {"answer": "Ship the image slides", "figures": [Figure(value="20", label="images"), Figure(value="3", label="layouts")]}


def test_ac51_ac52_ac53_cover_image_and_card(store, tmp_path):
    s = _cover(store, tmp_path, **FULL)
    plain = _cover(store, tmp_path, cover_image=None, **FULL)
    assert _box(s["cover:image"]) == pytest.approx([760, 0, 1160, 1080], abs=1)
    card, label, last = _box(s["cover:card"]), _box(s["cover:answer:label"]), _box(s["cover:figure:2:label"])
    assert (card[0], card[2]) == pytest.approx((808, 1064), abs=1)
    assert card[1] == pytest.approx(label[1] - 48, abs=1) and card[1] + card[3] == pytest.approx(last[1] + last[3] + 48, abs=1)
    assert "#" + str(s["cover:card"].fill.fore_color.rgb) == palette(load_tokens(), "light")["panel"].upper()
    for name in ("cover:answer", "cover:figure:1"):
        assert _box(s[name]) == pytest.approx(_box(plain[name]), abs=1)
    assert "cover:image" not in plain and "cover:card" not in plain
    names = list(s)
    assert names.index("cover:image") < names.index("cover:panel") < names.index("cover:card") < names.index("cover:answer:label")


def test_ac54_cover_without_answer_has_no_card(store, tmp_path):
    s = _cover(store, tmp_path)
    assert "cover:image" in s and "cover:card" not in s
