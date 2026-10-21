from __future__ import annotations

import json
from pathlib import Path

import typer

from arp.transition_plan.indicators import load_indicators

transition_plan_app = typer.Typer(help="Transition Plan Assessment: the 64 walk/talk disclosure indicators (Colesanti Senni et al. 2024).")


@transition_plan_app.command("indicators")
def transition_plan_indicators(out: Path = typer.Option(None, help="Write the 64 indicators as JSON here; omit to print a summary.")) -> None:
    indicators = load_indicators()
    if out:
        out.write_text(json.dumps([i.model_dump(mode="json") for i in indicators], indent=2))
        typer.echo(f"Wrote {len(indicators)} indicators to {out}")
        return
    for i in indicators:
        typer.echo(f"{i.number:>2}. {i.identifier} [{i.category.value}/{i.walk_or_talk.value}] {i.question}")
