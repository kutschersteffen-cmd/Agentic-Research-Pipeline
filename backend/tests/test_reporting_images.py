"""Registering and storing house-deck images (spec house-deck-image-slides, slice 1)."""

import hashlib
import io
import json
import re

import click
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from typer.testing import CliRunner

from arp.api.deps import get_reporting_store
from arp.api.routers import reporting as reporting_router
from arp.cli import reporting as cli
from arp.reporting.service import ReportingService
from arp.schemas.reporting import (
    Deck,
    LayoutInstructions,
    OutputFormat,
    ReportImage,
    ReportManifest,
    ReportRequest,
    ReportStatus,
    Storyline,
)
from arp.storage.reporting_store import ReportingStore


def _png(w, h, colour="#ff0000") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, "PNG")
    return buf.getvalue()


def _quad() -> bytes:
    im = Image.new("RGB", (2000, 1000), "#0000ff")
    im.paste(Image.new("RGB", (1000, 1000), "#ff0000"), (0, 0))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _rotated_jpeg() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    Image.new("RGB", (400, 200), "#00ff00").save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def store(tmp_path) -> ReportingStore:
    return ReportingStore(tmp_path / "reports", tmp_path / "tpl")


# ---- CLI --------------------------------------------------------------------


@pytest.fixture
def plan(tmp_path, monkeypatch, store, fake_llm):
    llm = fake_llm({"Storyline": [Storyline(title="D", slides=[])]})
    monkeypatch.setattr(cli, "_reporting_store", lambda: store)
    monkeypatch.setattr(cli, "build_llm_client", lambda settings: llm)
    monkeypatch.setattr("arp.reporting.service.with_run_datasets", lambda request, settings: request)
    notes = tmp_path / "notes.txt"
    notes.write_text("notes")

    def run(*args, format="house_deck"):
        return CliRunner().invoke(cli.reporting_app, [
            "plan", "--title", "T", "--notes", str(notes), "--out", str(tmp_path / "s.json"), "--format", format, *args,
        ])
    return run


