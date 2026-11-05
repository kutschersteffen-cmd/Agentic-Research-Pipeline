from arp.research.indirect_exposure.criticality import (
    apply_criticality_overlay,
    critical_isic_codes,
)
from arp.research.indirect_exposure.migrate import icio_sectors
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition


def test_critical_isic_codes_returns_nonempty_set():
    assert len(critical_isic_codes()) > 0


def _theme() -> ThemeDefinition:
    return ThemeDefinition(
        name="Electrification",
        description="",
        activities=[
            ActivityDefinition(
                name="Battery materials mining", in_scope_description="x", out_of_scope_description="y", core_sectors=icio_sectors("B07")
            ),
            ActivityDefinition(
                name="Software", in_scope_description="x", out_of_scope_description="y", core_sectors=icio_sectors("J62_63")
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


def _one(sectors: list[str]) -> ThemeDefinition:
    return ThemeDefinition(name="t", description="", activities=[
        ActivityDefinition(name="a", in_scope_description="x", out_of_scope_description="y", core_sectors=sectors)
    ])


def test_copper_production_is_critical():  # AC-42
    assert apply_criticality_overlay(_one(["Copper production"])).activities[0].criticality_flag is True


def test_wheat_is_not_critical():  # AC-43
    assert apply_criticality_overlay(_one(["Cultivation of wheat"])).activities[0].criticality_flag is False
