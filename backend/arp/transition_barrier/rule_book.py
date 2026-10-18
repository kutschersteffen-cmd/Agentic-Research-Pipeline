from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

RULE_BOOK_FILE = "rule_book.json"


class RuleBookNotFound(FileNotFoundError):
    pass


class RuleBookError(ValueError):
    """The rule book can't be read or fails validation; the message is the first error line."""


class SourceRef(BaseModel):
    title: str
    url: str | None = None
    locator: str | None = None


class RegionOverride(BaseModel):
    value: float
    source: SourceRef | None = None


class FactDef(BaseModel):
    """A measured fact (has `type`) or a computed one (has `formula` and `inputs`)."""

    id: str
    label: str
    type: Literal["number", "boolean", "enum", "date"] | None = None
    unit: str | None = None
    allowed_values: list[str] | None = None
    definition: str = ""
    max_age_days: int | None = None
    formula: Literal["ratio", "ratio_pct", "difference"] | None = None
    inputs: list[str] = []


class ParamDef(BaseModel):
    id: str
    label: str
    value: float | None = None
    unit: str | None = None
    by_region: dict[str, RegionOverride] = {}
    rationale: str = ""
    source: SourceRef | None = None
    status: Literal["set", "open"] = "set"
    question: str = ""


class CriterionRules(BaseModel):
    rationale: str = ""
    actions: list[str] = []
    facts: list[FactDef] = []
    params: list[ParamDef] = []
    # Conditions stay raw dicts so the validator can report bad shapes.
    levels: dict[str, dict] = {}


class RuleBook(BaseModel):
    version: int = Field(strict=True)
    fingerprint: str
    history: list[dict]
    actions: dict[str, list[dict]]
    conversions: list[dict]
    domain_tiers: dict[str, str]
    criteria: dict[str, CriterionRules]


def load_rule_book(data_dir: Path) -> tuple[RuleBook, dict]:
    path = Path(data_dir) / RULE_BOOK_FILE
    if not path.exists():
        raise RuleBookNotFound(f"Rule book not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RuleBook.model_validate(raw), raw


def compute_fingerprint(raw: dict) -> str:
    content = {k: v for k, v in raw.items() if k not in ("fingerprint", "history")}
    text = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sign_rule_book(data_dir: Path, approved_by: str, today: date) -> int:
    """Bump the version, refresh the fingerprint and log the approval. Returns the new version."""
    _, raw = load_rule_book(data_dir)
    raw["version"] += 1
    raw["fingerprint"] = compute_fingerprint(raw)
    raw.setdefault("history", []).append(
        {
            "version": raw["version"],
            "fingerprint": raw["fingerprint"],
            "approved_by": approved_by,
            "approved_at": today.isoformat(),
        }
    )
    (Path(data_dir) / RULE_BOOK_FILE).write_text(
        json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return raw["version"]
