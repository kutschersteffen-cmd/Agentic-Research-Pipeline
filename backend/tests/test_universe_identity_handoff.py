"""Spec universe-identity-handoff (docs/superpowers/specs/2026-11-03-universe-identity-handoff-design.md)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import arp.cli.identity as cli_identity
from arp.discovery.identity_pipeline import create_identity_run, enriched_universe, run_identity_resolution
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import IdentityResolutionResult, IdentitySignals, IdentityVerdict
from arp.storage.run_store import RunStore
from arp.universe import UniverseRejected, load_company_universe
from tests.test_identity_pipeline import _FakeEdgar, _NullSearch, _settings
from tests.test_review_decide import ALICE, BOB, decide, env  # noqa: F401 -- env is a fixture

pytestmark = pytest.mark.usefixtures("pg")

LEI_X = "5493001KJTIIGC8Y1R12"
LEI_Y = "529900T8BM49AURSDO55"
CORRECT = {"decision": "correct", "reason_code": "wrong_entity", "comment": "GLEIF record"}


def _result(cid: str, *, resolved: bool = True, flagged: bool = False, **kw) -> dict:
    return IdentityResolutionResult(
        company_id=cid, input_name=kw.pop("input_name", f"{cid} AG"),
        verdict=IdentityVerdict.RESOLVED if resolved else IdentityVerdict.UNCERTAIN, confidence=1.0 if resolved else 0.5,
        signals=IdentitySignals(), rationale="r", flagged_for_review=flagged, match_rule=kw.pop("match_rule", "supplied"),
        **kw,
    ).model_dump(mode="json")


def _run(rs: RunStore, companies: list[CompanyRef], results: list[dict]) -> str:
    run_id = create_identity_run(companies, rs)
    for r in results:
        rs.append_result(run_id, r)
        if r["flagged_for_review"]:
            rs.append_review_item(run_id, {"item_key": r["company_id"], "company_id": r["company_id"], **r})
    return run_id


def _export(rs: RunStore, run_id: str) -> dict[str, CompanyRef]:
    return {c.company_id: c for c in enriched_universe(rs, run_id)}


def _final(run_id: str, key: str, corrected: dict) -> None:
    for who in (ALICE, BOB):
        r = decide(who, {**CORRECT, "corrected_value": corrected}, key=key, run_id=run_id)
        assert r.status_code == 200, r.text


C1 = CompanyRef(
    company_id="C1", name="C1 AG", ticker="C1X", website="https://c1.example", isin="DE0007236101", country="DE",
    sector="Industrials", isic_code="2829", nace_code="28.29", nace_rev="2", gics_code="201040", regimes=["CSRD"],
    fiscal_year_end="03-31",
)


def test_ac_1_2_export_keeps_every_input_field(env, pg):  # noqa: F811
    from sqlalchemy.orm import Session

    from arp.db.models import Company
    from arp.db.session import engine

    with Session(engine(pg)) as s, s.begin():
        row = Company(name="C1 AG")
        s.add(row)
        s.flush()
        c1 = C1.model_copy(update={"entity_id": row.id})
    rs = env[0]
    run_id = _run(rs, [c1], [_result("C1", resolved_website="https://c1.example", identifiers={"isin": "DE0007236101"})])
    assert _export(rs, run_id)["C1"] == c1


def test_ac_3_correction_keeps_input_codes(env):  # noqa: F811
    rs = env[0]
    run_id = _run(rs, [CompanyRef(company_id="C2", name="C2", isic_code="2711")], [_result("C2", resolved=False, flagged=True)])
    _final(run_id, "C2", {"resolved_website": "https://c2.example"})
    c2 = _export(rs, run_id)["C2"]
    assert (c2.website, c2.isic_code) == ("https://c2.example", "2711")


def test_ac_3c_missing_result_isin_keeps_input(env):  # noqa: F811
    rs = env[0]
    run_id = _run(rs, [CompanyRef(company_id="C9", name="C9", website="https://c9.example", isin="DE0007236101")],
                  [_result("C9", resolved_website="https://c9.example")])
    assert _export(rs, run_id)["C9"].isin == "DE0007236101"


def test_ac_4_run_without_saved_companies_exports_result_only(env):  # noqa: F811
    rs = env[0]
    run_id = _run(rs, [], [_result("C10", input_name="C10 SA", resolved_website="https://c10.example")])
    assert rs.load_companies(run_id) in (None, [])
    assert _export(rs, run_id)["C10"] == CompanyRef(company_id="C10", name="C10 SA", website="https://c10.example")


def test_ac_5_lei_only_company_is_exported_after_approve(env):  # noqa: F811
    rs = env[0]
    run_id = _run(rs, [CompanyRef(company_id="C3", name="C3", lei=LEI_X)],
                  [_result("C3", resolved=False, flagged=True, match_rule="exact_lei", identifiers={"lei": LEI_X})])
    assert decide(ALICE, {"decision": "approve", "reason_code": "confirmed"}, key="C3", run_id=run_id).status_code == 200
    c3 = _export(rs, run_id)["C3"]
    assert (c3.lei, c3.website, c3.cik) == (LEI_X, None, None)


def test_ac_6_7_open_flag_and_reject_stay_excluded(env):  # noqa: F811
    rs = env[0]
    companies = [CompanyRef(company_id=c, name=c, lei=LEI_X) for c in ("C4", "C5")]
    results = [_result(c, resolved=False, flagged=True, match_rule="exact_lei", identifiers={"lei": LEI_X}) for c in ("C4", "C5")]
    run_id = _run(rs, companies, results)
    assert decide(ALICE, {"decision": "reject", "reason_code": "wrong_entity"}, key="C5", run_id=run_id).status_code == 200
    assert _export(rs, run_id) == {}


def test_ac_13_to_14b_cli_lei_correction(env, monkeypatch):  # noqa: F811
    rs = env[0]
    run_id = _run(rs, [CompanyRef(company_id="C7", name="C7")],
                  [_result("C7", resolved=False, flagged=True, resolved_lei=LEI_Y, resolved_website="https://c7.example")])
    monkeypatch.setattr(cli_identity, "_run_store", lambda: rs)
    monkeypatch.setattr("arp.cli._shared._run_store", lambda: rs)
    monkeypatch.setattr(cli_identity, "get_settings", lambda: env[2])
    monkeypatch.setattr("arp.cli.identity.cli_principal", lambda s: ALICE, raising=False)
    monkeypatch.setattr("arp.cli._shared.cli_principal", lambda s: ALICE)
    args = ["review", run_id, "C7", "--decision", "correct", "--reason", "wrong_entity", "--comment", "GLEIF record"]
    res = CliRunner().invoke(cli_identity.identity_app, [*args, "--lei", LEI_X])
    assert (res.exit_code, res.stdout.strip()) == (0, "Recorded (first_done)."), res.output
    assert decide(BOB, {**CORRECT, "corrected_value": {"resolved_lei": LEI_X}}, key="C7", run_id=run_id).status_code == 200
    c7 = _export(rs, run_id)["C7"]
    assert (c7.lei, c7.website) == (LEI_X, "https://c7.example")

    bad = CliRunner().invoke(cli_identity.identity_app, [*args, "--lei", "NOTANLEI"])
    assert bad.exit_code == 1 and "an identity correction needs a valid LEI" in bad.output
    none = CliRunner().invoke(cli_identity.identity_app, args)
    assert none.exit_code == 1 and all(f in none.output for f in ("--website", "--cik", "--lei"))


def test_ac_15_17_18_api_lei_correction(env):  # noqa: F811
    rs = env[0]
    companies = [CompanyRef(company_id=c, name=c) for c in ("C11", "C12", "C13")]
    run_id = _run(rs, companies, [_result(c.company_id, resolved=False, flagged=True) for c in companies])
    r = decide(ALICE, {**CORRECT, "corrected_value": {"resolved_lei": "NOTANLEI"}}, key="C11", run_id=run_id)
    assert (r.status_code, r.json()["detail"]) == (422, "an identity correction needs a valid LEI")
    r = decide(ALICE, {**CORRECT, "corrected_value": {"resolved_lei": LEI_X}}, key="C12", run_id=run_id)
    assert (r.status_code, r.json()["state"]) == (200, "first_done")
    assert decide(BOB, {**CORRECT, "corrected_value": {"resolved_lei": LEI_X}}, key="C12", run_id=run_id).status_code == 200
    _final(run_id, "C13", {"resolved_lei": " 5493001kjtiigc8y1r12 "})
    out = _export(rs, run_id)
    assert (out["C12"].lei, out["C13"].lei) == (LEI_X, LEI_X)


def test_ac_19_website_and_cik_corrections_unchanged(env):  # noqa: F811
    rs = env[0]
    companies = [CompanyRef(company_id=c, name=c) for c in ("C8", "C15")]
    run_id = _run(rs, companies, [_result(c.company_id, resolved=False, flagged=True) for c in companies])
    r = decide(ALICE, {**CORRECT, "corrected_value": {"resolved_website": "https://c8.example"}}, key="C8", run_id=run_id)
    assert (r.status_code, r.json()["state"]) == (200, "first_done")
    assert decide(BOB, {**CORRECT, "corrected_value": {"resolved_website": "https://c8.example"}}, key="C8",
                  run_id=run_id).status_code == 200
    _final(run_id, "C15", {"resolved_cik": "0000320193"})
    out = _export(rs, run_id)
    assert (out["C8"].website, out["C15"].cik) == ("https://c8.example", "0000320193")


def test_ac_19d_invalid_input_lei_exports_null(env):  # noqa: F811
    rs = env[0]
    run_id = _run(rs, [CompanyRef(company_id="C14", name="C14", lei="BADLEI", website="https://c14.example")],
                  [_result("C14", resolved_website="https://c14.example")])
    assert _export(rs, run_id)["C14"].lei is None


async def test_ac_8_9_previous_run_reuses_unchanged_results(tmp_path, fake_llm, pg):
    settings = _settings(tmp_path)
    rs = RunStore(pg, settings.runs_dir)
    c6 = CompanyRef(company_id="C6", name="C6", website="https://c6.example", cik="0000320193")
    kw = dict(llm=fake_llm({}), settings=settings, run_store=rs, edgar=_FakeEdgar(), search_client=_NullSearch())
    r1 = await run_identity_resolution([c6], **kw)
    first = rs.read_results(r1)[0]["generated_at"]
    r2 = await run_identity_resolution([c6], previous_run_id=r1, **kw)
    assert rs.read_results(r2)[0]["generated_at"] == first
    r3 = await run_identity_resolution([c6.model_copy(update={"cik": "0000789019"})], previous_run_id=r1, **kw)
    assert rs.read_results(r3)[0]["generated_at"] != first


def test_ac_10_unknown_previous_run_exits_before_llm(tmp_path, pg, monkeypatch):
    settings = _settings(tmp_path)
    rs = RunStore(pg, settings.runs_dir)
    (tmp_path / "u.csv").write_text("company_id,name\nC6,C6\n")
    monkeypatch.setattr(cli_identity, "_run_store", lambda: rs)
    monkeypatch.setattr(cli_identity, "get_settings", lambda: settings)
    monkeypatch.setattr(cli_identity, "build_llm_client", lambda s: pytest.fail("LLM client built"))
    before = len(rs.list_runs("identity"))
    res = CliRunner().invoke(cli_identity.identity_app, ["resolve", "--names-file", str(tmp_path / "u.csv"), "--previous-run", "R404"])
    assert (res.exit_code, res.stderr.strip()) == (1, "Run not found: R404")
    assert len(rs.list_runs("identity")) == before


def test_ac_11_duplicate_company_id_rejected(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text("company_id,name\nA,Alpha\nA,Alpha again\n")
    with pytest.raises(UniverseRejected, match="^duplicate company_id 'A'$"):
        load_company_universe(p)
    j = tmp_path / "dup.json"
    j.write_text(json.dumps([{"company_id": "A", "name": "x"}, {"company_id": "A", "name": "y"}]))
    with pytest.raises(UniverseRejected):
        load_company_universe(j)
