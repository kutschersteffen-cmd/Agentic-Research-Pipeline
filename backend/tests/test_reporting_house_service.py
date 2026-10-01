import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.deps import get_reporting_store
from arp.api.routers import reporting as reporting_router
from arp.reporting import house_pipeline
from arp.reporting.browser import BrowserUnavailable
from arp.reporting.lint import lint_deck
from arp.reporting.service import ReportingService
from arp.reporting.visual_qa import QAEdit, QAResult
from arp.schemas.reporting import (
    Finding,
    LayoutInstructions,
    OutputFormat,
    ReportManifest,
    ReportRequest,
    ReportStatus,
    SlideContent,
    Storyline,
    StorylineSlide,
)
from arp.storage.reporting_store import ReportingStore

_REQ = ReportRequest(title="T", qualitative_notes="notes", goal="g", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK))


def _store(tmp_path) -> ReportingStore:
    return ReportingStore(tmp_path / "reports", tmp_path / "templates")


def _storyline(n: int) -> Storyline:
    return Storyline(title="Deck", subtitle="Sub", slides=[StorylineSlide(headline=f"Point {i} holds.", purpose="p") for i in range(n)])


def _bullets() -> SlideContent:
    return SlideContent(headline="x", layout="bullets", variant="three", slots={"items": ["a", "b"]})


async def test_create_and_plan_drafts_storyline_for_house_deck(tmp_path, fake_llm):
    store = _store(tmp_path)
    manifest = await ReportingService(store).create_and_plan(_REQ, fake_llm({"Storyline": [_storyline(2)]}))
    assert manifest.status == ReportStatus.STORYLINE_READY
    assert len(store.load_storyline(manifest.report_id).slides) == 2 and store.load_plan(manifest.report_id) is None


async def test_approve_rejects_empty_and_double_approval(tmp_path, fake_llm):
    store = _store(tmp_path)
    service = ReportingService(store)
    manifest = await service.create_and_plan(_REQ, fake_llm({"Storyline": [_storyline(0)]}))
    with pytest.raises(ValueError, match="no slides"):
        await service.approve_storyline(manifest.report_id, fake_llm({}))

    store.save_storyline(manifest.report_id, _storyline(1).model_copy(update={"approved": True}))
    with pytest.raises(ValueError, match="already approved"):
        await service.approve_storyline(manifest.report_id, fake_llm({}))


async def test_house_deck_end_to_end_writes_pdf_png_and_findings(tmp_path, fake_llm):
    store = _store(tmp_path)
    service = ReportingService(store)
    manifest = await service.create_and_plan(_REQ, fake_llm({"Storyline": [_storyline(3)]}))
    bad = SlideContent(headline="x", layout="nope", variant="nope")
    llm = fake_llm({"SlideContent": [_bullets(), _bullets(), bad, bad], "QAResult": [QAResult(edits=[])]})

    manifest = await service.approve_storyline(manifest.report_id, llm)
    assert llm.calls[-1] == "QAResult" and len(llm.images[-1]) == 4  # one QA call, one PNG per slide

    rid = manifest.report_id
    assert manifest.status == ReportStatus.COMPLETED and manifest.output_filename == "output.pdf"
    assert manifest.output_files == ["output.pdf", "output.pptx"]
    assert store.output_path(rid, "output.pptx").exists()
    assert store.output_path(rid, "output.pdf").exists()
    assert len(list(store.preview_dir(rid).glob("page-*.png"))) == 4  # title + 3
    deck = store.load_deck(rid)
    assert [s.headline for s in deck.slides] == ["Deck", "Point 0 holds.", "Point 1 holds.", "Point 2 holds."]
    assert any(f.rule == "bad_reference" and f.slide == 3 for f in store.load_findings(rid))
    assert store.load_storyline(rid).approved
    assert (manifest.input_tokens, manifest.output_tokens) == (60, 60)  # storyline + 3 fills + 1 retry + QA


