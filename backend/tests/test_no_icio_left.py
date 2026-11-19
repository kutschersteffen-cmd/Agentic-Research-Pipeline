from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = [ROOT / "backend/arp", ROOT / "frontend/src"]
EXCLUDED = {"backend/arp/replication/sanity_check.py", "frontend/src/pages/StrategyReplication.tsx"}
ALLOWED = {  # AC-50
    "backend/arp/schemas/thematic.py",
    "backend/arp/schemas/exposure.py",
    "backend/arp/research/indirect_exposure/migrate/__init__.py",
    "backend/arp/research/indirect_exposure/migrate/exiobase_ixi_to_icio2025.csv",
    "backend/arp/research/pipeline.py",
    "backend/arp/cli/io_tables.py",
}


def _files():
    for base in SCAN:
        for p in base.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                yield p


def test_icio_only_in_allowed_files():
    found = set()
    for p in _files():
        rel = p.relative_to(ROOT).as_posix()
        if rel in EXCLUDED:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "icio" in text.lower():
            found.add(rel)
    assert found == ALLOWED


def test_icio_filenames():  # AC-68
    names = {p.relative_to(ROOT).as_posix() for p in _files() if "icio" in p.name.lower()}
    assert names == {"backend/arp/research/indirect_exposure/migrate/exiobase_ixi_to_icio2025.csv"}
