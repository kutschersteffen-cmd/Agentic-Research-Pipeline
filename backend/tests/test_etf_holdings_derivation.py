import pytest

from arp.research.taxonomy_sources.corpus_synthesis import _SynthesizedActivityDraft, _SynthesizedActivityDraftList
from arp.research.taxonomy_sources.etf_holdings import build_theme_from_holdings, load_holdings_corpus
from arp.schemas.taxonomy_sources import CorpusSourceType


def test_load_holdings_corpus_recognizes_common_column_variants(tmp_path):
    path = tmp_path / "holdings.csv"
    path.write_text("Ticker,Name,Sector\nABC,Acme Batteries Inc,Electrical Equipment\nXYZ,Widget Co,Consumer Goods\n")

    corpus = load_holdings_corpus(path)
    assert len(corpus) == 2
    assert corpus[0].source_type == CorpusSourceType.ETF_HOLDINGS
    assert corpus[0].source_ref == "ABC"
    assert "Acme Batteries Inc" in corpus[0].text
    assert "Electrical Equipment" in corpus[0].text


def test_load_holdings_corpus_skips_rows_with_no_usable_fields(tmp_path):
    path = tmp_path / "holdings.csv"
    path.write_text("Ticker,Weight\nABC,0.05\n")  # no name/sector/description column at all
    corpus = load_holdings_corpus(path)
    assert corpus == []


async def test_build_theme_from_holdings(tmp_path, fake_llm):
    path = tmp_path / "holdings.csv"
    path.write_text("ticker,name,sector\nABC,Acme Batteries,Electrical Equipment\n")

    draft = _SynthesizedActivityDraftList(
        activities=[_SynthesizedActivityDraft(name="Battery manufacturing", in_scope_description="x", out_of_scope_description="y")],
        corpus_assessment="One holding, illustrative only.",
    )
    llm = fake_llm({_SynthesizedActivityDraftList.__name__: [draft]})

    theme, notes, usage = await build_theme_from_holdings("Electrification", "desc", path, llm)
    assert theme.activities[0].name == "Battery manufacturing"
    assert "1 fund holding" in notes
    assert usage.input_tokens > 0


async def test_build_theme_from_holdings_raises_on_empty_file(tmp_path, fake_llm):
    path = tmp_path / "empty.csv"
    path.write_text("ticker,weight\nABC,0.05\n")
    llm = fake_llm({})
    with pytest.raises(ValueError):
        await build_theme_from_holdings("Electrification", "desc", path, llm)
