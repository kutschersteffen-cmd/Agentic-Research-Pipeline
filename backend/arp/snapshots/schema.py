"""Monthly snapshot dataset schemas (E77). A breaking change adds major N+1 and sets `retire_after`
of major N to the month after it ships, so both majors are built side by side for one month."""

from __future__ import annotations

from pydantic import BaseModel

CURRENT_MAJOR = 1
DATASETS = ("index_holdings", "portfolio_holdings", "esg_signals")
SCHEMAS: dict[int, dict] = {
    1: {
        "version": "1.0",
        "retire_after": None,
        "datasets": {
            "index_holdings": {
                "key": ["index_id", "issuer_key", "isin", "as_of"],
                "columns": ["issuer_scheme", "weight", "shares", "free_float", "price", "currency", "calibration_version"],
            },
            "portfolio_holdings": {
                "key": ["portfolio_id", "issuer_key", "isin", "as_of"],
                "columns": ["issuer_scheme", "weight", "market_value", "currency", "fx_rate_to_eur", "source_file"],
            },
            "esg_signals": {
                "key": ["issuer_key", "field_id", "period_end", "basis"],
                "columns": ["issuer_scheme", "value", "canonical_unit", "state", "fact_id", "fact_version", "release_id",
                            "published_at", "restated"],
            },
        },
    },
}


def header(dataset: str, major: int = CURRENT_MAJOR) -> list[str]:
    ds = SCHEMAS[major]["datasets"][dataset]
    return [*ds["key"], *ds["columns"]]


def live_majors(month: str) -> list[int]:
    return sorted(m for m, s in SCHEMAS.items() if s["retire_after"] is None or s["retire_after"] >= month)


class DatasetEntry(BaseModel):
    name: str
    major: int
    schema_version: str
    rows: int
    files: dict[str, str]  # {"csv": sha256, "jsonl": sha256}


class SnapshotManifest(BaseModel):
    snapshot_id: str
    month: str
    revision: int
    as_of: str
    frozen_at: str
    cutoff: str | None = None  # taken before facts were read; the next correction counts events after it
    # The highest outbox event id read for a correction; the next one counts events after it (ids follow
    # commit order, timestamps do not). Older manifests lack it and fall back to `cutoff`.
    event_id_cutoff: int | None = None
    schema_version: str
    datasets: list[DatasetEntry]
    supersedes: str | None = None
    changes: list[dict] = []
