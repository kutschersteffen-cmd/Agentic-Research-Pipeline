"""Argus step 1, showcase fixes: the ticker lookup, broken lists, editing and removing a row, discarding a draft,
and the result of an identity run (spec showcase-argus-fixes, items 2 to 5 and 7)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arp.api.auth import Principal, current_user
from arp.api.deps import get_edgar_source, get_run_store, settings_dep
from arp.api.main import app
from arp.argus.flows import FlowStore, safe_key
from arp.config import Settings
from arp.db.models import Company, CompanyIdentifier
from arp.db.session import engine
from arp.schemas.common import RunManifest
from arp.schemas.discovery import IdentityResolutionResult, IdentitySignals
from arp.storage.run_store import RunStore
from tests.pdf_fixtures import FILLER, make_pdf

NO_IDENTIFIER = "No identifier: add an ISIN, LEI or CIK"
STARTED = "Companies cannot be changed once the extraction has started."


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache",
                    documents_dir=tmp_path / "docs", discovery_state_dir=tmp_path / "state", postgres_dsn=pg,
                    max_upload_bytes=1_000_000)


@pytest.fixture
def run_store(settings, pg):
    return RunStore(pg, settings.runs_dir)


class _SecList:
    """Stands in for the SEC ticker list (`EdgarDocumentSource.resolve_cik`)."""

    def __init__(self):
        self.tickers: dict[str, str] | None = {}
        self.asked: list[str] = []

    async def resolve_cik(self, ticker):
        self.asked.append(ticker)
        if self.tickers is None:
            raise OSError("the SEC is unreachable")
        return self.tickers.get(ticker.upper())


@pytest.fixture
def sec():
    return _SecList()


@pytest.fixture
def client(settings, run_store, sec):
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_run_store] = lambda: run_store
    app.dependency_overrides[get_edgar_source] = lambda: sec
    yield TestClient(app)
    for dep in (settings_dep, get_run_store, get_edgar_source, current_user):
        app.dependency_overrides.pop(dep, None)


@pytest.fixture
def fid(client):
    return client.post("/api/argus/flows").json()["flow_id"]


def add(client, fid, **company):
    r = client.post(f"/api/argus/flows/{fid}/companies", json={"company": company})
    assert r.status_code == 200, r.text
    return r.json()


def by_name(flow):
    return {c["name"]: c for c in flow["companies"]}


def count(pg, model=Company):
    with Session(engine(pg)) as s:
        return s.scalar(select(func.count()).select_from(model))


def seed(pg, name, **ids):
    with Session(engine(pg)) as s, s.begin():
        c = Company(name=name)
        s.add(c)
        s.flush()
        for scheme, value in ids.items():
            s.add(CompanyIdentifier(company_id=c.id, scheme=scheme.upper(), value=value))


def upload_pdf(client, fid, company_id, tmp_path, name="report.pdf", title="Annual Report 2025"):
    data = make_pdf(tmp_path / name, [title, FILLER], n_pages=2).read_bytes()
    r = client.post(f"/api/argus/flows/{fid}/documents/upload", data={"company_id": company_id, "doc_type": "10-K"},
                    files={"file": (name, data, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def edit(client, fid, company_id, **body):
    return client.put(f"/api/argus/flows/{fid}/companies/{company_id}", json=body)


def rewrite(settings, fid, **fields):
    """Changes the stored flow file as it lies on disk (`updated_at` included, which every save through the store resets)."""
    path = settings.runs_dir / "_flows" / f"{fid}.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), **fields}))


def ago(seconds):
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


# --- item 1: a list's row numbers are not keys ---

def upload(client, fid, text):
    r = client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", text)})
    assert r.status_code == 200, r.text
    return r.json()


def test_two_lists_that_number_their_rows_do_not_share_a_key(client, fid, tmp_path):  # AC-1, AC-3
    acme = upload(client, fid, "company_id,name\n1,Acme\n")["companies"][0]["company_id"]
    other = client.post("/api/argus/flows").json()["flow_id"]
    foo = upload(client, other, "company_id,name\n1,Foo Corp\n")["companies"][0]["company_id"]
    assert acme != foo
    upload_pdf(client, fid, acme, tmp_path, title="Acme Annual Report 2025")
    assert client.get(f"/api/argus/flows/{other}").json()["files"] == []


def test_one_list_that_repeats_a_row_number_keeps_both_rows(client, fid):  # AC-2
    flow = upload(client, fid, "company_id,name\n1,Acme\n1,Foo Corp\n")
    assert [c["name"] for c in flow["companies"]] == ["Acme", "Foo Corp"]


def test_the_same_numbered_row_has_one_key_in_every_flow(client, fid):  # AC-4
    first = upload(client, fid, "company_id,name\n7,Acme\n")["companies"][0]["company_id"]
    other = client.post("/api/argus/flows").json()["flow_id"]
    assert upload(client, other, "company_id,name\n7,Acme\n")["companies"][0]["company_id"] == first


def test_a_list_id_with_a_letter_stays_the_key(client, fid):
    """Documents and earlier runs are filed under ids like these; only a bare row number says nothing about the company."""
    flow = upload(client, fid, "company_id,name\naapl,Apple Inc\nA1,Acme\n")
    assert [c["company_id"] for c in flow["companies"]] == ["aapl", "A1"]


# --- item 2: the ticker ---

def test_a_ticker_is_matched_through_its_cik(client, fid, sec, pg):  # AC-7
    sec.tickers = {"MSFT": "789019"}
    flow = add(client, fid, name="Microsoft", ticker="MSFT")
    ms = flow["companies"][0]
    assert ms["entity_id"] and ms["cik"].lstrip("0") == "789019"
    assert flow["rows"][0]["problem"] is None


def test_a_ticker_the_sec_does_not_list_never_matches(client, fid, sec, pg):  # AC-8, AC-9
    seed(pg, "Zed Holdings", ticker="ZZZZ")
    before = count(pg)
    flow = add(client, fid, name="Zed", ticker="ZZZZ")
    assert flow["companies"][0]["entity_id"] is None and count(pg) == before
    problem = "Ticker ZZZZ is not listed at the SEC: add an ISIN, LEI or CIK"
    assert flow["rows"][0]["problem"] == problem
    assert client.get(f"/api/argus/flows/{fid}").json()["rows"][0]["problem"] == problem


def test_an_unreadable_ticker_list_still_adds_the_row(client, fid, sec):  # AC-10
    sec.tickers = None
    flow = add(client, fid, name="Microsoft", ticker="MSFT")
    assert flow["rows"][0]["problem"] == "The SEC ticker list could not be read: add an ISIN, LEI or CIK"


def test_a_row_with_an_identifier_is_not_looked_up(client, fid, sec):  # AC-11
    sec.tickers = {"MSFT": "789019"}
    flow = add(client, fid, name="Microsoft", ticker="MSFT", isin="US5949181045")
    assert flow["companies"][0]["cik"] is None and sec.asked == []


def test_an_invalid_identifier_does_not_stop_the_lookup(client, fid, sec):  # AC-144
    sec.tickers = {"MSFT": "789019"}
    ms = add(client, fid, name="Microsoft", ticker="MSFT", isin="XX")["companies"][0]
    assert ms["cik"].lstrip("0") == "789019" and ms["isin"] is None


def test_no_ticker_and_no_identifier_reads_as_before(client, fid, sec):  # AC-12
    assert add(client, fid, name="Acme")["rows"][0]["problem"] == NO_IDENTIFIER
    assert sec.asked == []


def test_every_ticker_lookup_runs_on_the_apps_event_loop(settings, run_store):
    """Code review of PR #425, round 2: the SEC source is one shared object with one `asyncio.Lock`. A lookup run on
    an event loop of its own (`asyncio.run` in a request thread) waits for ever when another loop holds that lock."""
    import asyncio

    loops = []

    class Sec:
        async def resolve_cik(self, ticker):
            loops.append(asyncio.get_running_loop())
            return "789019"

    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_run_store] = lambda: run_store
    app.dependency_overrides[get_edgar_source] = Sec
    try:
        with TestClient(app) as c:  # one app loop for every request, as in the running app
            fid = c.post("/api/argus/flows").json()["flow_id"]
            key = add(c, fid, name="Microsoft", ticker="MSFT")["companies"][0]["company_id"]  # a sync endpoint
            assert edit(c, fid, key, name="Microsoft", ticker="MSFT", isin="XX").status_code == 200  # a sync endpoint
            upload(c, fid, "name,ticker\nApple,AAPL\n")  # an async endpoint: on the app's loop already
    finally:
        for dep in (settings_dep, get_run_store, get_edgar_source):
            app.dependency_overrides.pop(dep, None)
    assert len(loops) == 3 and loops[0] is loops[1] is loops[2]


def test_official_filings_get_the_cik_the_ticker_gave(client, fid, sec, run_store, monkeypatch):  # AC-140
    from arp.api.routers import argus as router

    async def no_search(run_id, companies, **kw):
        pass

    monkeypatch.setattr(router, "execute_discovery_run", no_search)
    sec.tickers = {"MSFT": "789019"}
    add(client, fid, name="Microsoft", ticker="MSFT")
    client.patch(f"/api/argus/flows/{fid}", json={"source": "filings"})
    flow = client.post(f"/api/argus/flows/{fid}/documents/find").json()
    stored = run_store.load_companies(flow["discovery_run_id"])
    assert [(c.name, c.cik.lstrip("0")) for c in stored] == [("Microsoft", "789019")]


# --- item 5: a list that cannot be read ---

def test_a_list_the_csv_reader_rejects_is_a_400(client, fid):  # AC-28
    body = 'name,isin\n"' + "x" * 200_000
    r = client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("x.csv", body)})
    assert r.status_code == 400 and r.json()["detail"].startswith("Could not read the list:")


def test_an_oversized_list_is_a_413(client, fid):  # AC-29
    body = "name\n" + "Acme Corporation\n" * 90_000  # 1.5 MB
    r = client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("x.csv", body)})
    assert (r.status_code, r.json()["detail"]) == (413, "File is larger than the 1 MB upload limit.")


# --- stored flows keep their keys ---

def test_a_stored_unmatched_row_keeps_its_key_and_files(client, fid, settings, tmp_path):  # AC-134
    rewrite(settings, fid, companies=[{"company_id": "1", "name": "Acme"}])
    folder = settings.documents_dir / "1" / "10-K"
    folder.mkdir(parents=True)
    make_pdf(folder / "acme.pdf", ["Acme Annual Report 2025", FILLER], n_pages=2)
    flow = client.get(f"/api/argus/flows/{fid}").json()
    assert flow["companies"][0]["company_id"] == "1"
    assert [f["key"] for f in flow["files"]] == ["1/10-K/acme.pdf"]


# --- item 3: edit ---

def test_an_edit_matches_the_row_in_place(client, fid):  # AC-13
    add(client, fid, name="Apple", isin="US0378331005")
    borealis = add(client, fid, name="Borealis")["companies"][1]["company_id"]
    add(client, fid, name="Microsoft", isin="US5949181045")
    r = edit(client, fid, borealis, name="Borealis", isin="DE000A1EWWW0")
    assert r.status_code == 200, r.text
    flow = r.json()
    assert [c["name"] for c in flow["companies"]] == ["Apple", "Borealis", "Microsoft"]
    second = flow["companies"][1]
    assert second["entity_id"] and second["isin"] == "DE000A1EWWW0" and flow["rows"][1]["problem"] is None


def test_an_edit_onto_a_company_already_listed_is_refused(client, fid):  # AC-14, AC-15
    add(client, fid, name="Apple", isin="US0378331005")
    acme = add(client, fid, name="Acme")["companies"][1]["company_id"]
    r = edit(client, fid, acme, name="Acme", isin="US0378331005")
    assert (r.status_code, r.json()["detail"]) == (400, "Apple is already in this extraction.")
    flow = client.get(f"/api/argus/flows/{fid}").json()
    assert len(flow["companies"]) == 2 and by_name(flow)["Acme"]["entity_id"] is None


def test_a_started_flow_cannot_change_its_companies(client, fid, settings):  # AC-18, AC-31, AC-32
    acme = add(client, fid, name="Acme")["companies"][0]["company_id"]
    FlowStore(settings.runs_dir / "_flows").update(fid, lambda f: setattr(f, "run_id", "extraction_x"))
    for r in (edit(client, fid, acme, name="Acme Corp"), client.delete(f"/api/argus/flows/{fid}/companies/{acme}")):
        assert (r.status_code, r.json()["detail"]) == (409, STARTED)
    r = client.post(f"/api/argus/flows/{fid}/discard")
    assert (r.status_code, r.json()["detail"]) == (409, "An extraction that has started cannot be deleted.")
    assert client.get(f"/api/argus/flows/{fid}").status_code == 200


def test_a_company_not_in_the_flow_is_a_400(client, fid):  # AC-19
    add(client, fid, name="Acme")
    for r in (edit(client, fid, "nope", name="X"), client.delete(f"/api/argus/flows/{fid}/companies/nope")):
        assert (r.status_code, r.json()["detail"]) == (400, "That company is not in this extraction.")
    assert edit(client, "nope", "x", name="X").status_code == 404
    acme = client.get(f"/api/argus/flows/{fid}").json()["companies"][0]["company_id"]
    r = edit(client, fid, acme, name="")
    assert (r.status_code, r.json()["detail"]) == (400, "A company needs a name.")
    assert client.post("/api/argus/flows/nope/discard").status_code == 404


def test_a_viewer_cannot_edit_remove_or_discard(client, fid):  # AC-20
    acme = add(client, fid, name="Acme")["companies"][0]["company_id"]
    app.dependency_overrides[current_user] = lambda: Principal(user_id="v", name="V", role="viewer")
    assert edit(client, fid, acme, name="Acme Corp").status_code == 403
    assert client.delete(f"/api/argus/flows/{fid}/companies/{acme}").status_code == 403
    assert client.post(f"/api/argus/flows/{fid}/discard").status_code == 403


def test_an_edit_that_would_move_a_row_with_files_is_refused(client, fid, tmp_path, pg):  # AC-21, AC-22
    add(client, fid, name="Cedar", isin="FR0000120271")
    other = client.post("/api/argus/flows").json()["flow_id"]
    cedar = add(client, other, name="Cedar")["companies"][0]["company_id"]
    upload_pdf(client, other, cedar, tmp_path, title="Cedar Annual Report 2025")
    identifiers = count(pg, CompanyIdentifier)
    r = edit(client, other, cedar, name="Cedar", isin="FR0000120271", lei="969500WEPS61H6TJM037")
    assert (r.status_code, r.json()["detail"]) == (
        409, "Cedar has files in this extraction. Remove the company and add it again with the identifier.")
    flow = client.get(f"/api/argus/flows/{other}").json()
    assert flow["companies"][0]["entity_id"] is None and [f["filename"] for f in flow["files"]] == ["report.pdf"]
    assert count(pg, CompanyIdentifier) == identifiers  # the register transaction was rolled back: no LEI was attached


def test_without_files_the_row_moves_to_the_stored_company(client, fid):
    stored = add(client, fid, name="Cedar", isin="FR0000120271")["companies"][0]
    other = client.post("/api/argus/flows").json()["flow_id"]
    cedar = add(client, other, name="Cedar")["companies"][0]["company_id"]
    client.patch(f"/api/argus/flows/{other}", json={"repeat": {cedar: "skip"}})
    flow = edit(client, other, cedar, name="Cedar", isin="FR0000120271").json()
    moved = flow["companies"][0]
    assert (moved["company_id"], moved["entity_id"]) == (stored["company_id"], stored["entity_id"]) and cedar != moved["company_id"]
    assert flow["repeat"] == {}  # nothing stays keyed by the old id


def test_renaming_an_unmatched_row_keeps_its_key_and_files(client, fid, tmp_path):  # AC-135
    dune = add(client, fid, name="Dune")["companies"][0]["company_id"]
    upload_pdf(client, fid, dune, tmp_path, title="Dune Annual Report 2025")
    r = edit(client, fid, dune, name="Dune Corp")
    assert r.status_code == 200, r.text
    flow = r.json()
    assert (flow["companies"][0]["name"], flow["companies"][0]["company_id"]) == ("Dune Corp", dune)
    assert [f["filename"] for f in flow["files"]] == ["report.pdf"]
    assert flow["rows"][0]["problem"] == NO_IDENTIFIER


def test_a_row_with_files_matched_to_a_new_company_keeps_its_key(client, fid, tmp_path):  # AC-136
    elm = add(client, fid, name="Elm")["companies"][0]["company_id"]
    upload_pdf(client, fid, elm, tmp_path, title="Elm Annual Report 2025")
    r = edit(client, fid, elm, name="Elm", isin="NL0000009165")
    assert r.status_code == 200, r.text
    flow = r.json()
    assert flow["companies"][0]["entity_id"] and flow["companies"][0]["company_id"] == elm
    assert [f["filename"] for f in flow["files"]] == ["report.pdf"]


def test_an_edit_keeps_the_columns_the_form_does_not_show(client, fid):  # AC-157
    r = client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", "name,sector,country\nFir,Software,DE\n")})
    fir = r.json()["companies"][0]["company_id"]
    r = edit(client, fid, fir, name="Fir", isin="SE0000108656")
    assert r.status_code == 200, r.text
    c = r.json()["companies"][0]
    assert c["entity_id"] and (c["sector"], c["country"]) == ("Software", "DE")


def test_an_edit_looks_a_ticker_up_as_adding_does(client, fid, sec):
    acme = add(client, fid, name="Microsoft")["companies"][0]["company_id"]
    sec.tickers = {"MSFT": "789019"}
    c = edit(client, fid, acme, name="Microsoft", ticker="MSFT").json()["companies"][0]
    assert c["entity_id"] and c["cik"].lstrip("0") == "789019" and c["company_id"] == acme


# --- item 3: remove ---

def test_remove_drops_the_row_and_its_file_choices(client, fid, tmp_path):  # AC-16, AC-17
    add(client, fid, name="Apple", isin="US0378331005")
    add(client, fid, name="Microsoft", isin="US5949181045")
    acme = add(client, fid, name="Acme")["companies"][2]["company_id"]
    client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025})
    upload_pdf(client, fid, acme, tmp_path, title="Acme Annual Report 2025")
    key = f"{acme}/10-K/report.pdf"
    kept = client.post(f"/api/argus/flows/{fid}/files", json={"keys": [key], "state": "kept"}).json()
    assert kept["decisions"] == {key: "kept"}
    r = client.delete(f"/api/argus/flows/{fid}/companies/{acme}")
    assert r.status_code == 200, r.text
    flow = r.json()
    assert [c["name"] for c in flow["companies"]] == ["Apple", "Microsoft"]
    assert flow["decisions"] == {} and flow["files"] == []
    again = add(client, fid, name="Acme")
    assert [f["key"] for f in again["files"]] == [key]


# --- item 7: discard, and the 60-second start flag ---

def test_a_draft_with_companies_can_be_discarded(client, fid, tmp_path):  # AC-30, AC-34
    apple = add(client, fid, name="Apple", isin="US0378331005")["companies"][0]["company_id"]
    add(client, fid, name="Microsoft", isin="US5949181045")
    upload_pdf(client, fid, apple, tmp_path, title="Apple Annual Report 2025")
    client.patch(f"/api/argus/flows/{fid}", json={"step": 2})
    r = client.post(f"/api/argus/flows/{fid}/discard")
    assert r.status_code == 204 and r.content == b""
    assert client.get(f"/api/argus/flows/{fid}").status_code == 404
    other = client.post("/api/argus/flows").json()["flow_id"]
    assert [f["filename"] for f in add(client, other, name="Apple", isin="US0378331005")["files"]] == ["report.pdf"]


def test_plain_delete_still_needs_an_empty_draft(client, fid):  # AC-33
    client.patch(f"/api/argus/flows/{fid}", json={"step": 2})
    r = client.delete(f"/api/argus/flows/{fid}")
    assert (r.status_code, r.json()["detail"]) == (409, "Only an empty draft can be deleted.")


def test_a_flow_being_started_cannot_be_changed_or_discarded(client, fid, settings):  # AC-138, AC-139
    acme = add(client, fid, name="Acme")["companies"][0]["company_id"]
    rewrite(settings, fid, starting=True, updated_at=ago(5))
    for r in (edit(client, fid, acme, name="Acme Corp"), client.delete(f"/api/argus/flows/{fid}/companies/{acme}")):
        assert (r.status_code, r.json()["detail"]) == (409, STARTED)
    r = client.post(f"/api/argus/flows/{fid}/discard")
    assert (r.status_code, r.json()["detail"]) == (409, "An extraction that has started cannot be deleted.")


def test_a_save_does_not_make_an_old_start_flag_fresh(client, fid, settings):
    acme = add(client, fid, name="Acme")["companies"][0]["company_id"]
    rewrite(settings, fid, starting=True, updated_at=ago(600))  # a Start that died ten minutes ago
    assert client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025}).json()["starting"] is False
    assert edit(client, fid, acme, name="Acme Corp").status_code == 200


def test_writes_during_a_dead_start_do_not_keep_its_flag_alive(client, fid, settings):
    acme = add(client, fid, name="Acme")["companies"][0]["company_id"]
    rewrite(settings, fid, starting=True, starting_at=ago(120), updated_at=ago(1))  # the flow was written a second ago
    assert edit(client, fid, acme, name="Acme Corp").status_code == 200


def test_a_start_flag_older_than_a_minute_blocks_nothing(client, settings):  # AC-155
    flows = []
    for _ in range(3):
        fid = client.post("/api/argus/flows").json()["flow_id"]
        flows.append((fid, add(client, fid, name="Acme")["companies"][0]["company_id"]))
        rewrite(settings, fid, starting=True, updated_at=ago(120))
    assert edit(client, flows[0][0], flows[0][1], name="Acme Corp").status_code == 200
    assert client.delete(f"/api/argus/flows/{flows[1][0]}/companies/{flows[1][1]}").status_code == 200
    assert client.post(f"/api/argus/flows/{flows[2][0]}/discard").status_code == 204


# --- item 4: the result of an identity run ---

def identity_run(client, fid, run_store, status, *results):
    run_store.save_manifest(RunManifest(run_id="identity_x", run_type="identity", status=status))
    for r in results:
        run_store.append_result("identity_x", {"_key": r.company_id, **r.model_dump(mode="json")})
    assert client.patch(f"/api/argus/flows/{fid}", json={"identity_run_id": "identity_x"}).status_code == 200


def found(company_id, name, **fields):
    return IdentityResolutionResult(company_id=company_id, input_name=name, verdict="resolved", confidence=0.9,
                                    signals=IdentitySignals(), rationale="one exact EDGAR match", **fields)


@pytest.fixture
def acme(client, fid):
    return add(client, fid, name="Acme")["companies"][0]["company_id"]


def test_a_finished_identity_run_matches_the_rows_it_resolved(client, fid, acme, run_store, pg):  # AC-23, AC-25
    identity_run(client, fid, run_store, "completed", found(acme, "Acme", resolved_cik="1234567"))
    flow = client.get(f"/api/argus/flows/{fid}").json()
    c = flow["companies"][0]
    assert c["entity_id"] and c["cik"] == "1234567" and c["company_id"] == acme
    assert flow["rows"][0]["problem"] is None
    register = (count(pg), count(pg, CompanyIdentifier))
    assert client.get(f"/api/argus/flows/{fid}").json()["companies"][0] == c
    assert (count(pg), count(pg, CompanyIdentifier)) == register


def test_a_run_that_is_not_an_identity_run_is_ignored(client, fid, acme, run_store):
    """A hand-made PATCH can name any run; its rows are not identity results and made every read a 500."""
    run_store.save_manifest(RunManifest(run_id="extraction_x", run_type="extraction", status="completed"))
    run_store.append_result("extraction_x", {"_key": acme, "company_id": acme, "name": "Acme", "fields": []})
    client.patch(f"/api/argus/flows/{fid}", json={"identity_run_id": "extraction_x"})
    r = client.get(f"/api/argus/flows/{fid}")
    assert r.status_code == 200 and r.json()["companies"][0]["entity_id"] is None


def test_a_result_flagged_for_review_is_not_applied(client, fid, acme, run_store):  # AC-24
    identity_run(client, fid, run_store, "completed", found(acme, "Acme", resolved_cik="1234567", flagged_for_review=True))
    assert client.get(f"/api/argus/flows/{fid}").json()["companies"][0]["entity_id"] is None


def test_a_running_identity_run_is_not_applied(client, fid, acme, run_store):  # AC-26
    identity_run(client, fid, run_store, "running", found(acme, "Acme", resolved_cik="1234567"))
    assert client.get(f"/api/argus/flows/{fid}").json()["companies"][0]["entity_id"] is None


def test_an_identity_result_never_strands_a_rows_files(client, fid, acme, run_store, tmp_path, pg):  # AC-27
    seed(pg, "Acme Incorporated", cik="1234567", universe="ACME-OLD")
    upload_pdf(client, fid, acme, tmp_path, title="Acme Annual Report 2025")
    identity_run(client, fid, run_store, "completed", found(acme, "Acme", resolved_cik="1234567"))
    flow = client.get(f"/api/argus/flows/{fid}").json()
    assert flow["companies"][0]["entity_id"] is None and [f["filename"] for f in flow["files"]] == ["report.pdf"]


def test_an_identity_result_for_a_new_company_keeps_the_rows_key(client, fid, acme, run_store, tmp_path):  # AC-137
    upload_pdf(client, fid, acme, tmp_path, title="Acme Annual Report 2025")
    identity_run(client, fid, run_store, "completed", found(acme, "Acme", resolved_cik="1234567"))
    flow = client.get(f"/api/argus/flows/{fid}").json()
    assert flow["companies"][0]["entity_id"] and flow["companies"][0]["company_id"] == acme == safe_key("Acme")
    assert [f["filename"] for f in flow["files"]] == ["report.pdf"]
