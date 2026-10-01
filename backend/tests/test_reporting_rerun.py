import json

import pytest

from arp.config import Settings
from arp.reporting import adapters
from arp.reporting.scheduler import ReportScheduleConfig, ReportScheduler
from arp.reporting.service import ReportingService
from arp.reporting.visual_qa import QAResult
from arp.schemas.common import RunManifest
from arp.schemas.reporting import (
    Deck,
    LayoutInstructions,
    OutputFormat,
    ReportManifest,
    ReportRequest,
    ReportStatus,
    RunRef,
    SlideContent,
    Storyline,
    StorylineSlide,
)
from arp.storage.reporting_store import ReportingStore
from arp.storage.run_store import RunStore


def _setup(tmp_path, share: float) -> tuple[Settings, ReportingStore, str]:
    s = Settings(runs_dir=tmp_path / "runs", frameworks_dir=tmp_path / "frameworks", reports_dir=tmp_path / "reports", report_templates_dir=tmp_path / "tpl")
    runs = RunStore(s.runs_dir)
    runs.save_manifest(RunManifest(run_id="run_1", run_type="theme"))
    runs.results_path("run_1").write_text(json.dumps({"company": "Acme", "revenue": 42.5}) + "\n")
    store = ReportingStore(s.reports_dir, s.report_templates_dir)
    request = ReportRequest(title="T", qualitative_notes="notes", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK),
                            run_refs=[RunRef(kind="run", ref_id="run_1")])
    m = ReportManifest(title="T", output_format=OutputFormat.HOUSE_DECK, status=ReportStatus.COMPLETED)
    store.save_manifest(m)
    store.save_request(m.report_id, request)
    store.save_storyline(m.report_id, Storyline(title="Deck", slides=[StorylineSlide(headline="Acme revenue reached 42.5.", purpose="p")], approved=True))
    store.save_deck(m.report_id, Deck(title="Deck", slides=[]))
    runs.results_path("run_1").write_text(json.dumps({"company": "Acme", "revenue": share}) + "\n")  # the data moves on
    return s, store, m.report_id


def _llm(fake_llm):
    fill = SlideContent(headline="x", layout="bullets", variant="three", slots={"items": ["Acme leads.", "Beta trails."]})
    return fake_llm({"SlideContent": [fill], "QAResult": [QAResult(edits=[])]})


async def test_rerun_reuses_storyline_with_fresh_data(tmp_path, fake_llm, monkeypatch):
    s, store, rid = _setup(tmp_path, 42.5)
    llm = _llm(fake_llm)
    loads = []
    real = adapters.load_run_datasets
    monkeypatch.setattr(adapters, "load_run_datasets", lambda *a: loads.append(1) or real(*a))
    new = await ReportingService(store, s).rerun(rid, llm)
    assert new.report_id != rid and new.status == ReportStatus.COMPLETED
    assert "Storyline" not in llm.calls
    assert store.output_path(new.report_id, "output.pdf").exists()
    assert store.load_manifest(rid).status == ReportStatus.COMPLETED  # original untouched
    [ds] = store.load_request(new.report_id).datasets
    assert ds.rows == [{"company": "Acme", "revenue": 42.5}]
    assert len(loads) == 1 and new.rerun_of == rid  # adapters read once per rerun


async def test_rerun_of_unknown_id_raises_without_creating_a_dir(tmp_path):
    s, store, _ = _setup(tmp_path, 42.5)
    with pytest.raises(ValueError, match="rpt_nope"):
        await ReportingService(store, s).rerun("rpt_nope", None)
    assert not (s.reports_dir / "rpt_nope").exists()


async def test_rerun_after_reapproval_starts_from_the_approved_rerun(tmp_path, fake_llm):
    s, store, rid = _setup(tmp_path, 51.0)
    service = ReportingService(store, s)
    stopped = await service.rerun(rid, fake_llm({}))
    assert stopped.status == ReportStatus.STORYLINE_READY
    fixed = Storyline(title="Deck", slides=[StorylineSlide(headline="Acme revenue reached 51.", purpose="p")])
    store.save_storyline(stopped.report_id, fixed)  # a person edits the headline, then approves
    await service.approve_storyline(stopped.report_id, _llm(fake_llm))
    nxt = await service.rerun(rid, _llm(fake_llm))
    assert nxt.status == ReportStatus.COMPLETED and nxt.rerun_of == stopped.report_id
    assert store.load_storyline(nxt.report_id).slides[0].headline == "Acme revenue reached 51."


async def test_rerun_stops_when_headline_number_no_longer_in_data(tmp_path, fake_llm):
    s, store, rid = _setup(tmp_path, 51.0)
    llm = fake_llm({})
    new = await ReportingService(store, s).rerun(rid, llm)
    assert new.status == ReportStatus.STORYLINE_READY and llm.calls == []
    assert store.load_storyline(new.report_id).approved is False
    [f] = store.load_findings(new.report_id)
    assert f.rule == "number_not_in_source" and f.slot == "headline" and f.slide == 1
    assert store.load_deck(new.report_id) is None


async def test_scheduler_continues_after_one_failing_report(tmp_path, fake_llm):
    s, store, rid = _setup(tmp_path, 42.5)
    scheduler = ReportScheduler(s, llm_factory=lambda: _llm(fake_llm))
    assert scheduler._config_path == s.reports_dir / "_schedule" / "schedule.json"
    await scheduler._run(ReportScheduleConfig(enabled=True, report_ids=["rpt_missing", rid]))
    done = [m for m in store.list_reports() if m.report_id != rid]
    assert [m.status for m in done] == [ReportStatus.COMPLETED]


async def test_create_and_plan_drafts_storyline_on_loaded_run_data(tmp_path, fake_llm):
    s, store, rid = _setup(tmp_path, 42.5)
    llm = fake_llm({"Storyline": [Storyline(title="Deck", slides=[])]})
    m = await ReportingService(store, s).create_and_plan(store.load_request(rid), llm)
    assert "run_run_1" in llm.prompts[0] and "revenue" in llm.prompts[0]
    assert [d.dataset_id for d in store.load_request(m.report_id).datasets] == ["run_run_1"]


async def test_scheduler_skips_lineage_with_rerun_awaiting_approval(tmp_path, fake_llm, caplog):
    s, store, rid = _setup(tmp_path, 51.0)  # the headline number moved: the rerun stops for approval
    scheduler = ReportScheduler(s, llm_factory=lambda: fake_llm({}))
    config = ReportScheduleConfig(enabled=True, report_ids=[rid])
    await scheduler._run(config)
    [waiting] = [m for m in store.list_reports() if m.report_id != rid]
    assert waiting.status == ReportStatus.STORYLINE_READY and waiting.report_id in caplog.text
    await scheduler._run(config)  # next tick: nothing new while that one waits
    assert len(store.list_reports()) == 2
