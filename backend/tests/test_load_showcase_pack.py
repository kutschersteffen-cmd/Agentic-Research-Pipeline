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
