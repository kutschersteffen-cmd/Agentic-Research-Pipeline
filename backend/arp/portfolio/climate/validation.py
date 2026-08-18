from __future__ import annotations

from arp.schemas.portfolio import DataPointObservation
from arp.storage.portfolio_store import PortfolioStore


def cross_check_and_store(
    store: PortfolioStore,
    internal_obs: DataPointObservation | None,
    extracted_obs: DataPointObservation | None,
    *,
    tolerance_pct: float = 0.15,
) -> DataPointObservation | None:
    """Reconciles one company/field's internal-API value against the
    Extraction Engine's independent read of the same figure from company
    disclosures (decision 4's validation requirement).

    The internal-API value remains the one used for computation -- it's
    the operational source of truth -- but a disagreement beyond
    `tolerance_pct` is stamped `conflicting_sources=True` and both values
    are persisted, never silently reconciled in either direction. This is
    the same discipline `ExtractedField.conflicting_sources` already
    applies inside the Extraction Engine, applied here across sources
    instead of across documents.

    Returns the observation that should feed downstream aggregation: the
    (possibly flagged) internal-API one if present, else the extracted one
    tagged as the best available source, else None if neither exists.
    """
    if internal_obs is None and extracted_obs is None:
        return None
    if internal_obs is None:
        store.append_observation(extracted_obs)
        return extracted_obs
    if extracted_obs is None:
        store.append_observation(internal_obs)
        return internal_obs

    a, b = internal_obs.value, extracted_obs.value
    if _is_number(a) and _is_number(b):
        denominator = max(abs(a), abs(b), 1e-9)
        conflicting = abs(a - b) / denominator > tolerance_pct
    else:
        conflicting = a != b

    resolved = internal_obs.model_copy(
        update={
            "conflicting_sources": conflicting,
            "conflicting_value": b if conflicting else None,
            "conflicting_source_label": "extracted" if conflicting else None,
            "notes": (
                "Independent extraction from company disclosures disagreed beyond tolerance."
                if conflicting
                else internal_obs.notes
            ),
        }
    )
    store.append_observation(resolved)
    store.append_observation(extracted_obs)  # kept for audit even though not selected for computation
    return resolved


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
