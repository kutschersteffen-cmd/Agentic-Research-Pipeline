from types import SimpleNamespace

import pytest

from arp.ingestion.registry import DocumentSourceRegistry
from arp.research.stock_inference import pick as pick_mod
from arp.research.stock_inference.run import WrongStage, _save
from arp.research.stock_inference.schemas import ActivityOrigin, InferRun, Selection, StockProfile, Theme
from arp.schemas.common import Citation, DocType
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ActivityDefinition
from arp.storage.taxonomy_store import TaxonomyStore
from tests.test_stock_inference_profile import _doc, _FixedDocSource


def _profile(cid, described=True):
    cite = Citation(doc_id=f"D{cid}", doc_type=DocType.ANNUAL_REPORT_10K, quote="We make PEM stacks.")
    return StockProfile(company_id=cid, name=f"Stock {cid}", description="Makes PEM stacks." if described else None,
                        citation=cite if described else None, error=None if described else "no_document")


def _run(run_id, stage="themes_ready"):
    return InferRun(run_id=run_id, stage=stage, name="fund", extractor_model="m", verifier_model="v",
                    selection=Selection(method="sample", cutoff_reason="sample"),
                    profiles=[_profile("s1"), _profile("s2"), _profile("s3", described=False)],
                    themes=[Theme(rank=1, name="Hydrogen", description="H2", supporting=["s1"], count_share=0.5),
                            Theme(rank=2, name="Fuel", description="F", supporting=["s2"], count_share=0.5)])


def fake_steps(calls=None):
    """Every later pick step faked: synthesis returns the theme's name as one activity."""
    calls = calls if calls is not None else []

    async def synthesize(theme, profiles, chunks, llm, *, fuzzy_threshold):
        calls.append(("synthesize", sorted(chunks)))
        return [ActivityDefinition(activity_id="a1", name=theme.name, in_scope_description="in",
                                   out_of_scope_description="out")]

    async def top_down(sources, theme_name, llm, settings, fetch, *, scope):
        calls.append(("top_down", sources))
        return []

    async def merge(stock_acts, method_acts, scope, llm, matcher):
        return stock_acts, [ActivityOrigin(activity_id=a.activity_id, name=a.name, origin="stocks")
                            for a in stock_acts]

    async def keywords(activities, chunks_supporting, chunks_other, boundary_quotes, llm):
        calls.append(("keywords", sorted(chunks_supporting), sorted(chunks_other)))
        return activities

    async def map_stocks(profiles, activities, chunks, llm, *, fuzzy_threshold):
        return [], []

    async def tiers(theme_definition, mapping, segments, llm, mapper):
        return mapping

    async def draft_kpis(theme, activities, methodology_text, llm, draft):
        return []

    return dict(synthesize=synthesize, top_down=top_down, merge=merge, keywords=keywords, map_stocks=map_stocks,
                tiers=tiers, draft_kpis=draft_kpis)


@pytest.fixture
def ctx(pg, tmp_path):
    from arp.config import Settings
    from arp.db.runs import RunStore
    from arp.orchestration.job_manager import JobManager

    store = RunStore(pg, tmp_path / "runs")
    run_id = JobManager(store).create_run("stock_inference", {"methodology": [], "segments": None}, 3).run_id
    source = _FixedDocSource({c: [_doc(f"D{c}", c)] for c in ("s1", "s2", "s3")})
    tax = TaxonomyStore(tmp_path / "tax")
    kw = dict(run_store=store, taxonomy_store=tax, settings=Settings(anthropic_api_key="x"), llm=None,
              registry=DocumentSourceRegistry([source]))
    return run_id, store, tax, kw


@pytest.mark.asyncio
async def test_supporting_chunks_cover_every_described_stock(ctx):
    run_id, _store, _tax, kw = ctx
    run = _run(run_id)
    chunks = await pick_mod.supporting_chunks(run, run.themes[0], kw["registry"])
    assert sorted(chunks) == ["s1", "s2"]  # s3 has no description
    assert all(chunks[c] and all(ch.doc_id == f"D{c}" for ch in chunks[c]) for c in chunks)


