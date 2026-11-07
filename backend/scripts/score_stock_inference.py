"""Scores a stock-inference run against golden cases (spec 2026-11-04-taxonomy-from-stocks, Golden scoring).

    python scripts/score_stock_inference.py --run <run_id> --cases <cases.json> --split tune --check theme \
        --theme-pattern electroly --min-recall 0.8
    python scripts/score_stock_inference.py --run <run_id> --cases <cases.json> --split tune --check mapping \
        --min-precision 0.8

Cases are matched to run stocks by case_id = company_id; only described stocks (with a description) count.
Prints one score line; exits 1 when a given threshold fails (or the theme pattern does not match)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _load(run_id: str):
    from arp.cli._shared import _run_store
    from arp.research.stock_inference.run import load_run

    return load_run(run_id, _run_store())


def score_theme(run, labels: dict[str, str], pattern: str | None) -> tuple[str, float, bool]:
    """(line, recall, name matches): recall of described core+peripheral cases among the top theme's supporting."""
    top = run.themes[0] if run.themes else None
    want = {i for i, lab in labels.items() if lab in ("core", "peripheral")}
    recall = len(want & set(top.supporting)) / len(want) if top and want else 0.0
    ok = bool(top) and (pattern is None or re.search(pattern, top.name, re.I) is not None)
    return f"theme '{top.name if top else None}' recall {recall:.2f} ({len(want)} described core+peripheral)", recall, ok


def score_mapping(run, labels: dict[str, str]) -> tuple[str, float]:
    """Precision: share of described `not` cases mapped to none or to an activity no described core case has."""
    act = {m.company_id: m.activity_id for m in run.mapping}  # unmapped described stock counts as none
    core = {act.get(i) for i, lab in labels.items() if lab == "core"} - {None}
    nots = [i for i, lab in labels.items() if lab == "not"]
    good = sum(act.get(i) is None or act[i] not in core for i in nots)
    precision = good / len(nots) if nots else 0.0
    return f"mapping precision {precision:.2f} ({good} of {len(nots)} described not)", precision


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", required=True)
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--split", choices=["tune", "holdout"], required=True)
    p.add_argument("--check", choices=["theme", "mapping"], required=True)
    p.add_argument("--theme-pattern")
    p.add_argument("--min-recall", type=float)
    p.add_argument("--min-precision", type=float)
    a = p.parse_args(argv)
    run = _load(a.run)
    described = {s.company_id for s in run.profiles if s.description}
    labels = {
        c["case_id"]: c["label"]
        for c in json.loads(a.cases.read_text())["cases"]
        if c["split"] == a.split and c["case_id"] in described
    }
    if a.check == "theme":
        line, score, ok = score_theme(run, labels, a.theme_pattern)
        floor = a.min_recall
    else:
        (line, score), ok, floor = score_mapping(run, labels), True, a.min_precision
    print(line)
    return int(not ok or (floor is not None and score < floor))


if __name__ == "__main__":
    sys.exit(main())
