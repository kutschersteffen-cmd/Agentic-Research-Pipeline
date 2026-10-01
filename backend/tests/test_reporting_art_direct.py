import pytest

from arp.reporting.art_direct import candidates, direct, next_layout, relayout, shape_of
from arp.schemas.reporting import ChartSpec, Deck, SlideContent, TableSpec

BAR = ChartSpec(dataset_id="d", chart_type="bar", category_column="c", value_columns=["v"])
SCATTER = ChartSpec(dataset_id="d", chart_type="scatter", x_column="x", value_columns=["y"])
SHORT = ["Code checks every quote", "A second model rechecks", "Analysts review the rest"]


def S(layout="bullets", variant="three", slots=None, headline="h", **kw):
    return SlideContent(headline=headline, layout=layout, variant=variant, slots=slots or {}, **kw)


def D(*slides):
    return Deck(title="T", slides=[S("title", "plain", {"title": "T"}), *slides])


def layouts(deck):
    return [(s.layout, s.variant) for s in deck.slides[1:]]


@pytest.mark.parametrize("slide,shape", [
    (S("big_number", "one", {"number_1": "143", "label_1": "companies"}), "stat_1"),
    (S("big_number", "two", {"number_1": "143", "label_1": "a", "number_2": "28", "label_2": "b"}), "stats"),
    (S(slots={"items": SHORT}), "parallel"),
    (S(slots={"items": ["Q1 2026: pilot", "Q2 2026: review", "Q3 2026: scale"]}), "ordered"),
    (S(slots={"items": ["1. Retrieve", "2. Answer", "3. Verify", "4. Review"]}), "ordered"),
    (S(slots={"items": ["First we retrieve", "Then we answer", "Finally we review"]}), "ordered"),
    (S("statement", "support", {"statement": "Disclosure skews toward talk."}), "statement"),
    (S("chart_takeaway", "full", {"takeaway": "Strategy holds most walk indicators."}, chart=BAR), "chart_short"),
    (S("chart_takeaway", "full", {"takeaway": " ".join(["word"] * 26)}, chart=BAR), "chart_long"),
    (S("two_column", "text_text", {"left": "First pass.", "right": "Second pass."}), "contrast"),
    (S("table", "compact", table=TableSpec(dataset_id="d")), "table"),
    (S(slots={"items": [" ".join(["word"] * 12)] * 3}), "other"),
], ids=lambda x: x if isinstance(x, str) else "")
def test_shape_rules(slide, shape):
    assert shape_of(slide) == shape


def test_bullets_three_short_items_become_cards():
    deck, _ = direct(D(S(slots={"items": SHORT})), density="present")
    assert layouts(deck) == [("cards", "three")]


def test_dated_items_become_steps():
    deck, _ = direct(D(S(slots={"items": ["Q1 2026: pilot", "Q2 2026: review", "Q3 2026: scale", "Q4 2026: renew"]})), density="present")
    assert layouts(deck) == [("steps", "four")]


def test_legacy_bullets_with_long_items_still_become_cards():
    deck, _ = direct(D(S(slots={"items": [" ".join(["word"] * 15)] * 3})), density="present")
    assert layouts(deck) == [("cards", "three")]


def test_no_three_in_a_row():
    deck, _ = direct(D(*[S(slots={"items": SHORT}) for _ in range(4)]), density="present")
    ls = [ly for ly, _ in layouts(deck)]
    assert all(len({ls[i], ls[i + 1], ls[i + 2]}) > 1 for i in range(len(ls) - 2)), ls


def test_visual_every_three_content_slides():
    contrast = {"left": "First pass.", "right": "Second pass."}
    heat_table = S("table", "highlight", {"takeaway": "The gap is the number to raise."}, table=TableSpec(dataset_id="d", heat={"v": [30, 60]}))
    deck, _ = direct(D(S("compare", "default", contrast), S("two_column", "text_text", contrast), heat_table), density="present")
    assert layouts(deck)[2] == ("table", "heat")
    deck, _ = direct(D(heat_table), density="present")  # alone, present mode keeps the plain table
    assert layouts(deck) == [("table", "highlight")]


