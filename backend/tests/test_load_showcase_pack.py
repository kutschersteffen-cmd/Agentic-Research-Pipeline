"""The showcase pack loader, backend/scripts/load_showcase_pack.py (spec 2026-11-12-showcase-demo-pack-design)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import load_showcase_pack as loader  # noqa: E402

PACK = Path(__file__).parents[2] / "demo" / "showcase"
PROXIES = ["NEE_proxy_statement_2026.pdf", "DUK_proxy_statement_2026.pdf", "NUE_proxy_statement_2026.pdf",
           "DOW_proxy_statement_2026.pdf"]


@pytest.fixture
def pack(tmp_path, monkeypatch):
    """A copy of the pack with an empty documents/ folder, and runs/documents dirs of the test's own."""
    from arp.config import get_settings

    copy = tmp_path / "pack"
    shutil.copytree(PACK, copy)
    for pdf in (copy / "documents").glob("*.pdf"):
        pdf.unlink()
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ARP_DOCUMENTS_DIR", str(tmp_path / "docs"))
    get_settings.cache_clear()
    yield copy
    get_settings.cache_clear()


def run(capsys, *args: str, **kw) -> tuple[int, list[str]]:
    code = loader.main(list(args), **kw)
    return code, capsys.readouterr().out.splitlines()


def test_companies_twice(pg, pack, capsys):  # AC-8
    from sqlalchemy import func, select

    from arp.db.models import Company
    from arp.db.session import transaction

    for _ in range(2):
        code, out = run(capsys, "--pack", str(pack), "--only", "companies")
        assert (code, out) == (0, ["ok companies: 10 registered"])
    with transaction(pg) as s:
        assert s.scalar(select(func.count()).select_from(Company)) == 10
        assert s.scalar(select(func.count()).select_from(Company).where(Company.isic_code.is_not(None))) == 10


def test_universe_twice(pack, capsys):  # AC-45
    from arp.catalog import universes
    from arp.config import get_settings

    for _ in range(2):
        code, out = run(capsys, "--pack", str(pack), "--only", "universe")
        assert (code, out) == (0, ["ok universe: Showcase companies (10 companies)"])
    assert [u["name"] for u in universes(get_settings().runs_dir)] == ["Showcase companies (10 companies)"]


def _stub(monkeypatch, tmp_path, body: str) -> None:
    script = tmp_path / "stub.py"
    script.write_text(body)
    monkeypatch.setattr(loader, "SHOWCASE_LOAD", [sys.executable, str(script)])
    monkeypatch.setattr(loader, "showcase_load_available", lambda: True)


def test_portfolios_relays_showcase_load(pack, capsys, monkeypatch, tmp_path):  # AC-9
    _stub(monkeypatch, tmp_path, "print('ok import: 7 portfolios')\n")
    code, out = run(capsys, "--pack", str(pack), "--only", "portfolios")
    assert (code, out) == (0, ["ok portfolios: arp showcase load", "  ok import: 7 portfolios"])


def test_portfolios_fail_exit_code(pack, capsys, monkeypatch, tmp_path):  # AC-52
    _stub(monkeypatch, tmp_path, "import sys\nsys.exit(1)\n")
    code, out = run(capsys, "--pack", str(pack), "--only", "portfolios")
    assert code == 1 and out[0] == "FAIL portfolios: arp showcase load exited 1"


def test_portfolios_skip_when_missing(pack, capsys, monkeypatch):  # Review Focus 4
    monkeypatch.setattr(loader, "showcase_load_available", lambda: False)
    code, out = run(capsys, "--pack", str(pack), "--only", "portfolios")
    assert (code, out) == (0, ["skip portfolios: arp showcase load not available"])


def _proxies(pack: Path) -> None:
    for name in PROXIES:
        (pack / "documents" / name).write_bytes(b"%PDF-1.4 " + name.encode())


