"""Scores an extraction run against the answer-check cards (spec 2026-10-31-table-aware-extraction, Design 6).

    python scripts/answer_check_score.py --truth tests/golden/answer_check/approved.json --run <run_id> \
        --schema green-capex --min-correct 30 [--max-not-found 8]

The truth file is a list of {"company", "kind", "item", "period", "value"}; `kind` is "green-capex" or
"transition-plan", `item` the field id, `period` the period_end ("" for yes/no questions). Prints
`correct <c>/<n> · not_found_on_yes_no <k>` and exits 1 below --min-correct or above --max-not-found."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_NUM = re.compile(r"^\s*(-?[\d.,]+)\s*(.*)$")
_NOT_FOUND = {"not found", "not in report", "n/a", ""}


def _number(text: str) -> tuple[float | None, str]:
    m = _NUM.match(text)
    if not m:
        return None, ""
    try:
        return float(m.group(1).replace(",", "")), m.group(2).strip().lower()
    except ValueError:
        return None, ""


def same(answer: str | None, truth: str) -> bool:
    """Yes/no and text match case-insensitively; numbers within 1% with the same last unit word;
    "not in report" matches "not found"; an unanswered card is wrong."""
    if answer is None:
        return False
    a, t = answer.strip().lower(), truth.strip().lower()
    if t in _NOT_FOUND or a in _NOT_FOUND:
        return t in _NOT_FOUND and a in _NOT_FOUND
    (na, ua), (nt, ut) = _number(a), _number(t)
    if na is not None and nt is not None:
        last = lambda u: u.split()[-1:] if u else []  # noqa: E731
        return abs(na - nt) <= 0.01 * max(abs(nt), 1e-9) and (not ut or last(ua) == last(ut))
    return a == t


def answer_of(row: dict) -> str:
    v = row.get("value")
    if v is None:
        return "not found"
    if isinstance(v, bool):
        return "YES" if v else "NO"
    if isinstance(v, (int, float)):
        return f"{v:g} {row.get('unit') or ''}".strip()
    return str(v)


def score(truth: list[dict], answers: dict[tuple[str, str, str], str]) -> tuple[int, int, int]:
    """(correct, cards, not-found answers where the truth is YES or NO)."""
    correct = not_found = 0
    for card in truth:
        ans = answers.get((card["company"], card["item"], card.get("period") or ""))
        correct += same(ans, card["value"])
        if card["value"].strip().upper() in ("YES", "NO") and (ans or "").strip().lower() in _NOT_FOUND:
            not_found += 1
    return correct, len(truth), not_found


def run_answers(results: list[dict]) -> dict[tuple[str, str, str], str]:
    """First stored row per (company, field, period); yes/no questions are keyed with period ""."""
    out: dict[tuple[str, str, str], str] = {}
    for company in results:
        for row in company.get("fields", []):
            key = (company["company_id"], row["field_id"], row.get("period_end") or "")
            out.setdefault(key, answer_of(row))
            out.setdefault((company["company_id"], row["field_id"], ""), answer_of(row))
    return out


def _load_run(run_id: str) -> list[dict]:
    from arp.config import Settings
    from arp.db.runs import RunStore

    settings = Settings()
    return RunStore(settings.postgres_dsn, settings.runs_dir).read_results(run_id)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--truth", type=Path, required=True)
    p.add_argument("--run", help="run id, read from the run store")
    p.add_argument("--results-file", type=Path, help="stored results as JSON instead of --run")
    p.add_argument("--schema", choices=["green-capex", "transition-plan"], required=True)
    p.add_argument("--min-correct", type=int, default=0)
    p.add_argument("--max-not-found", type=int)
    a = p.parse_args(argv)
    results = json.loads(a.results_file.read_text()) if a.results_file else _load_run(a.run)
    truth = [c for c in json.loads(a.truth.read_text()) if c["kind"] == a.schema]
    correct, n, nf = score(truth, run_answers(results))
    print(f"correct {correct}/{n} · not_found_on_yes_no {nf}")
    return int(correct < a.min_correct or (a.max_not_found is not None and nf > a.max_not_found))


if __name__ == "__main__":
    sys.exit(main())
