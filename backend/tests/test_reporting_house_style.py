import itertools

import pytest

from arp.reporting.house_style import get_variant, load_layouts, load_tokens, slot_rect


def _overlap(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def test_layouts_cover_spec_library():
    assert set(load_layouts()) == {"title", "section", "big_number", "chart_takeaway", "two_column", "table",
                                   "bullets", "timeline", "quote", "matrix", "image", "summary",
                                   "statement", "cards", "steps", "stat_row", "split", "chart_focus", "compare"}


def test_v2_layouts_present():
    assert {"statement", "cards", "steps", "stat_row", "split", "chart_focus", "compare"} <= set(load_layouts())


def test_list_layouts_share_items_slot():
    for lid in ("cards", "steps", "summary", "bullets", "timeline"):
        for v in load_layouts()[lid].variants:
            assert [s.name for s in v.slots if s.kind == "list"] == ["items"]


def test_short_text_steps_up_type_role():
    from arp.reporting.html_render import render_deck_html
    from arp.schemas.reporting import Deck, SlideContent

    def html(text):
        return render_deck_html(Deck(title="T", slides=[SlideContent(headline="h", layout="statement", variant="plain",
                                                                     slots={"statement": text})]), [])
    assert 'data-role="big_number"' in html("Short claim.")
    assert 'data-role="big_number"' not in html("word " * 20)


def test_short_role_is_a_larger_type_step():
    t = load_tokens()
    for layout in load_layouts().values():
        for v in layout.variants:
            for s in v.slots:
                if s.type_role_short:
                    assert s.short_words and t.type[s.type_role_short].size > t.type[s.type_role].size, (layout.id, v.id, s.name)


def test_visual_flag_on_visual_layouts():
    ly = load_layouts()
    assert all(v.visual for lid in ("stat_row", "steps", "chart_focus", "cards") for v in ly[lid].variants)
    assert get_variant("split", "chart").visual and not get_variant("split", "list").visual
    assert not any(v.visual for v in ly["statement"].variants)


def test_type_scale_has_exactly_five_sizes():
    assert set(load_tokens().type) == {"headline", "subhead", "body", "caption", "big_number"}


def test_every_slot_rect_inside_canvas_and_slots_disjoint():
    t = load_tokens()
    for layout in load_layouts().values():
        for v in layout.variants:
            rects = [slot_rect(t, s) for s in v.slots]
            for r in rects:
                assert r.x >= t.grid.margin_x and r.x + r.w <= t.canvas.width - t.grid.margin_x + 1e-6
                assert r.y >= t.grid.margin_top + t.grid.headline_band
                assert r.y + r.h <= t.canvas.height - t.grid.margin_bottom - t.grid.footer_band + 1e-6
            assert not any(_overlap(a, b) for a, b in itertools.combinations(rects, 2)), (layout.id, v.id)


def test_roomier_points_to_existing_variant_of_same_layout():
    for layout in load_layouts().values():
        ids = {v.id for v in layout.variants}
        assert all(v.roomier in ids | {None} for v in layout.variants)


def test_text_slots_declare_word_limits():
    for layout in load_layouts().values():
        for v in layout.variants:
            for s in v.slots:
                if s.kind in ("text", "list"):
                    assert s.max_words, (layout.id, v.id, s.name)
                if s.kind == "list":
                    assert s.max_items


def test_get_variant_unknown_raises_readable_keyerror():
    with pytest.raises(KeyError, match="bullets/seven"):
        get_variant("bullets", "seven")


def test_bullets_and_quote_slot_names_are_fixed():
    for v in load_layouts()["bullets"].variants:
        assert [s.name for s in v.slots if s.kind == "list"] == ["items"]
    assert {s.name for s in get_variant("quote", "default").slots} == {"quote", "attribution"}


def _contrast(a: str, b: str) -> float:
    def lum(h):
        c = [int(h.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_house_colours_meet_wcag_aa_in_both_modes(mode):
    c = load_tokens().colors(mode)
    assert _contrast(c.ink, c.background) >= 4.5 and _contrast(c.ink_muted, c.background) >= 4.5  # text
    assert _contrast(c.accent, c.background) >= 3  # large figures and marks only
    assert all(_contrast(x, c.background) >= 3 for x in c.categorical), c.categorical  # chart marks


def test_title_slide_title_is_big_number_and_section_has_number():
    t = load_tokens()
    for v in load_layouts()["title"].variants:
        title = next(s for s in v.slots if s.name == "title")
        assert t.type[title.type_role].size >= t.type["big_number"].size
    assert "number" in {s.name for s in get_variant("section", "default").slots}
