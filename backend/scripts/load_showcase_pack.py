"""Loads the showcase demo pack (demo/showcase/) into ARP, in the order the app needs.

Spec: docs/superpowers/specs/2026-11-12-showcase-demo-pack-design.md. Run from backend/ the day before, after
`scripts/launch_jupyter.sh up`:

    python scripts/load_showcase_pack.py [--only STEP] [--again] [--base-url URL]

One line per step, `ok|skip|FAIL <step>: <reason>`, detail lines indented; exit 1 if any step failed.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from arp.config import Settings, get_settings

REPO = Path(__file__).resolve().parents[2]
DEFAULT_URL = "http://127.0.0.1:8000"
SHOWCASE_LOAD = [sys.executable, "-m", "arp", "showcase", "load"]


@dataclass
class Ctx:
    settings: Settings
    pack: Path
    client: httpx.Client
    base_url: str
    again: bool
    lines: list[str] = field(default_factory=list)  # printed indented under the step's line


def _read(ctx: Ctx, name: str) -> list[dict]:
    with (ctx.pack / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _companies(ctx: Ctx):
    from arp.universe import load_company_universe

    return load_company_universe(ctx.pack / "companies.csv")


def companies(ctx: Ctx) -> tuple[str, str]:
    from sqlalchemy import update

    from arp.db.companies import resolve_company
    from arp.db.models import Company
    from arp.db.session import require_dsn, transaction

    rows = _companies(ctx)
    with transaction(require_dsn(ctx.settings)) as session:
        for c in rows:
            r = resolve_company(session, c)  # also records company_id as the universe id documents are filed under
            if r.conflict:
                raise ValueError(f"{c.company_id}: its identifiers match more than one registered company")
            # an existing company gets the code only if it has none, as the Argus list upload does
            session.execute(update(Company).where(Company.id == r.company_id, Company.isic_code.is_(None))
                            .values(isic_code=c.isic_code))
    return "ok", f"{len(rows)} registered"


def universe(ctx: Ctx) -> tuple[str, str]:
    from arp.api.routers.universe import save_universe

    saved = save_universe(ctx.settings, _companies(ctx), "Showcase companies")  # the same list reuses its file
    return "ok", f"Showcase companies ({saved['company_count']} companies)"


def showcase_load_available() -> bool:
    return importlib.util.find_spec("arp.showcase.load") is not None


def portfolios(ctx: Ctx) -> tuple[str, str]:
    if not showcase_load_available():
        return "skip", "arp showcase load not available"
    done = subprocess.run(SHOWCASE_LOAD, cwd=REPO / "backend", capture_output=True, text=True)
    ctx.lines += [line for line in (done.stdout + done.stderr).splitlines() if line.strip()]
    if done.returncode:
        raise RuntimeError(f"arp showcase load exited {done.returncode}")
    return "ok", "arp showcase load"


def documents(ctx: Ctx) -> tuple[str, str]:
    rows = _read(ctx, "documents.csv")
    present = 0
    for r in rows:
        src = ctx.pack / "documents" / r["file_name"]
        if not src.is_file():
            ctx.lines.append(f"missing: {r['file_name']}")
            continue
        dest = Path(ctx.settings.documents_dir) / r["company_id"] / r["doc_type"]
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest / r["file_name"])  # same name: a second run overwrites, never adds a copy
        present += 1
    return "ok", f"{present} of {len(rows)} present"


def _present(ctx: Ctx, doc_type: str, company_ids: set[str] | None = None) -> list[str]:
    """Company ids, in companies.csv order, whose document of this type is in the pack."""
    have = {r["company_id"] for r in _read(ctx, "documents.csv")
            if r["doc_type"] == doc_type and (ctx.pack / "documents" / r["file_name"]).is_file()}
    return [c.company_id for c in _companies(ctx) if c.company_id in have and (company_ids is None or c.company_id in company_ids)]


def argus_capex(ctx: Ctx) -> tuple[str, str]:
    if not _present(ctx, "10-K"):
        return "skip", "no document present"
    raise NotImplementedError


def argus_plan(ctx: Ctx) -> tuple[str, str]:
    if not _present(ctx, "10-K", {"RWE"}):
        return "skip", "no document present"
    raise NotImplementedError


def voting(ctx: Ctx) -> tuple[str, str]:
    if not _present(ctx, "DEF-14A"):
        return "skip", "no document present"
    raise NotImplementedError


STEPS: dict[str, Callable[[Ctx], tuple[str, str]]] = {
    "companies": companies, "universe": universe, "portfolios": portfolios, "documents": documents,
    "argus-capex": argus_capex, "argus-plan": argus_plan, "voting": voting,
}


def main(argv: list[str] | None = None, *, client: httpx.Client | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--only", choices=list(STEPS), help="Run one step.")
    p.add_argument("--again", action="store_true", help="Start the prepared runs even when they already exist.")
    p.add_argument("--base-url", default=DEFAULT_URL, help="The running ARP API.")
    p.add_argument("--pack", type=Path, default=REPO / "demo" / "showcase")
    args = p.parse_args(argv)
    token = os.environ.get("ARP_SHOWCASE_TOKEN")
    client = client or httpx.Client(base_url=args.base_url, timeout=120,
                                    headers={"Authorization": f"Bearer {token}"} if token else {})
    failed = False
    for name in [args.only] if args.only else list(STEPS):
        ctx = Ctx(get_settings(), args.pack, client, args.base_url, args.again)
        try:
            status, reason = STEPS[name](ctx)
        except Exception as e:  # one failing step never stops the next
            status, reason, failed = "FAIL", str(e) or type(e).__name__, True
        print(f"{status} {name}: {reason}")
        for line in ctx.lines:
            print(f"  {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
