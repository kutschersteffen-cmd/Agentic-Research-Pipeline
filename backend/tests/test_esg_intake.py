from __future__ import annotations

import pytest

from arp.holdings.intake import IntakeError
from arp.portfolio.climate.esg_intake import ESG_TEMPLATE_COLUMNS, FIELD_IDS, ingest_esg, template, validate_esg
from arp.portfolio.loads import latest_load
from arp.storage.portfolio_store import PortfolioStore

KNOWN = {"acme", "globex"}
MONTH = "2026-09"


@pytest.fixture
def store(tmp_path):
    return PortfolioStore(tmp_path / "pf")


def row(cid="acme", n=2, **over):
    r = {"_row": n, "company_id": cid, **{f: 1.5 for f in FIELD_IDS}}
    return r | over


def run(store, raw, **kw):
    v = validate_esg(raw, month=MONTH, known_company_ids=KNOWN, **kw)
    return ingest_esg(store, v, provider="default", month=MONTH, source_ref="sha256:x")


def n_obs(store):
    return sum(len(store.load_observations(c, f)) for c in KNOWN for f in FIELD_IDS)


def test_valid_file_writes_one_observation_per_company_field(store):
    res = run(store, [row("acme"), row("globex", 3)])
    assert (res.status, res.rows) == ("written", 2)
    assert n_obs(store) == 12
    o = store.latest_observation("acme", FIELD_IDS[0])
    assert (o.source, o.period, o.notes, o.value) == ("internal_api", MONTH, "file:sha256:x", 1.5)


def test_identical_reupload_is_unchanged_and_adds_no_observations(store):
    run(store, [row()])
    assert run(store, [row()]).status == "unchanged"
    assert n_obs(store) == 6


def test_changed_reupload_appends_new_values_latest_wins(store):
    run(store, [row()])
    assert run(store, [row(**{FIELD_IDS[0]: 9.0})]).status == "written"
    assert store.latest_observation("acme", FIELD_IDS[0]).value == 9.0
    assert len(store.load_observations("acme", FIELD_IDS[0])) == 2


def test_comma_decimals_parsed_with_decimal_comma():
    v = validate_esg([row(**{FIELD_IDS[0]: "1.234,5"})], month=MONTH, known_company_ids=KNOWN, decimal=",")
    assert not v.errors and v.rows[0][FIELD_IDS[0]] == 1234.5
    assert validate_esg([row(**{FIELD_IDS[0]: "abc"})], month=MONTH, known_company_ids=KNOWN).errors


def test_unknown_company_id_rejects_whole_file_and_writes_nothing(store):
    with pytest.raises(IntakeError) as e:
        run(store, [row("acme"), row("nope", 3)])
    assert [(x.row, x.column) for x in e.value.errors] == [(3, "company_id")]
    assert n_obs(store) == 0


def test_blank_value_is_row_error(store):
    with pytest.raises(IntakeError) as e:
        run(store, [row(**{FIELD_IDS[1]: ""})])
    assert [(x.row, x.column, x.message) for x in e.value.errors] == [(2, FIELD_IDS[1], "required")]
    assert n_obs(store) == 0


def test_failed_validation_records_failed_load(store):
    with pytest.raises(IntakeError):
        run(store, [row("nope")])
    rec = latest_load(store, "esg", "default", MONTH)
    assert rec and rec.status == "failed"


def test_template_has_all_climate_field_columns():
    assert ["company_id", *FIELD_IDS] == ESG_TEMPLATE_COLUMNS and len(FIELD_IDS) == 6
    assert template("csv").decode().strip().split(",") == ESG_TEMPLATE_COLUMNS
    assert template("xlsx")[:2] == b"PK"


def test_upload_route_end_to_end(tmp_path):
    from fastapi.testclient import TestClient

    from arp.api.deps import get_portfolio_store
    from arp.api.main import app

    st = PortfolioStore(tmp_path / "pf2")
    from arp.schemas.common import CompanyRef
    st.save_company(CompanyRef(company_id="acme", name="Acme"))
    app.dependency_overrides[get_portfolio_store] = lambda: st
    try:
        c = TestClient(app)
        body = ",".join(ESG_TEMPLATE_COLUMNS) + "\nacme," + ",".join("1" for _ in FIELD_IDS) + "\n"
        up = lambda: c.post("/api/portfolio/esg/upload", data={"month": MONTH}, files={"file": ("e.csv", body)})  # noqa: E731
        assert up().json() == {"status": "written", "rows": 1}
        assert up().json()["status"] == "unchanged"
        assert c.get("/api/portfolio/esg/template?format=csv").text.startswith("company_id,")
    finally:
        app.dependency_overrides.pop(get_portfolio_store, None)


def _file_store(tmp_path):
    from arp.schemas.common import CompanyRef

    st = PortfolioStore(tmp_path / "pf3")
    st.save_company(CompanyRef(company_id="acme", name="Acme"))
    return st


def _csv(value):
    return (",".join(ESG_TEMPLATE_COLUMNS) + "\nacme," + ",".join(f'"{value}"' for _ in FIELD_IDS) + "\n").encode()


def test_comma_decimal_with_default_mapping_rejects_whole_file(tmp_path):
    from arp.portfolio.climate.esg_intake import ingest_esg_bytes

    st = _file_store(tmp_path)
    with pytest.raises(IntakeError) as e:
        ingest_esg_bytes(st, _csv("12,5"), "e.csv", provider="default", month=MONTH, source_ref=None)
    assert {x.column for x in e.value.errors} == set(FIELD_IDS)
    assert st.load_observations("acme", FIELD_IDS[0]) == []
    assert latest_load(st, "esg", "default", MONTH).status == "failed"


def test_thousands_group_with_default_mapping_is_accepted(tmp_path):
    from arp.portfolio.climate.esg_intake import ingest_esg_bytes

    st = _file_store(tmp_path)
    assert ingest_esg_bytes(st, _csv("1,234.5"), "e.csv", provider="default", month=MONTH, source_ref=None).status == "written"
    assert st.latest_observation("acme", FIELD_IDS[0]).value == 1234.5


def test_malformed_thousands_group_with_decimal_comma_is_row_error():
    assert validate_esg([row(**{FIELD_IDS[0]: "12.5"})], month=MONTH, known_company_ids=KNOWN, decimal=",").errors
