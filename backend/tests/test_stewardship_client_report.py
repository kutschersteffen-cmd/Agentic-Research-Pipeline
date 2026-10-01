from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("zen")
pptx = pytest.importorskip("pptx")

from arp.api.routers.stewardship import CreateStreamRequest, create_stream  # noqa: E402
from arp.stewardship.client_report import build_pptx, client_report  # noqa: E402
from arp.stewardship.policy_review import DATA  # noqa: E402
from arp.stewardship.process import StreamStore, build_stream_policy  # noqa: E402


def _stream(tmp_path, built: bool) -> tuple[StreamStore, dict]:
    streams = StreamStore(tmp_path)
    stream = streams.get(create_stream(CreateStreamRequest(name="Example Pension Fund"), streams)["stream_id"])
    if built:
        decisions = json.loads((DATA / "examples" / "client_policy_example_decisions.json").read_text())
        stream = streams.save(build_stream_policy({**stream, "decisions": decisions}))
    return streams, stream


def _texts(path) -> list[str]:
    return [sh.text_frame.text for s in pptx.Presentation(path).slides for sh in s.shapes if sh.has_text_frame]


def test_stewardship_client_report_uses_house_renderer_without_llm(tmp_path, monkeypatch):
    import arp.llm.factory

    monkeypatch.setattr(arp.llm.factory, "build_llm_client", lambda *a, **k: pytest.fail("no LLM for stewardship decks"))
    streams, stream = _stream(tmp_path, built=False)
    out = build_pptx(client_report(streams.root, stream, [], sla_days=45), tmp_path / "r.pptx")
    assert out == tmp_path / "r.pptx" and out.exists() and (tmp_path / "r.pdf").exists()
    assert "Data sources" in _texts(out)


def test_pptx_endpoint_skips_the_pdf_and_the_browser(tmp_path, monkeypatch):
    from fastapi import BackgroundTasks

    import arp.stewardship.client_report as cr
    from arp.api.routers.stewardship import get_client_report_pptx
    from arp.config import Settings
    from arp.storage.engagement_store import EngagementStore

    monkeypatch.setattr(cr, "write_pdf", lambda *a: pytest.fail("the endpoint deletes its temp dir; no PDF"))
    streams, stream = _stream(tmp_path, built=False)
    tasks = BackgroundTasks()
    resp = get_client_report_pptx(stream["stream_id"], tasks, Settings(), streams, EngagementStore(tmp_path / "eng"))
    out = Path(resp.path)
    assert out.suffix == ".pptx" and out.exists() and not list(out.parent.glob("*.pdf"))
    shutil.rmtree(out.parent)


def test_report_of_a_new_stream_says_what_is_still_in_review(tmp_path):
    streams, stream = _stream(tmp_path, built=False)
    report = client_report(streams.root, stream, [], sla_days=45)
    assert "in review, 0 of" in report["summary"][1]
    assert report["votes"] == [] and report["exceptions"] == [] and report["policy_decisions"] == []
    assert sum(t["companies"] for t in report["tiers"]) == 12


def test_built_stream_report_renders_every_section_as_a_deck(tmp_path):
    streams, stream = _stream(tmp_path, built=True)
    stream = streams.save(
        {
            **stream,
            "exception_decisions": [
                {
                    "issue_id": "iss_x",
                    "company_id": "SYN10",
                    "theme": "climate_transition",
                    "house_step": "written_escalation_to_board",
                    "client_step": "escalation_to_chair",
                    "decision": "adopt",
                    "decided_by": "Lead",
                    "note": "",
                    "decided_at": "2026-09-01T00:00:00+00:00",
                }
            ],
        }
    )
    report = client_report(streams.root, stream, [], sla_days=45)
    assert "custom policy built" in report["summary"][1] and "1 adopted" in report["summary"][3]
    assert report["exceptions"][0]["company"] == "Synthetic Company 10"
    house, client = (sum(v[k] for v in report["votes"]) for k in ("house", "client"))
    assert house == client > 0  # the same resolutions, voted by both policies
    titles = _texts(build_pptx(report, tmp_path / "r.pptx"))
    for heading in (
        "Expected votes: client policy against the house",
        "Client escalations decided by the house",
        "Voting policy decisions",
        "Data sources",
    ):
        assert heading in titles
