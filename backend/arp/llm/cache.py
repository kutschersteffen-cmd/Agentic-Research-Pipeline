from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class DiskLLMCache:
    """Content-addressed cache for LLM calls.

    Keyed on the full request (model, system, prompt, schema name+shape),
    so identical calls across dev iterations or resumed batch runs cost
    nothing and return instantly. Cache hits are reported to cost tracking
    as $0 so real spend is never inflated.
    """

    def __init__(self, cache_dir: Path, enabled: bool = True, refresh: bool = False) -> None:
        self.cache_dir = cache_dir
        self.enabled = enabled
        # Refresh: never read, still write -- a restarted step calls the
        # model afresh and leaves its new answer for the steps after it.
        self.refresh = refresh
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(
        *, model: str, system: str, prompt: str, schema_name: str, schema_json: dict, temperature: float = 0.0,
        image_hashes: list[str] | None = None,
    ) -> str:
        fields = {
            "model": model,
            "system": system,
            "prompt": prompt,
            "schema": schema_name,
            "schema_json": schema_json,
            "temperature": temperature,
        }
        if image_hashes:  # absent for text-only calls, so their existing keys stay valid
            fields["image_hashes"] = image_hashes
        payload = json.dumps(fields, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled or self.refresh:
            return None
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self.cache_dir / f"{key}.json"
        path.write_text(json.dumps(value))
