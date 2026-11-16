"""UI polish 2, PR B (docs/superpowers/specs/2026-11-16-ui-polish-2-linear-design.md) against the running app."""

import pytest

from tests.e2e.test_ui_polish_2 import URL, _open, _probe, _style, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]


def _runs_stub(pg, runs):
    """Prepend these manifests to the real /api/runs answer, each filled out from the first real one (or bare)."""
    def handle(route):
        resp = route.fetch()
        body = resp.json()
        real = body.get("runs", [])
        base = real[0] if real else {"status": "completed", "review_count": 0, "params": {}}
        body["runs"] = [{**base, "updated_at": "2026-11-16T00:00:00Z", "created_at": "2026-11-16T00:00:00Z", **r} for r in runs] + real
        route.fulfill(response=resp, json=body)

    pg.route("**/api/runs", handle)


def _box(loc):
    return loc.bounding_box()


@pytest.mark.parametrize("path", ["/#/stewardiq", "/#/rdLab"])
def test_ac11_two_column_head(page, path):  # noqa: F811
    _open(page, path)
    h1, intro = _box(page.locator(".page > h1")), _box(page.locator(".page > h1 + p"))
    assert intro["x"] >= h1["x"] + h1["width"] - 0.5, (h1, intro)
    assert abs((intro["y"] + intro["height"]) - (h1["y"] + h1["height"])) <= 4, (h1, intro)


@pytest.mark.parametrize("path,width", [("/#/stewardiq", 1099), ("/#/review", 1440)])
def test_ac11b_stacked_below_1100_and_elsewhere(page, path, width):  # noqa: F811
    _open(page, path, width)
    h1, intro = _box(page.locator(".page > h1")), _box(page.locator(".page > h1 + p"))
    assert intro["y"] >= h1["y"] + h1["height"] - 0.5, (h1, intro)


def _tiles(pg):
    return [_box(t) for t in pg.locator(".argus-tile").all()]


def test_ac12_strip_desktop(page):  # noqa: F811
    _open(page, "/#/argus")
    boxes = _tiles(page)
    assert len(boxes) == 5 and len({round(b["y"]) for b in boxes}) == 1
    for prev, cur in zip(boxes, boxes[1:], strict=False):
        assert abs(cur["x"] - (prev["x"] + prev["width"] - 1)) <= 0.5, (prev, cur)
    tiles = page.locator(".argus-tile")
    assert _style(tiles.first, "borderTopLeftRadius") == "12px" and _style(tiles.last, "borderTopRightRadius") == "12px"
    assert _style(tiles.first, "borderTopRightRadius") == "0px" and _style(tiles.nth(2), "borderTopLeftRadius") == "0px"


def test_ac12b_strip_phone(page):  # noqa: F811
    _open(page, "/#/argus", 390, 844)
    boxes = _tiles(page)
    assert len({round(b["x"]) for b in boxes}) == 1
    for prev, cur in zip(boxes, boxes[1:], strict=False):
        assert abs(cur["y"] - (prev["y"] + prev["height"] - 1)) <= 0.5, (prev, cur)


def test_ac12c_failed_tile_on_top(page):  # noqa: F811
    _runs_stub(page, [{"run_id": f"e2e-fail-{i}", "run_type": "extraction", "status": "failed", "params": {}} for i in range(2)])
    _open(page, "/#/argus")
    failed = page.locator(".argus-tile-failed").first
    failed.wait_for()
    plain = page.locator(".argus-tile:not(.argus-tile-failed):not(.argus-tile-await)").first
    assert int(_style(failed, "zIndex")) > int(_style(plain, "zIndex").replace("auto", "0"))
    assert _style(failed, "borderTopColor") == _probe(page, "--low")


def test_focused_tile_on_top(page):  # noqa: F811
    _open(page, "/#/argus")
    tiles = page.locator(".argus-tile")
    tiles.nth(1).focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")  # keyboard focus, so :focus-visible applies
    assert int(_style(tiles.nth(1), "zIndex")) > int(_style(tiles.nth(2), "zIndex").replace("auto", "0"))
