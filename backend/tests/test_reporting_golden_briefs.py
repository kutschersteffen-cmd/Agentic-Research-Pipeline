"""One end-to-end brief per deck type, real Chromium, scripted LLM.

Each deck must come out with both files, a PDF page per slide, and no fit or lint findings, so the
scripted text is written clean on purpose: if a rule starts firing here, the rule or the layout changed.
"""

import asyncio
import json

import pytest
from pypdf import PdfReader

from arp.config import Settings
from arp.reporting.fit import fit_deck
from arp.reporting.service import ReportingService
from arp.reporting.visual_qa import QAResult
from arp.schemas.common import RunManifest
from arp.schemas.decision import PublishedDecision, PublishedRow
from arp.schemas.reporting import (
    LayoutInstructions,
    OutputFormat,
    ReportRequest,
    ReportStatus,
    RunRef,
    SlideContent,
    Storyline,
    StorylineSlide,
)
from arp.storage.decision_store import DecisionStore
from arp.storage.reporting_store import ReportingStore
from arp.storage.run_store import RunStore


def _settings(tmp_path) -> Settings:
    return Settings(runs_dir=tmp_path / "runs", frameworks_dir=tmp_path / "frameworks", reports_dir=tmp_path / "reports", report_templates_dir=tmp_path / "tpl")


def _storyline(*headlines: str) -> Storyline:
    return Storyline(title="Quarterly review", subtitle="Prepared for the investment committee", slides=[StorylineSlide(headline=h, purpose="state the point") for h in headlines])


def _bullets(*items: str) -> SlideContent:
    return SlideContent(headline="x", layout="bullets", variant="three", slots={"items": list(items)})


def _numbers() -> SlideContent:
    return SlideContent(headline="x", layout="big_number", variant="two", slots={"number_1": "72.5", "label_1": "Acme score", "number_2": "40.0", "label_2": "Beta score"})


def _assert_clean_deck(store: ReportingStore, report_id: str) -> None:
    deck = store.load_deck(report_id)
    assert store.output_path(report_id, "output.pptx").exists()
    pdf = store.output_path(report_id, "output.pdf")
    assert pdf.exists() and len(PdfReader(pdf).pages) == len(deck.slides)
    assert [f for f in store.load_findings(report_id) if f.stage in ("fit", "lint")] == []


async def test_free_form_brief(tmp_path, fake_llm):
    store = ReportingStore(tmp_path / "reports", tmp_path / "tpl")
    service = ReportingService(store)
    request = ReportRequest(title="Review", qualitative_notes="Grid work slowed two projects.", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK))
    story = _storyline("Grid delays slowed two projects.", "Permits are the next constraint.")
    manifest = await service.create_and_plan(request, fake_llm({"Storyline": [story]}))
    fills = [
        _bullets("Two projects waited on grid connections.", "Both have since been connected.", "Cost overruns stayed under budget."),
        _bullets("Permit queues run about six months.", "Two filings are still open.", "Staff are tracking each one weekly."),
    ]
    manifest = await service.approve_storyline(manifest.report_id, fake_llm({"SlideContent": fills, "QAResult": [QAResult(edits=[])]}))
    assert manifest.status == ReportStatus.COMPLETED
    _assert_clean_deck(store, manifest.report_id)


def _published(settings: Settings) -> str:
    pub = DecisionStore(settings.frameworks_dir).save_published(PublishedDecision(
        framework_id="fw", framework_version=1, framework_name="Climate tiers", dataset_id="d", dataset_name="D",
        as_of="2026-06-30", id_column="id", published_by="A",
        rows=[PublishedRow(entity_id="e1", name="Acme", score=72.5, tier=1), PublishedRow(entity_id="e2", name="Beta", score=40.0, tier=2)],
    ))
    return pub.snapshot_id


async def test_pipeline_brief_from_a_published_decision(tmp_path, fake_llm):
    s = _settings(tmp_path)
    store = ReportingStore(s.reports_dir, s.report_templates_dir)
    service = ReportingService(store, s)
    request = ReportRequest(title="Tiers", qualitative_notes="Acme leads Beta.", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK),
                            run_refs=[RunRef(kind="decision", ref_id=_published(s))])
    story = _storyline("Acme scores 72.5 and Beta scores 40.0.")
    manifest = await service.create_and_plan(request, fake_llm({"Storyline": [story]}))
    manifest = await service.approve_storyline(manifest.report_id, fake_llm({"SlideContent": [_numbers()], "QAResult": [QAResult(edits=[])]}))
    assert manifest.status == ReportStatus.COMPLETED
    assert [d.dataset_id for d in store.load_request(manifest.report_id).datasets] == [f"decision_{request.run_refs[0].ref_id}"]
    _assert_clean_deck(store, manifest.report_id)


async def test_periodic_brief_reruns_on_fresh_run_data(tmp_path, fake_llm):
    s = _settings(tmp_path)
    runs = RunStore(s.runs_dir)
    runs.save_manifest(RunManifest(run_id="run_1", run_type="theme"))
    runs.results_path("run_1").write_text(json.dumps({"company": "Acme", "revenue": 42.5}) + "\n")
    store = ReportingStore(s.reports_dir, s.report_templates_dir)
    service = ReportingService(store, s)
    request = ReportRequest(title="Revenue", qualitative_notes="Acme grew.", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK),
                            run_refs=[RunRef(kind="run", ref_id="run_1")])
    manifest = await service.create_and_plan(request, fake_llm({"Storyline": [_storyline("Acme revenue reached 42.5.")]}))
    fill = _bullets("Acme leads the group.", "Beta trails by a wide margin.", "Gamma has not reported.")
    first = await service.approve_storyline(manifest.report_id, fake_llm({"SlideContent": [fill], "QAResult": [QAResult(edits=[])]}))
    _assert_clean_deck(store, first.report_id)

    second = await service.rerun(first.report_id, fake_llm({"SlideContent": [fill], "QAResult": [QAResult(edits=[])]}))
    assert second.status == ReportStatus.COMPLETED and second.rerun_of == first.report_id
    _assert_clean_deck(store, second.report_id)


def test_client_brief_renders_without_an_llm(tmp_path, fake_llm, monkeypatch):
    pytest.importorskip("zen")
    pytest.importorskip("pptx")
    from arp.api.routers.stewardship import CreateStreamRequest, create_stream
    from arp.stewardship import client_report as cr
    from arp.stewardship.policy_review import DATA
    from arp.stewardship.process import StreamStore, build_stream_policy

    streams = StreamStore(tmp_path)
    stream = streams.get(create_stream(CreateStreamRequest(name="Example Pension Fund"), streams)["stream_id"])
    decisions = json.loads((DATA / "examples" / "client_policy_example_decisions.json").read_text())
    stream = streams.save(build_stream_policy({**stream, "decisions": decisions}))
    seen = {}
    real = cr.build_house_pptx
    monkeypatch.setattr(cr, "build_house_pptx", lambda deck, datasets, *a, **k: seen.update(deck=deck, datasets=datasets) or real(deck, datasets, *a, **k))

    out = cr.build_pptx(cr.client_report(streams.root, stream, [], sla_days=45), tmp_path / "r.pptx")

    deck = seen["deck"]
    assert out.exists() and len(PdfReader(out.with_suffix(".pdf")).pages) == len(deck.slides)
    request = ReportRequest(title="x", qualitative_notes="", datasets=seen["datasets"], layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK))
    _, fit_findings = asyncio.run(fit_deck(deck, request, fake_llm({})))  # a rewrite call would hit the empty script and fail
