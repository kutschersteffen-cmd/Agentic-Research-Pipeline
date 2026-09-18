from arp.portfolio.genbi import narrator
from arp.portfolio.genbi.narrator import _NarrativeDraft, _PanelNote
from arp.portfolio.genbi.schemas import DashboardFact, PanelResult, PanelSpec

FACTS = [
    DashboardFact(
        panel_id="pan_1",
        kind="total",
        label="Total market value in scope",
        value=1_234_567.0,
        unit="EUR",
        text="Total market value in scope: EUR 1,234,567 across 12 holdings (as of 2026-04-01).",
    ),
    DashboardFact(
        panel_id="pan_1",
        kind="concentration",
        label="Top 3 sector concentration",
        value=0.723,
        unit="share",
        text="The top 3 sector groups (Energy, Autos, Banks) hold EUR 892,592, 72.3% of the total.",
    ),
]


def test_text_quoting_computed_figures_is_grounded():
    text = "Total exposure is EUR 1,234,567 as of 2026-04-01, with 72.3% of it in the top 3 sectors."
    assert narrator.check_grounding(text, FACTS) == []


def test_rescaled_figure_is_accepted_as_the_same_number():
    # EUR 1.23 million is a rounding of a real computed figure, not a new one
    assert narrator.check_grounding("Exposure stands at EUR 1.23 million.", FACTS) == []


def test_invented_figure_is_caught():
    text = "Total exposure is EUR 1,234,567, of which EUR 410,000 sits in utilities."
    assert narrator.check_grounding(text, FACTS) == ["410,000"]


def test_derived_figure_is_caught_even_though_it_is_arithmetically_true():
    # 1,234,567 - 892,592 = 341,975: correct, but no panel computed it, so it
    # is not a number this dashboard is allowed to assert
    assert narrator.check_grounding("The remaining EUR 341,975 sits outside the top 3.", FACTS) == ["341,975"]


def test_date_outside_the_computed_snapshots_is_caught():
    assert narrator.check_grounding("As of 2026-06-30 exposure was EUR 1,234,567.", FACTS) == ["2026-06-30"]


def test_prose_without_numbers_is_grounded():
    assert narrator.check_grounding("Exposure is concentrated in a small number of sectors.", FACTS) == []


def _panel_result(panel_id: str = "pan_1") -> PanelResult:
    panel = PanelSpec(panel_id=panel_id, title="Exposure by sector", group_by="sector", metric="market_value_sum")
    return PanelResult(panel=panel, as_of="2026-04-01", facts=FACTS)


async def test_narrate_keeps_a_grounded_draft(fake_llm):
    draft = _NarrativeDraft(
        headline="Total market value in scope is EUR 1,234,567 across 12 holdings.",
        panel_notes=[_PanelNote(panel_id="pan_1", text="The top 3 sectors hold 72.3% of the total.")],
    )
    llm = fake_llm({"_NarrativeDraft": [draft]})

    headline, narratives, warnings, _usage = await narrator.narrate(
        title="Exposure review", brief="b", goal="g", panels=[_panel_result()], dashboard_facts=[], llm=llm
    )

    assert headline.grounded and headline.source == "llm"
    assert headline.text == draft.headline
    assert narratives["pan_1"].source == "llm"
    assert warnings == []


async def test_narrate_falls_back_to_computed_facts_when_a_figure_is_invented(fake_llm):
    draft = _NarrativeDraft(
        headline="Exposure of EUR 9,000,000 is heavily concentrated.",
        panel_notes=[_PanelNote(panel_id="pan_1", text="The top 3 sectors hold 72.3% of the total.")],
    )
    llm = fake_llm({"_NarrativeDraft": [draft]})

    headline, narratives, warnings, _usage = await narrator.narrate(
        title="Exposure review", brief="b", goal="g", panels=[_panel_result()], dashboard_facts=[], llm=llm
    )

    assert headline.grounded is False
    assert headline.source == "deterministic_fallback"
    assert headline.ungrounded_tokens == ["9,000,000"]
    # the dashboard still ships, with the computed facts in place of the rejected prose
    assert "EUR 1,234,567" in headline.text
    assert headline.rejected_sentences == [draft.headline]
    assert any("no computed figure supports" in w for w in warnings)
    # a panel note that passed is unaffected by the headline's rejection
    assert narratives["pan_1"].grounded is True


