from pathlib import Path

from arp.research.standards_mapping.crosswalk import CrosswalkTable, load_crosswalk
from arp.schemas.standards import StandardCodeMatch


def _table() -> CrosswalkTable:
    return CrosswalkTable(
        {
            "29": [StandardCodeMatch(code="3361", label="Motor Vehicle Manufacturing")],
            "27": [StandardCodeMatch(code="3353", label="Electrical Equipment Manufacturing")],
        }
    )


def test_exact_match():
    assert _table().lookup("29") == [StandardCodeMatch(code="3361", label="Motor Vehicle Manufacturing")]


def test_prefix_match_finer_query_code():
    # a taxonomy ISIC code finer than the table's granularity still resolves
    assert _table().lookup("2910") == [StandardCodeMatch(code="3361", label="Motor Vehicle Manufacturing")]


def test_prefix_match_coarser_table_entry():
    table = CrosswalkTable({"2910": [StandardCodeMatch(code="3361", label="Motor Vehicle Manufacturing")]})
    assert table.lookup("29") == [StandardCodeMatch(code="3361", label="Motor Vehicle Manufacturing")]


def test_no_match_returns_empty():
    assert _table().lookup("99") == []


def test_lookup_many_tracks_unmapped_codes():
    matches, unmapped = _table().lookup_many(["29", "99"])
    assert matches == [StandardCodeMatch(code="3361", label="Motor Vehicle Manufacturing")]
    assert unmapped == ["99"]


def test_empty_table_is_falsy():
    assert not CrosswalkTable.empty()
    assert bool(_table())


def test_load_crosswalk_from_bundled_sample():
    path = Path(__file__).parent.parent / "arp/research/standards_mapping/sample_data/isic_naics_sample.csv"
    table = load_crosswalk(path)
    assert table.lookup("29") == [StandardCodeMatch(code="3361", label="Motor Vehicle Manufacturing")]
