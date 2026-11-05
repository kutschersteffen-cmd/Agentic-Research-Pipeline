from pathlib import Path

from arp.config import Settings
from arp.research.authority_taxonomy.consolidate import consolidate
from arp.research.authority_taxonomy.extract import SourceExtraction, _ActivitiesDraft, extract_source
from arp.research.indirect_exposure.core_sectors import _CoreSectorSelection
from arp.research.indirect_exposure.factory import SAMPLE_DIR, resolve_indirect_exposure_model
from arp.research.indirect_exposure.migrate import icio_sectors
from arp.research.standards_mapping.gics import _GicsSelectionList
from arp.schemas.authority_taxonomy import Definition, SectorCode, SourceCitation, Technology, Threshold, merge_key
from arp.schemas.thematic import ActivityDefinition
from tests.conftest import FakeLLMClient
from tests.test_authority_taxonomy_extract import _llm

FIX = Path(__file__).parent / "fixtures" / "authority_taxonomy"


def _settings(tmp_path, io: bool = False) -> Settings:
    return Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
        value_chain_dir=SAMPLE_DIR if io else None,
    )


def _act(name, url, role="core", isic=None):
    return ActivityDefinition(
        name=name, in_scope_description=name, out_of_scope_description="", value_chain_role=role,
        core_sectors=[s for c in isic or [] for s in icio_sectors(c)], citations=[SourceCitation(quote=name, source_url=url)],
    )


def _fake(n: int, isic: list[str] | None = None) -> FakeLLMClient:
    script = {_GicsSelectionList.__name__: [_GicsSelectionList(matches=[]) for _ in range(n)]}
    if isic is not None:
        script[_CoreSectorSelection.__name__] = [_CoreSectorSelection(sectors=[s for c in isic for s in icio_sectors(c)], rationale="r") for _ in range(n)]
    return FakeLLMClient(script)


async def _run(exts, tmp_path, *, value_chain=False, model=None, io=False, llm=None):
    return await consolidate(
        exts, theme_name="hydrogen", scope="", value_chain=value_chain, settings=_settings(tmp_path, io),
        llm=llm or _fake(10), value_chain_model=model,
    )


async def test_merge_keeps_both_citations(tmp_path):
    a = SourceExtraction(url="A", activities=[_act("Electrolyser stack manufacturing", "A")], report={"activities": "found"})
    b = SourceExtraction(url="B", activities=[_act("electrolyser-stack manufacturing", "B")])
    theme, _ = await _run([a, b], tmp_path)
    keys = [merge_key(x.name) for x in theme.activities]
    assert keys.count(merge_key("Electrolyser stack manufacturing")) == 1
    assert [c.source_url for c in theme.activities[0].citations] == ["A", "B"]
    assert theme.checklist_report == {"A": {"activities": "found"}, "B": {}}


async def test_value_chain_role_present(tmp_path):
    a = SourceExtraction(url="A", activities=[_act("Stacks", "A"), _act("Membranes", "A", role="upstream")])
    b = SourceExtraction(url="B", activities=[_act("Power electronics", "B", role="enabling"), _act("stacks", "B")])
    theme, _ = await _run([a, b], tmp_path, value_chain=True, model=resolve_indirect_exposure_model(_settings(tmp_path), use_sample=True))
    roles = {x.name: x.value_chain_role for x in theme.activities}
    assert roles == {"Stacks": "core", "Membranes": "upstream", "Power electronics": "enabling"}


async def test_input_extractions_unchanged(tmp_path):
    from arp.schemas.authority_taxonomy import ActivityCriterion
    a = SourceExtraction(url="A", activities=[_act("Stacks", "A")])
    b = SourceExtraction(url="B", activities=[_act("stacks", "B")])
    b.activities[0].criteria = [ActivityCriterion(text="c"), ActivityCriterion(text="c")]
    b.activities[0].seed_keywords = ["k"]
    before = [a.model_dump(), b.model_dump()]
    theme, _ = await _run([a, b], tmp_path)
    assert [a.model_dump(), b.model_dump()] == before
    assert [c.text for c in theme.activities[0].criteria] == ["c"]


