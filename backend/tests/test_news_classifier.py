from arp.portfolio.news.classifier import _ClassificationOutput, classify_article
from arp.schemas.portfolio import NewsItem


def _article() -> NewsItem:
    return NewsItem(
        company_id="shell", headline="Court orders Shell to accelerate emissions cuts",
        excerpt="A ruling found Shell's climate transition plan insufficient.", published_at="2026-06-02",
    )


async def test_relevant_grounded_quote_produces_flag(fake_llm):
    output = _ClassificationOutput(
        relevant=True, category="litigation", severity="high", rationale="Court-ordered emissions acceleration.",
        quote="Court orders Shell to accelerate emissions cuts",
    )
    llm = fake_llm({"_ClassificationOutput": [output]})

    flag, _usage = await classify_article(_article(), llm)

    assert flag is not None
    assert flag.category == "litigation"
    assert flag.severity == "high"
    assert flag.grounded is True


async def test_ungrounded_quote_is_dropped_not_just_unmarked(fake_llm):
    output = _ClassificationOutput(
        relevant=True, category="other", severity="low", rationale="x",
        quote="This exact sentence does not appear anywhere in the article",
    )
    llm = fake_llm({"_ClassificationOutput": [output]})

    flag, _usage = await classify_article(_article(), llm)

    assert flag is None


async def test_not_relevant_returns_none(fake_llm):
    llm = fake_llm({"_ClassificationOutput": [_ClassificationOutput(relevant=False)]})

    flag, _usage = await classify_article(_article(), llm)

    assert flag is None
