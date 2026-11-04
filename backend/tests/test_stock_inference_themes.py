from arp.research.stock_inference.schemas import Cluster, StockProfile
from arp.research.stock_inference.themes import ProposedTheme, Support, ThemeProposals, propose_themes
from arp.schemas.common import DocType, SourceDocument

WEIGHTS = {"p1": 0.10, "p2": 0.05, "p3": 0.10, "p4": 0.10, "p5": 0.15}  # 5 described, total 0.50


def _profiles(weights=WEIGHTS):
    return [StockProfile(company_id=c, name=c.upper(), weight=w, description=f"{c} business") for c, w in weights.items()]


def _theme(name, ids, **kw):
    return ProposedTheme(name=name, description=f"{name} desc", supporting=[Support(company_id=i, reason="r") for i in ids], **kw)


async def _propose(fake_llm, themes, profiles=None, docs=()):
    llm = fake_llm({"ThemeProposals": [ThemeProposals(themes=themes)]})
    return await propose_themes(profiles or _profiles(), [Cluster(cluster_id=0, terms=["a"], members=["p1"])], None,
                                list(docs), llm)


async def test_ac21_shares_from_described_stocks_only(fake_llm):
    themes, outliers = await _propose(fake_llm, [_theme("H2", ["x1", "p2", "p1"], weight_share=0.9, count_share=0.9)])
    t = themes[0]
    assert t.supporting == ["p1", "p2"]
    assert t.weight_share == 0.3
    assert t.count_share == 0.4
    assert t.rank == 1
    assert outliers == ["p3", "p4", "p5"]


async def test_ac22_ties_ranked_by_name(fake_llm):
    themes, _ = await _propose(fake_llm, [_theme("Beta", ["p1", "p2"]), _theme("Alpha", ["p4", "p2"])])
    assert [(t.rank, t.name) for t in themes] == [(1, "Alpha"), (2, "Beta")]


async def test_ranked_by_weight_share(fake_llm):
    themes, _ = await _propose(fake_llm, [_theme("Small", ["p2"]), _theme("Big", ["p5", "p1"])])
    assert [t.name for t in themes] == ["Big", "Small"]


async def test_unweighted_ranks_by_count_share(fake_llm):
    profiles = _profiles({c: None for c in WEIGHTS})
    themes, _ = await _propose(fake_llm, [_theme("One", ["p1"]), _theme("Two", ["p1", "p2"])], profiles)
    assert [t.name for t in themes] == ["Two", "One"]
    assert [t.weight_share for t in themes] == [None, None]
    assert themes[0].count_share == 0.4


async def test_ac23_theme_with_no_described_support_is_dropped(fake_llm):
    themes, _ = await _propose(fake_llm, [_theme("T1", ["p1"]), _theme("T2", ["x1"])])
    assert [t.name for t in themes] == ["T1"]


async def test_undescribed_profile_does_not_count(fake_llm):
    profiles = _profiles() + [StockProfile(company_id="p6", name="P6", weight=0.5, error="not_found")]
    themes, outliers = await _propose(fake_llm, [_theme("T1", ["p1", "p6"])], profiles)
    assert themes[0].supporting == ["p1"] and themes[0].count_share == 0.2
    assert "p6" not in outliers


METHODOLOGY = SourceDocument(doc_id="m1", company_id="methodology", doc_type=DocType.OTHER, title="m",
                             full_text="The index tracks companies that make hydrogen electrolysers.")


async def test_ac24_ungrounded_methodology_quote_is_dropped(fake_llm):
    themes, _ = await _propose(fake_llm, [_theme("H2", ["p1"], stated_in_methodology=True,
                                                 methodology_quote="The index tracks solar panel makers.")],
                               docs=[METHODOLOGY])
    assert themes[0].stated_in_methodology is False
    assert themes[0].methodology_quote is None


async def test_grounded_methodology_quote_is_kept(fake_llm):
    quote = "The index tracks companies that make hydrogen electrolysers."
    themes, _ = await _propose(fake_llm, [_theme("H2", ["p1"], stated_in_methodology=True, methodology_quote=quote)],
                               docs=[METHODOLOGY])
    assert themes[0].stated_in_methodology is True
    assert themes[0].methodology_quote == quote


async def test_no_methodology_means_not_stated(fake_llm):
    themes, _ = await _propose(fake_llm, [_theme("H2", ["p1"], stated_in_methodology=True, methodology_quote="x")])
    assert themes[0].stated_in_methodology is False and themes[0].methodology_quote is None


async def test_fuzzy_threshold_reaches_grounding(fake_llm, monkeypatch):
    from arp.research.stock_inference import themes as mod

    seen = []
    real = mod.ground_citations

    def spy(citations, docs, fuzzy_threshold=0.92, **kw):
        seen.append(fuzzy_threshold)
        return real(citations, docs, fuzzy_threshold, **kw)

    monkeypatch.setattr(mod, "ground_citations", spy)
    llm = fake_llm({"ThemeProposals": [ThemeProposals(themes=[_theme("H2", ["p1"], stated_in_methodology=True,
                                                                     methodology_quote="x")])]})
    await propose_themes(_profiles(), [], None, [METHODOLOGY], llm, fuzzy_threshold=0.5)
    assert seen == [0.5]
