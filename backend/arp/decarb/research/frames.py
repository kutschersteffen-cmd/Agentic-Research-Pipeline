"""Bridge between the stdlib `Panel` and pandas.

`arp.decarb` core is deliberately dependency-free so it runs anywhere.
`arp.decarb.research` is where the econometrics lives and it needs the
scientific stack:

    pip install "arp[research]"

Keeping the split means the label construction, attribution and saturation
analyses stay portable while the estimators that genuinely need numpy get to
use it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arp.decarb.schemas import Panel

__all__ = ["to_frame", "add_growth_columns"]


def to_frame(panel: Panel) -> pd.DataFrame:
    """Flatten a Panel into a tidy firm-year DataFrame.

    Indicator and red-flag dictionaries are expanded into `ind_*` and
    `flag_*` columns; the metric dictionary into `metric_*`.
    """
    records = []
    for row in panel.rows:
        rec = {
            "firm_id": row.firm_id,
            "year": row.year,
            "scope1": row.scope1,
            "scope2": row.scope2,
            "scope2_location": row.scope2_location,
            "scope2_market": row.scope2_market,
            "scope12": row.scope12,
            "revenue": row.revenue,
            "evic": row.evic,
            "intensity": row.intensity(),
            "basis": row.basis.value,
            "sector": row.sector,
            "region": row.region,
            "ltnz_adoption_year": row.ltnz_adoption_year,
            "treated": row.is_treated,
        }
        rec.update({f"ind_{k}": v for k, v in row.indicators.items()})
        rec.update({f"flag_{k}": v for k, v in row.red_flags.items()})
        rec.update({f"metric_{k}": v for k, v in row.metrics.items()})
        records.append(rec)
    frame = pd.DataFrame.from_records(records)
    return frame.sort_values(["firm_id", "year"]).reset_index(drop=True)


def add_growth_columns(frame: pd.DataFrame, *, value: str = "scope12") -> pd.DataFrame:
    """Add log level, one-year log growth, and lagged growth.

    Lagged growth is the persistence baseline. It is computed within firm and
    is NaN for each firm's first observation, which is correct: there is no
    prior year to difference against and filling it would fabricate history.
    """
    out = frame.sort_values(["firm_id", "year"]).copy()
    vals = out[value].astype(float)
    out[f"log_{value}"] = np.where(vals > 0, np.log(vals.where(vals > 0, 1.0)), np.nan)
    out[f"g_{value}"] = out.groupby("firm_id")[f"log_{value}"].diff()
    out[f"g_{value}_lag"] = out.groupby("firm_id")[f"g_{value}"].shift(1)
    return out
