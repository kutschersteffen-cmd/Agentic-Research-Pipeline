from __future__ import annotations

from arp.schemas.common import CompanyRef
from arp.schemas.issuer import IdentifierMap, issuer_key
from arp.storage.identifier_map import IdentifierMapStore
from arp.universe_workbench.mapping import MasterIndex, enrich, map_company

LEI = "529900ABCDEFGHIJ1234"


def _store(tmp_path, rows):
    s = IdentifierMapStore(tmp_path / "idmap.jsonl")
    for key, scheme, value, *rest in rows:
        s.add(IdentifierMap(issuer_key=key, scheme=scheme, value=value,
                            valid_to=rest[0] if rest else None))
    return s


def _map(store, **kw):
    return map_company(CompanyRef(company_id="X", name="X", **kw), MasterIndex.build(store))


def test_mapped_by_lei_isin_cik(tmp_path):
    s = _store(tmp_path, [("I1", "LEI", LEI), ("I1", "ISIN", "US0378331005"), ("I1", "CIK", "320193")])
    for kw in ({"lei": LEI}, {"isin": "US0378331005"}, {"cik": "320193"}):
        m = _map(s, **kw)
        assert (m.status, m.issuer_key, m.key_scheme) == ("mapped", "I1", "INTERNAL")
        assert m.identifiers == {"LEI": [LEI], "CIK": ["320193"], "ISIN": ["US0378331005"]}


def test_cik_leading_zeros_and_lower_case_lei(tmp_path):
    s = _store(tmp_path, [("I1", "CIK", "320193"), ("I2", "LEI", LEI)])
    assert _map(s, cik="0000320193").issuer_key == "I1"
    assert _map(s, lei=" 5299 00abcdefghij1234").issuer_key == "I2"


def test_ambiguous_when_identifier_points_at_two_issuers(tmp_path):
    s = _store(tmp_path, [("I1", "ISIN", "US1"), ("I2", "ISIN", "US1")])
    m = _map(s, isin="US1")
    assert m.status == "ambiguous" and m.issuer_key is None and m.candidates == ["I1", "I2"]


def test_unmapped_and_no_identifier(tmp_path):
    s = _store(tmp_path, [("I1", "CIK", "1")])
    assert _map(s, cik="999").status == "unmapped"
    assert _map(s).status == "no_identifier"


def test_expired_rows_are_ignored(tmp_path):
    s = _store(tmp_path, [("I1", "CIK", "1", "2000-01-01")])
    assert _map(s, cik="1").status == "unmapped"


def test_missing_map_file_is_empty(tmp_path):
    s = IdentifierMapStore(tmp_path / "none.jsonl")
    assert _map(s, cik="1").status == "unmapped"
    assert _map(s).status == "no_identifier"
    c = CompanyRef(company_id="X", name="X", cik="1")
    assert map_company(c, None).status == "unmapped"
    assert map_company(CompanyRef(company_id="X", name="X"), None).status == "no_identifier"


def test_parity_with_issuer_key(tmp_path):
    s = _store(tmp_path, [("I1", "LEI", LEI), ("I2", "ISIN", "US2"), ("I3", "CIK", "3"),
                          ("I4", "CIK", "4"), ("I5", "CIK", "4"), ("I6", "ISIN", "US6"), ("I7", "CIK", "6"),
                          ("I8", "ISIN", "US8"), ("I9", "ISIN", "US8"), ("I8", "CIK", "8")])
    idx = MasterIndex.build(s)
    cos = [
        dict(lei=LEI), dict(isin="US2", cik="3"), dict(cik="4"),
        dict(isin="US6", cik="6"), dict(cik="404"), dict(),
        dict(isin="US8", cik="8"),  # first scheme ambiguous, a later one unique
    ]
    for kw in cos:
        c = CompanyRef(company_id="X", name="X", **kw)
        k, scheme = issuer_key(c, s)
        m = map_company(c, idx)
        assert (scheme == "INTERNAL") == (m.status == "mapped")
        if m.status == "mapped":
            assert m.issuer_key == k


def test_enrich_fills_only_empty_fields(tmp_path):
    s = _store(tmp_path, [("I1", "LEI", LEI), ("I1", "CIK", "320193"), ("I1", "ISIN", "US1")])
    c = CompanyRef(company_id="X", name="X", cik="320193", lei="OWNLEI", country="DE")
    e = enrich(c, map_company(c, MasterIndex.build(s)))
    assert (e.lei, e.cik, e.isin, e.country) == ("OWNLEI", "320193", "US1", "DE")


def test_enrich_skips_multi_valued_scheme(tmp_path):
    s = _store(tmp_path, [("I1", "CIK", "5"), ("I1", "ISIN", "A"), ("I1", "ISIN", "B")])
    c = CompanyRef(company_id="X", name="X", cik="5")
    assert enrich(c, map_company(c, MasterIndex.build(s))).isin is None


def test_index_reads_the_file_once(tmp_path, monkeypatch):
    s = _store(tmp_path, [("I1", "CIK", "1")])
    calls = []
    orig = IdentifierMapStore.rows
    monkeypatch.setattr(IdentifierMapStore, "rows", lambda self: (calls.append(1), orig(self))[1])
    idx = MasterIndex.build(s)
    c = CompanyRef(company_id="X", name="X", cik="1")
    for _ in range(5000):
        map_company(c, idx)
    assert len(calls) == 1


def test_same_identifier_spelled_twice_is_one_value(tmp_path):
    s = _store(tmp_path, [("I1", "CIK", "320193"), ("I1", "CIK", "0000320193"), ("I1", "ISIN", "US1")])
    c = CompanyRef(company_id="X", name="X", isin="US1")
    m = map_company(c, MasterIndex.build(s))
    assert m.identifiers["CIK"] == ["320193"]
    assert enrich(c, m).cik == "320193"


def test_enrich_treats_whitespace_only_fields_as_empty(tmp_path):
    s = _store(tmp_path, [("I1", "CIK", "320193"), ("I1", "LEI", LEI)])
    c = CompanyRef(company_id="X", name="X", cik="320193", lei="  ")
    assert enrich(c, map_company(c, MasterIndex.build(s))).lei == LEI


def test_enrich_leaves_an_ambiguous_mapping_alone(tmp_path):
    s = _store(tmp_path, [("I1", "ISIN", "US8"), ("I2", "ISIN", "US8"), ("I1", "CIK", "8")])
    c = CompanyRef(company_id="X", name="X", isin="US8")
    m = map_company(c, MasterIndex.build(s))
    assert m.status == "ambiguous"
    assert enrich(c, m) == c
