import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.deps import get_reporting_store
from arp.api.routers import reporting as reporting_router
from arp.reporting.template_frame import font_family_of
from arp.schemas.reporting import TemplateStyleProfile
from arp.storage.reporting_store import ReportingStore
from tests.fixtures.frame_template import frame_fonts, make_frame_pptx


def test_old_profile_loads_with_null_frame():
    old = {"template_id": "tpl_old", "source_filename": "a.pptx", "slide_width_emu": 12192000, "slide_height_emu": 6858000, "stored_path": "x"}
    p = TemplateStyleProfile.model_validate(old)
    assert p.frame is None
    assert p.frame_error is None


@pytest.fixture
def store(tmp_path) -> ReportingStore:
    return ReportingStore(tmp_path / "reports", tmp_path / "templates")


@pytest.fixture
def client(store) -> TestClient:
    app = FastAPI()
    app.include_router(reporting_router.router)
    app.dependency_overrides[get_reporting_store] = lambda: store
    return TestClient(app)


def upload(client, tmp_path, fonts=("TestaSerif-700.ttf", "TestaSans-400.ttf"), layout_name=None, **pptx):
    path = make_frame_pptx(tmp_path / "frame.pptx", **pptx)
    files = [("file", ("frame.pptx", path.read_bytes()))]
    files += [("fonts", (f.name, f.read_bytes())) for f in frame_fonts(tmp_path / "fonts", fonts)]
    r = client.post("/api/reports/templates", files=files, data={"layout_name": layout_name} if layout_name else None)
    assert r.status_code == 200, r.text
    return r.json()


def _box(b):
    return [b["x"], b["y"], b["w"], b["h"]]


def test_ac1_boxes(client, tmp_path):
    f = upload(client, tmp_path)["frame"]
    assert f["layout_name"] == "Content"
    assert _box(f["headline"]) == pytest.approx([144, 72, 1584, 144], abs=1)
    assert _box(f["subheading"]) == pytest.approx([144, 230.4, 1584, 72], abs=1)
    assert _box(f["body"]) == pytest.approx([144, 345.6, 1584, 561.6], abs=1)


def test_ac2_fonts(client, tmp_path):
    f = upload(client, tmp_path)["frame"]
    assert (f["headline_font"]["family"], f["headline_font"]["bold"]) == ("Testa Serif", True)
    assert f["headline_font"]["size_px"] == pytest.approx(64, abs=0.1)
    assert (f["subheading_font"]["family"], f["subheading_font"]["bold"]) == ("Testa Sans", False)
    assert f["subheading_font"]["size_px"] == pytest.approx(36, abs=0.1)
    assert f["body_font_family"] == "Testa Sans"


@pytest.mark.parametrize(("kwargs", "error"), [
    ({"width_emu": 9144000}, "Template must be 16:9 (got 9144000×6858000)."),
    ({"with_subheading": False}, "No layout has a title, a subheading and a body placeholder."),
    ({"fonts": ("TestaSans-400.ttf",)}, 'Upload the font file for "Testa Serif".'),
    ({"layout_name": "Missing"}, 'No layout named "Missing".'),
], ids=["ac3_not_16_9", "ac4_no_subheading", "ac5_missing_font", "ac26_unknown_layout"])
def test_frame_errors(client, tmp_path, kwargs, error):
    style = upload(client, tmp_path, **kwargs)
    assert style["frame"] is None
    assert style["frame_error"] == error


def test_ac6_fonts_stored(client, store, tmp_path):
    tid = upload(client, tmp_path)["template_id"]
    assert sorted(os.listdir(store.template_font_dir(tid))) == ["TestaSans-400.ttf", "TestaSerif-700.ttf"]


def test_ac23_old_profile_listed(client, store):
    d = store.template_dir("tpl_old")
    (d / "style.json").write_text(json.dumps({"template_id": "tpl_old", "source_filename": "a.pptx", "slide_width_emu": 1, "slide_height_emu": 1, "stored_path": "x"}))
    r = client.get("/api/reports/templates")
    assert r.status_code == 200
    assert [t["frame"] for t in r.json()["templates"] if t["template_id"] == "tpl_old"] == [None]


def test_inherits_master_position(client, tmp_path):
    body = upload(client, tmp_path, body_xfrm=False)["frame"]["body"]
    s = 1920 / 12192000  # the master's body placeholder box, at the template's scale
    assert _box(body) == pytest.approx([457200 * s, 1600200 * s, 8229600 * s, 4525963 * s], abs=1)


def test_first_qualifying_layout_wins(client, tmp_path):
    assert upload(client, tmp_path, layouts=("Content", "Content 2"))["frame"]["layout_name"] == "Content"


def test_font_family_of():
    assert font_family_of("TestaSerif-700.ttf") == "testaserif"
    assert font_family_of("x.otf") is None
    assert font_family_of("Geist-400.WOFF2") == "geist"
