"""Company risk view for one annual report PDF or 10-K/20-F HTML (specs company-risk-view and theme-risk-mode, slice 1)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from bs4 import BeautifulSoup

from arp import grounding, models
from arp.ingestion import local_files
from arp.retrieval import embeddings
from arp.risk_view.mitigations import MITIGATION_SYSTEM, MitigationQuotes, mitigation_prompt
from arp.risk_view.section import clean, find_risk_section, is_start

DATA = Path(__file__).parent / "data"
THEMES: dict[str, str] = json.loads((DATA / "themes.json").read_text())
THRESHOLDS: dict[str, float] = json.loads((DATA / "thresholds.json").read_text())
_HTML_SUFFIXES = (".htm", ".html")
_BOLD = re.compile(r"font-weight\s*:\s*(bold|600|700)|font-style\s*:\s*italic", re.I)


def _html_headings(html: str) -> tuple[str, list[tuple[int, int, str]]]:
    """The 10-K text and its bold/italic headings as (start, end, heading), located in order (A3)."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n")
    found, seen, cursor = [], set(), 0
    for el in soup.find_all(lambda t: t.name in ("b", "strong", "i", "em") or bool(_BOLD.search(t.get("style", "")))):
        if any(id(p) in seen for p in el.parents):
            continue
        seen.add(id(el))
        raw = el.get_text("\n").strip()
        if not raw or is_start(" ".join(raw.split())):
            continue
        pos = text.find(raw, cursor)
        if pos < 0:
            continue
        cursor = pos + len(raw)
        found.append((pos, cursor, " ".join(raw.split())))
    return text, found


def _line_headings(text: str) -> list[tuple[int, int, str]]:
    """PDF/text headings: lines of 41 to 200 characters not ending in . , ; or : (A3)."""
    found, offset = [], 0
    for line in text.split("\n"):
        s = clean(line)
        if 40 < len(s) <= 200 and not s.endswith((".", ",", ";", ":")) and not is_start(s):
            found.append((offset, offset + len(line), s))
        offset += len(line) + 1
    return found


def _theme(heading: str) -> str:
    scores = models.classify([heading], list(THEMES.values()), hypothesis="This risk is about {}.")[0][0]
    key, label = max(THEMES.items(), key=lambda kv: scores.get(kv[1], 0.0))
    return key if scores.get(label, 0.0) >= 0.5 else "other"


def _year_on_year(risks: list[dict], prior: list[dict]) -> list[dict]:
    """Label each risk same/reworded/new against the prior year's risks; append the unmatched prior ones as dropped (A10)."""
    for r in risks:
        r["change"], r["prior_id"] = "new", None
    if risks and prior:
        vecs = np.asarray(embeddings.embed_texts([r["heading"] for r in risks] + [p["heading"] for p in prior]), dtype=float)
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        sims = vecs[: len(risks)] @ vecs[len(risks):].T
        pairs = sorted(((sims[i, j], i, j) for i in range(len(risks)) for j in range(len(prior))
                        if sims[i, j] >= THRESHOLDS["reworded"]), key=lambda p: -p[0])
        used_cur, used_prior = set(), set()
        for sim, i, j in pairs:
            if i in used_cur or j in used_prior:
                continue
            used_cur.add(i)
            used_prior.add(j)
            risks[i]["change"] = "same" if sim >= THRESHOLDS["same"] else "reworded"
            risks[i]["prior_id"] = prior[j]["id"]
    matched = {r["prior_id"] for r in risks}
    dropped = [{"id": f"r{len(risks) + n + 1}", "heading": p["heading"], "category": p.get("category"),
                "theme": p.get("theme"), "change": "dropped", "prior_id": p["id"], "mitigations": []}
               for n, p in enumerate(p for p in prior if p["id"] not in matched)]
    return risks + dropped


async def build_risk_view(path: Path, company_id: str, fiscal_year: int, llm, prior: dict | None = None) -> dict:
    """The risk view JSON of one document. `prior` is last year's risk view JSON, or None."""
    html = path.suffix.lower() in _HTML_SUFFIXES
    if html:
        text, headings = _html_headings(path.read_text(errors="ignore"))
        page_breaks: list[int] = []
    else:
        text, page_breaks, _ = local_files.parse_file_to_text_with_pages(path)
        headings = _line_headings(text)
    out = {"company_id": company_id, "fiscal_year": fiscal_year, "source": path.name, "status": "no_section",
           "risks": [], "dropped_quotes": 0}
    span = find_risk_section(text)
    if span is None:
        return out
    out["status"] = "ok"
    start, end = span
    section = "Item 1A" if re.match(r"Item 1A\b", clean(text[start:].split("\n", 1)[0]), re.I) else "Item 3.D"
    inside = [h for h in headings if start <= h[0] < end]
    risks, category = [], None
    for n, (pos, h_end, heading) in enumerate(inside):
        if html and len(heading) <= 40:
            category = heading
            continue
        if not grounding.is_grounded(heading, text):
            continue
        body_start = h_end
        body_end = inside[n + 1][0] if n + 1 < len(inside) else end
        body = text[body_start:body_end]
        result, _ = await llm.complete_structured(system=MITIGATION_SYSTEM, prompt=mitigation_prompt(heading, body),
                                                  output_model=MitigationQuotes)
        mitigations = []
        for quote in result.quotes:
            if not grounding.is_grounded(quote, body):
                out["dropped_quotes"] += 1
            elif html:
                mitigations.append({"quote": quote, "section": section})
            else:
                at = body.find(quote)
                mitigations.append({"quote": quote, "page": grounding._page_for_offset(page_breaks, body_start + at if at >= 0 else pos)})
        locator = {"section": section} if html else {"page": grounding._page_for_offset(page_breaks, pos)}
        risks.append({"id": f"r{len(risks) + 1}", "heading": heading, "category": category if html else None,
                      "theme": _theme(heading), **locator, "change": None, "prior_id": None, "mitigations": mitigations})
    if prior is not None:
        risks = _year_on_year(risks, [r for r in prior.get("risks", []) if r.get("change") != "dropped"])
    out["risks"] = risks
    return out