@pytest.mark.asyncio
async def test_pick_saves_a_draft_and_splits_chunks_by_support(ctx):
    run_id, store, tax, kw = ctx
    _save(_run(run_id), store)
    calls = []
    run = await pick_mod.pick(run_id, 1, **kw, **fake_steps(calls))
    assert run.stage == "drafted" and run.taxonomy_id
    assert [a.name for a in run.activities] == ["Hydrogen"]
    saved = tax.get(run.taxonomy_id)
    assert saved.derivation_method == DerivationMethod.STOCK_INFERENCE
    assert saved.name == "fund" and saved.theme.name == "Hydrogen"
    assert [a.name for a in saved.theme.activities] == ["Hydrogen"]
    assert ("keywords", ["s1"], ["s2"]) in calls
    assert ("top_down", []) not in calls  # no methodology: top-down is skipped


@pytest.mark.asyncio
async def test_pick_refuses_a_second_time(ctx):  # Review Focus 1
    run_id, store, tax, kw = ctx
    _save(_run(run_id), store)
    await pick_mod.pick(run_id, 1, **kw, **fake_steps())
    with pytest.raises(WrongStage) as e:
        await pick_mod.pick(run_id, 1, **kw, **fake_steps())
    assert str(e.value) == f"Run {run_id} is at stage 'drafted'; 'pick' needs 'themes_ready'."
    assert len(tax.list_all()) == 1


@pytest.mark.asyncio
async def test_unknown_rank(ctx):
    run_id, store, _tax, kw = ctx
    _save(_run(run_id), store)
    with pytest.raises(ValueError, match=f"^Run {run_id} has no theme 9.$"):
        await pick_mod.pick(run_id, 9, **kw, **fake_steps())
    assert pick_mod.load_run(run_id, store).stage == "themes_ready"


@pytest.mark.asyncio
async def test_step_failure_marks_run_failed(ctx):
    from arp.schemas.common import JobStatus

    run_id, store, tax, kw = ctx
    _save(_run(run_id), store)

    async def boom(*a, **k):
        raise RuntimeError("model down")

    with pytest.raises(pick_mod.InferFailed, match="^RuntimeError: model down$"):
        await pick_mod.pick(run_id, 1, **kw, **{**fake_steps(), "synthesize": boom})
    assert pick_mod.load_run(run_id, store).stage == "failed"
    manifest = store.load_manifest(run_id)
    assert manifest.status == JobStatus.FAILED and manifest.error == "RuntimeError: model down"
    assert tax.list_all() == []


@pytest.mark.asyncio
async def test_pick_fetches_with_the_stocks_file_identifiers(ctx, tmp_path):  # review fix: EDGAR needs ticker/cik
    from arp.ingestion.base import DocumentSource

    run_id, store, tax, kw = ctx

    class _EdgarLike(DocumentSource):
        name = "edgar_like"
        refs = []

        async def fetch(self, company, doc_types=None):
            self.refs.append(company)
            return [_doc(f"D{company.company_id}", company.company_id)] if company.ticker or company.cik else []

    stocks = tmp_path / "fund.csv"
    stocks.write_text("company_id,name,ticker\ns1,Stock s1,AAA\n")  # s2 is missing from the file: profile fallback
    manifest = store.load_manifest(run_id)
    manifest.params["stocks"] = str(stocks)
    store.save_manifest(manifest)
    _save(_run(run_id), store)
    source = _EdgarLike()
    calls = []
    await pick_mod.pick(run_id, 1, **{**kw, "registry": DocumentSourceRegistry([source])}, **fake_steps(calls))
    assert ("keywords", ["s1"], ["s2"]) in calls
    assert {r.company_id: r.ticker for r in source.refs} == {"s1": "AAA", "s2": None}
    chunks = await pick_mod.supporting_chunks(_run(run_id), None, DocumentSourceRegistry([source]))
    assert not chunks["s1"] and not chunks["s2"]  # without the stocks file neither ref carries a ticker


