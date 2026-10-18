"""Fixture F from the theme exposure layers spec: run R with A (catalogue 0.60), B (extracted 0.25)
and C (qualitative), and supply edges S1 -> A (0.40) and S2 -> S1 (0.50)."""

from __future__ import annotations

import uuid

from arp.schemas.common import CompanyRef, RunManifest
from arp.schemas.issuer import issuer_key

HEADER = "supplier_key,supplier_name,customer_key,customer_name,revenue_share,source_doc,source_passage,effective_date,published_at"


def match(company_id: str, name: str, value, source: str, verdict: str = "include") -> dict:
    return {
        "company_id": company_id,
        "company_name": name,
        "verdict": verdict,
        "revenue_exposure": {"activity_id": "act", "revenue": {"value_pct": value, "source": source}},
    }


def make_theme_run(store, run_id: str, companies: dict[str, tuple]) -> dict[str, str]:
    """companies: name -> (value, source); returns name -> issuer key."""
    store.save_manifest(RunManifest(run_id=run_id, run_type="theme"))
    refs = store.save_companies(run_id, [CompanyRef(company_id=n.lower(), name=n) for n in companies])
    for n, (value, source) in companies.items():
        store.append_result(run_id, {"_key": n.lower(), "company_matches": [match(n.lower(), n, value, source)]})
    return {r.name: issuer_key(r)[0] for r in refs}


def fixture_f(store, tmp_path, run_id: str = "R") -> tuple[dict[str, str], object]:
    """Run R and the edge CSV; returns (name -> issuer key, CSV path)."""
    keys = make_theme_run(store, run_id, {"A": (0.60, "catalogue"), "B": (0.25, "extracted"), "C": (None, "qualitative")})
    keys["S1"], keys["S2"] = str(uuid.uuid4()), str(uuid.uuid4())
    path = tmp_path / "edges.csv"
    path.write_text(
        "\n".join([
            HEADER,
            f"{keys['S1']},S1,{keys['A']},A,0.40,10-K 2023,A is our largest customer.,2023-12-31,2024-03-01",
            f"{keys['S2']},S2,{keys['S1']},S1,0.50,10-K 2023,S1 buys most of our output.,2023-12-31,2024-03-01",
        ]) + "\n"
    )
    return keys, path
