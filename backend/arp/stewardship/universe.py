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

from arp.schemas.portfolio import DataPointObservation
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


def held_isins(store: PortfolioStore) -> dict[str, str]:
    """ISIN -> house issuer id for the securities held in the latest snapshot, resolved as `from_portfolio` resolves
    them, so data keyed by ISIN (the vote ledger) reaches that issuer. The first holding of an ISIN wins."""
    dates = store.all_snapshot_dates()
    if not dates:
        return {}
    securities, _ = portfolio_directories(store)
    resolutions = store.list_resolutions()
    out: dict[str, str] = {}
    for h in store.load_holdings_as_of(dates[-1]):
        r, sec = resolutions.get(h.security_id), securities.get(h.security_id)
        isin = h.isin or (sec.isin if sec else None)
        if isin and r is not None and r.company_id:
            out.setdefault(isin.upper(), r.company_id)
    return out


def company_by_security(store: PortfolioStore) -> dict[str, str]:
    """security_id -> company_id: the security's resolution, else (no resolution at all) the company the security
    itself names, as the showcase import sets it without writing resolutions."""
    out, resolutions = {}, store.list_resolutions()
    for sec in store.list_securities():
        r = resolutions.get(sec.security_id)
        if cid := r.company_id if r is not None else sec.company_id:
            out[sec.security_id] = cid
    return out


def _value_by_company(store: PortfolioStore, as_of: str, companies: dict[str, str]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for h in store.load_holdings_as_of(as_of):
        if cid := companies.get(h.security_id):
            out[cid] += h.market_value_eur
    return out


def latest_observations(store: PortfolioStore, as_of: str | None = None) -> dict[str, dict[str, DataPointObservation]]:
    """company_id -> {field_id: its latest observation as of `as_of` (default: the latest holdings snapshot)}, every
    recorded (company, field) pair read once."""
    dates = store.all_snapshot_dates()
    if not dates:
        return {}
    out: dict[str, dict[str, DataPointObservation]] = defaultdict(dict)
    for company_id, field_id in store.list_observation_keys():
        if (obs := store.latest_observation(company_id, field_id, as_of or dates[-1])) is not None:
            out[company_id][field_id] = obs
    return dict(out)


def from_portfolio(store: PortfolioStore, as_of: str | None = None, observations: dict | None = None) -> dict:
    """The held companies in the shape of the synthetic sample. `as_of` dates the observation lookups (default: the
    latest holdings snapshot); `observations`: `latest_observations(store, as_of)` when the caller already read them."""
    dates = store.all_snapshot_dates()
    if not dates:
        return {"source": "portfolio", "note": "No portfolio holdings loaded.", "issuers": [], "engagements": [], "meetings": []}
    obs_as_of, as_of = as_of or dates[-1], dates[-1]
    held = company_by_security(store)
    now, before = _value_by_company(store, as_of, held), _value_by_company(store, dates[-2], held) if len(dates) > 1 else {}
    total = sum(now.values())
    _, companies = portfolio_directories(store)
    observed: dict[str, dict] = defaultdict(dict)
    simulated: set[str] = set()
    observations = latest_observations(store, obs_as_of) if observations is None else observations
    for company_id, by_field in observations.items():
        for field_id, obs in by_field.items():
            if isinstance(obs.value, int | float | bool):
                observed[company_id][f"portfolio.{field_id}"] = obs.value
                if obs.source == "simulated":
                    simulated.add(company_id)
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
        "share of house holdings, not an index weight."
        + (f" Simulated: {n} of these companies carry simulated ESG values, not real data." if (n := len(simulated & now.keys())) else ""),
        "issuers": issuers,
        "engagements": [],
        "meetings": [],
    }