@pytest.mark.asyncio
async def test_supporting_chunk_fetches_are_bounded():  # review fix: like _benchmark_chunks (F10)
    import asyncio

    class _Registry:
        live = peak = 0

        async def fetch_all(self, ref):
            self.live += 1
            self.peak = max(self.peak, self.live)
            await asyncio.sleep(0.01)
            self.live -= 1
            return []

    run = _run("r1").model_copy(update={"profiles": [_profile(f"s{i}") for i in range(6)]})
    reg = _Registry()
    await pick_mod.supporting_chunks(run, None, reg, limit=2)
    assert reg.peak == 2


def _act(name, quote, url="m"):
    from arp.schemas.authority_taxonomy import SourceCitation

    return ActivityDefinition(name=name, in_scope_description="in", out_of_scope_description="out",
                              citations=[SourceCitation(quote=quote, source_url=url)])


@pytest.mark.asyncio
async def test_synthesized_activities_need_a_grounded_quote(ctx, fake_llm):  # AC-31
    run_id, store, tax, kw = ctx
    _save(_run(run_id), store)
    reply = pick_mod.StockActivities(activities=[
        pick_mod.StockActivity(name="A", in_scope_description="in", out_of_scope_description="out",
                               quotes=["We make PEM stacks."]),
        pick_mod.StockActivity(name="B", in_scope_description="in", out_of_scope_description="out",
                               quotes=["We mine lithium in Chile."]),
    ])
    llm = fake_llm({"StockActivities": [reply]})
    steps = {k: v for k, v in fake_steps().items() if k != "synthesize"}
    run = await pick_mod.pick(run_id, 1, **{**kw, "llm": llm}, **steps)
    acts = tax.get(run.taxonomy_id).theme.activities
    assert [a.name for a in acts] == ["A"]
    assert [c.quote for c in acts[0].citations] == ["We make PEM stacks."]
    assert "Stock s1" in llm.prompts[0] and "Stock s2" not in llm.prompts[0]  # supporting stocks only


@pytest.mark.asyncio
async def test_matched_pair_becomes_one_activity_from_both(ctx):  # AC-35
    from arp.research.authority_taxonomy.matching import Match

    run_id, store, tax, kw = ctx
    _save(_run(run_id), store)
    manifest = store.load_manifest(run_id)
    manifest.params["methodology"] = ["https://index.example/method.pdf"]
    store.save_manifest(manifest)

    async def synthesize(theme, profiles, chunks, llm, *, fuzzy_threshold):
        return [_act("PEM stacks", "Q1", "s1")]

    async def top_down(sources, theme_name, llm, settings, fetch, *, scope):
        return [_act("Stack making", "Q2"), _act("Hydrogen storage", "Q3")]

    async def matcher(left, right, *, scope, llm):
        assert [a.name for a in left] == ["PEM stacks"] and scope == "H2"
        return [Match(left=0, right=0, method="model", reason="same")]

    steps = {**fake_steps(), "synthesize": synthesize, "top_down": top_down}
    del steps["merge"]
    run = await pick_mod.pick(run_id, 1, **{**kw, "matcher": matcher}, **steps)
    acts = tax.get(run.taxonomy_id).theme.activities
    assert [(a.name, [c.quote for c in a.citations]) for a in acts] == [
        ("PEM stacks", ["Q1", "Q2"]), ("Hydrogen storage", ["Q3"])]
    assert [(o.activity_id, o.name, o.origin) for o in run.activities] == [
        (acts[0].activity_id, "PEM stacks", "both"), (acts[1].activity_id, "Hydrogen storage", "methodology")]


