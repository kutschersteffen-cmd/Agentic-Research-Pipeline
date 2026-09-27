from __future__ import annotations

import json

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
    titles = [s.shapes.title.text for s in pptx.Presentation(build_pptx(report, tmp_path / "r.pptx")).slides]
    for heading in (
        "Expected votes: client policy against the house",
        "Client escalations decided by the house",
        "Voting policy decisions",
        "Data sources",
    ):
        assert heading in titles
