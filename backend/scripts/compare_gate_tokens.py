"""Exit 1 unless the evidence gate cut extractor input tokens enough (long-document golden cases spec, AC-16/AC-21).

    python scripts/compare_gate_tokens.py off.txt on.txt [--max-ratio 0.9]

Each file is the output of `arp golden-set run --gate off|on`; its last line is `extractor input tokens: N`."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def tokens(path: Path) -> int:
    last = Path(path).read_text().strip().splitlines()[-1]
    m = re.fullmatch(r"extractor input tokens: (\d+)", last.strip())
    if not m:
        raise SystemExit(f"{path}: last line is not 'extractor input tokens: N': {last!r}")
    return int(m.group(1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("off", type=Path)
    ap.add_argument("on", type=Path)
    ap.add_argument("--max-ratio", type=float, default=0.9)
    args = ap.parse_args(argv)
    off, on = tokens(args.off), tokens(args.on)
    print(f"extractor input tokens: gate off {off}, gate on {on}")
    if on > args.max_ratio * off:
        print(f"The gate cut extractor input by less than {100 - round(args.max_ratio * 100)}%.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
