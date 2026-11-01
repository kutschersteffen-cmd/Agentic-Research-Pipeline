import json

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.llm.base import LLMUsage
from arp.pageindex import cli as C
from arp.pageindex import navigate as N
from arp.pageindex import tree as T

runner = CliRunner()


class FakeLLM:
    """Tree calls: one section per page (or the given starts). Navigation: `nav(prompt, model)`."""

    def __init__(self, n_pages=3, nav=None, starts=None, tree_error=None):
        self.n, self.nav, self.tree_error = n_pages, nav, tree_error
        self.starts = starts or list(range(1, n_pages + 1))

    async def complete_structured(self, *, system, prompt, output_model, **_):
        if output_model is T.SectionList:
            if self.tree_error:
                raise self.tree_error
            return T.SectionList(sections=[{"title": f"P{s}", "start_page": s, "level": 1} for s in self.starts]), LLMUsage()
        if output_model is T.Summary:
            return T.Summary(summary="s"), LLMUsage()
        if self.nav:
            return self.nav(prompt, output_model), LLMUsage()
        return output_model(action="answer", answer="YES", pages=[1], quotes=["q"], reasoning="r") if output_model is N.Step \
            else output_model(answer="YES", pages=[1], quotes=["q"], reasoning="r"), LLMUsage()


def _setup(monkeypatch, tmp_path, llm, n_pages=3):
    pdf = tmp_path / "f.pdf"
    pdf.write_bytes(b"pdf")
    monkeypatch.setattr(T, "page_texts", lambda _p: [f"text {i + 1}" for i in range(n_pages)])
    monkeypatch.setattr(C, "make_llm", lambda: (llm, "m"))
    return pdf, tmp_path / "o.json"


def _run(pdf, out, *extra):
    return runner.invoke(app, ["pageindex", "run", "--pdf", str(pdf), "--out", str(out), *extra])


@pytest.fixture
def s_run(monkeypatch, tmp_path):
    pdf, out = _setup(monkeypatch, tmp_path, FakeLLM())
    r = _run(pdf, out)
    return r, json.loads(out.read_text())


def test_run_64_results(s_run):
    r, data = s_run
    assert r.exit_code == 0, r.output
    assert len(data["results"]) == 64


def test_all_yes_page1(s_run):
    for res in s_run[1]["results"]:
        assert (res["answer"], res["pages"], res["quotes"]) == ("YES", [1], ["q"])


def test_stdout_line(s_run):
    assert s_run[0].stdout.strip() == "PageIndex: 64 indicators, 64 YES, 0 pages read, $0.00"


def test_output_keys(s_run):
    data = s_run[1]
    assert set(data) == {"document", "sha256", "model", "tree_nodes", "results"}
    for res in data["results"]:
        assert set(res) == {"identifier", "answer", "pages", "pages_opened", "quotes", "reasoning", "steps"}


def test_indicator_filter(monkeypatch, tmp_path):
    pdf, out = _setup(monkeypatch, tmp_path, FakeLLM())
    _run(pdf, out, "--indicator", "A_headline_1")
    assert [r["identifier"] for r in json.loads(out.read_text())["results"]] == ["A_headline_1"]


def _open_next(prompt, model):
    if model is N.Answer:
        return N.Answer(answer="NO")
    opened = {int(line.split()[1].rstrip("]")) for line in prompt.splitlines() if line.startswith("[page ")}
    return N.Step(action="open", open=[str(p) for p in range(1, 21) if p not in opened][:1])


def test_forced_answer_at_step6(monkeypatch, tmp_path):
    pdf, out = _setup(monkeypatch, tmp_path, FakeLLM(20, nav=_open_next), n_pages=20)
    _run(pdf, out, "--indicator", "A_headline_1")
    res = json.loads(out.read_text())["results"][0]
    assert (res["steps"], res["answer"]) == (6, "NO")


def test_partial_open_budget(monkeypatch, tmp_path):
    calls = iter([N.Step(action="open", open=["1"]), N.Step(action="open", open=["2"])])

    def nav(prompt, model):
        return next(calls, None) or (N.Answer(answer="NO") if model is N.Answer else N.Step(action="answer", answer="NO"))

    pdf, out = _setup(monkeypatch, tmp_path, FakeLLM(20, nav=nav, starts=[1, 11, 16]), n_pages=20)
    _run(pdf, out, "--indicator", "A_headline_1")
    assert json.loads(out.read_text())["results"][0]["pages_opened"] == list(range(1, 13))


def _raising_for(identifier, times):
    seen = {"n": 0}

    def nav(prompt, model):
        if identifier in prompt and seen["n"] < times:
            seen["n"] += 1
            raise RuntimeError("x")
        kw = dict(answer="YES", pages=[1], quotes=["q"], reasoning="r")
        return N.Step(action="answer", **kw) if model is N.Step else N.Answer(**kw)
    return nav


def test_error_isolated(monkeypatch, tmp_path):
    pdf, out = _setup(monkeypatch, tmp_path, FakeLLM(nav=_raising_for("A_headline_1", 99)))
    r = _run(pdf, out)
    res = {x["identifier"]: x for x in json.loads(out.read_text())["results"]}
    assert (res["A_headline_1"]["answer"], res["A_headline_1"]["error"]) == ("ERROR", "x")
    assert all(v["answer"] == "YES" for k, v in res.items() if k != "A_headline_1")
    assert r.exit_code == 0
    assert r.stdout.strip().endswith(", 1 errors")


def test_retry_once(monkeypatch, tmp_path):
    pdf, out = _setup(monkeypatch, tmp_path, FakeLLM(nav=_raising_for("A_headline_1", 1)))
    _run(pdf, out, "--indicator", "A_headline_1")
    res = json.loads(out.read_text())["results"][0]
    assert (res["answer"], res["steps"]) == ("YES", 1)


def test_tree_failure(monkeypatch, tmp_path):
    pdf, out = _setup(monkeypatch, tmp_path, FakeLLM(tree_error=RuntimeError("boom")))
    r = _run(pdf, out)
    assert r.exit_code == 1
    assert r.stderr.strip() == "Could not build page tree: boom"
    assert not out.exists()


def test_unknown_node_ignored(monkeypatch, tmp_path):
    calls = iter([N.Step(action="open", open=["nope"])])

    def nav(prompt, model):
        return next(calls, None) or N.Step(action="answer", answer="NO")

    pdf, out = _setup(monkeypatch, tmp_path, FakeLLM(nav=nav))
    _run(pdf, out, "--indicator", "A_headline_1")
    res = json.loads(out.read_text())["results"][0]
    assert (res["answer"], res["steps"], res["pages_opened"]) == ("NO", 2, [])
