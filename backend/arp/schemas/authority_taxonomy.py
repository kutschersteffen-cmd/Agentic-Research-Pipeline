from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field


class SourceCitation(BaseModel):
    quote: str
    source_url: str
    location: str = ""


class SectorCode(BaseModel):
    system: Literal["ISIC", "NACE", "NAICS", "SIC", "GICS"]
    code: str
    origin: Literal["source", "map_standards", "exiobase"]


class ActivityCriterion(BaseModel):
    text: str
    citations: list[SourceCitation] = Field(default_factory=list)


class Threshold(BaseModel):
    text: str
    citations: list[SourceCitation] = Field(default_factory=list)


class Technology(BaseModel):
    name: str
    citations: list[SourceCitation] = Field(default_factory=list)


class Definition(BaseModel):
    term: str
    text: str
    citations: list[SourceCitation] = Field(default_factory=list)


def merge_key(name: str) -> str:
    """Case-, whitespace- and punctuation-insensitive key for matching the same activity across sources."""
    return re.sub(r"[\W_]+", "", name.lower())
