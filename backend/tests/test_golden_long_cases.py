"""Long-document golden cases (long-document golden cases spec): the bundled file's shape, checked without a model."""

import re
from pathlib import Path

import pytest
import yaml

from arp.golden_set.runner import load_cases
from arp.ingestion.parsing import chunk_document
from arp.schemas.common import SourceDocument

TAGS = ["[prior-year]", "[units]", "[segment]", "[table]", "[footnote]", "[not-disclosed]"]
LONG = load_cases(long=True)
WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "golden-set.yml"


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _passages(case) -> list[str]:
    doc = SourceDocument(company_id="golden", doc_type=case.doc_type, title=case.case_id, full_text=case.document_text)
    return [_squash(c.text) for c in chunk_document(doc)]


def _quote(case, label: str) -> str | None:
    m = re.search(rf'^{label}: "(.+)"\s*$', case.notes, re.MULTILINE)
    return _squash(m.group(1)) if m else None


def _holding(passages, sentence):
    return [i for i, p in enumerate(passages) if sentence in p]


def test_six_long_cases():  # AC-1
    assert len(LONG) == 6


def test_short_set_unchanged():  # AC-2
    assert [(c.case_id, c.expected_value) for c in load_cases()] == [
        ("green_capex_clean_number", 128.4), ("revenue_share_percentage", 34),
        ("not_disclosed_is_null_not_estimated", None), ("unit_scale_trap_thousands_vs_millions", 18.65),
        ("conflicting_sources_prefers_most_recent", 64.2),
    ]


@pytest.mark.parametrize("case", LONG, ids=lambda c: c.case_id)
def test_long_case_shape(case):  # AC-3 to AC-8
    assert len(case.document_text) >= 50000
    passages = _passages(case)
    assert len(passages) >= 15
    key = "Near-miss" if case.expect_not_disclosed else "Answer"
    anchor = _quote(case, key)
    assert anchor, f"notes needs a {key}: line"
    held = _holding(passages, anchor)
    if case.expect_not_disclosed:
        assert held, "the near-miss sentence must be in the document"
    else:
        assert len(held) == 1, f"the answer sentence must be in exactly 1 passage, found {len(held)}"
    distractor = _quote(case, "Distractor")
    assert distractor, "notes needs a Distractor: line"
    d_held = _holding(passages, distractor)
    assert d_held and not set(d_held) & set(held[:1]), "the distractor must be in a passage other than the answer's"
    assert re.search(r"^Source: \d{10}-\d{2}-\d{6}, Item \S+, Section: .+$", case.notes, re.MULTILINE)


def test_tags_and_not_disclosed():  # AC-9, AC-10
    tags = [next((t for t in TAGS if c.description.startswith(t)), None) for c in LONG]
    assert sorted(t for t in tags if t) == sorted(TAGS)
    nd = [c for c in LONG if c.expect_not_disclosed]
    assert len(nd) == 1 and nd[0].expected_value is None and nd[0].description.startswith("[not-disclosed]")


def test_cli_runs_only_long_cases(monkeypatch, pg):  # AC-11; pg: the CLI callback needs a DSN
    from typer.testing import CliRunner

    from arp.cli import app as cli_app
    from arp.cli import golden_set as cli
    from arp.golden_set.schema import GoldenSetCaseResult, GoldenSetReport

    async def fake_run(cases, **kw):
        return GoldenSetReport(total=len(cases), passed=len(cases), results=[
            GoldenSetCaseResult(case_id=c.case_id, description=c.description, passed=True, expected_value=None,
                                actual_value=None, confidence=1.0, grounded=True, needs_review=False) for c in cases])

    monkeypatch.setattr(cli, "build_llm_client", lambda *a, **k: None)
    monkeypatch.setattr(cli, "build_verifier_llm_client", lambda *a, **k: None)
    monkeypatch.setattr(cli, "run_golden_set", fake_run)
    out = CliRunner().invoke(cli_app, ["golden-set", "run", "--long"]).output
    long_ids, short_ids = {c.case_id for c in LONG}, {c.case_id for c in load_cases()}
    lines = [ln for ln in out.splitlines() if ln.startswith(("[PASS]", "[FAIL]"))]
    assert len(lines) == 6 and all(any(i in ln for i in long_ids) for ln in lines)
    assert not any(i in out for i in short_ids)


def _steps():
    return {s.get("name"): s.get("run", "") for s in yaml.safe_load(WORKFLOW.read_text())["jobs"]["golden-set"]["steps"]}


def test_workflow_runs_both_sets():  # AC-12
    run = _steps()["Run the golden set"]
    assert "set -eo pipefail" in run
    assert "arp golden-set run |" in run and "arp golden-set run --long" in run


def test_short_set_gate_check_has_no_threshold():  # AC-18
    step = _steps()["Compare the golden set with the evidence gate on and off"]
    assert "--gate off | tee off.txt" in step and "compare_gate_tokens.py off.txt on.txt" not in step


def test_long_gate_check_uses_the_threshold():  # AC-16 is wired
    step = _steps()["Compare the long golden set with the evidence gate on and off"]
    assert "compare_gate_tokens.py long_off.txt long_on.txt --max-ratio 0.9" in step


@pytest.mark.parametrize(("on", "code"), [(950, 1), (850, 0)])
def test_compare_script(tmp_path, on, code):  # AC-21
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import compare_gate_tokens

    (tmp_path / "off.txt").write_text("c1: pass\nextractor input tokens: 1000\n")
    (tmp_path / "on.txt").write_text(f"c1: pass\nextractor input tokens: {on}\n")
    assert compare_gate_tokens.main([str(tmp_path / "off.txt"), str(tmp_path / "on.txt")]) == code
