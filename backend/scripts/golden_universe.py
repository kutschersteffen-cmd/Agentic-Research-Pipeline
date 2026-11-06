"""Writes a company universe (unweighted) from golden cases: company_id is each case's case_id.

    python scripts/golden_universe.py --cases tests/golden/exposure/electrolyser_makers/cases.json \
        --split tune --out /tmp/universe.json"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--split", choices=["tune", "holdout"], required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    cases = json.loads(a.cases.read_text())["cases"]
    rows = [
        {"company_id": c["case_id"], "name": c["company"], "isin": c.get("isin")}
        for c in cases
        if c["split"] == a.split
    ]
    a.out.write_text(json.dumps(rows, indent=2))
    print(f"{len(rows)} companies -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
