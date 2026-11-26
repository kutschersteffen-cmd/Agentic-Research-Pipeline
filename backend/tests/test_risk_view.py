"""Company risk view (theme-risk-mode slice 1): section finder, headings, mitigations, theme, year-on-year, CLI."""

from __future__ import annotations

import json

import numpy as np
import pytest
from typer.testing import CliRunner

from arp import grounding
from arp.cli import app
from arp.config import get_settings
from arp.risk_view.section import find_risk_section
from arp.risk_view.view import THEMES

R1 = "Our business depends on construction activity in our markets"
R2 = "Water scarcity could limit the operation of our quarries"
TOC = "<p>Item 1A. Risk Factors 12</p><p>Item 1B. Unresolved Staff Comments 20</p>"
TAIL = ("<p><b>Item 1B. Unresolved Staff Comments</b></p>"
        "<p><b>Our competitors are larger than we are in most of our regions</b></p><p>None.</p>")
B1 = "<p>Construction fell in 2025. We diversify across regions to reduce this risk.</p>"
B2 = "<p>Some quarries are in dry regions. We recycle process water at our quarries.</p>"


def k_html(risks: list[tuple[str, str]]) -> str:
    body = "".join(f"<p><b>{h}</b></p>{b}" for h, b in risks)
    return (f"<html><body>{TOC}<p><b>Item 1A. Risk Factors</b></p><p><b>Industry Risk Factors</b></p>"
            f"{body}{TAIL}</body></html>")


K1 = k_html([(R1, B1), (R2, B2)])
P1 = [["Annual report 2025"], ["Risk report", "Our risk management is described below."],
      ["Rising energy prices could raise our production costs sharply", "Energy is a large share of our costs.",
       "We hedge energy purchases two years ahead."],
      ["Outlook", "Demand should stay stable next year while our costs keep falling"]]
P0 = [["Annual report 2025", "We make cement in three countries."]]


def pdf_text(pages):
    texts = ["\n".join(p) for p in pages]
    breaks, at = [], 0
    for t in texts:
        breaks.append(at)
        at += len(t) + 2
    return "\n\n".join(texts), breaks


@pytest.fixture
def env(tmp_path, monkeypatch):
    stand = tmp_path / "standins"
    (stand / "model").mkdir(parents=True)
    monkeypatch.setenv("ARP_STANDINS_DIR", str(stand))
    for key in ("ARP_ANTHROPIC_API_KEY", "ARP_GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARP_HYBRID_RETRIEVAL_ENABLED", "false")
    monkeypatch.setenv("ARP_MODELS_UNIVERSE_FUNNEL_ENABLED", "false")
    get_settings.cache_clear()
    pdfs: dict[str, list] = {}
    monkeypatch.setattr("arp.ingestion.local_files.parse_file_to_text_with_pages",
                        lambda path: (*pdf_text(pdfs[path.name]), []))
    scores: dict[str, dict[str, float]] = {}
    monkeypatch.setattr("arp.models.classify", lambda texts, labels, hypothesis="": (
        [{lab: scores.get(t, {}).get(lab, 0.1) for lab in labels} for t in texts], {}))

    class Env:
        dir = tmp_path

        def mitigations(self, entries):
            (stand / "model" / "MitigationQuotes.json").write_text(json.dumps([{"output": e} for e in entries]))

        def pdf(self, name, pages):
            pdfs[name] = pages
            path = tmp_path / name
            path.write_bytes(b"%PDF")
            return path

        def html(self, name, html):
            path = tmp_path / name
            path.write_text(html)
            return path

        def nli(self, text, by_key):
            scores[text] = {THEMES[k]: v for k, v in by_key.items()}

        def run(self, *args):
            return CliRunner().invoke(app, ["risk-view", *args])

        def view(self, company, year=2025):
            return json.loads((tmp_path / "O" / company / f"{year}.json").read_text())

        def calls(self, name=None):
            path = stand / "calls.jsonl"
            lines = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
            return [x for x in lines if name is None or x.get("name") == name]

    e = Env()
    e.mitigations([{"quotes": []}])
    yield e
    get_settings.cache_clear()


def run_doc(env, path, company, *extra):
    result = env.run("run", "--input", str(path), "--company", company, "--year", "2025", "--out", str(env.dir / "O"), *extra)
    assert result.exit_code == 0, result.output
    return env.view(company)


def test_section_finder_prefers_the_longest_span():
    text = "Item 1A. Risk Factors 12\nItem 1B. x\nItem 1A. Risk Factors\nbody line\nItem 1B. y\n"
    assert find_risk_section(text) == (text.index("Item 1A. Risk Factors\n"), text.index("Item 1B. y"))
    assert find_risk_section("no risks here") is None
    assert find_risk_section("## Risk report\nbody\n**Outlook**\nlater") == (0, len("## Risk report\nbody\n"))


