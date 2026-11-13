"""The showcase demo pack's data files (spec: docs/superpowers/specs/2026-11-12-showcase-demo-pack-design.md)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from arp.argus.companies import _SHAPE, parse_rows
from arp.transition_alignment.benchmarks import load_benchmarks, sector_for_isic
from arp.universe import load_company_universe

PACK = Path(__file__).parents[2] / "demo" / "showcase"

TRANSITION_SECTOR = {
    "RWE": "Power & Utilities", "EOAN": "Power & Utilities", "ENGI": "Power & Utilities", "BAS": "Chemicals",
    "TKA": "Steel", "HEI": "Cement", "NEE": "Power & Utilities", "DUK": "Power & Utilities", "NUE": "Steel",
    "DOW": "Chemicals",
}


def _isin_ok(isin: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d // 10 + d % 10
    return (10 - total % 10) % 10 == int(isin[-1])


def _lei_ok(lei: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{18}[0-9]{2}", lei)) and int("".join(str(int(c, 36)) for c in lei)) % 97 == 1


def test_companies_csv_loads():  # AC-1
    with (PACK / "companies.csv").open(newline="") as f:
        header = next(csv.reader(f))
    assert "regimes" not in header
    companies = load_company_universe(PACK / "companies.csv")
    assert [c.company_id for c in companies] == list(TRANSITION_SECTOR)
    for c in companies:
        assert c.company_id and c.name and c.country and c.isic_code
        assert c.isin or c.lei or c.cik


def test_identifier_check_digits():  # AC-2
    companies = load_company_universe(PACK / "companies.csv")
    assert all(_isin_ok(c.isin) for c in companies if c.isin)
    assert all(_lei_ok(c.lei) for c in companies if c.lei)
    assert all(re.fullmatch(r"\d{1,10}", c.cik) for c in companies if c.cik)
    assert not _isin_ok("US65339F1013") and not _lei_ok("529900GB7KCA94ACC941")  # the checks can fail  # gitleaks:allow


def test_isic_maps_to_transition_sector():  # AC-3
    b = load_benchmarks()
    for c in load_company_universe(PACK / "companies.csv"):
        assert sector_for_isic(b, c.isic_code) == TRANSITION_SECTOR[c.company_id], c.company_id


def test_argus_parser_reads_all():  # AC-4
    rows = parse_rows("companies.csv", (PACK / "companies.csv").read_bytes())
    assert len(rows) == 10
    for r in rows:
        assert any(r.get(s.lower()) and re.fullmatch(p, r[s.lower()]) for s, p in _SHAPE.items()), r


def _plain(name: str) -> str:
    forms = {"ag", "aktiengesellschaft", "se", "sa", "s a", "inc", "incorporated", "corp", "corporation"}
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    text = " ".join(words)
    for form in sorted(forms, key=len, reverse=True):
        text = re.sub(rf"(^| ){form}$", "", text).strip()
    return text


def test_identifiers_match_source():  # AC-21
    source = json.loads((PACK / "identifiers_source.json").read_text())["companies"]
    for c in load_company_universe(PACK / "companies.csv"):
        entry = source[c.company_id]
        if c.lei:
            assert entry["lei"]["value"] == c.lei
            assert _plain(entry["lei"]["legal_name"]) == _plain(c.name), c.company_id
        if c.cik:
            assert entry["cik"]["value"] == c.cik
            assert _plain(entry["cik"]["name"]) == _plain(c.name), c.company_id


HOLDINGS = Path(__file__).parents[2] / "data" / "holdings"
ETF_FILES = {"etf_dax.csv": ("DAX.xlsx", 40), "etf_euro_stoxx_50.csv": ("EURO_STOXX_50.xlsx", 52),
             "etf_ai_big_data.csv": ("AI_Big_Data.xlsx", 100)}


def _equity_rows(xlsx: Path) -> tuple[str, list[dict]]:
    import openpyxl

    ws = openpyxl.load_workbook(xlsx, read_only=True, data_only=True).worksheets[0]
    rows = ws.iter_rows(min_row=4, values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows)]
    return ws.title, [r for r in (dict(zip(header, raw, strict=False)) for raw in rows)
                      if r.get("Name") and r.get("ISIN") and r.get("Type of Security") in ("Aktien", "Equities")]


def test_documents_csv():  # AC-5
    ids = {c.company_id for c in load_company_universe(PACK / "companies.csv")}
    with (PACK / "documents.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 14
    assert {r["company_id"] for r in rows} <= ids
    annual = [r for r in rows if r["doc_type"] == "10-K"]
    proxy = [r for r in rows if r["doc_type"] == "DEF-14A"]
    assert len(annual) == 10 and len(proxy) == 4
    assert all(r["reporting_year"] == "2025" and re.findall(r"20\d\d", r["file_name"]) == ["2025"] for r in annual)
    assert sorted(r["company_id"] for r in proxy) == ["DOW", "DUK", "NEE", "NUE"]
    assert all(r["reporting_year"] == "2026" and re.findall(r"20\d\d", r["file_name"]) == ["2026"] for r in proxy)
    assert all(r["file_name"].endswith(".pdf") for r in rows)


def test_etf_files_match_xlsx():  # AC-6
    from arp.research.taxonomy_sources.etf_holdings import load_holdings_with_weights

    for csv_name, (xlsx, count) in ETF_FILES.items():
        holdings = load_holdings_with_weights(PACK / csv_name)
        _, rows = _equity_rows(HOLDINGS / xlsx)
        assert len(holdings) == len(rows) == count, csv_name
        for h, r in zip(holdings, rows, strict=True):
            assert (h.name, h.isin, h.weight) == (str(r["Name"]).strip(), str(r["ISIN"]).strip(), r["Weighting"])


def test_etf_overlap_counts_isins():  # AC-25
    from arp.research.taxonomy_sources.etf_holdings import load_holdings_with_weights
    from arp.research.taxonomy_sources.overlap import compute_holdings_overlap

    funds = {n: load_holdings_with_weights(PACK / n) for n in ("etf_dax.csv", "etf_euro_stoxx_50.csv")}
    result = compute_holdings_overlap(funds)
    shared_isins = set.intersection(*({h.isin for h in rows} for rows in funds.values()))
    assert len(result.core_tickers) == len(shared_isins) >= 5


def test_etf_line_one():  # AC-26
    for csv_name, (xlsx, _) in ETF_FILES.items():
        first = (PACK / csv_name).read_text().splitlines()[0]
        assert first.startswith("Source:") and _equity_rows(HOLDINGS / xlsx)[0] in first, csv_name
    assert [(PACK / n).read_text().splitlines()[0].split()[-1] for n in ETF_FILES] == ["2026-11-02", "2026-11-02", "2026-11-12"]


def test_readme_lines():  # AC-27
    lines = (PACK / "README.md").read_text().splitlines()
    sources = [line for line in lines if line.startswith("Source:")]
    for csv_name in ETF_FILES:
        assert sum(csv_name in line for line in sources) == 1, csv_name
    assert any(line.startswith("Simulated:") and "data/simulated/esg_simulated.csv" in line for line in lines)
    assert "invented weights" not in "\n".join(lines)


def _git(*args: str):
    import subprocess

    return subprocess.run(["git", *args], cwd=PACK.parents[1], capture_output=True, text=True)


def test_documents_pdf_ignored():  # AC-13
    assert _git("check-ignore", "demo/showcase/documents/x.pdf").returncode == 0


def test_gitkeep_tracked():  # AC-53
    assert _git("ls-files", "demo/showcase/documents/.gitkeep").stdout.strip() == "demo/showcase/documents/.gitkeep"
