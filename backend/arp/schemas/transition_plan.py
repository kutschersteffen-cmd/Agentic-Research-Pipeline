from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class IndicatorCategory(StrEnum):
    TARGET = "target"
    GOVERNANCE = "governance"
    STRATEGY = "strategy"
    TRACKING = "tracking"


class WalkOrTalk(StrEnum):
    WALK = "walk"
    TALK = "talk"


class TransitionPlanIndicator(BaseModel):
    """One of the 64 assessment indicators from Colesanti Senni, Schimanski,
    Bingler, Ni & Leippold (2024), 'Using AI to assess corporate climate
    transition disclosures' -- static reference data, not a per-run record.
    See arp/transition_plan/indicators.py for the loader.
    """

    number: int = Field(description="1-64, the paper's sequential indicator number.")
    identifier: str = Field(description="The original masterfile identifier, e.g. 'A_headline_1'.")
    category: IndicatorCategory
    walk_or_talk: WalkOrTalk
    question: str
    guideline: str = Field(description="Expert-centric question extension: guidance on how to interpret and answer the question.")