def test_no_section_makes_no_call(env):  # AC-1, AC-2
    v = run_doc(env, env.pdf("p0.pdf", P0), "Z")
    assert v["status"] == "no_section" and v["risks"] == []
    assert env.calls("MitigationQuotes") == []


def test_10k_headings_categories_and_calls(env):  # AC-3, AC-4, AC-5, AC-15
    v = run_doc(env, env.html("k1.htm", K1), "M")
    assert [r["heading"] for r in v["risks"]] == [R1, R2]
    for r in v["risks"]:
        assert r["section"] == "Item 1A" and "page" not in r and r["category"] == "Industry Risk Factors"
        assert r["change"] is None and r["theme"] == "other"
    assert len(env.calls("MitigationQuotes")) == 2


def test_10k_mitigations_are_grounded(env):  # AC-6, AC-7
    env.mitigations([{"quotes": ["We diversify across regions to reduce this risk.", "We own the moon."]}, {"quotes": []}])
    v = run_doc(env, env.html("k1.htm", K1), "M")
    assert v["risks"][0]["mitigations"] == [{"quote": "We diversify across regions to reduce this risk.", "section": "Item 1A"}]
    assert v["risks"][1]["mitigations"] == []
    assert v["dropped_quotes"] == 1


def test_pdf_risk_page_mitigation_and_stop(env):  # AC-8, AC-9
    env.mitigations([{"quotes": ["We hedge energy purchases two years ahead."]}])
    v = run_doc(env, env.pdf("p1.pdf", P1), "H")
    assert len(v["risks"]) == 1
    r = v["risks"][0]
    assert r["heading"] == P1[2][0] and r["page"] == 3 and r["category"] is None
    assert r["mitigations"] == [{"quote": "We hedge energy purchases two years ahead.", "page": 3}]


@pytest.mark.parametrize("scores, theme", [
    ({**{k: 0.3 for k in THEMES}, "climate_transition": 0.8}, "climate_transition"),  # AC-10
    ({k: 0.4 for k in THEMES}, "other"),  # AC-11
])
def test_theme(env, scores, theme):
    env.nli(P1[2][0], scores)
    assert run_doc(env, env.pdf("p1.pdf", P1), "H")["risks"][0]["theme"] == theme


def prior_file(env, headings):
    path = env.dir / "prior.json"
    path.write_text(json.dumps({"risks": [{"id": f"p{i + 1}", "heading": h, "mitigations": []}
                                          for i, h in enumerate(headings)]}))
    return path


def patch_embeddings(monkeypatch, cur, prior, sims):
    """Unit vectors: current i and prior j have cosine sims[(i, j)], every other pair 0."""
    n = len(cur) + len(prior)
    vec = {}
    for i, h in enumerate(cur):
        vec[h] = np.eye(n)[i]
    for j, h in enumerate(prior):
        v = np.zeros(n)
        for (i, jj), s in sims.items():
            if jj == j:
                v[i] = s
        v[len(cur) + j] = np.sqrt(max(0.0, 1 - (v ** 2).sum()))
        vec[h] = v
    monkeypatch.setattr("arp.retrieval.embeddings.embed_texts", lambda texts: np.array([vec[t] for t in texts]))


def test_year_on_year(env, monkeypatch):  # AC-12, AC-13
    cur = [f"Current risk number {i} is a heading of more than forty characters" for i in range(1, 6)]
    prior = [f"Prior risk {i}" for i in range(1, 7)]
    patch_embeddings(monkeypatch, cur, prior, {(0, 0): 0.95, (1, 1): 0.85, (2, 2): 0.70, (3, 3): 0.60, (4, 4): 0.40})
    path = env.html("k5.htm", k_html([(h, "<p>One sentence body.</p>") for h in cur]))
    v = run_doc(env, path, "M", "--prior", str(prior_file(env, prior)))
    risks = v["risks"][:5]
    assert [r["change"] for r in risks] == ["same", "same", "reworded", "reworded", "new"]
    assert [r["prior_id"] for r in risks] == ["p1", "p2", "p3", "p4", None]
    dropped = v["risks"][5:]
    assert [(d["change"], d["prior_id"], d["heading"], d["mitigations"]) for d in dropped] == [
        ("dropped", "p5", "Prior risk 5", []), ("dropped", "p6", "Prior risk 6", [])]