def test_section_inserted_in_long_deck():
    slides = [S(slots={"items": SHORT}, headline=f"h{i}") if i % 2 else S("statement", "plain", {"statement": "s"}, headline=f"h{i}")
              for i in range(1, 12)]
    deck, findings = direct(D(*slides))  # 12 slides with the title
    sec = deck.slides[7]
    assert (sec.layout, sec.slots["number"], sec.slots["title"]) == ("section", "1", "h7")
    assert deck.slides[8].headline == "h7" and len(deck.slides) == 13
    assert any(f.slide == 7 and f.rule == "relayout" for f in findings)


def test_title_and_section_untouched():
    sec = S("section", "default", {"number": "1", "title": "Part"})
    deck, findings = direct(D(sec, S(slots={"items": SHORT})), density="present")
    assert deck.slides[0] == D().slides[0] and deck.slides[1] == sec
    assert len(deck.slides) == 3 and [f.slide for f in findings] == [2]


def test_short_decks_get_no_section():
    deck, _ = direct(D(*[S("statement", "plain", {"statement": "s"}) for _ in range(10)]), density="present")
    assert "section" not in [s.layout for s in deck.slides]


def test_placeholder_slide_left_alone():
    deck, findings = direct(D(S(slots={"items": []})))
    assert layouts(deck) == [("bullets", "three")] and findings == []


@pytest.mark.parametrize("density", ["present", "committee"])
def test_never_drops_non_empty_slot(density):
    slide = S("scatter_zone", "default", {"items": ["plain one", "plain two"]}, chart=BAR)
    deck, _ = direct(D(slide), density=density)
    assert deck.slides[1].chart == BAR and deck.slides[1].slots["items"] == ["plain one", "plain two"]


def test_relayout_reports_dropped_slots():
    _, dropped = relayout(S("split", "list", {"statement": "s", "items": SHORT}), "cards", "three")
    assert dropped == ["statement"]
    moved, dropped = relayout(S("chart_takeaway", "full", {"takeaway": "t"}, chart=BAR), "split", "chart")
    assert dropped == [] and moved.slots == {"statement": "t"} and moved.chart == BAR


def test_every_change_is_an_info_finding():
    deck, findings = direct(D(S(slots={"items": SHORT}), S("big_number", "one", {"number_1": "1", "label_1": "a"}),
                              S("statement", "plain", {"statement": "s"})), density="present")
    assert [f.slide for f in findings] == [1, 2]
    assert all((f.stage, f.rule, f.severity) == ("design", "relayout", "info") for f in findings)
    assert "bullets/three → cards/three" in findings[0].message


def test_shift_moves_earlier_findings_past_an_inserted_section():
    from arp.schemas.reporting import Finding

    old = Finding(slide=8, stage="data", rule="llm_failed", message="x")
    direct(D(*[S("statement", "plain", {"statement": "s"}) for _ in range(11)]), shift=[old])
    assert old.slide == 9


def _tpa(fixture):
    req, story, fills = fixture()
    for s, h in zip(fills, story.slides, strict=True):
        s.headline = h.headline
    return req, D(*fills)


def test_tpa_fixture_has_no_plain_bullets_after_direct():
    from tests.fixtures.tpa_pitch import tpa_pitch

    req, deck = _tpa(tpa_pitch)
    out, _ = direct(deck, density=req.layout.density)
    assert "bullets" not in [s.layout for s in out.slides]


def test_tpa_committee_fixture_keeps_its_exhibits():
    from tests.fixtures.tpa_pitch_committee import tpa_pitch_committee

    req, deck = _tpa(tpa_pitch_committee)
    out, findings = direct(deck, density=req.layout.density)
    assert layouts(out) == layouts(deck) and findings == []


