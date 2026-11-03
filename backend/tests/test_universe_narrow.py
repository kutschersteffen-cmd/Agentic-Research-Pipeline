"""`arp universe narrow` (spec theme-funnel AC-26...AC-31, amended 2026-11-03)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.schemas.common import CompanyRef
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.taxonomy_store import TaxonomyStore
from arp.universe_narrow import narrow_universe


@pytest.fixture(autouse=True)
def _no_postgres(monkeypatch):
    monkeypatch.setattr("arp.db.session.require_postgres", lambda s: None)
    monkeypatch.setattr("arp.db.session.require_cutover", lambda s: None)


def _theme(*codes):
    act = ActivityDefinition(name="e", in_scope_description="i", out_of_scope_description="o", core_isic_codes=list(codes))
    return ThemeDefinition(name="t", description="", activities=[act])


def test_narrow_drops_out_of_sector():  # AC-26 (function)
    kept, dropped = narrow_universe([CompanyRef(company_id="X", name="X", isic_code="2610")], _theme("2790"))
    assert kept == []
    assert dropped == [{"company_id": "X", "name": "X", "isic_code": "2610", "nace_code": None,
                        "reason": "no sector match (company 26, taxonomy 27)"}]


def test_narrow_keeps_company_without_codes():  # AC-27
    kept, _ = narrow_universe([CompanyRef(company_id="X", name="X", gics_code="2010")], _theme("2790"))
    assert [c.company_id for c in kept] == ["X"]


def test_narrow_division_width():  # AC-28
    kept, _ = narrow_universe([CompanyRef(company_id="X", name="X", isic_code="2711")], _theme("2790"))
    assert len(kept) == 1


def test_narrow_nace_matches_isic_division():
    kept, _ = narrow_universe([CompanyRef(company_id="X", name="X", nace_code="27.90")], _theme("2790"))
    assert len(kept) == 1


def test_narrow_keep_overrides():  # AC-31 (function)
    kept, dropped = narrow_universe([CompanyRef(company_id="X", name="X", isic_code="2610")], _theme("2790"), keep={"X"})
    assert [c.company_id for c in kept] == ["X"] and dropped == []


def _cli_setup(tmp_path, theme, companies):
    store = TaxonomyStore(tmp_path / "tax")
    t = store.create("t", theme, DerivationMethod.MANUAL)
    u = tmp_path / "u.json"
    u.write_text(json.dumps([c.model_dump(mode="json") for c in companies]))
    return t, u


def _narrow(tmp_path, t, u, *extra):
    return CliRunner().invoke(app, ["universe", "narrow", "--universe", str(u), "--taxonomy", t.taxonomy_id,
                                    "--taxonomies-dir", str(tmp_path / "tax"), "--out", str(tmp_path / "out.json"), *extra])


def test_narrow_cli_writes_out_and_dropped(tmp_path):  # AC-26
    t, u = _cli_setup(tmp_path, _theme("2790"), [CompanyRef(company_id="X", name="X", isic_code="2610"),
                                                CompanyRef(company_id="Y", name="Y", isic_code="2790")])
    r = _narrow(tmp_path, t, u)
    assert r.exit_code == 0, r.output
    assert [c["company_id"] for c in json.loads((tmp_path / "out.json").read_text())] == ["Y"]
    dropped = json.loads((tmp_path / "out.dropped.json").read_text())
    assert [(d["company_id"], d["reason"]) for d in dropped] == [("X", "no sector match (company 26, taxonomy 27)")]
    assert "Kept 1 of 2 companies; 1 dropped (see" in r.output


def test_narrow_cli_keep(tmp_path):  # AC-31
    t, u = _cli_setup(tmp_path, _theme("2790"), [CompanyRef(company_id="X", name="X", isic_code="2610")])
    assert _narrow(tmp_path, t, u, "--keep", "X").exit_code == 0
    assert [c["company_id"] for c in json.loads((tmp_path / "out.json").read_text())] == ["X"]
    assert json.loads((tmp_path / "out.dropped.json").read_text()) == []


def test_narrow_taxonomy_without_codes_is_noop(tmp_path):  # AC-29
    t, u = _cli_setup(tmp_path, _theme(), [CompanyRef(company_id="X", name="X", isic_code="2610")])
    r = _narrow(tmp_path, t, u)
    assert "Taxonomy has no sector codes; nothing narrowed." in r.output
    assert [c["company_id"] for c in json.loads((tmp_path / "out.json").read_text())] == ["X"]


def test_narrow_unknown_taxonomy(tmp_path):
    _, u = _cli_setup(tmp_path, _theme("2790"), [])
    r = CliRunner().invoke(app, ["universe", "narrow", "--universe", str(u), "--taxonomy", "tax_nope",
                                 "--taxonomies-dir", str(tmp_path / "tax"), "--out", str(tmp_path / "o.json")])
    assert r.exit_code == 1 and "Taxonomy not found: tax_nope" in r.output


def _golden(tmp_path, rows):
    cases = [{"case_id": cid, "company": cid, "label": label, "role": "r", "rationale": "x",
              "label_sources": ["https://example.com/a"], "documents": [{"url": "https://example.com/d.pdf"}],
              "split": "holdout", "nace_code": nace, "nace_source": "https://example.com/reg"}
             for cid, label, nace in rows]
    d = tmp_path / "set"
    d.mkdir()
    (d / "cases.json").write_text(json.dumps({"set_id": "s", "kind": "activity", "subject": "x",
                                              "labels": ["core", "peripheral", "not"], "checked_on": "2026-11-02",
                                              "cases": cases}))
    return d


def test_golden_universe_and_cases_label_lines(tmp_path):  # AC-32 shape
    d = _golden(tmp_path, [("a", "core", "27.90"), ("b", "core", "28.29"), ("c", "core", "72.19"), ("n", "not", "35.11")])
    r = CliRunner().invoke(app, ["golden-set", "exposure", "universe", "--set", str(d), "--out", str(tmp_path / "u.json")])
    assert r.exit_code == 0, r.output
    u = json.loads((tmp_path / "u.json").read_text())
    assert {c["company_id"]: c["nace_code"] for c in u} == {"a": "27.90", "b": "28.29", "c": "72.19", "n": "35.11"}
    store = TaxonomyStore(tmp_path / "tax")
    t = store.create("t", _theme("2790", "2829"), DerivationMethod.MANUAL)
    r = _narrow(tmp_path, t, tmp_path / "u.json", "--cases", str(d / "cases.json"))
    assert r.output.strip().splitlines()[-3:] == ["core dropped: 1/3", "peripheral dropped: 0/0", "not dropped: 1/1"]