def test_one_to_one_matching(env, monkeypatch):  # AC-14
    c1, c2 = "First current risk heading longer than forty chars", "Second current risk heading longer than forty chars"
    monkeypatch.setattr("arp.retrieval.embeddings.embed_texts", lambda texts: np.array(
        [{c1: [1, 0, 0], c2: [0.9, np.sqrt(1 - 0.81), 0], "P": [1, 0, 0]}[t] for t in texts]))
    v = run_doc(env, env.html("k2.htm", k_html([(c1, B1), (c2, B2)])), "M", "--prior", str(prior_file(env, ["P"])))
    assert (v["risks"][0]["change"], v["risks"][0]["prior_id"]) == ("same", "p1")
    assert v["risks"][1]["change"] == "new"


def test_batch_skips_missing_rows(env):  # AC-16
    k1, p1, missing = env.html("k1.htm", K1), env.pdf("p1.pdf", P1), env.dir / "gone.pdf"
    manifest = env.dir / "m.csv"
    manifest.write_text(f"company_id,year,path\nA,2024,{k1}\nB,2025,{p1}\nC,2025,{missing}\n")
    result = env.run("batch", "--manifest", str(manifest), "--out", str(env.dir / "O"))
    assert result.exit_code == 1
    assert (env.dir / "O/A/2024.json").exists() and (env.dir / "O/B/2025.json").exists()
    assert not (env.dir / "O/C").exists()
    assert str(missing) in result.output


def test_golden_checks_files_before_any_call(env):  # AC-17, AC-17b
    docs = env.dir / "D"
    docs.mkdir()
    labels = env.dir / "labels.json"
    labels.write_text(json.dumps([{"company_id": "m", "fiscal_year": 2025, "file": "m/2025.htm", "prior_file": None, "risks": []}]))
    result = env.run("golden", "--documents-dir", str(docs), "--labels", str(labels))
    assert result.exit_code == 1 and "Golden document missing:" in result.output
    assert env.calls() == []
    result = env.run("golden", "--documents-dir", str(docs), "--labels", str(docs / "none.json"))
    assert result.exit_code == 1 and "Golden labels missing:" in result.output


def test_golden_scores_documents(env):
    (env.dir / "D").mkdir()
    (env.dir / "D/k1.htm").write_text(K1)
    labels = env.dir / "labels.json"
    labels.write_text(json.dumps([{"company_id": "m", "fiscal_year": 2025, "file": "k1.htm", "prior_file": None,
                                   "risks": [{"heading": R1, "mitigations": [], "change": None},
                                             {"heading": R2, "mitigations": [], "change": None}]}]))
    result = env.run("golden", "--documents-dir", str(env.dir / "D"), "--labels", str(labels))
    assert result.exit_code == 0, result.output
    assert "heading recall 1.000" in result.output
    labels.write_text(json.dumps([{"company_id": "m", "fiscal_year": 2025, "file": "k1.htm", "prior_file": None,
                                   "risks": [{"heading": "A risk the view does not find in this document", "mitigations": [], "change": None}]}]))
    assert env.run("golden", "--documents-dir", str(env.dir / "D"), "--labels", str(labels)).exit_code == 1


def test_ungrounded_heading_is_not_emitted(env, monkeypatch):  # AC-18
    real = grounding.is_grounded
    monkeypatch.setattr("arp.grounding.is_grounded", lambda q, t, *a, **k: q != R2 and real(q, t, *a, **k))
    v = run_doc(env, env.html("k1.htm", K1), "M")
    assert [r["heading"] for r in v["risks"]] == [R1]


def test_golden_recall_ignores_dropped_prior_risks(env, monkeypatch):
    r3 = "A third risk that only last year's report named in its risk factors"
    monkeypatch.setattr("arp.retrieval.embeddings.embed_texts", lambda texts: np.array(
        [{R1: [1, 0, 0], R2: [0, 1, 0], r3: [0, 0, 1]}[t] for t in texts]))
    (env.dir / "D").mkdir()
    (env.dir / "D/m24.htm").write_text(k_html([(R1, B1), (R2, B2), (r3, "<p>Body.</p>")]))
    (env.dir / "D/m25.htm").write_text(K1)
    risks = [{"heading": h, "mitigations": [], "change": "same"} for h in (R1, R2, r3)]
    labels = env.dir / "labels.json"
    labels.write_text(json.dumps([
        {"company_id": "m", "fiscal_year": 2024, "file": "m24.htm", "prior_file": None, "risks": []},
        {"company_id": "m", "fiscal_year": 2025, "file": "m25.htm", "prior_file": "m24.htm", "risks": risks}]))
    result = env.run("golden", "--documents-dir", str(env.dir / "D"), "--labels", str(labels), "--min-recall", "0")
    assert "m25.htm: heading recall 0.667" in result.output, result.output