@pytest.mark.asyncio
async def test_unreachable_methodology_keeps_the_bottom_up_work(ctx):  # Review Focus 2
    run_id, store, tax, kw = ctx
    _save(_run(run_id), store)
    manifest = store.load_manifest(run_id)
    manifest.params["methodology"] = ["https://gone.example/method.pdf"]
    store.save_manifest(manifest)

    async def fetch(sources, user_agent):
        raise OSError("connection refused")

    steps = {k: v for k, v in fake_steps().items() if k != "top_down"}
    run = await pick_mod.pick(run_id, 1, **{**kw, "fetch": fetch}, **steps)
    assert run.stage == "drafted" and [o.origin for o in run.activities] == ["stocks"]
    assert "https://gone.example/method.pdf" in tax.get(run.taxonomy_id).source_notes


@pytest.mark.asyncio
async def test_no_grounded_activity_fails_the_run(ctx):  # Review Focus 3
    run_id, store, tax, kw = ctx
    _save(_run(run_id), store)
    steps = {k: v for k, v in fake_steps().items() if k != "synthesize"}
    empty = DocumentSourceRegistry([_FixedDocSource({})])
    with pytest.raises(pick_mod.InferFailed, match=r"^No activity could be grounded in the supporting stocks\.$"):
        await pick_mod.pick(run_id, 1, **{**kw, "registry": empty}, **steps)  # llm=None: no model call either
    assert pick_mod.load_run(run_id, store).stage == "failed"
    assert store.load_manifest(run_id).error == "No activity could be grounded in the supporting stocks."
    assert tax.list_all() == []


@pytest.mark.asyncio
async def test_top_down_extracts_each_document_with_the_value_chain(monkeypatch):
    from arp.config import Settings
    from arp.schemas.authority_taxonomy import SourceCitation
    from arp.schemas.common import SourceDocument
    from arp.schemas.thematic import ThemeDefinition

    seen = []
    boundary = SourceCitation(quote="Fuel retail is excluded.", source_url="u1")

    async def fetch(sources, user_agent):
        return [SourceDocument(company_id="methodology", doc_type=DocType.OTHER, title=s, source_url=s,
                               full_text=f"text of {s}") for s in sources]

    async def extract_source(url, text, *, theme_name, scope, value_chain, llm):
        seen.append(("extract", url, text, theme_name, scope, value_chain))
        return SimpleNamespace(url=url)

    async def consolidate(extractions, *, theme_name, scope, value_chain, settings, llm, value_chain_model):
        seen.append(("consolidate", [e.url for e in extractions], scope, value_chain, value_chain_model))
        act = _act("Stacks", "Q2").model_copy(update={"out_of_scope_citations": [boundary]})
        return ThemeDefinition(name=theme_name, description="", activities=[act]), ""

    monkeypatch.setattr(pick_mod, "extract_source", extract_source)
    monkeypatch.setattr(pick_mod, "consolidate", consolidate)
    acts = await pick_mod.top_down(["u1", "u2"], "Hydrogen", None, Settings(anthropic_api_key="x"), fetch,
                                   scope="Green hydrogen")
    assert seen == [("extract", "u1", "text of u1", "Hydrogen", "Green hydrogen", True),
                    ("extract", "u2", "text of u2", "Hydrogen", "Green hydrogen", True),
                    ("consolidate", ["u1", "u2"], "Green hydrogen", True, None)]
    assert acts[0].out_of_scope_citations == [boundary]  # kept for Task 4's exclusion-keyword grounding


