from __future__ import annotations

import json
from pathlib import Path

import typer

from arp.rfp.fill import FillRefused, fill

rfp_app = typer.Typer(help="RFP answers: the answer library, filling an investor's file, golden checks.")


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
