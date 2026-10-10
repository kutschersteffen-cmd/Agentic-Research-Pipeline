from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.pipeline import load_run_schema, run_extraction
from arp.extraction.verifier_agent import VerifierOutput
from arp.golden_set.runner import _BUNDLED_CASES_PATH, load_cases
from arp.ingestion.base import DocumentSource
from arp.ingestion.local_files import parser_version
from arp.ingestion.registry import DocumentSourceRegistry
from arp.orchestration.review_queue import append_decision
from arp.publish.candidates import run_candidates
from arp.retrieval.content_store_factory import content_store_for
from arp.review.quality import _perturb, record_confirmed_correction, reviewer_stats, seed_known_answers
from arp.schemas.common import Citation, CompanyRef, DocType, RunManifest, SourceDocument
from arp.schemas.datapoints import DataPointSchema
from arp.schemas.review import ReviewDecision
from arp.storage.run_store import RunStore
from tests.test_review_context import _schema
from tests.test_review_decide import ALICE, BOB, CAROL, CORRECT, client, ctx, decide, env  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.usefixtures("pg")

ANALYST = Principal(user_id="u_ann", name="Ann Analyst", role="analyst")
BANNED = ("known", "gold", "case_", "perturb")


@pytest.fixture
def qenv(tmp_path):
    settings = Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", schema_registry_dir=tmp_path / "reg",
        document_store_dir=tmp_path / "docstore", review_quality_dir=tmp_path / "rq", hybrid_retrieval_enabled=False,
        cache_dir=tmp_path / "cache",
    )
    rs = RunStore(settings.runs_dir)
    store = content_store_for(settings)
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[get_document_content_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: settings
    yield rs, store, settings
    for dep in (get_run_store, get_document_content_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)


def _client(who):
    app.dependency_overrides[current_user] = lambda: who
    return TestClient(app)


def _real_run(rs, store, settings, field):
    text = "Item 7. In fiscal year 2025, the Company invested $90.5 million in green capital expenditures."
    key = hashlib.sha256(text.encode()).hexdigest()
    store.store(key, key_kind="file", parser_version=parser_version(), source_suffix=".txt", byte_size=len(text),
                text=text, page_breaks=[])
    doc = SourceDocument(company_id="c9", doc_type=DocType.ANNUAL_REPORT_10K, title="Annual report", full_text=text,
                         content_key=key, parser_version=parser_version())

    class _Fixed(DocumentSource):
        name = "fixed"

        async def fetch(self, company, doc_types=None):
            return [doc]

    from tests.conftest import FakeLLMClient

    llm = FakeLLMClient({
        "ExtractionDraft": [ExtractionDraft(values=[PeriodValue(
            value=90.5, raw_value_text="$90.5 million", unit_text="USD millions", period_text="fiscal year 2025",
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="invested $90.5 million in green capital expenditures")],
        )], confidence=0.8)],
        "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.8, notes="Matches the cited text.")],
    })
    schema = DataPointSchema(name="Green capex", fields=[field])
    return asyncio.run(run_extraction(
        schema, [CompanyRef(company_id="c9", name="Real Co")], llm=llm, registry=DocumentSourceRegistry([_Fixed()]),
        settings=settings, run_store=rs, trial=True,
    ))


def _same_keys(a, b, path="$"):
    if isinstance(a, dict) and isinstance(b, dict):
        assert a.keys() == b.keys(), (path, sorted(a.keys() ^ b.keys()))
        for k in a:
            _same_keys(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list) and a and b:
        _same_keys(a[0], b[0], f"{path}[0]")


def _strings(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)
    elif isinstance(x, str):
        yield x


def _no_tells(response):
    for s in _strings(response):
        assert not any(w in s.lower() for w in BANNED), s


