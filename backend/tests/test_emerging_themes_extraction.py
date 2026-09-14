from arp.emerging_themes.extraction import _TagDraft, _TagDraftList, tag_mention
from arp.schemas.emerging_themes import MentionSourceType, RawMention


def _mention() -> RawMention:
    return RawMention(
        source_type=MentionSourceType.GDELT,
        title="Acme Battery Co unveils solid-state battery breakthrough",
        text="The company says the new cell chemistry could cut charging times in half.",
        url="https://news.example.com/acme-battery",
    )


async def test_grounded_quote_produces_tag(fake_llm):
    draft = _TagDraftList(
        tags=[
            _TagDraft(
                label="solid-state battery breakthrough",
                claim="Acme Battery Co unveiled a new solid-state cell chemistry.",
                entity_names=["Acme Battery Co"],
                quote="Acme Battery Co unveils solid-state battery breakthrough",
            )
        ]
    )
    llm = fake_llm({"_TagDraftList": [draft]})

    tags, _usage = await tag_mention(_mention(), llm)

    assert len(tags) == 1
    assert tags[0].grounded is True
    assert tags[0].label == "solid-state battery breakthrough"
    assert tags[0].entity_names == ["Acme Battery Co"]


async def test_ungrounded_quote_is_dropped_not_just_unmarked(fake_llm):
    draft = _TagDraftList(
        tags=[
            _TagDraft(
                label="fabricated topic", claim="x", entity_names=[],
                quote="This exact sentence does not appear anywhere in the mention",
            )
        ]
    )
    llm = fake_llm({"_TagDraftList": [draft]})

    tags, _usage = await tag_mention(_mention(), llm)

    assert tags == []


async def test_empty_mention_text_skips_llm_call(fake_llm):
    mention = _mention().model_copy(update={"text": "  ", "title": ""})
    llm = fake_llm({})

    tags, _usage = await tag_mention(mention, llm)

    assert tags == []
    assert llm.calls == []  # confirms the LLM was never actually called for empty text