async def test_no_model_still_labels_isic_division(tmp_path):  # sector -> ISIC goes through NACE, no IO model needed
    ext = SourceExtraction(url="A", activities=[_act("Power", "A", isic=["D"])])
    theme, _ = await _run([ext], tmp_path)
    assert [c.code for c in theme.activities[0].sector_codes if c.system == "ISIC"] == ["D35"]


async def test_exiobase_top5(tmp_path):
    model = resolve_indirect_exposure_model(_settings(tmp_path), use_sample=True)
    ext = SourceExtraction(url="A", activities=[_act("Stacks", "A", isic=["C27"])])
    theme, notes = await _run([ext], tmp_path, value_chain=True, model=model, io=True)
    exio = [c for c in theme.activities[0].sector_codes if c.origin == "exiobase"]
    assert len(exio) == 5
    assert all(c.system == "ISIC" and c.code != "C27" for c in exio)
    assert "no IO model" not in notes


async def test_map_standards_origin(tmp_path):
    llm = _llm(_ActivitiesDraft=_ActivitiesDraft.model_validate({"activities": [{
        "name": "Wind power generation", "in_scope_description": "Electricity from wind",
        "quote": "installations generating electricity from wind energy"}]}))
    ext = await extract_source("U", (FIX / "power_gen.txt").read_text(), theme_name="wind", scope="", value_chain=False, llm=llm)
    theme, _ = await _run([ext], tmp_path, io=True, llm=_fake(1, isic=["D"]))
    codes = [c.model_dump() for c in theme.activities[0].sector_codes]
    assert {"system": "ISIC", "code": "D35", "origin": "map_standards"} in codes


async def test_value_chain_off_all_core(tmp_path):
    ext = SourceExtraction(url="A", activities=[_act("Stacks", "A", isic=["C27"])])
    theme, _ = await _run([ext], tmp_path, io=True)
    assert all(a.value_chain_role == "core" for a in theme.activities)
    assert not any(c.origin == "exiobase" for a in theme.activities for c in a.sector_codes)


async def test_no_io_model_note(tmp_path):
    ext = SourceExtraction(url="A", activities=[_act("Stacks", "A")])
    theme, notes = await _run([ext], tmp_path, value_chain=True)
    assert "no IO model" in notes
    assert not any(c.origin == "exiobase" for a in theme.activities for c in a.sector_codes)


def _c(q, url):
    return [SourceCitation(quote=q, source_url=url)]


async def test_theme_level_items_merged_across_sources(tmp_path):
    a = SourceExtraction(
        url="A", technologies=[Technology(name="PEM electrolysis", citations=_c("t", "A"))],
        definitions=[Definition(term="Green hydrogen", text="x", citations=_c("d", "A"))],
        thresholds=[Threshold(text="50 %", citations=_c("q", "A"))],
    )
    b = SourceExtraction(
        url="B", technologies=[Technology(name="pem-electrolysis", citations=_c("t", "B"))],
        definitions=[Definition(term="green hydrogen", text="x", citations=_c("d", "B"))],
        thresholds=[Threshold(text="half", citations=_c("q", "B")), Threshold(text="other", citations=_c("z", "B"))],
    )
    theme, _ = await _run([a, b], tmp_path)
    assert len(theme.technologies) == 1 and [c.source_url for c in theme.technologies[0].citations] == ["A", "B"]
    assert len(theme.definitions) == 1 and [c.source_url for c in theme.definitions[0].citations] == ["A", "B"]
    assert [t.text for t in theme.thresholds] == ["50 %", "other"]
    assert [c.source_url for c in theme.thresholds[0].citations] == ["A", "B"]


async def test_sector_codes_deduped_on_first_activity(tmp_path):
    code = SectorCode(system="NACE", code="C28", origin="source")
    a = SourceExtraction(url="A", activities=[_act("Stacks", "A")], sector_codes=[code, code.model_copy()])
    theme, _ = await _run([a], tmp_path)
    assert [(c.system, c.code, c.origin) for c in theme.activities[0].sector_codes if c.origin == "source"] == [("NACE", "C28", "source")]