def test_known_answer_item_indistinguishable_in_api(qenv):
    rs, store, settings = qenv
    seeded = seed_known_answers(rs, settings, count=5, seed=3)
    field = next(f for f in load_run_schema(rs, seeded).fields if f.name == "green_capex_fy2025")
    real = _real_run(rs, store, settings, field)

    c = _client(ANALYST)
    items = c.get("/api/review/items").json()["items"]
    [real_item] = [i for i in items if i["run_id"] == real]
    seeded_items = [i for i in items if i["run_id"] == seeded]
    assert len(seeded_items) == 5
    _no_tells(real_item)

    def views(item):
        base = f"/api/review/runs/{item['run_id']}/items/{item['item_key']}"
        ctx = c.get(f"{base}/context")
        assert ctx.status_code == 200, ctx.text
        ctx = ctx.json()
        sources = []
        for d in ctx["documents"]:
            r = c.get(f"{base}/source", params={"doc_id": d["doc_id"], "page": 1})
            assert r.status_code == 200, r.text
            sources.append(r.json())
        return ctx, sources

    real_ctx, real_sources = views(real_item)
    assert real_sources and real_ctx["evidence"]
    _no_tells(real_ctx)
    for item in seeded_items:
        assert item.keys() == real_item.keys()
        _same_keys(item, real_item)
        _no_tells(item)
        ctx, sources = views(item)
        _same_keys(ctx, real_ctx)
        _no_tells(ctx)
        assert len(sources) == len(ctx["documents"]) >= 1
        for s in sources:
            assert s.keys() == real_sources[0].keys() and s["page_text"]
            _no_tells(s)
    assert any(i["payload"]["field"]["value"] is not None and i["payload"]["field"]["grounded"] for i in seeded_items)

    def first_decision(item):
        base = f"/api/review/runs/{item['run_id']}/items/{item['item_key']}"
        etag = c.get(f"{base}/context").json()["etag"]
        r = c.post(f"{base}/decision", json={"decision": "approve", "reason_code": "confirmed", "context_etag": etag})
        assert r.status_code == 200, r.text
        return r.json()

    real_decision, seeded_decision = first_decision(real_item), first_decision(seeded_items[0])
    assert real_decision.keys() == seeded_decision.keys()
    _no_tells(real_decision)
    _no_tells(seeded_decision)


def test_seeded_run_manifest_params_look_like_a_real_trial_run(qenv):
    rs, store, settings = qenv
    seeded = seed_known_answers(rs, settings, count=2, seed=5)
    real = _real_run(rs, store, settings, load_run_schema(rs, seeded).fields[0])
    sp, rp = rs.load_manifest(seeded).params, rs.load_manifest(real).params
    assert sp.keys() == rp.keys()
    for s in _strings(sp):
        assert not any(w in s.lower() for w in (*BANNED, "trial extraction")), s
    listed = _client(ANALYST).get("/api/runs").json()
    _no_tells(listed)


def _row(rs, run_id, key, who, decision, step, value=None, second_required=False):
    append_decision(rs, run_id, ReviewDecision(
        item_key=key, decision=decision, reason_code="confirmed" if decision == "approve" else "wrong_value",
        reviewer=who.name, user_id=who.user_id, role=who.role,
        corrected_value={"value": value} if decision == "correct" else None, snapshot_id="s", step=step,
        second_required=second_required,
    ))


def test_reviewer_stats_agreement_and_overturn(qenv):
    rs, _, settings = qenv
    rs.save_manifest(RunManifest(run_id="ext1", run_type="extraction"))
    _row(rs, "ext1", "A", ALICE, "correct", "first", 1100, second_required=True)
    _row(rs, "ext1", "A", BOB, "correct", "second", 1100)  # agrees: second_done, effective = Alice's
    _row(rs, "ext1", "B", ALICE, "approve", "first", second_required=True)
    _row(rs, "ext1", "B", BOB, "reject", "second")  # disagrees
    _row(rs, "ext1", "B", CAROL, "reject", "resolution")  # final: reject
    _row(rs, "ext1", "C", BOB, "approve", "first")  # final at once
    stats = {s.name: s for s in reviewer_stats(rs, settings)}
    alice, bob, carol = stats["Alice Reviewer"], stats["Bob Builder"], stats["Carol Approver"]
    assert (alice.decisions, alice.agreement_rate, alice.overturn_rate) == (2, 0.5, 0.5)
    assert (bob.decisions, bob.agreement_rate, bob.overturn_rate) == (3, 1.0, 0.0)
    assert (carol.decisions, carol.agreement_rate, carol.overturn_rate) == (1, 0.0, 0.0)
    for s in stats.values():
        d = asdict(s)
        assert "user_id" not in d and not any(str(v).startswith("u_") for v in d.values())


