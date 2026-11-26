from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent / "data" / "funnel_thresholds.json"


def thresholds_for(theme_id: str, path: Path | None = None, tuned_only: bool = False) -> dict[str, float] | None:
    """The funnel's k1/k2/t_rerank/t_entail for a theme: its own entry over the `default` one, key by key.
    With `tuned_only`, None unless the theme's entry has a `tuned` object; `tuned` itself is never returned."""
    data = json.loads((path or _DEFAULT_PATH).read_text())
    entry = dict(data.get(theme_id, {}))
    if entry.pop("tuned", None) is None and tuned_only:
        return None
    return {**data["default"], **entry}
