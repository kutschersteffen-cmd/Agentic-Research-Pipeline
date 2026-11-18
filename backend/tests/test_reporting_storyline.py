from arp.reporting.storyline import draft_storyline
from arp.schemas.reporting import LayoutInstructions, OutputFormat, ReportRequest, Storyline, StorylineSlide


async def test_storyline_prompt_carries_goal_and_target_length(fake_llm):
    llm = fake_llm({"Storyline": [Storyline(title="T", slides=[StorylineSlide(headline="h", purpose="p")], approved=True)]})
    request = ReportRequest(
        title="T", qualitative_notes="notes", goal="Approve the utilities underweight",
        layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK, target_length=5),
    )

    storyline, _ = await draft_storyline(request, llm)

    assert "Goal: Approve the utilities underweight" in llm.prompts[0] and "exactly 5 slides" in llm.prompts[0]
    assert storyline.approved is False  # only a human approves


def _subheaded() -> Storyline:
    return Storyline(title="T", slides=[StorylineSlide(headline="h", subheading="Sub one", purpose="p"),
                                        StorylineSlide(headline="h2", subheading="Sub two", purpose="p")])


async def test_ac15_prompt_asks_for_subheadings_with_a_template(fake_llm):
    llm = fake_llm({"Storyline": [_subheaded()]})
    request = ReportRequest(title="T", qualitative_notes="n", template_id="tpl_x", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK))
    storyline, _ = await draft_storyline(request, llm)
    assert "subheading" in llm.prompts[0] and "at most 16 words" in llm.prompts[0]
    assert [s.subheading for s in storyline.slides] == ["Sub one", "Sub two"]


async def test_ac21_no_template_keeps_subheading(fake_llm):
    # Spec (slide components): every content slide has a subtitle zone, template or not.
    llm = fake_llm({"Storyline": [_subheaded()]})
    request = ReportRequest(title="T", qualitative_notes="n", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK))
    storyline, _ = await draft_storyline(request, llm)
    assert "subheading" in llm.prompts[0] and "at most 16 words" in llm.prompts[0]
    assert [s.subheading for s in storyline.slides] == ["Sub one", "Sub two"]
