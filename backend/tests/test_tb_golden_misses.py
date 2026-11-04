"""The transition-barrier golden score lists the cases that were not counted or counted wrong."""

from __future__ import annotations

import asyncio
from datetime import date

from arp.config import Settings
from arp.transition_barrier import golden
from arp.transition_barrier.extraction import Extraction


def _got(value, page, counted=True):
    return Extraction(value=value, unit=None, extracted=None, quote="q", page=page, locator=None, as_of=None,
                      counted=counted, reason=None if counted else "r")


def test_score_lists_misses(tmp_path, monkeypatch):
    (tmp_path / "d.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(golden.fetching, "parse", lambda fetched: (["page"], False))
    monkeypatch.setattr(golden.fetching, "doc_as_of", lambda fetched, today: today)
    cases = [golden.Case("AVI-R1", "European Union", "status", "d.pdf", "in_force", None, 15),
             golden.Case("AVI-R1", "European Union", "escalating", "d.pdf", True, None, 29),
             golden.Case("AVI-R1", "Japan", "status", "d.pdf", "in_force", None, 3)]
    answers = {("European Union", "status"): _got("in_force", 15), ("European Union", "escalating"): _got(True, 30),
               ("Japan", "status"): _got("in_force", 3, counted=False)}

    async def extract(fact, cell, doc, conversions, **kw):
        return answers[(cell.split(", ")[1], fact.id)]

    monkeypatch.setattr(golden, "extract", extract)
    misses: list[str] = []
    precision, coverage = asyncio.run(golden.score(
        cases, tmp_path, llm=None, verifier_llm=None, settings=Settings(), today=date(2026, 11, 3), misses=misses,
    ))
    assert (precision, coverage) == (0.5, 2 / 3)
    assert sorted(misses) == [
        "not counted: AVI-R1 Japan status (d.pdf): label 'in_force' p.3",
        "wrong: AVI-R1 European Union escalating (d.pdf): label True p.29, got True p.30",
    ]
