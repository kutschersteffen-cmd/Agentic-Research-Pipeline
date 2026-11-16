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
    assert (c["drafted"], c["answerable"], c["blank"], c["unanswerable"], c["unsupported"]) == (0, 14, 8, 8, 0)


class Chain:
    """Unchanged for the first question, a cited draft for the second, nothing for the third."""

    async def complete_structured(self, *, prompt, output_model, **_):
        if output_model is golden.FactCheck:
            return golden.FactCheck(), LLMUsage()
        question = prompt.rsplit("RFP question: ", 1)[1]
        if question == "Please describe your firm.":
            return DraftOut(use_entry=1), LLMUsage()
        if question == "When was the firm founded?":
            return DraftOut(answer="In 2011.", citations=[Cited(entry_id=1, quote="founded in 2011")]), LLMUsage()
        return DraftOut(), LLMUsage()


def test_golden_unchanged_counts():
    cases = {"library": [{"question": "Describe your firm.", "answer": "Example AM, founded in 2011."}],
             "questions": [{"question": "Please describe your firm.", "expect": "unchanged"},
                           {"question": "When was the firm founded?", "expect": "library"},
                           {"question": "What is your revenue?", "expect": "none"}]}
    c = asyncio.run(golden.score_drafts(cases, Chain(), Chain(), today=date(2026, 11, 15)))
    assert (c["unchanged"], c["unchanged_total"], c["drafted"], c["blank"]) == (1, 1, 2, 1)
    assert (c["library_first"], c["library_first_total"]) == (2, 2)


def test_golden_unchanged_case_file_is_well_formed():
    cases = golden.load(DATA / "rfp_unchanged_drafts.json")
    expects = [q["expect"] for q in cases["questions"]]
    assert set(expects) == {"unchanged", "library", "none"}
    assert all(expects.count(e) >= 10 for e in set(expects))
    assert "Example AM" not in str(cases)


def test_golden_drafts_cli_checks_min_unchanged(pg, tmp_path, monkeypatch):
    import json

    from typer.testing import CliRunner

    from arp.cli import app as cli
    from arp.cli import rfp as rfp_cli
    from arp.llm import factory

    monkeypatch.setattr(rfp_cli, "_llm", Chain)
    monkeypatch.setattr(factory, "build_verifier_llm_client", lambda _settings: Chain())
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"library": [{"question": "Describe your firm.", "answer": "Example AM, founded in 2011."}],
                                "questions": [{"question": "Please describe your firm.", "expect": "unchanged"},
                                              {"question": "Who owns the firm?", "expect": "unchanged"}]}))
    args = ["rfp", "golden", "drafts", "--cases", str(path), "--min-drafted", "0", "--min-blank", "0"]
    passed = CliRunner().invoke(cli, [*args, "--min-unchanged", "0.5", "--min-library-first", "1"])
    failed = CliRunner().invoke(cli, [*args, "--min-unchanged", "0.9"])
    assert (passed.exit_code, failed.exit_code) == (0, 1), passed.stdout
    assert "unchanged 0.500 (1/2)" in failed.stdout


class Library:
    """Cites the entry for the first question and the document for the second."""

    async def complete_structured(self, *, prompt, output_model, **_):
        if output_model is golden.FactCheck:
            return golden.FactCheck(), LLMUsage()
        question = prompt.rsplit("RFP question: ", 1)[1]
        if question == "When was the firm founded?":
            return DraftOut(answer="In 2011.", citations=[Cited(entry_id=1, quote="founded in 2011")]), LLMUsage()
        if question == "How many meetings did you hold?" and "[D1]" in prompt:
            return DraftOut(answer="We held 214 meetings.", citations=[Cited(document_id=1, quote="214 meetings")]), LLMUsage()
        return DraftOut(), LLMUsage()


def test_golden_library_first_counts():
    cases = {"library": [{"question": "Describe your firm.", "answer": "Example AM, founded in 2011."}],
             "documents": [{"title": "Report", "priority": 1, "text": "In 2025 we held 214 meetings with companies."}],
             "questions": [{"question": "When was the firm founded?", "expect": "library"},
                           {"question": "How many meetings did you hold?", "expect": "documents"}]}
    c = asyncio.run(golden.score_drafts(cases, Library(), Library(), today=date(2026, 11, 15)))
    assert (c["library_first"], c["library_first_total"], c["drafted"]) == (1, 1, 2)


def test_golden_chain_case_file_is_well_formed():
    cases = golden.load(DATA / "rfp_chain_drafts.json")
    expects = [q["expect"] for q in cases["questions"]]
    assert set(expects) == {"unchanged", "library", "documents", "none"}
    assert all(expects.count(e) >= 10 for e in set(expects))
    assert sorted(d["priority"] for d in cases["documents"]) == [1, 2]
    assert "Example AM" not in str(cases)
