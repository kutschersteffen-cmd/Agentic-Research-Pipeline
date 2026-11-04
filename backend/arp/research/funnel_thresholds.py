from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent / "data" / "funnel_thresholds.json"


def thresholds_for(theme_id: str, path: Path | None = None) -> dict[str, float]:
    """The funnel's k1/k2/t_rerank/t_entail for a theme: its own entry over the `default` one, key by key."""
    data = json.loads((path or _DEFAULT_PATH).read_text())
    return {**data["default"], **data.get(theme_id, {})}
