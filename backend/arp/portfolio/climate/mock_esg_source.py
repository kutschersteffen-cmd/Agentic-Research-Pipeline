from __future__ import annotations

import random

from arp.portfolio.climate.schemas import (
    FIELD_CARBON_INTENSITY,
    FIELD_EVIC,
    FIELD_GREEN_REVENUE_PCT,
    FIELD_SCOPE1,
    FIELD_SCOPE2,
    FIELD_SCOPE3,
    field_name,
)
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import DataPointObservation

# Illustrative sector baselines for the mock dataset only -- not sourced
# from any real emissions database. Shape: (scope1, scope2, scope3
# multiplier on scope1+scope2, carbon intensity, EVIC EUR M, green revenue
# share).
_SECTOR_BASELINES: dict[str, tuple[float, float, float, float, float, float]] = {
    "Energy": (4_500_000, 900_000, 6.0, 280.0, 95_000, 0.06),
    "Utilities": (2_800_000, 450_000, 3.5, 210.0, 55_000, 0.28),
    "Automobiles": (900_000, 350_000, 8.0, 55.0, 70_000, 0.12),
    "Industrials": (650_000, 220_000, 4.0, 42.0, 80_000, 0.10),
    "Software": (12_000, 18_000, 1.2, 3.5, 210_000, 0.02),
    "Insurance": (8_000, 15_000, 1.0, 1.8, 100_000, 0.01),
    "Luxury Goods": (95_000, 60_000, 2.5, 12.0, 350_000, 0.03),
    "Aerospace & Defense": (420_000, 180_000, 5.0, 65.0, 120_000, 0.05),
    "Pharmaceuticals": (180_000, 140_000, 2.0, 9.0, 220_000, 0.01),
    "Food Products": (600_000, 250_000, 5.5, 38.0, 250_000, 0.04),
    "Semiconductors": (110_000, 320_000, 3.0, 14.0, 340_000, 0.03),
}
_DEFAULT_BASELINE = (300_000, 120_000, 3.0, 30.0, 90_000, 0.05)


def _rng_for(key: str) -> random.Random:
    return random.Random(f"climate::{key}")


def generate_internal_api_observations(company: CompanyRef, period: str, observed_at: str) -> list[DataPointObservation]:
    """Stands in for a real call to the internal structured ESG/emissions
    API (decision 4): deterministic per `company_id` (seeded RNG) so
    re-running the mock dataset generator reproduces the same numbers.
    """
    scope1_base, scope2_base, scope3_mult, intensity_base, evic_base, green_base = _SECTOR_BASELINES.get(
        company.sector or "", _DEFAULT_BASELINE
    )
    rng = _rng_for(company.company_id)

    def jitter(base: float, spread: float) -> float:
        return round(base * rng.uniform(1 - spread, 1 + spread), 1)

    scope1 = jitter(scope1_base, 0.15)
    scope2 = jitter(scope2_base, 0.15)
    scope3 = jitter((scope1_base + scope2_base) * scope3_mult, 0.20)
    intensity = jitter(intensity_base, 0.15)
    evic = jitter(evic_base, 0.10)
    green_pct = round(min(max(green_base * rng.uniform(0.7, 1.4), 0.0), 0.95), 4)

    values: list[tuple[str, float, str]] = [
        (FIELD_SCOPE1, scope1, "tCO2e"),
        (FIELD_SCOPE2, scope2, "tCO2e"),
        (FIELD_SCOPE3, scope3, "tCO2e"),
        (FIELD_CARBON_INTENSITY, intensity, "tCO2e / EUR M revenue"),
        (FIELD_EVIC, evic, "EUR M"),
        (FIELD_GREEN_REVENUE_PCT, green_pct, "%"),
    ]
    return [
        DataPointObservation(
            company_id=company.company_id,
            field_id=field_id,
            field_name=field_name(field_id),
            value=value,
            unit=unit,
            period=period,
            observed_at=observed_at,
            source="internal_api",
        )
        for field_id, value, unit in values
    ]


def generate_extracted_observations(
    company: CompanyRef,
    internal_observations: list[DataPointObservation],
    period: str,
    observed_at: str,
    *,
    mismatch: bool = False,
) -> list[DataPointObservation]:
    """Stands in for the Extraction Engine's independent read of the same
    figures out of the company's own disclosures -- the validation
    counterpart decision 4 requires. Normally within noise of the internal
    API's figure; `mismatch=True` widens the gap deliberately so
    `validation.py`'s cross-check has something real to flag in the demo
    dataset.
    """
    rng = _rng_for(f"{company.company_id}::extracted")
    spread = 0.25 if mismatch else 0.04
    out: list[DataPointObservation] = []
    for obs in internal_observations:
        if not isinstance(obs.value, (int, float)) or isinstance(obs.value, bool):
            continue
        extracted_value = round(obs.value * rng.uniform(1 - spread, 1 + spread), 4)
        out.append(
            DataPointObservation(
                company_id=company.company_id,
                field_id=obs.field_id,
                field_name=obs.field_name,
                value=extracted_value,
                unit=obs.unit,
                period=period,
                observed_at=observed_at,
                source="extracted",
            )
        )
    return out
