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

    async def top_down(sources, theme_name, llm, settings, fetch):
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
