from __future__ import annotations

from fastapi import APIRouter

from arp.portfolio.climate.schemas import build_climate_schema
from arp.schemas.datapoints import DataPointSchema
from arp.showcase.schema import build_simulated_schema

router = APIRouter(prefix="/api/climate", tags=["climate"])


@router.get("/schema", response_model=DataPointSchema)
def climate_schema() -> DataPointSchema:
    return build_climate_schema()


@router.get("/simulated-schema", response_model=DataPointSchema)
def simulated_schema() -> DataPointSchema:
    """The fields of the SIMULATED ESG dataset (not real ESG data)."""
    return build_simulated_schema()
