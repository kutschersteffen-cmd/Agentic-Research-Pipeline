from __future__ import annotations

from pydantic import BaseModel


class DatasetMeta(BaseModel):
    columns: set[str]
    metrics: set[str]