@pytest.mark.asyncio
async def test_one_unreadable_source_keeps_the_readable_one(ctx, monkeypatch):  # review fix: fetch per source
    from arp.schemas.common import SourceDocument
    from arp.schemas.thematic import ThemeDefinition

    run_id, store, tax, kw = ctx
    _save(_run(run_id), store)
    manifest = store.load_manifest(run_id)
    manifest.params["methodology"] = ["https://ok.example/m.pdf", "https://gone.example/m.pdf"]
    store.save_manifest(manifest)
    seen = []

    async def fetch(sources, user_agent):
        if "https://gone.example/m.pdf" in sources:
            raise OSError("connection refused")
        return [SourceDocument(company_id="methodology", doc_type=DocType.OTHER, title=s, source_url=s,
                               full_text="text") for s in sources]

    async def extract_source(url, text, *, theme_name, scope, value_chain, llm):
        seen.append(("extract", url, scope))
        return SimpleNamespace(url=url)

    async def consolidate(extractions, *, theme_name, scope, value_chain, settings, llm, value_chain_model):
        seen.append(("consolidate", [e.url for e in extractions], scope))
        return ThemeDefinition(name=theme_name, description="", activities=[]), ""

    monkeypatch.setattr(pick_mod, "extract_source", extract_source)
    monkeypatch.setattr(pick_mod, "consolidate", consolidate)
    steps = {k: v for k, v in fake_steps().items() if k != "top_down"}
    run = await pick_mod.pick(run_id, 1, **{**kw, "fetch": fetch}, **steps)
    assert seen == [("extract", "https://ok.example/m.pdf", "H2"), ("consolidate", ["https://ok.example/m.pdf"], "H2")]
    notes = tax.get(run.taxonomy_id).source_notes
    assert "https://gone.example/m.pdf" in notes and "https://ok.example/m.pdf" not in notes


def _chunk(cid, text):
    return pick_mod.DocumentChunk(doc_id=f"D{cid}", company_id=cid, doc_type=DocType.ANNUAL_REPORT_10K, text=text,
                                  char_start=0, char_end=len(text))


def _kw_llm(**buckets):
    async def complete_structured(*, system, prompt, output_model):
        return output_model(activities=[dict(activity_id="a1", **buckets)]), None

    return SimpleNamespace(complete_structured=complete_structured)


_ACT = ActivityDefinition(activity_id="a1", name="Hydrogen", in_scope_description="in", out_of_scope_description="out")


@pytest.mark.asyncio
async def test_keywords_primary_must_occur_as_whole_phrase_in_supporting_chunk():  # AC-37
    llm = _kw_llm(primary=["PEM stack", "fusion reactor", "Herøya plants"])
    [a] = await pick_mod.keywords([_ACT], {"s1": [_chunk("s1", "Our PEM stack plant in Herøya")]}, {}, [], llm)
    assert a.seed_keywords == ["PEM stack"]


@pytest.mark.asyncio
async def test_keywords_contextual_and_exclusion_grounding():  # AC-38
    llm = _kw_llm(contextual=["stack efficiency", "warp drive"], exclusion=["fuel cell", "PEM stack"])
    [a] = await pick_mod.keywords([_ACT], {"s1": [_chunk("s1", "Stack efficiency rose to 70 %.")]},
                                  {"s2": [_chunk("s2", "We sell fuel cell systems.")]}, [], llm)
    assert a.contextual_keywords == ["stack efficiency"]
    assert a.exclusion_keywords == ["fuel cell"]
    assert a.contextual_window_words == 50


@pytest.mark.asyncio
async def test_keywords_exclusion_may_ground_in_boundary_quote():
    llm = _kw_llm(exclusion=["electrolyser"])
    [a] = await pick_mod.keywords([_ACT], {}, {}, ["Excludes electrolyser resale."], llm)
    assert a.exclusion_keywords == ["electrolyser"]


def _cited(quote, seeds):
    from arp.schemas.authority_taxonomy import SourceCitation

    return _ACT.model_copy(update={"seed_keywords": seeds,
                                   "citations": [SourceCitation(quote=quote, source_url="u", location="s1")]})


@pytest.mark.asyncio
async def test_keywords_omitted_activity_keeps_quote_grounded_seeds():
    act = _cited("We make PEM stacks.", ["PEM stacks", "warp drive"])

    async def other(*, system, prompt, output_model):
        return output_model(activities=[]), None
    [a] = await pick_mod.keywords([act], {}, {}, [], SimpleNamespace(complete_structured=other))
    assert a.seed_keywords == ["PEM stacks"]


