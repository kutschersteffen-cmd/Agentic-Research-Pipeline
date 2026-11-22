from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from arp.config import get_settings

agent_app = typer.Typer(help="The Agent screen: board golden set.")


@agent_app.command("board-golden")
def board_golden(
    cases: Path = typer.Option(..., help="One {id, prompt, expected_kind, expected_live?} JSON object per line."),
    min_pass: int = typer.Option(..., "--min-pass", help="Exit 1 when fewer cases pass."),
) -> None:
    """Draw each case once with the real model over Done plan D; a case passes on the first draft."""
    from arp.agent_board import golden
    from arp.llm.factory import build_llm_client

    llm = build_llm_client(get_settings())
    rows = golden.load_cases(cases)

    async def run() -> list[str | None]:
        return list(await asyncio.gather(*(golden.run_case(llm, c) for c in rows)))

    results = asyncio.run(run())
    for case, why in zip(rows, results, strict=True):
        typer.echo(f"{case['id']}: {'pass' if why is None else 'fail: ' + why}")
    passed = sum(why is None for why in results)
    typer.echo(f"board golden: {passed}/{len(rows)} passed (min {min_pass})")
    if passed < min_pass:
        raise typer.Exit(code=1)
