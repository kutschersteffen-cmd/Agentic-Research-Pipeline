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
