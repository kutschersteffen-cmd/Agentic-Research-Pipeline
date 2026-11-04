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

    async def map_stocks(profiles, activities, chunks, llm):
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