async def test_applied_qa_edit_replaces_stale_fit_and_lint_findings(tmp_path, fake_llm, monkeypatch):
    stale = [
        Finding(slide=1, slot="items", stage="fit", rule="overflow", message="ratio=1.2"),
        Finding(slide=1, slot="items", stage="fit", rule="slot_dropped", message="kept"),
        Finding(slide=1, slot="items", stage="lint", rule="exclamation", message="old"),
    ]

    async def fake_fit(deck, request, llm, max_passes=3, usage=None, shift=None):
        return deck, list(stale)

    monkeypatch.setattr(house_pipeline, "fit_deck", fake_fit)
    edit = QAEdit(slide=1, slot="items", text=["calm", "b"], reason="tidy")
    llm = fake_llm({"SlideContent": [_bullets()], "QAResult": [QAResult(edits=[edit])]})
    deck, findings = await house_pipeline.build_house_deck("r1", _REQ, _storyline(1), llm, _store(tmp_path))
    assert deck.slides[1].slots["items"] == ["calm", "b"]
    assert [f.rule for f in findings] == ["slot_dropped", "applied"]  # stale overflow + lint gone; QA's real re-fit finds nothing


def test_render_from_plan_rerenders_house_deck_without_llm(tmp_path, fake_llm):
    store = _store(tmp_path)
    service = ReportingService(store)
    manifest = asyncio.run(service.create_and_plan(_REQ, fake_llm({"Storyline": [_storyline(1)]})))
    asyncio.run(service.approve_storyline(manifest.report_id, fake_llm({"SlideContent": [_bullets()]})))
    store.output_path(manifest.report_id, "output.pdf").unlink()

    manifest = service.render_from_plan(manifest.report_id)

    assert manifest.status == ReportStatus.COMPLETED and store.output_path(manifest.report_id, "output.pdf").exists()


async def test_approve_build_failure_marks_manifest_failed(tmp_path, fake_llm, monkeypatch):
    monkeypatch.setenv("ARP_CHROMIUM_PATH", "/nonexistent/chrome")
    store = _store(tmp_path)
    service = ReportingService(store)
    manifest = await service.create_and_plan(_REQ, fake_llm({"Storyline": [_storyline(1)]}))
    with pytest.raises(BrowserUnavailable):
        await service.approve_storyline(manifest.report_id, fake_llm({"SlideContent": [_bullets()]}))
    after = store.load_manifest(manifest.report_id)
    assert after.status == ReportStatus.FAILED and after.error
    assert store.load_storyline(manifest.report_id).approved  # never built twice


async def test_approve_can_retry_after_fill_failure(tmp_path, fake_llm, monkeypatch):
    store = _store(tmp_path)
    service = ReportingService(store)
    manifest = await service.create_and_plan(_REQ, fake_llm({"Storyline": [_storyline(1)]}))

    async def boom(*a, **k):
        raise RuntimeError("fill blew up")

    with monkeypatch.context() as m:
        m.setattr(house_pipeline, "fill_slide", boom)
        with pytest.raises(RuntimeError):
            await service.approve_storyline(manifest.report_id, fake_llm({}))
    assert store.load_manifest(manifest.report_id).status == ReportStatus.FAILED and store.load_deck(manifest.report_id) is None

    manifest = await service.approve_storyline(manifest.report_id, fake_llm({"SlideContent": [_bullets()]}))

    assert manifest.status == ReportStatus.COMPLETED
    with pytest.raises(ValueError, match="already approved"):  # a built deck blocks re-approval
        await service.approve_storyline(manifest.report_id, fake_llm({}))


@pytest.fixture
def store(tmp_path) -> ReportingStore:
    return _store(tmp_path)


@pytest.fixture
def client(store, fake_llm, monkeypatch) -> TestClient:
    monkeypatch.setattr(reporting_router, "get_llm_client", lambda: fake_llm({}))  # no API key in tests
    app = FastAPI()
    app.include_router(reporting_router.router)
    app.dependency_overrides[get_reporting_store] = lambda: store
    return TestClient(app)


