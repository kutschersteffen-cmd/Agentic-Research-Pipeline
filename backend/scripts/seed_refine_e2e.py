"""Seeds the e2e stack for the Refine rows (spec refine-chat-design, amendment 2026-11-22): RFP project P with library
entry E1, report R `Climate review` with a 4-slide house deck, report N with a storyline and no deck, and ask thread T
asked through the ask stand-in. Writes where the app reads (Postgres, `reports_dir`) and, with ARP_STANDINS_DIR set
(as the API has it), the `DraftOut` and `FactCheck` stand-ins for a grounded draft of P. Prints the ids as JSON.

    ARP_STANDINS_DIR=/tmp/arp-standins bash backend/scripts/e2e_stack.sh up
    ARP_STANDINS_DIR=/tmp/arp-standins python backend/scripts/seed_refine_e2e.py
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, timedelta

from arp.api.deps import get_reporting_store
from arp.config import get_settings
from arp.db import models as m
from arp.db.session import transaction
from arp.schemas.reporting import (
    ChartSpec,
    DatasetColumn,
    Deck,
    Finding,
    OutputFormat,
    QuantitativeDataset,
    ReportManifest,
    ReportRequest,
    ReportStatus,
    SlideContent,
    Storyline,
    StorylineSlide,
)
from arp.storage.reporting_store import ReportingStore

INVESTOR = "Nordic Pension Fund"
LIB = "We screen all holdings quarterly."
GROUNDED = "We screen holdings quarterly."
API = os.environ.get("ARP_API_URL", "http://127.0.0.1:8000")
os.environ.setdefault("ARP_POSTGRES_DSN", "postgresql+psycopg://arp:arp@localhost:5432/arp_test")  # as e2e_stack.sh
T_QUESTION = "What can ARP answer?"
# 400 words, far more than slide 4's `text` slot holds, so the stage marks it `Text doesn't fit`.
SENTENCE = "Emissions intensity across the holdings kept falling while coverage of reported data widened"
LONG = " ".join((SENTENCE.split(" ") * 40)[:400])

DS = QuantitativeDataset(dataset_id="ds_em", name="Emissions", columns=[DatasetColumn(name="year"), DatasetColumn(name="t")],
                         rows=[{"year": "2022", "t": 12}, {"year": "2023", "t": 10}, {"year": "2024", "t": 8}])


def _chart() -> ChartSpec:
    return ChartSpec(dataset_id="ds_em", chart_type="line", category_column="year", value_columns=["t"])


def _rfp() -> dict:
    today = date.today()
    with transaction() as s:
        e1 = m.RfpLibraryEntry(question="How do you screen holdings?", answer=LIB, tags=[], approved_on=today,
                               review_by=today + timedelta(days=365), has_figures=False)
        p = m.RfpProject(investor=INVESTOR, filename="rfp.xlsx", content_key="seed-refine", run_status="done", created_by="dev")
        s.add_all([e1, p])
        s.flush()
        qs = [m.RfpQuestion(project_id=p.id, position=i, location=f"A{i}", answer_location=f"B{i}", question=f"Question {i}?",
                            answer=a, status=st, flags=[], sources=[])
              for i, (a, st) in enumerate([("A1", "drafted"), ("A2", "drafted"), ("A3", "approved"), ("", "no source")], 1)]
        s.add_all(qs)
        s.flush()
        return {"P": p.id, "E1": e1.id, "Q": [q.id for q in qs]}


def _report(store: ReportingStore, title: str, deck: Deck | None) -> str:
    man = ReportManifest(title=title, output_format=OutputFormat.HOUSE_DECK,
                         status=ReportStatus.COMPLETED if deck else ReportStatus.STORYLINE_READY)
    store.save_manifest(man)
    store.save_request(man.report_id, ReportRequest(title=title, qualitative_notes="Emissions fell each year.", datasets=[DS]))
    headlines = [s.headline for s in deck.slides] if deck else ["Emissions fell", "Coverage widened"]
    store.save_storyline(man.report_id, Storyline(title=title, slides=[StorylineSlide(headline=h, purpose="p") for h in headlines],
                                                  approved=deck is not None))
    store.save_findings(man.report_id, [Finding(slide=1, stage="qa", rule="r", message="Target year 2040.")])
    if deck:
        store.save_deck(man.report_id, deck)
    return man.report_id


def _deck() -> Deck:
    bullets = lambda h: SlideContent(headline=h, layout="bullets", variant="three", slots={"items": ["Scope 1 and 2", "Scope 3", "Targets"]})  # noqa: E731
    return Deck(title="Climate review", slides=[
        bullets("S1"),
        SlideContent(headline="S2", layout="two_column", variant="text_chart", slots={"text": "Emissions fell each year."}, chart=_chart()),
        bullets("S3"),
        SlideContent(headline="S4", layout="two_column", variant="text_chart", slots={"text": LONG}, chart=_chart()),
    ])


def _standins(e1: int) -> None:
    folder = get_settings().standins_dir
    if folder is None:
        return
    model = folder / "model"
    model.mkdir(parents=True, exist_ok=True)
    draft = {"answer": GROUNDED, "citations": [{"entry_id": e1, "quote": LIB}]}
    (model / "DraftOut.json").write_text(json.dumps({"output": draft}))
    (model / "FactCheck.json").write_text(json.dumps({"output": {}}))
    (model / "AskRouting.json").write_text(json.dumps({"output": {"tool": "none", "standalone_question": T_QUESTION}}))


def _ask_thread() -> str:
    """T: one ask through the running API, answered by the `AskRouting` stand-in."""
    req = urllib.request.Request(f"{API}/api/agent/asks", data=json.dumps({"question": T_QUESTION}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - the local e2e API
        return json.load(r)["thread_id"]


def main() -> dict:
    store = get_reporting_store()
    rfp = _rfp()
    _standins(rfp["E1"])
    out = {**rfp, "R": _report(store, "Climate review", _deck()), "N": _report(store, "Supply chain review", None), "T": _ask_thread()}
    print(json.dumps(out))
    return out


if __name__ == "__main__":
    main()
