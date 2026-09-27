"""Benchmarks for client programs: index constituents with weights.

The first source is an iShares ETF holdings export (e.g. URTH, which tracks MSCI
World): equities only, weights from market value (cash, collateral, futures and
unlisted lines are dropped). Uploaded files are runtime data, stored under
`benchmarks/` in the streams directory, never in the repository.

A benchmark becomes a universe in the same shape as the synthetic sample, so the
program pipeline runs on it unchanged. The holdings export has no company data,
so the only company field is a **placeholder** CLTI score, derived from the
ticker: fixed per company, and not an assessment of it. Every output says so.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from arp.storage.atomic_io import atomic_write_text

SAMPLE = "sample"


def _num(s: str) -> float:
    s = (s or "").replace(",", "").strip()
    return float(s) if s and s != "-" else 0.0


def parse_ishares_holdings(text: str) -> dict:
    """An iShares holdings CSV: a few lines of fund metadata, a blank line, then
    one row per holding."""
    lines = text.lstrip("﻿").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("Ticker,")), None)
    if start is None:
        raise ValueError("Not an iShares holdings export: no 'Ticker,' header row")
    meta = {}
    for row in csv.reader(lines[:start]):
        if len(row) >= 2 and row[0]:
            meta[row[0].strip()] = row[1].strip()
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))
    missing = {"Ticker", "Name", "Sector", "Asset Class", "Market Value", "Location", "Exchange"} - set(rows[0] if rows else {})
    if missing:
        raise ValueError(f"Holdings export is missing columns: {sorted(missing)}")
    equities = [
        r
        for r in rows
        if r.get("Asset Class") == "Equity" and _num(r["Market Value"]) > 1 and not r["Exchange"].upper().startswith("NO MARKET")
    ]
    if not equities:
        raise ValueError("No listed equity holdings in the file")
    total = sum(_num(r["Market Value"]) for r in equities)
    constituents, seen = [], set()
    for r in sorted(equities, key=lambda r: -_num(r["Market Value"])):
        issuer_id = f"{r['Ticker'].strip()}@{r['Location'].strip()}"  # tickers repeat across countries (MRK, SAN, RIO)
        if issuer_id in seen:
            raise ValueError(f"Duplicate holding: {issuer_id}")
        seen.add(issuer_id)
        constituents.append(
            {
                "issuer_id": issuer_id,
                "ticker": r["Ticker"].strip(),
                "name": r["Name"].strip(),
                "sector": r["Sector"].strip(),
                "country": r["Location"].strip(),
                "weight_pct": round(_num(r["Market Value"]) / total * 100, 6),
            }
        )
    fund = lines[0].strip().strip('"') if lines else "iShares fund"
    return {
        "name": fund,
        "as_of": meta.get("Fund Holdings as of", ""),
        "source": "iShares holdings export",
        "dropped": len(rows) - len(constituents),
        "constituents": constituents,
    }


def placeholder_clti(issuer_id: str) -> int:
    """A fixed 5-95 score per company from its id: stands in for CLTI until real
    scores are supplied, and says nothing about the company."""
    return 5 + int(hashlib.sha256(issuer_id.encode()).hexdigest(), 16) % 91


def as_universe(benchmark: dict) -> dict:
    """The benchmark in the shape of the synthetic sample: issuers with company
    fields and holdings; no engagements or meetings yet."""
    return {
        "note": f"{benchmark['name']} as of {benchmark['as_of']}; CLTI scores are placeholders.",
        "issuers": [
            {
                "issuer_id": c["issuer_id"],
                "name": c["name"],
                "region": c["country"],
                "sector": c["sector"],
                "fields": {"score.clti": placeholder_clti(c["issuer_id"])},
                "holding": {"index_weight_pct": c["weight_pct"], "aum_held_eur_m": None, "change_pct": None},
            }
            for c in benchmark["constituents"]
        ],
        "engagements": [],
        "meetings": [],
    }


class BenchmarkStore:
    """One JSON file per uploaded benchmark."""

    def __init__(self, root: Path) -> None:
        self.root = root / "benchmarks"

    def _path(self, benchmark_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]{1,80}", benchmark_id):
            raise KeyError(benchmark_id)
        return self.root / f"{benchmark_id}.json"

    def get(self, benchmark_id: str) -> dict:
        path = self._path(benchmark_id)
        if not path.exists():
            raise KeyError(benchmark_id)
        return json.loads(path.read_text())

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        out = []
        for p in sorted(self.root.glob("*.json")):
            b = json.loads(p.read_text())
            out.append({k: v for k, v in b.items() if k != "constituents"} | {"constituents": len(b["constituents"])})
        return out

    def save(self, benchmark: dict, uploaded_by: str) -> dict:
        if not uploaded_by.strip():
            raise ValueError("An upload needs uploaded_by")
        slug = re.sub(r"[^a-z0-9]+", "-", f"{benchmark['name']} {benchmark['as_of']}".lower()).strip("-")[:80] or "benchmark"
        record = {
            **benchmark,
            "benchmark_id": slug,
            "uploaded_by": uploaded_by,
            "uploaded_at": datetime.now(UTC).isoformat(),
        }
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path(slug), json.dumps(record, ensure_ascii=False))
        return record
