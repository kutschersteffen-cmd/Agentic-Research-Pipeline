import csv
from pathlib import Path

from arp.research.indirect_exposure.nace import (
    _SECTORS,
    isic_to_nace2,
    nace2_to_isic4,
    nace_known,
    nace_sectors,
    nace_title,
    normalise_nace,
    sector_nace2_codes,
)

_ICIO = _SECTORS.parent.parent / "migrate" / "exiobase_ixi_to_icio2025.csv"


def _table() -> list[dict[str, str]]:
    with Path(_SECTORS).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _rows(word: str) -> list[dict[str, str]]:
    return [r for r in _table() if word in r["exiobase_sector"]]


def test_ac1_every_exiobase_sector_present():
    with _ICIO.open(newline="", encoding="utf-8") as f:
        names = {r["exiobase_sector"] for r in csv.DictReader(f)}
    assert len(names) == 163
    assert names <= {r["exiobase_sector"] for r in _table()}


def test_ac1b_no_empty_codes():
    assert all(r["nace2_code"] and r["nace21_code"] for r in _table())


def test_ac2_wind_is_renewable():
    rows = _rows("electricity by wind")
    assert rows and all(r["nace21_code"] == "35.12" for r in rows)


def test_ac2b_coal_is_non_renewable():
    rows = _rows("electricity by coal")
    assert rows and all(r["nace21_code"] == "35.11" for r in rows)


def test_ac2c_solar_pv_is_renewable():
    rows = _rows("solar photovoltaic")
    assert rows and all(r["nace21_code"] == "35.12" for r in rows)


def test_ac2d_no_cross_division_for_2711():
    # 27.11 -> 27.11 and 29.10 in Eurostat; division 27 as a whole also reaches 29 and 32
    assert not [r for r in _table() if r["nace2_code"][:2] == "27" and r["nace21_code"][:2] != "27"]


def test_match_rule():
    assert {"Mining of copper ores and concentrates", "Mining of nickel ores and concentrates"} <= nace_sectors(
        "07.29", "2"
    )
    assert "Manufacture of electrical machinery and apparatus n.e.c. (31)" in nace_sectors("27", "2")
    assert "Production of electricity by wind" in nace_sectors("35.12", "2.1")
    assert "Production of electricity by wind" not in nace_sectors("35.11", "2.1")
    assert nace_sectors("35.12", "2") & {"Production of electricity by wind"} == set()


def test_normalise():
    assert normalise_nace(" 0729 ") == "07.29" and normalise_nace("35.11.1") == "35.11"
    assert normalise_nace("27") == "27" and normalise_nace("07.2") == "07.2"


def test_isic_route():
    assert isic_to_nace2("2710") == ["27.11", "27.12"]


def test_known_and_title():
    assert nace_known("35.11", "2") and nace_known("35.12", "2.1") and not nace_known("99.99", "2")
    assert nace_title("35.11", "2") and nace_title("99.99", "2") is None


def test_sector_nace2_codes_and_isic4():
    assert sector_nace2_codes("Copper production") == ["24.44"]
    assert nace2_to_isic4("24.44") == ["2420"]
