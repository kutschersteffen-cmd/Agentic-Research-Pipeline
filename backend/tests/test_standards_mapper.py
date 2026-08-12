import csv
import io
from pathlib import Path

from arp.config import Settings
from arp.research.standards_mapping.crosswalk import CrosswalkTable, load_crosswalk
from arp.research.standards_mapping.gics import GicsReferenceEntry, _GicsSelection, _GicsSelectionList, load_gics_reference
from arp.research.standards_mapping.mapper import format_standards_csv, map_activity_standards, map_theme_to_standards
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition

_SAMPLE_DIR = Path(__file__).parent.parent / "arp/research/standards_mapping/sample_data"


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )


def _sample_tables():
    nace = load_crosswalk(_SAMPLE_DIR / "isic_nace_sample.csv")
    naics = load_crosswalk(_SAMPLE_DIR / "isic_naics_sample.csv")
    sic = load_crosswalk(_SAMPLE_DIR / "isic_sic_sample.csv")
    gics_ref = load_gics_reference(_SAMPLE_DIR / "gics_reference_sample.csv")
    return nace, naics, sic, gics_ref


async def test_map_activity_standards_with_known_isic_code(fake_llm):
    nace, naics, sic, gics_ref = _sample_tables()
    activity = ActivityDefinition(
        name="EV manufacturing", in_scope_description="Assembly of electric vehicles.", out_of_scope_description="", core_isic_codes=["29"]
    )
    draft = _GicsSelectionList(matches=[_GicsSelection(code="25", rationale="Automobile manufacturing.")])
    llm = fake_llm({_GicsSelectionList.__name__: [draft]})

    mapping, _usage = await map_activity_standards(activity, nace, naics, sic, gics_ref, llm)
    assert [m.code for m in mapping.nace_codes] == ["29"]
    assert [m.code for m in mapping.naics_codes] == ["3361"]
    assert [m.code for m in mapping.sic_codes] == ["3711"]
    assert [m.code for m in mapping.gics] == ["25"]
    assert mapping.unmapped_isic_codes == []


async def test_map_activity_standards_unmapped_isic_code(fake_llm):
    nace, naics, sic, gics_ref = _sample_tables()
    activity = ActivityDefinition(name="Unknown", in_scope_description="x", out_of_scope_description="", core_isic_codes=["99"])
    llm = fake_llm({_GicsSelectionList.__name__: [_GicsSelectionList(matches=[])]})

    mapping, _usage = await map_activity_standards(activity, nace, naics, sic, gics_ref, llm)
    assert mapping.nace_codes == []
    assert mapping.unmapped_isic_codes == ["99"]


async def test_map_theme_to_standards_uses_sample_data_when_requested(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    theme = ThemeDefinition(
        name="Electrification", description="",
        activities=[ActivityDefinition(name="EV manufacturing", in_scope_description="x", out_of_scope_description="", core_isic_codes=["29"])],
    )
    llm = fake_llm({_GicsSelectionList.__name__: [_GicsSelectionList(matches=[])]})

    updated, _usage = await map_theme_to_standards(theme, settings, llm, use_sample_icio=False, use_sample_standards=True)
    mapping = updated.activities[0].standards_mapping
    assert mapping is not None
    assert [m.code for m in mapping.naics_codes] == ["3361"]


async def test_map_theme_to_standards_no_tables_configured_skips_gracefully(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    theme = ThemeDefinition(
        name="Electrification", description="",
        activities=[ActivityDefinition(name="EV manufacturing", in_scope_description="x", out_of_scope_description="", core_isic_codes=["29"])],
    )
    llm = fake_llm({})  # no GICS call expected: empty reference list short-circuits

    updated, _usage = await map_theme_to_standards(theme, settings, llm, use_sample_icio=False, use_sample_standards=False)
    mapping = updated.activities[0].standards_mapping
    assert mapping is not None
    assert mapping.nace_codes == mapping.naics_codes == mapping.sic_codes == mapping.gics == []
    assert mapping.unmapped_isic_codes == []  # no table was loaded, so "unmapped" can't be determined
    assert llm.calls == []


def test_format_standards_csv():
    from arp.schemas.standards import ActivityStandardsMapping, GicsMatch, StandardCodeMatch

    theme = ThemeDefinition(
        name="Electrification", description="",
        activities=[
            ActivityDefinition(
                name="EV manufacturing", in_scope_description="x", out_of_scope_description="", core_isic_codes=["29"],
                standards_mapping=ActivityStandardsMapping(
                    nace_codes=[StandardCodeMatch(code="29", label="Motor vehicles")],
                    naics_codes=[StandardCodeMatch(code="3361", label="Motor Vehicle Manufacturing")],
                    sic_codes=[StandardCodeMatch(code="3711", label="Motor Vehicles")],
                    gics=[GicsMatch(code="25", label="Consumer Discretionary", rationale="Auto manufacturing.")],
                ),
            )
        ],
    )
    rows = list(csv.reader(io.StringIO(format_standards_csv(theme))))
    assert rows[0][0] == "activity_id"
    assert rows[1][1] == "EV manufacturing"
    assert rows[1][3] == "29"  # nace_codes
    assert rows[1][4] == "3361"  # naics_codes
    assert rows[1][6] == "25"  # gics_codes
    assert "Auto manufacturing." in rows[1][8]  # gics_rationale
