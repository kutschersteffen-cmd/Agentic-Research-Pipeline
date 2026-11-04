from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from arp.db import models as m
from arp.db.session import transaction
from arp.research.stock_inference.schemas import InferStock
from arp.research.stock_inference.stored import load_segments, match_company, stored_data
from arp.storage.postgres import get_engine

ISIN = "NO0010081235"


def _snapshot(dsn):
    with get_engine(dsn).connect() as c:
        return [
            [tuple(r) for r in c.execute(text(f"SELECT * FROM {t} ORDER BY id"))]
            for t in ("companies", "company_identifiers")
        ]


def _company(dsn, name="Nel ASA", isin=ISIN, **attrs):
    with Session(get_engine(dsn)) as s, s.begin():
        c = m.Company(name=name, **attrs)
        s.add(c)
        s.flush()
        if isin:
            s.add(m.CompanyIdentifier(company_id=c.id, scheme="ISIN", value=isin))
        return c.id


def test_isin_match_is_read_only(pg):
    cid = _company(pg)
    before = _snapshot(pg)
    stock = InferStock(company_id="x", name="Other", isin=ISIN, lei="5493001KJTIIGC8Y1R12")
    with transaction(pg) as s:
        assert match_company(s, stock) == cid
    assert _snapshot(pg) == before


def test_no_match_returns_none_and_writes_nothing(pg):
    _company(pg)
    before = _snapshot(pg)
    with transaction(pg) as s:
        assert match_company(s, InferStock(company_id="x", name="Nobody", isin="US0000000000", cik="123")) is None
    assert _snapshot(pg) == before


def test_name_match_case_insensitive_and_ambiguous(pg):
    cid = _company(pg, isin=None)
    with transaction(pg) as s:
        assert match_company(s, InferStock(company_id="x", name="nel asa")) == cid
    _company(pg, name="NEL ASA", isin=None)
    with transaction(pg) as s:
        assert match_company(s, InferStock(company_id="x", name="Nel ASA")) is None


def test_stored_data_codes_exiobase_and_newest_fact(pg):
    cid = _company(pg, isic_code="2011", sector="Industrials")
    with Session(get_engine(pg)) as s, s.begin():
        s.add(m.Field(field_id="f1", kind=m.FieldKind.EXTRACTED))
        s.flush()
        s.add(m.FieldDefinition(field_id="f1", version=1, name="f1", data_type="number", definition={}))
        s.flush()
        for i, (period, v) in enumerate((("2023-12-31", 1), ("2024-12-31", 2))):
            obs = m.FieldObservation(company_id=cid, field_id="f1", field_version=1, source_kind=m.SourceKind.MANUAL,
                                     value=v, value_state=m.ValueState.FOUND, confidence=0.9)
            s.add(obs)
            s.flush()
            s.add(m.CompanyFact(company_id=cid, field_id="f1", period_end=date.fromisoformat(period), value=v,
                                basis=str(i), status=m.FactStatus.APPROVED, observation_id=obs.id))
    stock = InferStock(company_id="x", name="Nel ASA", codes={"nace": "20.1"})
    with transaction(pg) as s:
        out = stored_data(s, stock, cid, {})
    assert out["codes"] == {"nace": "20.1", "isic_code": "2011", "sector": "Industrials"}
    assert out["exiobase"]
    assert [(f["field_id"], f["period_end"], f["value"]) for f in out["facts"]] == [("f1", "2024-12-31", 2)]
    assert out["segments"] == []


def test_load_segments_and_shares(tmp_path):
    p = tmp_path / "seg.csv"
    p.write_text(
        "data_point_id,company_id,metric,label,description,value,unit,period\n"
        "1,x,revenue,Total Revenue,,100,USD,2024\n"
        "2,x,revenue,Electrolysers,,40,USD,2024\n"
    )
    segs = load_segments(p)
    stock = InferStock(company_id="x", name="n")
    out = stored_data(None, stock, None, segs)
    assert out["segments"] == [{"label": "Electrolysers", "metric": "revenue", "value": 40.0, "unit": "USD",
                                "period": "2024", "share": 0.4}]
    assert out["facts"] == [] and out["codes"] == {}
