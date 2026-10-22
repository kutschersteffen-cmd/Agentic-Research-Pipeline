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