def test_known_answer_accuracy(qenv):
    rs, _, settings = qenv
    run_id = seed_known_answers(rs, settings, count=2, seed=7)
    known = [json.loads(line) for line in (settings.review_quality_dir / "known.jsonl").read_text().splitlines()]
    assert {k["run_id"] for k in known} == {run_id} and sorted(k["perturbed"] for k in known) == [False, True]
    plain = next(k for k in known if not k["perturbed"])
    bent = next(k for k in known if k["perturbed"])
    _row(rs, run_id, plain["item_key"], ALICE, "approve", "first")  # right
    _row(rs, run_id, bent["item_key"], ALICE, "approve", "first")  # wrong: approved a perturbed value
    _row(rs, run_id, bent["item_key"], BOB, "correct", "first", bent["expected_value"])  # right
    stats = {s.name: s for s in reviewer_stats(rs, settings)}
    assert (stats["Alice Reviewer"].known_answer_items, stats["Alice Reviewer"].known_answer_accuracy) == (2, 0.5)
    assert (stats["Bob Builder"].known_answer_items, stats["Bob Builder"].known_answer_accuracy) == (1, 1.0)


def test_second_approved_correction_appends_gold_case(env):  # noqa: F811 - the review-decide fixture
    settings = env[2]
    bundled = _BUNDLED_CASES_PATH.read_bytes()
    assert decide(ALICE, CORRECT).json()["state"] == "first_done"
    gold = settings.review_quality_dir / "extraction_cases.json"
    assert not gold.exists()
    assert decide(BOB, CORRECT).json()["state"] == "second_done"  # the second reviewer confirms the correction
    [case] = load_cases(gold)
    assert case.expected_value == 1100 and case.field.field_id == "f1" and "1,100" in case.document_text
    assert _BUNDLED_CASES_PATH.read_bytes() == bundled


def test_quality_endpoint_requires_approver(qenv):
    assert _client(ANALYST).get("/api/review/quality").status_code == 403
    r = _client(CAROL).get("/api/review/quality")
    assert r.status_code == 200 and r.json() == {"reviewers": []}


def test_known_answer_run_never_published(qenv):
    rs, _, settings = qenv
    run_id = seed_known_answers(rs, settings, count=2)
    m = rs.load_manifest(run_id)
    assert m.run_type == "extraction" and m.params["trial"] is True
    assert {f["route"] for r in rs.read_jsonl(rs._results_path(run_id)) for f in r["fields"]} == {"review"}
    cands, _ = run_candidates(rs, run_id)
    assert cands == []


def test_cli_seed_known_answers_default_count(qenv, monkeypatch):
    from typer.testing import CliRunner

    from arp.cli.golden_set import golden_set_app

    rs, _, settings = qenv
    monkeypatch.setattr("arp.cli.golden_set.get_settings", lambda: settings)
    monkeypatch.setattr("arp.cli.golden_set._run_store", lambda: rs)
    result = CliRunner().invoke(golden_set_app, ["seed-known-answers", "--seed", "1"])
    assert result.exit_code == 0, result.output
    assert len((settings.review_quality_dir / "known.jsonl").read_text().splitlines()) == 1  # no open items: at least 1


