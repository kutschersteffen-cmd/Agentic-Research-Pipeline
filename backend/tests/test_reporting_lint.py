from arp.reporting.lint import RULES, lint_and_rewrite, lint_deck
from arp.reporting.slide_fill import SlotRewrite
from arp.schemas.reporting import ColumnKind, DatasetColumn, Deck, QuantitativeDataset, ReportRequest, SlideContent


def _ds(row):
    return QuantitativeDataset(name="d", columns=[DatasetColumn(name=k, kind=ColumnKind.NUMBER) for k in row], rows=[row])


def _req(notes="", datasets=()):
    return ReportRequest(title="T", qualitative_notes=notes, datasets=list(datasets))


def _slide(layout="two_column", variant="text_text", headline="Utilities lag the market", **slots):
    return SlideContent(headline=headline, layout=layout, variant=variant, slots=slots)


def _deck(*slides):
    title = SlideContent(headline="T", layout="title", variant="plain", slots={"title": "T", "subtitle": "S"})
    return Deck(title="T", slides=[title, *slides])


def _rules(findings):
    return {f.rule for f in findings}


def _lint_one(text, req=None):
    return lint_deck(_deck(_slide(left=text)), req or _req())


def _bullets(*items):
    return _slide("bullets", "five", items=list(items))


def test_every_rule_is_registered():
    assert set(RULES) == {
        "over_word_limit", "stock_ai_word", "not_x_but_y", "triad_repeat", "dash_overuse",
        "bold_label", "exclamation", "repeated_opener", "number_not_in_source",
    }


def test_over_word_limit_flags():
    f = lint_deck(_deck(_bullets(*[f"x{i}" for i in range(6)]), _slide("quote", "default", quote="w " * 41, attribution="x")), _req())
    assert [(x.slide, x.slot) for x in f if x.rule == "over_word_limit"] == [(1, "items"), (2, "quote")]
    assert {x.stage for x in f} == {"lint"}


def test_over_word_limit_flags_long_list_item():
    assert "over_word_limit" in _rules(lint_deck(_deck(_bullets("w " * 13)), _req()))


def test_over_word_limit_ignores_at_limit():
    assert not lint_deck(_deck(_bullets(*[f"w{i} " + "w " * 11 for i in range(5)])), _req())


def test_stock_ai_word_flags():
    assert _rules(_lint_one("We Leverage scale")) == {"stock_ai_word"}


def test_stock_ai_word_ignores_finance_terms_and_substrings():
    assert not _lint_one("A leveraged loan with a leverage ratio, not robustness")


def test_not_x_but_y_flags():
    assert _rules(_lint_one("It is not just a cost, but a signal")) == {"not_x_but_y"}


def test_not_x_but_y_ignores_not_yet():
    assert not _lint_one("Not yet priced in")


def test_triad_repeat_flags():
    d = _deck(*[_slide("bullets", "three", items=["a b", "c d", "e f"]) for _ in range(3)])
    assert [f.slide for f in lint_deck(d, _req()) if f.rule == "triad_repeat"] == [1, 2, 3]


def test_triad_repeat_ignores_single_triad():
    assert not lint_deck(_deck(_slide("bullets", "three", items=["a b", "c d", "e f"])), _req())


def test_dash_overuse_flags():
    assert _rules(_lint_one("Fell — then rose – again")) == {"dash_overuse"}
    assert _rules(_lint_one("Fell - then rose - again")) == {"dash_overuse"}


def test_dash_overuse_ignores_one_dash_and_hyphens():
    assert not _lint_one("Fell — and a long-term, year-on-year rise")


def test_bold_label_flags():
    assert _rules(lint_deck(_deck(_bullets("**Risk:** high", "Upside: some")), _req())) == {"bold_label"}


def test_bold_label_ignores_time_and_single_label():
    assert not lint_deck(_deck(_bullets("Call at 10:30", "Risk: high")), _req())


def test_exclamation_flags():
    assert _rules(_lint_one("Great result!")) == {"exclamation"}


def test_exclamation_ignores_plain_text():
    assert not _lint_one("Great result.")


def test_repeated_opener_flags():
    d = _deck(_slide(left="Emissions fell", right="The emissions rose"), _slide(left="Emissions peaked"))
    f = [x for x in lint_deck(d, _req()) if x.rule == "repeated_opener"]
    assert [(x.slide, x.slot) for x in f] == [(1, "left"), (1, "right"), (2, "left")]


def test_repeated_opener_ignores_two_uses():
    assert not lint_deck(_deck(_slide(left="Emissions fell", right="Emissions rose")), _req())


def test_number_formats_match_source():
    req = _req(notes="Emissions fell 12.4% to 1,234 kt; capex was 1200000000.", datasets=[_ds({"share": 0.12})])
    for text in ["12.4%", "1,234", "1.2bn", "12%", "1234"]:
        assert not _lint_one(text, req), text


def test_invented_number_flagged():
    assert _rules(_lint_one("Emissions fell 17%", _req(notes="fell 12%"))) == {"number_not_in_source"}


def test_number_exempts_small_integers_and_years():
    assert not _lint_one("Three of 10 firms in 2025 and Q3")


async def test_rewrite_only_touches_flagged_slots_and_stops_after_two_rounds(fake_llm):
    bad = SlotRewrite(text="We leverage scale")
    llm = fake_llm({"SlotRewrite": [bad, bad]})
    deck = _deck(_slide(left="We leverage scale", right="Clean text"))
    out, findings = await lint_and_rewrite(deck, _req(), llm)
    assert llm.calls == ["SlotRewrite"] * 2
    assert _rules(findings) == {"stock_ai_word"} and out.slides[1].slots["right"] == "Clean text"


async def test_rewrite_fixes_slot_and_clears_finding(fake_llm):
    llm = fake_llm({"SlotRewrite": [SlotRewrite(text="We use scale")]})
    out, findings = await lint_and_rewrite(_deck(_slide(left="We leverage scale")), _req(), llm)
    assert findings == [] and out.slides[1].slots["left"] == "We use scale" and llm.calls == ["SlotRewrite"]


async def test_headline_findings_never_rewritten(fake_llm):
    llm = fake_llm({})
    out, findings = await lint_and_rewrite(_deck(_slide(headline="Leverage drives returns", left="ok")), _req(), llm)
    assert llm.calls == []
    assert [(f.slide, f.slot, f.rule) for f in findings] == [(1, "headline", "stock_ai_word")]
