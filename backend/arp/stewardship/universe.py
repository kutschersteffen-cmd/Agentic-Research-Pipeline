"""Which companies the house stewardship program covers.

Two sources, chosen by a person and stored as a house setting:

- `sample`: the synthetic sample (fictional companies, rich company data and
  meetings), selectable for demos.
- `portfolio`: the companies held in the house portfolios (Risk Monitoring), the default.
  Issuer ids are then the portfolio company ids, which Decision Studio
  publications, Proxy Voting ballots and Risk Monitoring alerts use too, so
  every handoff into stewardship matches.

The portfolio universe is in the same shape as the sample (like a client
benchmark in `benchmark.as_universe`). What the holdings export does not
carry is not invented: company fields are the latest portfolio data-point
observations plus a **placeholder** CLTI score, and there are no meetings
or synthetic engagement history.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from arp.stewardship.benchmark import placeholder_clti
from arp.storage.atomic_io import atomic_write_text
from arp.storage.portfolio_store import PortfolioStore, portfolio_directories

SOURCES = ("sample", "portfolio")


class HouseUniverseSetting:
    def __init__(self, root: Path) -> None:
        # A subfolder: every *.json directly in the streams root is read as a client stream.
        self.path = root / "house" / "universe.json"

    def get(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"source": "portfolio", "set_by": None, "set_at": None}

    def set(self, source: str, set_by: str) -> dict:
        if source not in SOURCES:
            raise ValueError(f"Unknown issuer source: {source}")
        if not set_by.strip():
            raise ValueError("Changing the issuer source needs set_by")
        setting = {"source": source, "set_by": set_by.strip(), "set_at": datetime.now(UTC).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(setting))
        return setting


def _value_by_company(store: PortfolioStore, as_of: str) -> dict[str, float]:
    securities, _ = portfolio_directories(store)
    resolved = {s: store.get_resolution(s) for s in securities}
    out: dict[str, float] = defaultdict(float)
    for h in store.load_holdings_as_of(as_of):
        r = resolved.get(h.security_id)
        if r is not None and r.company_id:
            out[r.company_id] += h.market_value_eur
    return out


def from_portfolio(store: PortfolioStore) -> dict:
    """The held companies in the shape of the synthetic sample."""
    dates = store.all_snapshot_dates()
    if not dates:
        return {"source": "portfolio", "note": "No portfolio holdings loaded.", "issuers": [], "engagements": [], "meetings": []}
    as_of = dates[-1]
    now, before = _value_by_company(store, as_of), _value_by_company(store, dates[-2]) if len(dates) > 1 else {}
    total = sum(now.values())
    _, companies = portfolio_directories(store)
    observed: dict[str, dict] = defaultdict(dict)
    for company_id, field_id in store.list_observation_keys():
        obs = store.latest_observation(company_id, field_id, as_of)
        if obs is not None and isinstance(obs.value, int | float | bool):
            observed[company_id][f"portfolio.{field_id}"] = obs.value
    issuers = []
    for company_id, value in sorted(now.items(), key=lambda kv: -kv[1]):
        company = companies.get(company_id)
        issuers.append(
            {
                "issuer_id": company_id,
                "name": company.name if company else company_id,
                "region": (company.country if company else None) or "unknown",
                "sector": (company.sector if company else None) or "unknown",
                "fields": {"score.clti": placeholder_clti(company_id), **observed[company_id]},
                "holding": {
                    # No benchmark here: the weight is the company's share of all house holdings.
                    "index_weight_pct": round(value / total * 100, 3) if total else None,
                    "aum_held_eur_m": round(value / 1e6, 1),
                    "change_pct": round((value / before[company_id] - 1) * 100, 1) if before.get(company_id) else None,
                },
            }
        )
    return {
        "source": "portfolio",
        "note": f"Companies held in the house portfolios as of {as_of}. CLTI scores are placeholders; weights are the "
        "share of house holdings, not an index weight.",
        "issuers": issuers,
        "engagements": [],
        "meetings": [],
    }
