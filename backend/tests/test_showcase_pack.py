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