@pytest.mark.asyncio
async def test_keywords_methodology_seed_found_in_its_citation_is_kept_before_new_primaries():
    act = _cited("Electrolyser output.", ["electrolyser"])
    llm = _kw_llm(primary=["PEM stack", "electrolyser"])
    [a] = await pick_mod.keywords([act], {"s1": [_chunk("s1", "Our PEM stack plant")]}, {}, [], llm)
    assert a.seed_keywords == ["electrolyser", "PEM stack"]


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase,text,hit", [
    ("stack", "We make stacks.", False), ("C++", "We write C++ code.", True),
    ("PEM stack", "PEM\nstack", True), ("PEM", "a (PEM) cell", True)])
async def test_keywords_phrase_matching(phrase, text, hit):
    [a] = await pick_mod.keywords([_ACT], {"s1": [_chunk("s1", text)]}, {}, [], _kw_llm(primary=[phrase]))
    assert a.seed_keywords == ([phrase] if hit else [])


@pytest.mark.asyncio
async def test_keywords_no_activities_makes_no_call():
    async def boom(**k):
        raise AssertionError("called")

    assert await pick_mod.keywords([], {}, {}, [], SimpleNamespace(complete_structured=boom)) == []


def _weighted(cid, weight, described=True):
    return _profile(cid, described).model_copy(update={"weight": weight})


def _m(cid, activity_id="a1"):
    return pick_mod.Mapping(company_id=cid, activity_id=activity_id, reason="r", quote="q", tier="unknown")


@pytest.mark.asyncio
async def test_map_stocks_keeps_only_quotes_grounded_in_the_stocks_own_chunks(fake_llm):  # AC-32, AC-32a
    A = pick_mod.StockAssignment
    reply = pick_mod.StockAssignments(assignments=[
        A(company_id="p1", activity_id="a1", reason="makes stacks", quote="We make PEM stacks."),
        A(company_id="p3", activity_id="a1", reason="copied", quote="We make PEM stacks."),  # p1's text, not p3's
        A(company_id="p4", activity_id="none", reason="bakery", quote="We run a bakery chain."),
        A(company_id="p5", activity_id="a9", reason="no such activity", quote="We sell bread."),
    ])  # p2 left out of the reply
    chunks = {"p1": [_chunk("p1", "We make PEM stacks.")], "p2": [_chunk("p2", "We make PEM stacks.")],
              "p3": [_chunk("p3", "We sell bread.")], "p4": [_chunk("p4", "We run a bakery chain.")],
              "p5": [_chunk("p5", "We sell bread.")]}
    profiles = [_profile(c) for c in ("p1", "p2", "p3", "p4", "p5")] + [_profile("p6", described=False)]
    llm = fake_llm({"StockAssignments": [reply]})
    mapping, unmapped = await pick_mod.map_stocks(profiles, [_ACT], chunks, llm, fuzzy_threshold=0.92)
    assert [(m.company_id, m.activity_id, m.tier) for m in mapping] == [("p1", "a1", "unknown"), ("p4", None, "unknown")]
    assert unmapped == ["p2", "p3", "p5"]
    assert len(llm.calls) == 1 and "Stock p6" not in llm.prompts[0]


def test_coverage_shares_of_profiled_and_fund_weight():  # AC-33
    run = _run("r1").model_copy(update={
        "selection": Selection(method="weighted", cutoff_reason="weight_80", total_weight=1.0),
        "profiles": [_weighted("s1", 0.3), _weighted("s2", 0.2), _weighted("s3", 0.4, described=False)]})
    c = pick_mod.coverage(run, [_m("s1"), _m("s2", None)], ["s9", "s4"])
    assert (c.profiled_weight_share, c.fund_weight_share, c.unmapped) == (pytest.approx(0.6), 0.3, ["s4", "s9"])
    assert pick_mod.coverage_note(c) == "Coverage: 0.60 of profiled weight, 0.30 of fund weight."


def test_coverage_unweighted_is_na():  # AC-34
    c = pick_mod.coverage(_run("r1"), [_m("s1")], [])
    assert c.profiled_weight_share is None and c.fund_weight_share is None
    assert pick_mod.coverage_note(c) == "Coverage: n/a of profiled weight, n/a of fund weight."