def _seed(store, storyline: Storyline, **manifest) -> str:
    m = ReportManifest(title="T", output_format=OutputFormat.HOUSE_DECK, **manifest)
    store.save_manifest(m)
    store.save_storyline(m.report_id, storyline)
    return m.report_id


def test_put_storyline_after_approval_is_409(client, store):
    rid = _seed(store, _storyline(1).model_copy(update={"approved": True}))
    assert client.put(f"/api/reports/{rid}/storyline", json=_storyline(2).model_dump()).status_code == 409
    assert client.post(f"/api/reports/{rid}/storyline/approve").status_code == 409


def test_put_storyline_saves_edits_and_rejects_empty(client, store):
    rid = _seed(store, _storyline(1))
    edited = _storyline(2).model_copy(update={"approved": True})  # body can't self-approve
    assert client.put(f"/api/reports/{rid}/storyline", json=edited.model_dump()).status_code == 200
    got = client.get(f"/api/reports/{rid}/storyline").json()
    assert len(got["slides"]) == 2 and got["approved"] is False
    assert client.put(f"/api/reports/{rid}/storyline", json=_storyline(0).model_dump()).status_code == 422
    blank = _storyline(2)
    blank.slides[1].headline = "   "
    assert client.put(f"/api/reports/{rid}/storyline", json=blank.model_dump()).status_code == 422
    assert client.get(f"/api/reports/{rid}/findings").json() == {"findings": []}


def test_approve_empty_storyline_is_422(client, store):
    rid = _seed(store, _storyline(0))
    assert client.post(f"/api/reports/{rid}/storyline/approve").status_code == 422


def test_download_rejects_file_not_in_output_files(client, store):
    rid = _seed(store, _storyline(1), output_filename="output.pdf", output_files=["output.pdf"], status=ReportStatus.COMPLETED)
    store.output_path(rid, "output.pdf").write_bytes(b"%PDF-1.4")
    store.output_path(rid, "output.pptx").write_bytes(b"pk")
    assert client.get(f"/api/reports/{rid}/download?file=output.pptx").status_code == 404
    assert client.get(f"/api/reports/{rid}/download?file=manifest.json").status_code == 404
    assert client.get(f"/api/reports/{rid}/download?file=output.pdf").status_code == 200


async def test_findings_follow_a_fit_split_and_lint_matches_final_deck(tmp_path, fake_llm):
    long = SlideContent(headline="x", layout="bullets", variant="five", slots={"items": [" ".join(f"w{k}" for k in range(60))] * 10})
    bad = SlideContent(headline="x", layout="nope", variant="nope")
    llm = fake_llm({"SlideContent": [long, bad, bad], "QAResult": [QAResult(edits=[])]})  # lint rewrites fail: unscripted
    deck, findings = await house_pipeline.build_house_deck("r1", _REQ, _storyline(2), llm, _store(tmp_path))
    last = len(deck.slides) - 1
    assert last > 2 and deck.slides[last].headline == "Point 1 holds."  # slide 1 was split
    assert [f.slide for f in findings if f.rule == "bad_reference"] == [last]
    assert [f for f in findings if f.stage == "lint"] == lint_deck(deck, _REQ)


async def test_approve_after_failed_rerender_rerenders_saved_deck(tmp_path, fake_llm):
    store = _store(tmp_path)
    service = ReportingService(store)
    manifest = await service.create_and_plan(_REQ, fake_llm({"Storyline": [_storyline(1)]}))
    await service.approve_storyline(manifest.report_id, fake_llm({"SlideContent": [_bullets()]}))
    rid = manifest.report_id
    store.save_manifest(manifest.model_copy(update={"status": ReportStatus.FAILED, "error": "render failed"}))  # as a failed re-render leaves it
    store.output_path(rid, "output.pdf").unlink()

    manifest = await service.approve_storyline(rid, fake_llm({}))  # no LLM: the saved deck is re-rendered

    assert manifest.status == ReportStatus.COMPLETED and store.output_path(rid, "output.pdf").exists()