def test_documents_copy(pack, capsys):  # AC-19
    from arp.config import get_settings

    _proxies(pack)
    code, out = run(capsys, "--pack", str(pack), "--only", "documents")
    assert code == 0 and out[0] == "ok documents: 4 of 14 present"
    for name in PROXIES:
        assert (get_settings().documents_dir / name.split("_")[0] / "DEF-14A" / name).is_file()


def test_documents_twice(pack, capsys):  # AC-49
    from arp.config import get_settings

    _proxies(pack)
    for _ in range(2):
        run(capsys, "--pack", str(pack), "--only", "documents")
    for name in PROXIES:
        assert len(list((get_settings().documents_dir / name.split("_")[0] / "DEF-14A").iterdir())) == 1


def test_failing_step_continues(pg, pack, capsys, monkeypatch):  # AC-12
    def boom(ctx):
        raise RuntimeError("boom")

    monkeypatch.setitem(loader.STEPS, "universe", boom)
    monkeypatch.setattr(loader, "showcase_load_available", lambda: False)
    code, out = run(capsys, "--pack", str(pack))
    steps = [line.split(":")[0] for line in out if not line.startswith("  ")]
    assert code == 1
    assert "FAIL universe: boom" in out
    assert steps == ["ok companies", "FAIL universe", "skip portfolios", "ok documents", "skip argus-capex",
                     "skip argus-plan", "skip voting"]


class FakeApi:
    """The API calls the run steps make, answered from memory; `calls` records (method, path, json body)."""

    def __init__(self, flows=(), runs=(), released=False, refuse: tuple[str, int, str] | None = None):
        self.flows, self.runs, self.released, self.refuse = list(flows), list(runs), released, refuse
        self.calls: list[tuple[str, str, object]] = []

    def __call__(self, request):
        import json

        import httpx

        method, path = request.method, request.url.path
        body = json.loads(request.content) if request.headers.get("content-type") == "application/json" else None
        self.calls.append((method, path, body))
        if self.refuse and path.endswith(self.refuse[0]):
            return httpx.Response(self.refuse[1], json={"detail": self.refuse[2]})
        answers = {
            ("GET", "/api/argus/flows"): {"flows": self.flows},
            ("GET", "/api/runs"): {"runs": self.runs},
            ("POST", "/api/argus/flows"): {"flow_id": "f1", "companies": []},
            ("POST", "/api/voting/runs"): {"run_id": "v1", "company_count": len((body or {}).get("companies", []))},
        }
        if (method, path) in answers:
            return httpx.Response(200, json=answers[(method, path)])
        if path.endswith("/install"):
            return httpx.Response(200, json={"schema_id": path.split("/")[-2], "version": 1})
        if method == "GET" and path.startswith("/api/extraction/schemas/"):
            return httpx.Response(200, json={"release_flag": self.released})
        if path.endswith("/start"):
            return httpx.Response(200, json={"flow_id": "f1", "run_id": "r1"})
        return httpx.Response(200, json={"flow_id": "f1"})

    def posts(self, path: str) -> int:
        return sum(m == "POST" and p == path for m, p, _ in self.calls)


def _client(api):
    import httpx

    return httpx.Client(base_url=loader.DEFAULT_URL, transport=httpx.MockTransport(api))


def _annual(pack: Path, *ids: str) -> None:
    for cid in ids:
        (pack / "documents" / f"{cid}_annual_report_2025.pdf").write_bytes(b"%PDF-1.4 annual")


CAPEX_FLOW = {"flow_id": "f0", "reporting_year": 2025, "companies": [{"company_id": "RWE"}],
              "schema_choice": {"kind": "schema", "schema_id": "sch_transition_capex", "version": 1}}


def test_all_steps_no_documents(pg, pack, capsys, monkeypatch, tmp_path):  # AC-10
    _stub(monkeypatch, tmp_path, "print('ok import: 7 portfolios')\n")
    api = FakeApi()
    code, out = run(capsys, "--pack", str(pack), client=_client(api))
    import csv

    names = [r["file_name"] for r in csv.DictReader((pack / "documents.csv").open())]
    i = out.index("ok documents: 0 of 14 present")
    assert out[i + 1:i + 15] == [f"  missing: {n}" for n in names]
    assert out[i + 15:] == ["skip argus-capex: no document present", "skip argus-plan: no document present",
                            "skip voting: no document present"]
    assert code == 0 and api.calls == []


