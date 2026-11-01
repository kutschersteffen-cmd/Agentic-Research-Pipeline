"""Exposure golden sets: `cases.json` schema and validation (see `arp golden-set exposure`)."""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator, model_validator

KINDS = ("activity", "risk")
RISK_LABELS = ("exposed_disclosed", "exposed_undisclosed", "not_exposed")
_URL = re.compile(r"^https?://\S+$")


class ExposureDocument(BaseModel):
    url: str | None = None
    path: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> ExposureDocument:
        if not (self.url or self.path):
            raise ValueError("needs url or path")
        if self.url and not _URL.match(self.url):
            raise ValueError(f"url must be http(s): {self.url}")
        return self


class ExposureCase(BaseModel):
    case_id: str
    company: str
    label: str
    role: str
    rationale: str
    label_sources: list[str]
    documents: list[ExposureDocument]
    lei: str | None = None
    isin: str | None = None
    split: str | None = None

    @field_validator("label_sources")
    @classmethod
    def _sources(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("needs at least one source")
        bad = [s for s in v if not _URL.match(s)]
        if bad:
            raise ValueError(f"not an http(s) URL: {bad[0]}")
        return v

    @field_validator("documents")
    @classmethod
    def _docs(cls, v: list[ExposureDocument]) -> list[ExposureDocument]:
        if not v:
            raise ValueError("needs at least one document")
        return v


class ExposureSet(BaseModel):
    set_id: str
    kind: str
    subject: str
    labels: list[str]
    checked_on: str
    cases: list[ExposureCase]

    @field_validator("checked_on")
    @classmethod
    def _iso(cls, v: str) -> str:
        try:
            datetime.date.fromisoformat(v)
        except ValueError:
            raise ValueError(f"not an ISO date: {v!r}") from None
        return v


def _read(set_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads((set_dir / "cases.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "cases.json: not found"
    except (ValueError, OSError) as exc:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        return None, f"cases.json: invalid JSON ({exc})"
    if not isinstance(data, dict):
        return None, "cases.json: invalid JSON (top level must be an object)"
    return data, None


def _errors(prefix: str, exc: ValidationError) -> list[str]:
    out = []
    for e in exc.errors():
        field = ".".join(str(p) for p in e["loc"]) or "?"
        msg = "required" if e["type"] == "missing" else e["msg"].removeprefix("Value error, ")
        out.append(f"{prefix}{field}: {msg}")
    return out


def _check_doc_paths(case: ExposureCase, docs_dir: Path) -> list[str]:
    root = docs_dir.resolve()
    out = []
    for doc in case.documents:
        if doc.path is None:
            continue
        p = (docs_dir / doc.path).resolve()
        if not p.is_relative_to(root):
            out.append(f"{case.case_id}: documents: path outside documents/: {doc.path}")
        elif not p.is_file():
            out.append(f"{case.case_id}: documents: file not found: {doc.path}")
    return out


def validate_set(set_dir: Path) -> list[str]:
    data, err = _read(set_dir)
    if data is None:
        return [err or "cases.json: unreadable"]
    problems: list[str] = []
    raw_cases = data.get("cases")
    head = {k: v for k, v in data.items() if k != "cases"}
    try:
        ExposureSet.model_validate({**head, "cases": []})
    except ValidationError as exc:
        problems += _errors("", exc)
    kind = data.get("kind")
    if kind is not None and kind not in KINDS:
        problems.append(f"kind: must be one of {', '.join(KINDS)}, got {kind!r}")
    if not isinstance(raw_cases, list):
        return problems + ["cases: required list"]
    if not raw_cases:
        return problems + ["cases: empty"]
    labels = data.get("labels")
    allowed = set(RISK_LABELS) if kind == "risk" else set(labels) if isinstance(labels, list) else None
    seen: set[str] = set()
    for i, raw in enumerate(raw_cases):
        cid = raw.get("case_id") if isinstance(raw, dict) else None
        name = cid if isinstance(cid, str) else f"cases[{i}]"
        try:
            case = ExposureCase.model_validate(raw)
        except ValidationError as exc:
            problems += _errors(f"{name}: ", exc)
            continue
        if cid in seen:
            problems.append(f"{cid}: case_id: duplicate")
        seen.add(cid)
        if allowed is not None and case.label not in allowed:
            problems.append(f"{cid}: label: {case.label!r} not in {sorted(allowed)}")
        problems += _check_doc_paths(case, set_dir / "documents")
    return problems


def load_set(set_dir: Path) -> ExposureSet:
    data, err = _read(set_dir)
    if data is None:
        raise ValueError(err)
    return ExposureSet.model_validate(data)


def assign_splits(s: ExposureSet) -> ExposureSet:
    """Fills missing splits: per label, cases sorted by case_id, even positions holdout, odd tune.
    An existing split is kept and still occupies its position."""
    out = s.model_copy(deep=True)
    for label in s.labels:
        for i, c in enumerate(sorted((c for c in out.cases if c.label == label), key=lambda c: c.case_id)):
            if c.split is None:
                c.split = "holdout" if i % 2 == 0 else "tune"
    return out


def stats_lines(s: ExposureSet) -> list[str]:
    return [
        f"{label} tune={sum(c.label == label and c.split == 'tune' for c in s.cases)} "
        f"holdout={sum(c.label == label and c.split == 'holdout' for c in s.cases)}"
        for label in s.labels
    ]