def test_coverage_counts_a_missing_weight_as_zero():  # Review Focus 4
    run = _run("r1").model_copy(update={
        "selection": Selection(method="weighted", cutoff_reason="weight_80", total_weight=0.5),
        "profiles": [_weighted("s1", 0.25), _weighted("s2", None)]})
    c = pick_mod.coverage(run, [_m("s1"), _m("s2")], [])
    assert (c.profiled_weight_share, c.fund_weight_share) == (1.0, 0.5)


def _seg(cid, label, value=None, pct=None, metric="revenue", period=""):
    from arp.schemas.revenue_exposure import CatalogueDataPoint

    return CatalogueDataPoint(data_point_id=f"{cid}-{label}", company_id=cid, metric=metric, label=label, value=value,
                              as_pct_of_total=pct, period=period)


@pytest.mark.asyncio
async def test_tiers_from_revenue_share_in_labels_linked_to_the_mapped_activity():  # AC-36
    from arp.schemas.revenue_exposure import ActivityCatalogueMapping
    from arp.schemas.thematic import ThemeDefinition

    segments = {"p1": [_seg("p1", "Stacks", pct=0.6), _seg("p1", "Storage", pct=0.4)],
                "p6": [_seg("p6", "Stacks", 50), _seg("p6", "Total Revenue", 100), _seg("p6", "Stacks", pct=0.9,
                                                                                         metric="capex")],
                "p2": [_seg("p2", "Stacks", pct=0.25), _seg("p2", "Storage", pct=0.75)],
                "p4": [_seg("p4", "Stacks", pct=0.05)]}
    seen = []

    async def mapper(theme, labels_by_metric, llm):
        seen.append(labels_by_metric)
        return [ActivityCatalogueMapping(activity_id="a1", metric="revenue", matched_labels=["Stacks"]),
                ActivityCatalogueMapping(activity_id="a2", metric="revenue", matched_labels=["Storage"])], None

    a2 = _ACT.model_copy(update={"activity_id": "a2", "name": "Storage"})
    definition = ThemeDefinition(name="H", description="", activities=[_ACT, a2])
    mapping = [_m(c) for c in ("p1", "p6", "p2", "p4", "p5")] + [_m("p7", None)]
    out = await pick_mod.tiers(definition, mapping, segments, None, mapper)
    assert [(m.company_id, m.tier) for m in out] == [("p1", "core"), ("p6", "core"), ("p2", "enabler"),
                                                     ("p4", "adopter"), ("p5", "unknown"), ("p7", "unknown")]
    assert seen == [{"revenue": ["Stacks", "Storage"]}]  # capex links are never read: no calls for them


@pytest.mark.asyncio
async def test_tiers_use_only_the_latest_period():  # review fold-in: years are not added up
    from arp.schemas.revenue_exposure import ActivityCatalogueMapping
    from arp.schemas.thematic import ThemeDefinition

    segments = {"p1": [_seg("p1", "Stacks", pct=0.3, period="2023"), _seg("p1", "Stacks", pct=0.3, period="2024")]}

    async def mapper(theme, labels_by_metric, llm):
        return [ActivityCatalogueMapping(activity_id="a1", metric="revenue", matched_labels=["Stacks"])], None

    definition = ThemeDefinition(name="H", description="", activities=[_ACT])
    [m] = await pick_mod.tiers(definition, [_m("p1")], segments, None, mapper)
    assert m.tier == "enabler"


@pytest.mark.asyncio
async def test_tiers_without_segments_are_unknown_and_call_nothing():  # AC-39a
    async def mapper(*a):
        raise AssertionError("called")

    out = await pick_mod.tiers(None, [_m("p1")], {}, None, mapper)
    assert [m.tier for m in out] == ["unknown"]


