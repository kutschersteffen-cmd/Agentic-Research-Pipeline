from arp.presets.registry import PRESETS
from arp.presets.transition_delivery_kpis import (
    FIELD_PREFIXES,
    SCHEMA_ID,
    build_transition_delivery_kpis_schema,
)

IDS = [
    "tc_alt_fuel_share_pct", "tc_nh3_electrolytic_pct", "tc_meoh_electrolytic_pct", "tc_electrolysis_lc_power_pct",
    "tc_ccs_capex_share_pct", "tc_zev_sales_share_pct", "tc_fleet_lc_share_pct", "tc_saf_share_pct",
    "tc_ship_lc_fuel_share_pct",
]
CODES = [["2394"], ["201"], ["201"], ["201"], ["061", "062"], ["2910"], ["4923"], ["511"], ["501", "502"]]


def test_ac186_delivery_kpi_preset():
    s = build_transition_delivery_kpis_schema()
    assert [f.field_id for f in s.fields] == IDS == list(FIELD_PREFIXES)
    for f, codes in zip(s.fields, CODES, strict=True):
        assert (f.high_risk, f.unit, f.check_config.min_value, f.check_config.max_value) == (True, "%", 0, 100)
        assert f.applicability_rules.sector_codes == codes == list(FIELD_PREFIXES[f.field_id])
    assert PRESETS[SCHEMA_ID]().fields == s.fields
