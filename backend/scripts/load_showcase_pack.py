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
import io
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


class Unreachable(Exception):
    pass


def _api(ctx: Ctx, method: str, path: str, **kw) -> dict:
    try:
        r = ctx.client.request(method, path, **kw)
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        raise Unreachable from e
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise RuntimeError(f"{r.status_code} {detail}")
    return r.json() if r.content else {}


def _argus(ctx: Ctx, schema_id: str, company_ids: list[str], *, rwe_only: bool = False) -> tuple[str, str]:
    """One Argus extraction over the given companies' annual reports, reporting year 2025, template `schema_id`."""
    if not company_ids:
        return "skip", "no document present"
    try:
        flows = _api(ctx, "GET", "/api/argus/flows")["flows"]
    except Unreachable:
        return "skip", f"API not reachable at {ctx.base_url}"
    # Argus extractions have no name: the same template and year (and, for the plan, RWE alone) is the same one
    exists = any((f.get("schema_choice") or {}).get("schema_id") == schema_id and f.get("reporting_year") == 2025
                 and (not rwe_only or [c["company_id"] for c in f.get("companies", [])] == ["RWE"]) for f in flows)
    if exists and not ctx.again:
        return "skip", "already exists"
    version = _api(ctx, "POST", f"/api/extraction/presets/{schema_id}/install")["version"]
    if not _api(ctx, "GET", f"/api/extraction/schemas/{schema_id}", params={"version": version}).get("release_flag"):
        # a draft template runs as a trial on one company; the owner chose to release the presets (13 Nov)
        _api(ctx, "POST", f"/api/extraction/schemas/{schema_id}/versions/{version}/release")
    flow_id = _api(ctx, "POST", "/api/argus/flows")["flow_id"]
    rows = [r for r in _read(ctx, "companies.csv") if r["company_id"] in company_ids]
    upload = io.StringIO()
    writer = csv.DictWriter(upload, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    _api(ctx, "POST", f"/api/argus/flows/{flow_id}/companies/upload",
         files={"file": ("companies.csv", upload.getvalue().encode(), "text/csv")})
    _api(ctx, "PATCH", f"/api/argus/flows/{flow_id}", json={
        "reporting_year": 2025, "source": "upload", "step": 3,
        "schema_choice": {"kind": "schema", "schema_id": schema_id, "version": version}})
    _api(ctx, "POST", f"/api/argus/flows/{flow_id}/files", json={"all_that_pass": True})
    _api(ctx, "POST", f"/api/argus/flows/{flow_id}/start")
    return "ok", f"started for {len(company_ids)} companies (flow {flow_id})"


def argus_capex(ctx: Ctx) -> tuple[str, str]:
    return _argus(ctx, "sch_transition_capex", _present(ctx, "10-K"))


def argus_plan(ctx: Ctx) -> tuple[str, str]:
    return _argus(ctx, "transition_plan_indicators", _present(ctx, "10-K", {"RWE"}), rwe_only=True)


def voting(ctx: Ctx) -> tuple[str, str]:
    ids = _present(ctx, "DEF-14A")
    if not ids:
        return "skip", "no document present"
    try:
        runs = _api(ctx, "GET", "/api/runs", params={"run_type": "proxy_voting"})["runs"]
    except Unreachable:
        return "skip", f"API not reachable at {ctx.base_url}"
    if runs and not ctx.again:
        return "skip", "already exists"
    companies = [c.model_dump(mode="json", exclude_none=True) for c in _companies(ctx) if c.company_id in ids]
    run_id = _api(ctx, "POST", "/api/voting/runs", json={"companies": companies})["run_id"]
    return "ok", f"started for {len(companies)} companies (run {run_id})"


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
