"""UI polish 2, PR B (docs/superpowers/specs/2026-11-16-ui-polish-2-linear-design.md) against the running app."""

import pytest

from tests.e2e.test_ui_polish_2 import URL, _open, _probe, _style, page  # noqa: F401  (page is a fixture)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not URL, reason="ARP_E2E_URL not set -- start backend/scripts/e2e_stack.sh"),
]


def _runs_stub(pg, runs, pattern="**/api/runs"):
    """Prepend these manifests to the real /api/runs answer, each filled out from the first real one (or bare)."""
    def handle(route):
        resp = route.fetch()
        body = resp.json()
        real = body.get("runs", [])
        base = real[0] if real else {"status": "completed", "review_count": 0, "params": {}}
        base = {**base, "company_count": 1, "completed_count": 1}  # not every real manifest has these
        body["runs"] = [{**base, "updated_at": "2026-11-16T00:00:00Z", "created_at": "2026-11-16T00:00:00Z", **r} for r in runs] + real
        route.fulfill(response=resp, json=body)

    pg.route(pattern, handle)


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


def _row_frame(pg, row):
    assert _style(row, "borderTopStyle") == "solid" and _style(row, "borderTopWidth") == "1px"
    assert _style(row, "borderTopLeftRadius") == "8px"
    assert _style(row, "backgroundColor") == _probe(pg, "--panel", "backgroundColor")


def test_ac14_argus_card_frame(page):  # noqa: F811
    _three_runs(page)
    _open(page, "/#/argus", 390, 844)
    rows = page.get_by_role("table", name="Runs").locator("tbody tr")
    first, second = rows.nth(0), rows.nth(1)
    _row_frame(page, first)
    assert _style(first, "borderTopColor") == page.evaluate(
        "() => { const d = document.createElement('div'); d.style.border = '1px solid var(--panel-border)'; document.body.append(d); const c = getComputedStyle(d).borderTopColor; d.remove(); return c; }")
    assert _box(second)["y"] >= _box(first)["y"] + _box(first)["height"] + 8 - 0.5


def test_ac14b_voting_card_frame(page):  # noqa: F811
    _runs_stub(page, [{"run_id": "e2e-vote-1", "run_type": "proxy_voting", "status": "completed", "company_count": 3, "completed_count": 3}], "**/api/runs*")
    _open(page, "/#/voting", 390, 844)
    row = page.locator("table.stack-on-phone tbody tr").first
    row.wait_for()
    _row_frame(page, row)
    label = row.locator("td[data-label]").first.evaluate("e => getComputedStyle(e, '::before').content")
    assert label not in ("none", "normal", '""'), label


def test_ac15_argus_compact_card(page):  # noqa: F811
    _three_runs(page)
    _open(page, "/#/argus", 390, 844)
    card = page.locator('tr[data-row="e2e-mine-0"]')
    run, comp, step = (card.locator(f'td[data-label="{x}"]') for x in ("Run", "Companies", "Step"))
    assert _box(run)["y"] < _box(comp)["y"], "the name line is first"
    # "N companies · step" reads as one line; the separator is generated content, which innerText never returns.
    assert abs(_box(comp)["y"] - _box(step)["y"]) <= 1
    import re
    line = f'{comp.inner_text()}{comp.evaluate("e => getComputedStyle(e, `::after`).content").strip(chr(34))} {step.inner_text()}'
    assert re.fullmatch(r"\d+ compan(y|ies) · \d \w+", line), line
    pill, box = _box(card.locator('td[data-label="Status"]')), _box(card)
    assert pill["x"] + pill["width"] >= box["x"] + box["width"] * 0.75 and pill["y"] <= box["y"] + box["height"] / 2
    labels = card.locator("td").evaluate_all("tds => tds.map(e => getComputedStyle(e, '::before').content)")
    assert not any(c.strip('"') in ("Run", "Companies", "Step", "Status") for c in labels), labels


def _six_statuses(pg):
    runs = [
        {"run_id": f"e2e-st-{name}", "run_type": "extraction", "status": status, "params": {"label": f"Status {name}"}}
        for name, status in [("running", "running"), ("stopped", "cancelled"), ("failed", "failed"), ("finished", "completed"), ("needs", "completed")]
    ]
    _runs_stub(pg, runs)

    def items(route):
        resp = route.fetch()
        body = resp.json()
        base = (body.get("items") or [{}])[0]
        body["items"] = [{**base, "run_id": "e2e-st-needs", "item_key": "e2e-st-needs:1"}] + body.get("items", [])
        route.fulfill(response=resp, json=body)

    def flows(route):
        resp = route.fetch()
        body = resp.json()
        base = (body.get("flows") or [{}])[0]
        draft = {**base, "flow_id": "e2e-st-draft", "run_id": None, "step": 2, "created_at": "2026-11-16T00:00:01Z",
                 "started_by": "dev", "started_by_name": "dev", "companies": [{**((base.get("companies") or [{}])[0]), "name": "Acme"}]}
        body["flows"] = [draft] + body.get("flows", [])
        route.fulfill(response=resp, json=body)

    pg.route("**/api/review/items*", items)
    pg.route("**/api/argus/flows", flows)


