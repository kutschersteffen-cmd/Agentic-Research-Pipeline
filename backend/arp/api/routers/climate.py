from __future__ import annotations

from fastapi import APIRouter

from arp.portfolio.climate.schemas import build_climate_schema
from arp.schemas.datapoints import DataPointSchema

router = APIRouter(prefix="/api/climate", tags=["climate"])


@router.get("/schema", response_model=DataPointSchema)
def climate_schema() -> DataPointSchema:
    return build_climate_schema()
