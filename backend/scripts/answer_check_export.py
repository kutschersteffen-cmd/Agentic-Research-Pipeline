"""Exports the owner-approved answer-check cards for answer_check_score.py (spec 2026-11-01 roadmap, A1).

    python scripts/answer_check_export.py --cards <dir> --truth <dir> --out tests/golden/answer_check/approved.json

`--cards` and `--truth` are the sheet's `cards` and `truth` collections, saved one JSON file per document (the
ArtifactData tool's `out_dir`). Only truth documents with status "checked" and a non-empty value are exported."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _item(kind: str, item: str) -> str:
    # transition-plan cards carry the indicator identifier; results carry its field id
    return "tp_" + item.lower().replace(" ", "_") if kind == "transition-plan" else item


def export(cards_dir: Path, truth_dir: Path) -> list[dict]:
    cards = {it["id"]: it for f in sorted(cards_dir.glob("*.json")) for it in json.loads(f.read_text())["items"]}
    out = []
    for f in sorted(truth_dir.glob("*.json")):
        truth, card = json.loads(f.read_text()), cards.get(f.stem)
        if card is None or truth.get("status") != "checked" or not str(truth.get("value", "")).strip():
            continue
        kind = card["kind"].replace(" ", "-")
        out.append({"company": card["company"], "kind": kind, "item": _item(kind, card["item"]),
                    "period": card.get("period") or "", "value": truth["value"], "page": truth.get("page", ""),
                    "approved_by": truth.get("checked_by", ""), "approved_at": truth.get("checked_at", "")})
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cards", type=Path, required=True)
    p.add_argument("--truth", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    rows = export(a.cards, a.truth)
    a.out.write_text(json.dumps(rows, indent=1))
    print(f"exported {len(rows)} approved cards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
