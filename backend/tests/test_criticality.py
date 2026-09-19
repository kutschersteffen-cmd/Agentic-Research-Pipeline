from arp.research.indirect_exposure.criticality import (
    apply_criticality_overlay,
    critical_isic_codes,
    is_critical_isic_code,
    list_critical_minerals,
)
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition


def test_list_critical_minerals_well_formed():
    minerals = list_critical_minerals()
    assert len(minerals) > 0
    for mineral in minerals:
        assert mineral.name
        assert len(mineral.isic_codes) > 0
        assert mineral.source
        assert mineral.notes


def test_critical_isic_codes_returns_nonempty_set():
    assert len(critical_isic_codes()) > 0


def test_is_critical_isic_code_true_and_false_cases():
    assert is_critical_isic_code("07") is True  # mining of metal ores -- on the registry
    assert is_critical_isic_code("62") is False  # IT services -- not on the registry


def _theme() -> ThemeDefinition:
    return ThemeDefinition(
        name="Electrification",
        description="",
        activities=[
            ActivityDefinition(
                name="Battery materials mining", in_scope_description="x", out_of_scope_description="y", core_isic_codes=["07"]
            ),
            ActivityDefinition(
                name="Software", in_scope_description="x", out_of_scope_description="y", core_isic_codes=["62"]
            ),
            ActivityDefinition(name="Unclassified", in_scope_description="x", out_of_scope_description="y"),
        ],
    )


def test_apply_criticality_overlay_flags_matching_activities():
    updated = apply_criticality_overlay(_theme())
    by_name = {a.name: a for a in updated.activities}
    assert by_name["Battery materials mining"].criticality_flag is True
    assert by_name["Software"].criticality_flag is False


def test_apply_criticality_overlay_leaves_unclassified_activity_false():
    updated = apply_criticality_overlay(_theme())
    by_name = {a.name: a for a in updated.activities}
    assert by_name["Unclassified"].criticality_flag is False


def test_apply_criticality_overlay_does_not_mutate_input_theme():
    theme = _theme()
    apply_criticality_overlay(theme)
    assert all(a.criticality_flag is False for a in theme.activities)
