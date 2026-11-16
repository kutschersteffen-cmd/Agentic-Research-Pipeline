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


def _chips(pg):
    group = pg.get_by_role("group", name="Show runs")
    return group, group.get_by_role("button", name="All", exact=True), group.get_by_role("button", name="Only mine")


def test_ac13_chips_present(page):  # noqa: F811
    _open(page, "/#/argus")
    _, all_, mine = _chips(page)
    assert all_.get_attribute("aria-pressed") == "true" and mine.get_attribute("aria-pressed") == "false"
    for chip in (all_, mine):
        assert _box(chip)["height"] == 32 and float(_style(chip, "borderTopLeftRadius")[:-2]) >= 16
    assert page.get_by_role("checkbox", name="Only mine").count() == 0


def test_ac13b_pressed_state(page):  # noqa: F811
    _open(page, "/#/argus")
    _, all_, mine = _chips(page)
    mine.click()
    assert mine.get_attribute("aria-pressed") == "true" and all_.get_attribute("aria-pressed") == "false"
    mine.hover()  # pressed wins over hover
    page.wait_for_timeout(300)  # past the 100ms colour transition
    assert _style(mine, "backgroundColor") == _probe(page, "--accent-tint", "backgroundColor")


def test_ac13c_touch_height(page):  # noqa: F811
    _open(page, "/#/argus", 1024, 800)
    _, all_, mine = _chips(page)
    assert _box(all_)["height"] >= 44 and _box(mine)["height"] >= 44


def test_ac13d_signed_out(page):  # noqa: F811
    page.route("**/api/me", lambda r: r.fulfill(status=401, json={"detail": "Not signed in"}))
    _open(page, "/#/argus")
    _, all_, mine = _chips(page)
    assert mine.is_disabled() and all_.get_attribute("aria-pressed") == "true"


def _three_runs(pg):
    _runs_stub(pg, [
        {"run_id": f"e2e-mine-{i}", "run_type": "extraction", "status": "completed",
         "params": {"started_by": who, "started_by_name": who, "label": f"Chip run {i}"}}
        for i, who in enumerate(["dev", "dev", "other"])
    ])


def test_ac13e_filters_rows(page):  # noqa: F811
    _three_runs(page)
    _open(page, "/#/argus")
    _, all_, mine = _chips(page)
    rows = page.get_by_role("table", name="Runs").locator("tbody tr")
    ids = lambda: sorted(r for r in rows.evaluate_all("rs => rs.map(r => r.dataset.row)") if r and r.startswith("e2e-mine-"))  # noqa: E731
    assert ids() == ["e2e-mine-0", "e2e-mine-1", "e2e-mine-2"]
    mine.click()
    assert ids() == ["e2e-mine-0", "e2e-mine-1"]
    all_.click()
    assert ids() == ["e2e-mine-0", "e2e-mine-1", "e2e-mine-2"]


def test_chips_keyboard(page):  # noqa: F811
    _open(page, "/#/argus")
    _, all_, mine = _chips(page)
    all_.focus()
    page.keyboard.press("Tab")
    assert mine.evaluate("e => e === document.activeElement")
    page.keyboard.press("Space")
    assert mine.get_attribute("aria-pressed") == "true"
    assert _style(mine, "outlineStyle") != "none"
