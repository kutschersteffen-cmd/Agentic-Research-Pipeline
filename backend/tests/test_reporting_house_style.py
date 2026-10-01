import itertools

import pytest

from arp.reporting.house_style import get_variant, load_layouts, load_tokens, slot_rect


def _overlap(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def test_layouts_cover_spec_library():
    assert set(load_layouts()) == {"title", "section", "big_number", "chart_takeaway", "two_column", "table",
                                   "bullets", "timeline", "quote", "matrix", "image", "summary"}


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
