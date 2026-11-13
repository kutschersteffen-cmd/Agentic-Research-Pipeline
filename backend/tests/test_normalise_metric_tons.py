"""Emissions reported in "metric tons" convert to tCO2e; plain "tons" stays unknown, since a US filer may mean short tons."""

import pytest

from arp.extraction.extractor_agent import PeriodValue
from arp.normalise.value import typed_value
from arp.schemas.datapoints import FieldDataType, FieldDefinition
from arp.schemas.review import ReasonCode

FIELD = FieldDefinition(name="Scope 1", description="f", data_type=FieldDataType.NUMBER, unit="tCO2e", extraction_instructions="f")


def _value(unit_text, value=12.5):
    return typed_value(FIELD, PeriodValue(value=value, raw_value_text=str(value), unit_text=unit_text, period_text="FY2025"),
                       fiscal_year_end="12-31", decimal="point")


@pytest.mark.parametrize("unit_text", [
    "metric tons CO2e", "metric tonnes CO2e", "metric tons of CO2e", "metric tonnes of CO2e",
    "metric tons of CO2 equivalent", "metric tonnes of CO2 equivalent",
])
def test_metric_tons_are_tco2e(unit_text):  # AC-123
    tv = _value(unit_text)
    assert (tv.canonical_value, tv.canonical_unit, tv.reasons) == (12.5, "tCO2e", [])


def test_thousand_metric_tons(): # AC-124
    tv = _value("thousand metric tons CO2e")
    assert (tv.canonical_value, tv.canonical_unit, tv.reasons) == (12500.0, "tCO2e", [])


def test_plain_tons_stay_unknown():  # AC-125
    tv = _value("tons CO2e")
    assert tv.canonical_value is None and tv.reasons == [ReasonCode.CHECK_FAILED]
