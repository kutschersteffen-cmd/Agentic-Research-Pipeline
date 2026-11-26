"""`arp risk-view run | batch | golden`: one JSON file per company and year (spec company-risk-view, theme-risk-mode A7)."""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path

import typer

from arp.config import get_settings
from arp.llm.factory import build_llm_client
from arp.risk_view.view import build_risk_view

risk_view_app = typer.Typer(help="Read the risks a company names in its annual report or 10-K.")
DEFAULT_LABELS = Path(__file__).resolve().parents[2] / "tests" / "golden" / "risk_view" / "labels.json"


def _write(view: dict, out: Path) -> Path:
    path = out / view["company_id"] / f"{view['fiscal_year']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(view, indent=2, ensure_ascii=False))
    return path


@risk_view_app.command("run")
def run_cmd(
    input: Path = typer.Option(..., "--input", help="Annual report PDF or 10-K/20-F HTML."),
    company: str = typer.Option(..., "--company"),
    year: int = typer.Option(..., "--year"),
    out: Path = typer.Option(..., "--out"),
    prior: Path | None = typer.Option(None, "--prior", help="Last year's risk view JSON, for year-on-year labels."),
) -> None:
    llm = build_llm_client(get_settings())
    prior_view = json.loads(prior.read_text()) if prior else None
    view = asyncio.run(build_risk_view(input, company, year, llm, prior_view))
    typer.echo(f"{_write(view, out)}: {view['status']}, {len(view['risks'])} risks")


@risk_view_app.command("batch")
def batch_cmd(manifest: Path = typer.Option(..., "--manifest", help="CSV with columns company_id,year,path."),
              out: Path = typer.Option(..., "--out")) -> None:
    llm = build_llm_client(get_settings())
    missing = False
    with manifest.open(newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        path = Path(row["path"])
        if not path.exists():
            typer.echo(f"Missing file: {path}", err=True)
            missing = True
            continue
        view = asyncio.run(build_risk_view(path, row["company_id"], int(row["year"]), llm))
        typer.echo(f"{_write(view, out)}: {view['status']}, {len(view['risks'])} risks")
    if missing:
        raise typer.Exit(1)


def _norm(s: str) -> str:
    return " ".join(s.split()).casefold()


@risk_view_app.command("golden")
def golden_cmd(
    documents_dir: Path = typer.Option(..., "--documents-dir"),
    labels: Path = typer.Option(DEFAULT_LABELS, "--labels"),
    min_recall: float = typer.Option(0.90, "--min-recall"),
    min_precision: float = typer.Option(0.90, "--min-precision"),
    min_yoy: float = typer.Option(0.90, "--min-yoy"),
) -> None:
    """Score the risk view on hand-labelled documents with the real model; exit 1 below any threshold."""
    if not labels.exists():
        typer.echo(f"Golden labels missing: {labels}", err=True)
        raise typer.Exit(1)
    entries = json.loads(labels.read_text())
    for e in entries:
        for name in (e["file"], e.get("prior_file")):
            if name and not (documents_dir / name).exists():
                typer.echo(f"Golden document missing: {documents_dir / name}", err=True)
                raise typer.Exit(1)
    llm = build_llm_client(get_settings())
    views: dict[str, dict] = {}
    failed = False
    for e in sorted(entries, key=lambda e: e.get("prior_file") is not None):  # prior years first
        prior = views.get(e["prior_file"]) if e.get("prior_file") else None
        view = views[e["file"]] = asyncio.run(build_risk_view(documents_dir / e["file"], e["company_id"],
                                                              e["fiscal_year"], llm, prior))
        emitted = {_norm(r["heading"]): r for r in view["risks"] if r["change"] != "dropped"}  # this year's risks only
        current = [r for r in e["risks"] if r.get("change") != "dropped"]
        found = [emitted[_norm(r["heading"])] for r in current if _norm(r["heading"]) in emitted]
        recall = len(found) / len(current) if current else 1.0
        labelled = {_norm(r["heading"]): [_norm(q) for q in r.get("mitigations", [])] for r in e["risks"]}
        kept = [(_norm(r["heading"]), _norm(m["quote"])) for r in view["risks"] for m in r["mitigations"]]
        right = sum(any(q in lq or lq in q for lq in labelled.get(h, [])) for h, q in kept)
        precision = right / len(kept) if kept else 1.0
        # every emitted heading is grounded: build_risk_view drops the others
        line = f"{e['file']}: heading recall {recall:.3f}, mitigation precision {precision:.3f}"
        failed |= recall < min_recall or precision < min_precision
        if e.get("prior_file"):
            every = {_norm(r["heading"]): r for r in view["risks"]}
            pairs = [(r, every.get(_norm(r["heading"]))) for r in e["risks"] if r.get("change")]
            yoy = sum(1 for r, v in pairs if v and v["change"] == r["change"]) / len(pairs) if pairs else 1.0
            line += f", year-on-year {yoy:.3f}"
            failed |= yoy < min_yoy
        typer.echo(line)
    if failed:
        raise typer.Exit(1)