def test_ac15b_status_dots(page):  # noqa: F811
    _six_statuses(page)
    _open(page, "/#/argus", 390, 844)
    want = {"running": "--run", "needs-you": "--hi", "failed": "--low", "finished": "--text", "stopped": "--muted"}
    for status, token in want.items():
        cell = page.locator(f'td[data-status="{status}"]').first
        cell.wait_for()
        dot = cell.evaluate("e => { const s = getComputedStyle(e, '::before'); return [s.width, s.height, s.borderRadius, s.backgroundColor]; }")
        assert dot[:3] == ["6px", "6px", "0px"], (status, dot)
        assert dot[3] == _probe(page, token, "backgroundColor"), (status, dot, token)
    draft = page.locator('td[data-status="draft"]').first.evaluate("e => { const s = getComputedStyle(e, '::before'); return [s.backgroundColor, s.boxShadow]; }")
    assert draft[0] == "rgba(0, 0, 0, 0)" and "inset" in draft[1], draft


def test_ac16_desktop_table_unchanged(page):  # noqa: F811
    _three_runs(page)
    _open(page, "/#/argus")
    table = page.get_by_role("table", name="Runs")
    assert table.locator("thead").is_visible()
    assert _style(table.locator("tbody tr").first, "borderTopWidth") == "0px"


def test_long_name_clears_pill(page):  # noqa: F811
    _name_clears_pill(page)


def _name_clears_pill(pg):
    long = "A very long extraction run name that keeps going past the pill on a phone"
    _runs_stub(pg, [{"run_id": "e2e-long", "run_type": "extraction", "status": "running", "params": {"label": long}}])
    _open(pg, "/#/argus", 390, 844)
    card = pg.locator('tr[data-row="e2e-long"]')
    pill = _box(card.locator('td[data-label="Status"]'))
    rects = card.locator('td[data-label="Run"] > div').evaluate("e => [...e.getClientRects()].map(r => [r.x, r.y, r.width, r.height])")
    text_rects = card.locator('td[data-label="Run"] > div').evaluate(
        "e => { const r = document.createRange(); r.selectNodeContents(e.firstChild); return [...r.getClientRects()].map(x => [x.x, x.y, x.width, x.height]); }")
    for x, y, w, h in text_rects:
        overlap = x < pill["x"] + pill["width"] and pill["x"] < x + w and y < pill["y"] + pill["height"] and pill["y"] < y + h
        assert not overlap, (x, y, w, h, pill, rects)


def test_empty_row_card(page):  # noqa: F811
    page.route("**/api/runs", lambda r: r.fulfill(json={"runs": []}))
    page.route("**/api/argus/flows", lambda r: r.fulfill(json={"flows": []}))
    _open(page, "/#/argus", 390, 844)
    row = page.get_by_role("table", name="Runs").locator("tbody tr").first
    cell = row.locator("td").first
    assert "No runs yet" in cell.inner_text()
    rb, cb = _box(row), _box(cell)
    assert cb["x"] >= rb["x"] - 0.5 and cb["x"] + cb["width"] <= rb["x"] + rb["width"] + 0.5
    assert _style(cell, "borderTopWidth") == "0px"
    assert row.get_by_role("button", name="Start one").is_enabled()


def test_focus_ring_over_highlighted_neighbour(page):  # noqa: F811
    # Final review: a focused tile must also sit above a waiting/failed/pressed neighbour.
    _open(page, "/#/argus")
    tiles = page.locator(".argus-tile")
    tiles.nth(2).click()  # pressed: z-index 1
    tiles.nth(1).focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    assert int(_style(tiles.nth(1), "zIndex")) > int(_style(tiles.nth(2), "zIndex"))


def test_unbreakable_name_stays_inside_the_card(page):  # noqa: F811
    # Final review: content that cannot wrap (like the nowrap file-name buttons of ArgusDocuments) must not
    # widen a stacked table's cards past the phone, where the page clips them.
    _runs_stub(page, [{"run_id": "e2e-vote-wide", "run_type": "proxy_voting", "status": "completed", "company_count": 3, "completed_count": 3}], "**/api/runs*")
    _open(page, "/#/voting", 390, 844)
    row = page.locator("table.stack-on-phone tbody tr").first
    row.wait_for()
    row.locator("td").first.evaluate(
        "td => { const s = document.createElement('span'); s.style.whiteSpace = 'nowrap'; s.textContent = 'Unilever_Annual_Report_and_Accounts_2025_final_v2.pdf'; td.append(s); }")
    wrap = page.locator(".table-wrap:has(> table.stack-on-phone)").first
    assert _box(row)["x"] + _box(row)["width"] <= _box(wrap)["x"] + _box(wrap)["width"] + 0.5
    assert page.evaluate("() => document.documentElement.scrollWidth") <= 390

def test_long_name_clears_pill_at_large_text(page):  # noqa: F811
    # Final review: with a larger browser font the pill grows; the name must still clear it.
    page.add_init_script("document.addEventListener('DOMContentLoaded', () => document.documentElement.style.fontSize = '30px')")
    _name_clears_pill(page)


def test_disabled_chip_readable(page):  # noqa: F811
    page.route("**/api/me", lambda r: r.fulfill(status=401, json={"detail": "Not signed in"}))
    _open(page, "/#/argus")
    mine = page.get_by_role("group", name="Show runs").get_by_role("button", name="Only mine")
    from tests.e2e.test_ui_polish_2 import _contrast
    bg = _style(mine, "backgroundColor")
    if bg == "rgba(0, 0, 0, 0)":
        bg = _probe(page, "--bg", "backgroundColor")
    assert _style(mine, "opacity") == "1"
    assert _contrast(page, _style(mine, "color"), bg) >= 4.5