def test_blind_second_review_gold_case_uses_server_side_citation(env, monkeypatch):  # noqa: F811
    rs, _, settings = env
    (rs.run_dir("ext1") / "schema.json").write_text(_schema(high_risk=True).model_dump_json())
    seen = {}

    def spy(bundle, corrected_value, settings, *, citation=None):
        seen.update(bundle=bundle, citation=citation)
        record_confirmed_correction(bundle, corrected_value, settings, citation=citation)

    monkeypatch.setattr("arp.review.decide.record_confirmed_correction", spy)
    assert decide(ALICE, CORRECT).json()["state"] == "first_done"
    assert ctx(client(BOB))["blind"] is True
    assert decide(BOB, CORRECT).json()["state"] == "second_done"
    assert seen["bundle"]["blind"] is True and seen["bundle"]["decisions"] == []
    assert seen["citation"]["span_text"] == "Scope 1  1,234  1,100"
    [case] = load_cases(settings.review_quality_dir / "extraction_cases.json")
    assert "1,100" in case.document_text


def _bundle(page_text, run_id="ext1", item_key="K"):
    return {
        "item": {"run_id": run_id, "item_key": item_key, "payload": {"name": "Acme"}},
        "field_definition": _schema().fields[0].model_dump(mode="json"),
        "evidence": [{"doc_type": "sustainability_report", "page_text": page_text}],
        "decisions": [],
    }


def test_gold_case_text_from_citation_and_never_without_the_number(qenv):
    _, _, settings = qenv
    gold = settings.review_quality_dir / "extraction_cases.json"
    record_confirmed_correction(_bundle("Scope 1 1,234 on page 3"), {"value": 1100}, settings)
    assert not gold.exists()  # the number is nowhere in the text: no case that would always fail
    cit = {"doc_id": "d1", "doc_type": "sustainability_report", "span_text": "Scope 1 restated 1,100"}
    record_confirmed_correction(_bundle("Scope 1 1,234 on page 3"), {"value": 1100}, settings, citation=cit)
    [case] = load_cases(gold)
    assert "1,100" in case.document_text and case.expected_value == 1100


def test_known_answer_item_never_grows_the_gold_set(qenv):
    rs, _, settings = qenv
    run_id = seed_known_answers(rs, settings, count=2, seed=2)
    key = json.loads((settings.review_quality_dir / "known.jsonl").read_text().splitlines()[0])["item_key"]
    record_confirmed_correction(_bundle("Scope 1 1,100", run_id, key), {"value": 1100}, settings)
    assert not (settings.review_quality_dir / "extraction_cases.json").exists()
    assert _perturb(0) == 1 and _perturb(0.0) == 1 and _perturb(2.5) == 25 and _perturb(True) is False


def test_system_rows_are_not_a_reviewer(qenv):
    from arp.orchestration.reground import _reopen

    rs, _, settings = qenv
    rs.save_manifest(RunManifest(run_id="ext1", run_type="extraction"))
    _row(rs, "ext1", "A", ALICE, "approve", "first")
    _reopen(rs, "ext1", "A", "old", "new")  # a system span_moved escalate
    assert [s.name for s in reviewer_stats(rs, settings)] == ["Alice Reviewer"]


@pytest.mark.parametrize("high_risk", [False, True])
def test_seeded_provenance_matches_the_risk_class(qenv, high_risk):
    import random

    from arp.extraction import extractor_agent, verifier_agent
    from arp.review.quality import _record

    _, _, settings = qenv
    case = next(c for c in load_cases() if c.expected_value is not None)
    spec = case.field.model_copy(update={"high_risk": high_risk})
    schema = DataPointSchema(name="s", fields=[spec])
    record = asyncio.run(_record(CompanyRef(company_id="c1", name="Co"), case, case.expected_value, schema, spec,
                                 settings, random.Random(1)))
    prompt = (extractor_agent if high_risk else verifier_agent)._SYSTEM_PROMPT
    for f in record.fields:
        assert f.provenance.verifier_prompt_version == hashlib.sha256(prompt.encode()).hexdigest()[:12]
        assert f.provenance.adjudicator_model is None  # no third call ran
