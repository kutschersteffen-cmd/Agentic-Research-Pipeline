from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from arp.llm.base import LLMUsage
from arp.rfp import golden
from arp.rfp.detect import DetectedQuestions, ReportedQuestion
from arp.rfp.draft import Cited, DraftOut

DATA = Path(golden.__file__).parents[1] / "golden_set" / "data"


class Labels:
    """Reports each case's labelled questions, read back from the built file."""

    def __init__(self, case):
        self.case = case

    async def complete_structured(self, *, prompt, output_model, **_):
        lines = dict(line[1:].split("] ", 1) for line in prompt.splitlines())
        return DetectedQuestions(questions=[
            ReportedQuestion(location=lb["location"], question=lines[lb["location"]], answer_location=lb["answer_location"])
            for lb in self.case["labels"]
        ]), LLMUsage()


def test_golden_question_cases_are_locatable():
    """Every labelled question passes the app's own location checks, so a perfect model scores recall 1."""
    for case in golden.load(DATA / "rfp_questions.json")["cases"]:
        hit, total, misses = asyncio.run(golden.score_questions([case], Labels(case)))
        assert (hit, misses) == (total, []), case["name"]


class Drafter:
    async def complete_structured(self, *, prompt, output_model, **_):
        if output_model is golden.FactCheck:
            return golden.FactCheck(unsupported=["a bank"] if "Draft: Harbour" in prompt else []), LLMUsage()
        if "custodian" in prompt.rsplit("RFP question: ", 1)[1]:
            quote = "Our custodian for segregated mandates is Harbour Trust Bank."
            return DraftOut(answer="Harbour Trust Bank.", citations=[Cited(entry_id=8, quote=quote)]), LLMUsage()
        return DraftOut(), LLMUsage()


def test_golden_drafts_counts():
    c = asyncio.run(golden.score_drafts(golden.load(DATA / "rfp_drafts.json"), Drafter(), Drafter(), today=date(2026, 10, 21)))
    assert (c["drafted"], c["answerable"], c["blank"], c["unanswerable"], c["unsupported"]) == (1, 14, 8, 8, 1)
