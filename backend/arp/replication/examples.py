from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.strategy_replication import StrategySpec

_DATA_DIR = Path(__file__).parent / "data"


def list_examples() -> list[str]:
    return sorted(p.stem for p in _DATA_DIR.glob("*.json"))


def load_example_spec(name: str) -> StrategySpec:
    """Loads one of the bundled worked-example StrategySpecs (see
    data/*.json) -- hand-authored from well-established facts about each
    paper's methodology, not produced by the LLM extractor/verifier
    pipeline. Each one's extraction_notes/reported_performance.notes state
    exactly what is and isn't verified; treat these as a way to exercise
    the backtest engine end to end, not as ground truth for the paper's
    exact reported numbers.
    """
    path = _DATA_DIR / f"{name}.json"
    if not path.exists():
        available = ", ".join(list_examples())
        raise FileNotFoundError(f"No bundled example spec named {name!r}. Available: {available}")
    return StrategySpec.model_validate(json.loads(path.read_text()))
