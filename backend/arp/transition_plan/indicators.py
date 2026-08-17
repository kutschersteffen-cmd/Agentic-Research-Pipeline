from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from arp.schemas.transition_plan import TransitionPlanIndicator

_DEFAULT_PATH = Path(__file__).parent / "data" / "indicators.json"


@lru_cache
def load_indicators(path: Path | None = None) -> list[TransitionPlanIndicator]:
    """The 64 assessment indicators from Colesanti Senni et al. (2024),
    covering Target/Governance/Strategy/Tracking, each classified as a
    'walk' (concrete, verifiable activity) or 'talk' (future target/general
    management approach) indicator. Sourced verbatim -- question text,
    expert-centric guideline, and walk/talk classification -- from the
    paper's own reference implementation (github.com/tobischimanski/
    transition_NLP, questions_masterfile_100524.xlsx), not retyped from the
    PDF, so wording exactly matches what the paper's tool actually asked.
    """
    p = path or _DEFAULT_PATH
    rows = json.loads(p.read_text())
    return [TransitionPlanIndicator.model_validate(row) for row in rows]