def _flat(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", click.unstyle(text).lower())  # rich wraps the error box


def test_cli_registers_an_image_with_alt_and_focus(tmp_path, plan, store):
    (tmp_path / "quad.png").write_bytes(_quad())
    result = plan("--image", f"hero={tmp_path / 'quad.png'}", "--image-alt", "hero=Landing page", "--image-focus", "hero=0.2,0.5")
    assert result.exit_code == 0, result.output
    [m] = store.list_reports()
    request = json.loads(store.request_path(m.report_id).read_text())
    [img] = request["images"]
    assert (img["name"], img["media_type"], img["width"], img["height"], img["alt"], img["focus"]) == (
        "hero", "image/png", 2000, 1000, "Landing page", [0.2, 0.5])
    assert img["image_id"].startswith("img_")
    assert _sha((store.reports_dir / m.report_id / "images" / "hero.png").read_bytes()) == _sha(_quad())


@pytest.mark.parametrize(("args", "message"), [
    (["--image", "hero=missing.png"], "image 'hero': file not found: missing.png"),
    (["--image", "shot={fake}"], "image 'shot' is not a PNG or JPEG image"),
    (["--image", "Hero={quad}"], "image name 'Hero' must be 1-32 characters: a-z, 0-9, _ or -, starting with a letter or digit"),
    (["--image", "a={quad}", "--image", "a={quad}"], "image name 'a' is registered twice"),
    ([x for i in range(21) for x in ("--image", f"i{i}={{small}}")], "at most 20 images per report"),
    (["--image", "a={quad}", "--image-focus", "a=1.5,0"], "focus for 'a' must be two numbers from 0 to 1, like 0.5,0.3"),
    (["--image", "a={quad}", "--image-focus", "a=x"], "focus for 'a' must be two numbers from 0 to 1, like 0.5,0.3"),
    (["--image", "a={quad}", "--cover-image", "b"], "no image named 'b'; registered: a"),
    (["--image", "a={quad}", "--image-alt", "b=x"], "no image named 'b'; registered: a"),
])
def test_cli_rejects_bad_images_before_any_report(tmp_path, plan, store, args, message):
    (tmp_path / "quad.png").write_bytes(_quad())
    (tmp_path / "small.png").write_bytes(_png(800, 400))
    (tmp_path / "fake.png").write_text("not an image")
    paths = {k: tmp_path / f"{k}.png" for k in ("quad", "small", "fake")}
    result = plan(*[a.format(**paths) for a in args])
    assert result.exit_code == 2
    assert _flat(message) in _flat(result.output)
    assert store.list_reports() == []
    assert not store.images_dir.exists()  # nothing staged either


def test_cli_image_flags_need_the_house_deck(tmp_path, plan, store):
    (tmp_path / "quad.png").write_bytes(_quad())
    result = plan("--image", f"a={tmp_path / 'quad.png'}", format="pptx")
    assert result.exit_code == 2 and _flat("--image needs --format house_deck") in _flat(result.output)
    assert store.list_reports() == []


# ---- API --------------------------------------------------------------------


@pytest.fixture
def client(store, monkeypatch, fake_llm) -> TestClient:
    monkeypatch.setattr(reporting_router, "get_llm_client", lambda: fake_llm({"Storyline": [Storyline(title="D", slides=[])]}))
    monkeypatch.setattr("arp.reporting.service.with_run_datasets", lambda request, settings: request)
    app = FastAPI()
    app.include_router(reporting_router.router)
    app.dependency_overrides[get_reporting_store] = lambda: store
    return TestClient(app)


def _upload(client, data: bytes, filename="quad.png"):
    return client.post("/api/reports/images", files={"file": (filename, data)})


def _house(**extra) -> dict:
    return {"title": "T", "qualitative_notes": "n", "layout": {"output_format": "house_deck"}, **extra}


def test_api_uploads_creates_and_serves_an_image(client, store):
    r = _upload(client, _quad())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["image_id"].startswith("img_")
    assert (body["media_type"], body["width"], body["height"], body["sha256"]) == ("image/png", 2000, 1000, _sha(_quad()))

    r = client.post("/api/reports", json=_house(images=[{"image_id": body["image_id"], "name": "shot", "focus": [0.2, 0.5]}]))
    assert r.status_code == 200, r.text
    rid = r.json()["report_id"]
    got = client.get(f"/api/reports/{rid}/images/shot")
    assert got.status_code == 200 and got.headers["content-type"] == "image/png" and got.content == _quad()
    [img] = json.loads(store.request_path(rid).read_text())["images"]
    assert (img["focus"], img["alt"], img["width"], img["height"]) == ([0.2, 0.5], "", 2000, 1000)
    assert client.get(f"/api/reports/{rid}/images/x").status_code == 404
    assert client.get(f"/api/reports/{rid}/images/..%2Fmanifest").status_code == 404


@pytest.mark.parametrize(("data", "filename", "status", "detail"), [
    (b"\0" * (21 * 1024 * 1024), "big.png", 413, "image 'big.png' is larger than 20 MB"),
    (None, "a.gif", 400, "image 'a.gif' is not a PNG or JPEG image"),
    (b"hello", "a.png", 400, "image 'a.png' is not a PNG or JPEG image"),
    (None, "wide.png", 400, "image 'wide.png' has more than 50 megapixels"),
])
def test_api_upload_rejects(client, data, filename, status, detail):
    if filename == "a.gif":
        buf = io.BytesIO()
        Image.new("RGB", (4, 4)).save(buf, "GIF")
        data = buf.getvalue()
    if filename == "wide.png":
        data = _png(7072, 7072)
    r = _upload(client, data, filename)
    assert (r.status_code, r.json()["detail"]) == (status, detail)


def test_api_create_rejects_unknown_ids_and_cover_images(client, store):
    r = client.post("/api/reports", json=_house(images=[{"image_id": "img_nope", "name": "a"}]))
    assert (r.status_code, r.json()["detail"]) == (422, "unknown image_id 'img_nope'")
    image_id = _upload(client, _quad()).json()["image_id"]
    r = client.post("/api/reports", json=_house(images=[{"image_id": image_id, "name": "shot"}], deck={"cover_image": "zz"}))
    assert (r.status_code, r.json()["detail"]) == (422, "no image named 'zz'; registered: shot")
    r = client.post("/api/reports", json=_house(images=[{"image_id": image_id, "name": "shot", "focus": [2, 0]}]))
    assert (r.status_code, r.json()["detail"]) == (422, "focus for 'shot' must be two numbers from 0 to 1, like 0.5,0.3")
    assert client.get("/api/reports").json()["reports"] == []


def test_api_image_of_unknown_report_is_404_without_a_dir(client, store):
    assert client.get("/api/reports/rpt_nope/images/x").status_code == 404
    assert not (store.reports_dir / "rpt_nope").exists()


# ---- store and re-run ---------------------------------------------------------


def test_exif_rotated_jpeg_is_stored_upright(store):
    entry = store.save_report_image("rpt_1", "r", _rotated_jpeg())
    assert (entry.media_type, entry.width, entry.height) == ("image/jpeg", 200, 400)
    path = store.report_image_path("rpt_1", "r")
    assert path.name == "r.jpg" and Image.open(path).size == (200, 400)
    assert entry.sha256 == _sha(path.read_bytes())


def test_load_report_images_reads_the_stored_bytes(store):
    entry = store.save_report_image("rpt_1", "a", _quad(), alt="A", focus=[0.1, 0.9])
    request = ReportRequest(title="T", qualitative_notes="n", images=[entry])
    [(name, loaded)] = store.load_report_images("rpt_1", request).items()
    assert name == "a" and loaded.entry == entry and loaded.data == _quad()


async def test_rerun_copies_images_and_leaves_the_source_alone(store, monkeypatch):
    monkeypatch.setattr("arp.reporting.service.with_run_datasets", lambda request, settings: request)
    m = ReportManifest(title="T", output_format=OutputFormat.HOUSE_DECK, status=ReportStatus.COMPLETED)
    store.save_manifest(m)
    entry = store.save_report_image(m.report_id, "hero", _quad())
    store.save_request(m.report_id, ReportRequest(title="T", qualitative_notes="n", layout=LayoutInstructions(output_format=OutputFormat.HOUSE_DECK), images=[entry]))
    store.save_storyline(m.report_id, Storyline(title="D", slides=[], approved=True))
    store.save_deck(m.report_id, Deck(title="D", slides=[]))
    before = sorted(p.relative_to(store.reports_dir) for p in (store.reports_dir / m.report_id).rglob("*"))

    service = ReportingService(store)

    async def no_build(report_id, llm):
        return store.load_manifest(report_id)
    monkeypatch.setattr(service, "approve_storyline", no_build)
    new = await service.rerun(m.report_id, llm=None)

    assert _sha(store.report_image_path(new.report_id, "hero").read_bytes()) == _sha(_quad())
    assert isinstance(store.load_request(new.report_id).images[0], ReportImage)
    assert sorted(p.relative_to(store.reports_dir) for p in (store.reports_dir / m.report_id).rglob("*")) == before