def test_api_unreachable(pack, capsys):  # AC-11
    import httpx

    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    _annual(pack, "RWE")
    code, out = run(capsys, "--pack", str(pack), "--only", "argus-capex", client=_client(down))
    assert (code, out) == (0, ["skip argus-capex: API not reachable at http://127.0.0.1:8000"])


def test_already_exists(pack, capsys):  # AC-22
    _annual(pack, "RWE")
    api = FakeApi(flows=[CAPEX_FLOW])
    code, out = run(capsys, "--pack", str(pack), "--only", "argus-capex", client=_client(api))
    assert (code, out) == (0, ["skip argus-capex: already exists"])
    assert api.posts("/api/argus/flows") == 0


def test_again_creates(pack, capsys):  # AC-23
    _annual(pack, "RWE", "NEE")
    api = FakeApi(flows=[CAPEX_FLOW])
    code, out = run(capsys, "--pack", str(pack), "--only", "argus-capex", "--again", client=_client(api))
    assert code == 0 and api.posts("/api/argus/flows") == 1
    assert out[0].startswith("ok argus-capex:")
    assert api.posts("/api/extraction/schemas/sch_transition_capex/versions/1/release") == 1  # owner decision 3
    patch = next(b for m, p, b in api.calls if m == "PATCH")
    assert patch["reporting_year"] == 2025 and patch["schema_choice"]["schema_id"] == "sch_transition_capex"
    assert api.posts("/api/argus/flows/f1/start") == 1


def test_plan_already_exists(pack, capsys):  # AC-46
    _annual(pack, "RWE")
    flow = {**CAPEX_FLOW, "schema_choice": {"kind": "schema", "schema_id": "transition_plan_indicators", "version": 1}}
    api = FakeApi(flows=[flow])
    code, out = run(capsys, "--pack", str(pack), "--only", "argus-plan", client=_client(api))
    assert (code, out) == (0, ["skip argus-plan: already exists"])
    assert api.posts("/api/argus/flows") == 0


def test_voting_already_exists(pack, capsys):  # AC-47
    _proxies(pack)
    api = FakeApi(runs=[{"run_id": "v0", "run_type": "proxy_voting"}])
    code, out = run(capsys, "--pack", str(pack), "--only", "voting", client=_client(api))
    assert (code, out) == (0, ["skip voting: already exists"])
    assert api.posts("/api/voting/runs") == 0


def test_voting_starts_us_four(pack, capsys):  # AC-48
    _proxies(pack)
    api = FakeApi()
    code, out = run(capsys, "--pack", str(pack), "--only", "voting", client=_client(api))
    body = next(b for m, p, b in api.calls if (m, p) == ("POST", "/api/voting/runs"))
    assert sorted(c["company_id"] for c in body["companies"]) == ["DOW", "DUK", "NEE", "NUE"]
    assert code == 0 and out[0].startswith("ok voting: started for 4 companies")


def test_forbidden_is_fail(pack, capsys):  # Review Focus 3
    _annual(pack, "RWE")
    api = FakeApi(refuse=("/release", 403, "Requires role 'approver' or higher"))
    code, out = run(capsys, "--pack", str(pack), "--only", "argus-capex", client=_client(api))
    assert (code, out) == (1, ["FAIL argus-capex: 403 Requires role 'approver' or higher"])


def test_start_rejected_is_fail(pack, capsys):  # Review Focus 1
    _annual(pack, "RWE")
    api = FakeApi(refuse=("/start", 400, "Keep at least one file in step 2."))
    code, out = run(capsys, "--pack", str(pack), "--only", "argus-capex", client=_client(api))
    assert (code, out) == (1, ["FAIL argus-capex: 400 Keep at least one file in step 2."])
