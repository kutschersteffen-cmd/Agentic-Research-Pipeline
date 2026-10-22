from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.config import get_settings
from arp.llm.factory import build_llm_client
from arp.rfp.fill import FillRefused, fill
from arp.rfp.locations import SUFFIXES

rfp_app = typer.Typer(help="RFP answers: the answer library, filling an investor's file, golden checks.")
library_app = typer.Typer(help="The answer library of approved question-and-answer pairs.")
rfp_app.add_typer(library_app, name="library")


def _llm():
    return build_llm_client(get_settings())


@library_app.command("import")
def library_import(
    files: list[Path] = typer.Argument(..., exists=True, dir_okay=False, help="Past RFP responses (.docx, .xlsx)."),
) -> None:
    """Load the question-and-answer pairs of past RFP responses into the library, answers verbatim."""
    from arp.rfp.store import import_library

    bad = [f for f in files if f.suffix.lower() not in SUFFIXES]
    if bad:
        typer.echo(f"{bad[0]} is not a .docx or .xlsx file.", err=True)
        raise typer.Exit(1)
    imported, dropped = asyncio.run(import_library([(f.name, f.read_bytes()) for f in files], _llm()))
    typer.echo(f"imported {imported} entries, dropped {len(dropped)}")
    for question in dropped:
        typer.echo(f"dropped: {question}")


@rfp_app.command("fill")
def rfp_fill(
    original: Path = typer.Argument(..., exists=True, dir_okay=False, help="The investor's .xlsx or .docx file."),
    answers: Path = typer.Argument(..., exists=True, dir_okay=False, help='JSON list of {"answer_location", "answer"}.'),
    out: Path = typer.Option(..., "--out", help="Where to write the filled copy."),
) -> None:
    """Write answers into a copy of the investor's file. Prints nothing on success."""
    try:
        rows = json.loads(answers.read_text(encoding="utf-8"))
        pairs = [(str(r["answer_location"]), str(r["answer"])) for r in rows]
    except (ValueError, KeyError, TypeError):
        typer.echo(f'{answers} is not a JSON list of {{"answer_location", "answer"}} objects.', err=True)
        raise typer.Exit(1) from None
    try:
        data = fill(original.read_bytes(), original.suffix, pairs)
    except FillRefused as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    out.write_bytes(data)


golden_app = typer.Typer(help="Golden checks with the real model.")
rfp_app.add_typer(golden_app, name="golden")


@golden_app.command("questions")
def golden_questions(
    cases: Path = typer.Option(..., exists=True, dir_okay=False, help="Labelled RFP cases (JSON)."),
    min_recall: float = typer.Option(..., "--min-recall", help="Exit 1 below this recall."),
) -> None:
    """Share of labelled questions kept with their labelled location and answer location."""
    from arp.rfp import golden

    hit, total, misses = asyncio.run(golden.score_questions(golden.load(cases)["cases"], _llm()))
    for miss in misses:
        typer.echo(f"missed: {miss}")
    recall = hit / total if total else 0.0
    typer.echo(f"recall {recall:.3f} ({hit}/{total})")
    if recall < min_recall:
        raise typer.Exit(1)


@golden_app.command("drafts")
def golden_drafts(
    cases: Path = typer.Option(..., exists=True, dir_okay=False, help="Library and labelled questions (JSON)."),
    min_drafted: float = typer.Option(..., "--min-drafted", help="Exit 1 below this share of answerable drafted."),
    min_blank: float = typer.Option(..., "--min-blank", help="Exit 1 below this share of unanswerable left no source."),
) -> None:
    """Drafted and blank shares; also exits 1 when the verifier model finds any draft stating an uncited fact."""
    from datetime import date

    from arp.llm.factory import build_verifier_llm_client
    from arp.rfp import golden

    settings = get_settings()
    c = asyncio.run(golden.score_drafts(golden.load(cases), _llm(), build_verifier_llm_client(settings),
                                        today=date.today(), settings=settings))
    for note in c["notes"]:
        typer.echo(note)
    drafted = c["drafted"] / c["answerable"] if c["answerable"] else 0.0
    blank = c["blank"] / c["unanswerable"] if c["unanswerable"] else 0.0
    typer.echo(f"drafted {drafted:.3f} ({c['drafted']}/{c['answerable']}), no source {blank:.3f} "
               f"({c['blank']}/{c['unanswerable']}), drafts with unsupported facts {c['unsupported']}")
    if drafted < min_drafted or blank < min_blank or c["unsupported"]:
        raise typer.Exit(1)