@pytest.mark.asyncio
async def test_pick_stores_sorted_mapping_coverage_and_note(ctx):  # AC-33 through pick
    run_id, store, tax, kw = ctx
    _save(_run(run_id).model_copy(update={
        "selection": Selection(method="weighted", cutoff_reason="weight_80", total_weight=1.0),
        "profiles": [_weighted("s1", 0.3), _weighted("s2", 0.2), _weighted("s3", 0.5, described=False)]}), store)

    async def map_stocks(profiles, activities, chunks, llm, *, fuzzy_threshold):
        return [_m("s2", None), _m("s1")], ["s9", "s4"]

    steps = {k: v for k, v in fake_steps().items() if k != "tiers"}  # real tiers: no segments, so unknown
    run = await pick_mod.pick(run_id, 1, **kw, **{**steps, "map_stocks": map_stocks})
    assert [(m.company_id, m.tier) for m in run.mapping] == [("s1", "unknown"), ("s2", "unknown")]
    assert run.coverage.unmapped == ["s4", "s9"] and run.coverage.fund_weight_share == 0.3
    assert "Coverage: 0.60 of profiled weight, 0.30 of fund weight." in tax.get(run.taxonomy_id).source_notes
    saved = pick_mod.load_run(run_id, store)
    assert saved.coverage == run.coverage and [m.company_id for m in saved.mapping] == ["s1", "s2"]


@pytest.mark.asyncio
async def test_pick_unweighted_note_is_na(ctx):  # AC-34 through pick
    run_id, store, tax, kw = ctx
    _save(_run(run_id), store)
    run = await pick_mod.pick(run_id, 1, **kw, **fake_steps())
    assert "Coverage: n/a of profiled weight, n/a of fund weight." in tax.get(run.taxonomy_id).source_notes


def _kpi(name):
    from arp.schemas.datapoints import FieldDataType, FieldDefinition

    return FieldDefinition(name=name, description=name, data_type=FieldDataType.NUMBER, extraction_instructions="x")


def _drafting(fields, seen=None):
    async def draft(criteria_text, llm):
        from arp.schemas.datapoints import DataPointSchema

        if seen is not None:
            seen.append(criteria_text)
        return DataPointSchema(name="k", description="k", fields=fields), None
    return draft


@pytest.mark.asyncio
async def test_pick_saves_the_drafted_kpis_in_order(ctx):  # AC-39
    run_id, store, tax, kw = ctx
    _save(_run(run_id), store)
    steps = {k: v for k, v in fake_steps().items() if k != "draft_kpis"}  # the real draft_kpis
    run = await pick_mod.pick(run_id, 1, **kw, **steps, draft=_drafting([_kpi("k1"), _kpi("k2"), _kpi("k3")]))
    assert [f.name for f in tax.get(run.taxonomy_id).theme.kpis] == ["k1", "k2", "k3"]


@pytest.mark.asyncio
async def test_draft_kpis_names_theme_activities_and_methodology_and_keeps_five():
    seen = []
    theme = Theme(rank=1, name="Hydrogen", description="H2 economy", supporting=["s1"], count_share=1.0)
    act = ActivityDefinition(activity_id="a1", name="PEM stacks", in_scope_description="Makes stacks",
                             out_of_scope_description="out")
    out = await pick_mod.draft_kpis(theme, [act], "Electrolyser capacity counts.", None,
                                    _drafting([_kpi(f"k{i}") for i in range(7)], seen))
    assert [f.name for f in out] == ["k0", "k1", "k2", "k3", "k4"]
    assert all(s in seen[0] for s in ("Hydrogen", "H2 economy", "PEM stacks", "Makes stacks", "Electrolyser capacity counts."))


@pytest.mark.asyncio
async def test_pick_sorts_activities_by_activity_id(ctx):  # spec: `activities` by `activity_id`
    run_id, store, _tax, kw = ctx
    _save(_run(run_id), store)

    async def synthesize(theme, profiles, chunks, llm, *, fuzzy_threshold):
        return [ActivityDefinition(activity_id=i, name=i, in_scope_description="in", out_of_scope_description="out")
                for i in ("b", "a")]

    run = await pick_mod.pick(run_id, 1, **kw, **{**fake_steps(), "synthesize": synthesize})
    assert [a.activity_id for a in run.activities] == ["a", "b"]