async def test_panel_with_no_note_gets_the_deterministic_fact_text(fake_llm):
    llm = fake_llm({"_NarrativeDraft": [_NarrativeDraft(headline="Exposure is concentrated.", panel_notes=[])]})

    _headline, narratives, _warnings, _usage = await narrator.narrate(
        title="t", brief="b", goal="g", panels=[_panel_result()], dashboard_facts=[], llm=llm
    )

    assert narratives["pan_1"].source == "deterministic_fallback"
    assert narratives["pan_1"].grounded is True
    assert "EUR 1,234,567" in narratives["pan_1"].text


async def test_dashboard_level_facts_are_quotable_by_the_headline(fake_llm):
    flags_fact = DashboardFact(kind="news_flags", label="Grounded news risk flags", value=3.0, text="3 grounded news risk flag(s) across 2 issuer(s) (bmw, total); 1 rated high severity.")
    draft = _NarrativeDraft(headline="3 grounded news risk flags are outstanding, 1 of them high severity.", panel_notes=[])
    llm = fake_llm({"_NarrativeDraft": [draft]})

    headline, _narratives, warnings, _usage = await narrator.narrate(
        title="t", brief="b", goal="g", panels=[_panel_result()], dashboard_facts=[flags_fact], llm=llm
    )

    assert headline.grounded and headline.source == "llm"
    assert warnings == []


# --- per-sentence checking: one loose figure costs its sentence, not the draft


def test_one_ungrounded_sentence_does_not_discard_the_correct_ones():
    draft = (
        "Total market value in scope is EUR 1,234,567 across 12 holdings. "
        "Energy is roughly 18% of the book. "
        "The top 3 sectors hold 72.3% of the total."
    )
    narrative = narrator._narrative_from(draft, FACTS)

    assert narrative.source == "llm_partial"
    assert narrative.grounded is False  # something was dropped
    # the two correct sentences survive, in order
    assert narrative.text == (
        "Total market value in scope is EUR 1,234,567 across 12 holdings. The top 3 sectors hold 72.3% of the total."
    )
    assert narrative.rejected_sentences == ["Energy is roughly 18% of the book."]
    assert narrative.ungrounded_tokens == ["18"]


def test_a_decimal_figure_is_never_split_into_two_sentences():
    # "EUR 1.23 million" must survive as one sentence, not become "EUR 1." + "23 million"
    narrative = narrator._narrative_from("Exposure stands at EUR 1.23 million. Concentration is high.", FACTS)

    assert narrative.source == "llm"
    assert narrative.text == "Exposure stands at EUR 1.23 million. Concentration is high."


def test_a_fully_grounded_draft_is_still_kept_whole():
    draft = "Total exposure is EUR 1,234,567. The top 3 sectors hold 72.3% of it."
    narrative = narrator._narrative_from(draft, FACTS)

    assert narrative.source == "llm" and narrative.grounded is True
    assert narrative.text == draft
    assert narrative.rejected_sentences == []


def test_when_every_sentence_fails_the_computed_facts_take_over():
    draft = "Exposure is EUR 9,000,000. Utilities hold EUR 410,000 of it."
    narrative = narrator._narrative_from(draft, FACTS)

    assert narrative.source == "deterministic_fallback"
    assert narrative.grounded is False
    assert "EUR 1,234,567" in narrative.text
    assert len(narrative.rejected_sentences) == 2
    assert narrative.ungrounded_tokens == ["9,000,000", "410,000"]


async def test_warning_says_what_was_dropped_and_what_survived(fake_llm):
    draft = _NarrativeDraft(
        headline="Total market value in scope is EUR 1,234,567. Energy is roughly 18% of the book.",
        panel_notes=[],
    )
    llm = fake_llm({"_NarrativeDraft": [draft]})

    headline, _narratives, warnings, _usage = await narrator.narrate(
        title="t", brief="b", goal="g", panels=[_panel_result()], dashboard_facts=[], llm=llm
    )

    assert headline.source == "llm_partial"
    assert any("1 sentence(s) dropped, rest kept" in w and "18" in w for w in warnings)