# ---- committee preferences (the density amendment) ----


def test_committee_chart_with_text_goes_to_split():
    slide = S("chart_takeaway", "chart_left", {"takeaway": "Strategy holds most walk indicators."}, chart=BAR)
    assert layouts(direct(D(slide))[0]) == [("split", "chart")]
    assert layouts(direct(D(slide), density="present")[0]) == [("chart_focus", "full")]


def test_committee_scatter_with_deltas_goes_to_scatter_zone():
    slide = S("chart_focus", "full", {"items": ["+11 :: ahead of peers", "-3 :: behind"]}, chart=SCATTER)
    assert layouts(direct(D(slide))[0]) == [("scatter_zone", "default")]
    plain = slide.model_copy(update={"slots": {"items": ["ahead of peers", "behind"]}})
    assert layouts(direct(D(plain))[0]) == [("chart_focus", "full")]  # items do not parse: candidate skipped


def test_committee_table_with_text_prefers_heat_then_split():
    heat = S("table", "highlight", {"takeaway": "t"}, table=TableSpec(dataset_id="d", heat={"v": [30, 60]}))
    assert layouts(direct(D(heat))[0]) == [("table", "heat")]
    plain = heat.model_copy(update={"table": TableSpec(dataset_id="d")})
    assert layouts(direct(D(plain))[0]) == [("split", "table")]


def test_takeaway_bar_kept_or_candidate_skipped():
    slide = S("table", "heat", {"commentary": "c", "takeaway_bar": "Ask: engage."}, table=TableSpec(dataset_id="d"))
    deck, findings = direct(D(slide))  # split/table and table/highlight have no takeaway_bar
    assert deck.slides[1] == slide and findings == []


def test_committee_meter_items_go_to_profile():
    meters = ["Target :: 0%", "Governance :: 22%", "Strategy :: 71%", "Tracking :: 79%"]
    deck, _ = direct(D(S("bullets", "five", {"items": meters})))
    assert layouts(deck) == [("profile", "default")] and deck.slides[1].slots["meters"] == meters
    assert layouts(direct(D(S("bullets", "five", {"items": meters})), density="present")[0]) == [("cards", "four")]


STAGES = ["Retrieve :: 8 passages", "Answer :: YES, NO or NA", "Verify :: *a second model", "Ground :: code checks quotes"]


def test_committee_staged_list_goes_to_flow():
    assert layouts(direct(D(S("steps", "four", {"items": STAGES})))[0]) == [("flow", "default")]
    assert candidates("other", S("steps", "four", {"items": STAGES}), "present") == []


def test_flow_needs_four_parsing_stages():
    no_boxes = [s.split(" :: ")[0] for s in STAGES]
    assert layouts(direct(D(S("steps", "four", {"items": no_boxes})))[0]) == [("cards", "four")]  # parallel, not a flow
    three = S("steps", "three", {"items": STAGES[:3]})
    assert ("flow", "default") not in candidates(shape_of(three), three, "committee")


def test_committee_imperatives_at_end_go_to_decisions():
    asks = ["Agree the pilot sample", "Calibrate with your analysts", "Pick the engagement gaps"]
    deck, _ = direct(D(S("statement", "plain", {"statement": "s"}), S("summary", "default", {"items": asks})))
    assert layouts(deck)[-1] == ("decisions", "default")
    deck, _ = direct(D(S("summary", "default", {"items": asks}), S("statement", "plain", {"statement": "s"})))
    assert layouts(deck)[0] == ("cards", "three")  # not the last slide
    deck, _ = direct(D(S("statement", "plain", {"statement": "s"}), S("summary", "default", {"items": asks})), density="present")
    assert layouts(deck)[-1] == ("cards", "three")


def test_next_layout_steps_past_the_current_one():
    slide = S("cards", "three", {"items": SHORT})
    assert next_layout(slide, density="present") == ("summary", "default")
    assert next_layout(S("summary", "default", {"items": SHORT}), density="present") is None
