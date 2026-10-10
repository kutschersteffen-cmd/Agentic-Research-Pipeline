import json

from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef
from arp.storage.document_store import DocumentContentStore, derive_doc_id
from arp.storage.run_store import RunStore
from arp.universe_workbench.availability import availability
from arp.xbrl_pipeline.store import XbrlStore


class Env:
    def __init__(self, tmp_path):
        self.run_store = RunStore(tmp_path / "runs")
        self.jobs = JobManager(self.run_store)
        self.content = DocumentContentStore(tmp_path / "store")
        self.xbrl = XbrlStore(tmp_path / "xbrl")
        self.docs = tmp_path / "docs"
        self.n = 0

    def run(self, run_type, rows):
        m = self.jobs.create_run(run_type, {}, len(rows))
        self.n += 1  # run ids are random, so pin the order through created_at
        self.run_store.save_manifest(m.model_copy(update={"created_at": f"2026-01-0{self.n}T00:00:00+00:00"}))
        path = self.run_store.results_path(m.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return m

    def avail(self, *ids):
        return availability([CompanyRef(company_id=i, name=i) for i in ids], run_store=self.run_store,
                            content_store=self.content, xbrl_store=self.xbrl, documents_dir=self.docs)


def _ident(cid, verdict="match", cik=None, site=None):
    return {"company_id": cid, "input_name": cid, "verdict": verdict, "confidence": 0.9,
            "resolved_cik": cik, "resolved_website": site, "signals": {}, "rationale": ""}


def test_company_with_nothing_stored(tmp_path):
    a = Env(tmp_path).avail("acme")["acme"]
    assert a.identity is None and a.xbrl is None
    assert (a.documents.registered, a.documents.parsed, a.documents.on_disk) == (0, 0, 0)
    assert a.documents.doc_types == [] and a.documents.last_seen_at is None
    assert a.extraction.runs == 0 and a.extraction.last_run_id is None


def test_documents_registered_and_on_disk(tmp_path):
    e = Env(tmp_path)
    e.content.register_document(doc_id=derive_doc_id("acme", "10-K", "k"), company_id="acme", doc_type="10-K",
                                content_key="k", title="k", local_path=None, source_url=None)
    (e.docs / "acme" / "10-K").mkdir(parents=True)
    (e.docs / "acme" / "10-K" / "a.pdf").write_bytes(b"x")
    d = e.avail("acme")["acme"].documents
    assert (d.registered, d.on_disk, d.doc_types) == (1, 1, ["10-K"])
    assert d.last_seen_at is not None


def test_extraction_runs_counted_and_latest_reported(tmp_path):
    e = Env(tmp_path)
    e.run("extraction", [{"company_id": "acme"}, {"company_id": "acme"}])
    e.run("tnfd", [{"company_id": "acme"}, {"company_id": "beta"}])
    new = e.run("financials", [{"company_id": "acme"}])
    out = e.avail("acme", "beta")
    assert out["acme"].extraction.runs == 3
    assert out["acme"].extraction.run_types == ["extraction", "financials", "tnfd"]
    assert out["acme"].extraction.last_run_id == new.run_id
    assert out["acme"].extraction.last_run_at == "2026-01-03T00:00:00+00:00"
    assert out["beta"].extraction.runs == 1


def test_identity_latest_run_wins(tmp_path):
    e = Env(tmp_path)
    e.run("identity", [_ident("acme", "no_match")])
    new = e.run("identity", [_ident("acme", "match", cik="0000000001", site="https://a.example")])
    i = e.avail("acme")["acme"].identity
    assert (i.run_id, i.verdict, i.resolved_cik, i.resolved_website) == (
        new.run_id, "match", "0000000001", "https://a.example")


def test_xbrl_found_by_any_company_id(tmp_path):
    e = Env(tmp_path)
    e.xbrl.set_meta("0000000001", source_sha="a" * 64, tags=None, company_id="c1", company_name=None, fact_count=7)
    e.xbrl.add_company_id("0000000001", "c2")
    e.xbrl.set_meta("LEI1", source_sha="b" * 64, tags=None, company_id="eu1", company_name=None, fact_count=3,
                    market="esef")
    out = e.avail("c1", "c2", "eu1", "zzz")
    assert out["c1"].xbrl == out["c2"].xbrl
    assert (out["c1"].xbrl.key, out["c1"].xbrl.market, out["c1"].xbrl.fact_count) == ("0000000001", "sec", 7)
    assert out["c1"].xbrl.report is False
    assert out["eu1"].xbrl.market == "esef" and out["zzz"].xbrl is None


def test_duplicate_company_ids_give_one_entry(tmp_path):
    assert list(Env(tmp_path).avail("acme", "acme")) == ["acme"]


def test_each_results_file_read_once(tmp_path, monkeypatch):
    e = Env(tmp_path)
    ids = [f"c{i}" for i in range(100)]
    e.run("extraction", [{"company_id": i} for i in ids])
    e.run("tnfd", [{"company_id": i} for i in ids])
    e.run("identity", [_ident(i) for i in ids])
    calls = []
    real = RunStore.read_jsonl
    monkeypatch.setattr(RunStore, "read_jsonl", staticmethod(lambda p: calls.append(p) or real(p)))
    e.avail(*ids)
    assert len(calls) == 3
