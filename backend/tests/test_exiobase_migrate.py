import re

import pytest

from arp.research.indirect_exposure.factory import sectors
from arp.research.indirect_exposure.migrate import (
    UnknownIcioCode,
    convert_document,
    convert_parts,
    convert_theme,
    icio_sectors,
)


def test_sectors_count_and_first():
    assert len(sectors()) == 163
    assert sectors()[0] == "Cultivation of paddy rice"
    assert not any(re.search(r" \(\d+\)$", s) for s in sectors())


def test_icio_sectors_b07():
    s = icio_sectors("B07")
    assert len(s) == 8 and "Mining of uranium and thorium ores" in s
    assert s == sorted(s)


def test_icio_sectors_split_code():
    s = icio_sectors("D_GEN_REN")
    assert len(s) == 7 and all(n.startswith("Production of electricity by") for n in s)


def test_unknown_code():
    with pytest.raises(UnknownIcioCode) as e:
        icio_sectors("ZZZ")
    assert e.value.code == "ZZZ"


def test_convert_theme_key_order():
    theme = {"activities": [{"activity_id": "a1", "name": "n", "core_isic_codes": ["B07"], "source_citation": None}]}
    assert convert_theme(theme) is True
    assert list(theme["activities"][0]) == ["activity_id", "name", "core_sectors", "source_citation"]
    assert theme["activities"][0]["core_sectors"] == icio_sectors("B07")
    assert convert_theme(theme) is False


def test_convert_unmapped():
    theme = {"activities": [], "standards_mapping": {"unmapped_isic_codes": ["B07"]}}
    assert convert_theme(theme) is True
    assert theme["standards_mapping"] == {"unmapped_sectors": icio_sectors("B07")}


def test_convert_parts():
    parts = [{"icio_code": "B07", "share": 0.4}, {"icio_code": "D_GEN_REN", "share": 0.6}]
    assert convert_parts("split", parts) == [
        {"sectors": icio_sectors("B07"), "share": 0.4},
        {"sectors": icio_sectors("D_GEN_REN"), "share": 0.6},
    ]
    assert convert_parts("nodes", [{"region": "DE", "sector": "Copper production", "share": 1}]) is None
    assert convert_parts("split", [{"sectors": ["x"], "share": 1}]) is None


def test_convert_document_taxonomy_and_bare_theme():
    act = {"activity_id": "a1", "core_isic_codes": ["B07"]}
    tax = {"theme": {"activities": [dict(act)]}}
    assert convert_document(tax) is True
    assert tax["theme"]["activities"][0]["core_sectors"] == icio_sectors("B07")
    bare = {"activities": [dict(act)]}
    assert convert_document(bare) is True
    assert "core_isic_codes" not in bare["activities"][0]


def test_convert_parts_llm_like_split():
    assert convert_parts("llm", [{"icio_code": "B07", "share": 1}]) == [{"sectors": icio_sectors("B07"), "share": 1}]


def test_convert_theme_unknown_code():
    with pytest.raises(UnknownIcioCode):
        convert_theme({"activities": [{"core_isic_codes": ["ZZZ"]}]})


def test_convert_document_bare_run_theme():
    theme = {"activities": [{"activity_id": "a1", "name": "n", "core_isic_codes": ["B07"]}]}
    assert convert_document(theme) is True
    assert theme["activities"][0]["core_sectors"] == icio_sectors("B07")
