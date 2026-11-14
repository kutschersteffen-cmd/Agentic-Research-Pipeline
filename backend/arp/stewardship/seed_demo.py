"""`arp stewardship seed-demo`: SIMULATED VOICE engagements for the top MSCI World companies (spec "Demo data").

Everything derives from `random.Random(seed)` and a fixed base date, and every external_id starts with `s<seed>:`, so a
re-run with the same seed writes nothing and a different seed finds the old rows by their prefix and replaces them."""

from __future__ import annotations

import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import openpyxl
from sqlalchemy import delete, select

from arp.db.company_view import resolve_ref
from arp.db.session import transaction
from arp.stewardship.intake import intake_engagements
from arp.storage.postgres_models import (
    StwActivityModel,
    StwCommitmentModel,
    StwCompanyModel,
    StwContactModel,
    StwEngagementModel,
    StwEventModel,
    StwObjectiveModel,
    StwTransitionModel,
)

SOURCE = "mock_voice_seed"
MSCI_WORLD = Path(__file__).resolve().parents[3] / "data" / "holdings" / "MSCI_World.xlsx"
BASE = datetime(2024, 1, 15, 9, tzinfo=UTC)  # fixed, never now()

# German `Industry Classification` -> (FIR theme, weight); the first theme leads
SECTOR_THEMES: dict[str, list[tuple[str, int]]] = {
    "Energie": [("climate_mitigation", 6), ("pollution", 2), ("climate_adaptation", 2)],
    "Finanzen": [("governance_board_pay", 5), ("climate_mitigation", 2), ("business_ethics", 3)],
    "Informationstechnologie": [("digital_responsibility", 5), ("human_capital", 3), ("climate_mitigation", 2)],
    "Industrieunternehmen": [("climate_mitigation", 4), ("human_capital", 3), ("resources_circular", 3)],
    "Nicht-Basiskonsumgüter": [("human_rights", 4), ("resources_circular", 3), ("consumer_protection", 3)],
    "Basiskonsumgüter": [("natural_capital", 4), ("human_rights", 3), ("consumer_protection", 3)],
    "Gesundheitswesen": [("consumer_protection", 5), ("business_ethics", 3), ("human_capital", 2)],
    "Material": [("pollution", 4), ("natural_capital", 3), ("climate_mitigation", 3)],
    "Versorgungsunternehmen": [("climate_mitigation", 5), ("climate_adaptation", 3), ("communities", 2)],
    "Kommunikationsdienste": [("digital_responsibility", 5), ("shareholder_rights", 2), ("consumer_protection", 3)],
    "Immobilien": [("climate_adaptation", 4), ("climate_mitigation", 4), ("communities", 2)],
}
_FALLBACK = [("governance_board_pay", 4), ("climate_mitigation", 3), ("human_capital", 3)]
_PILLAR = {"E": ("climate_mitigation", "climate_adaptation", "natural_capital", "resources_circular", "pollution"),
           "S": ("human_capital", "human_rights", "consumer_protection", "digital_responsibility", "communities")}  # fmt: skip
_LABEL = {
    "climate_mitigation": "climate targets", "climate_adaptation": "climate resilience", "natural_capital": "nature and land use",
    "resources_circular": "waste and circularity", "pollution": "pollution controls", "human_capital": "workforce practices",
    "human_rights": "human rights due diligence", "consumer_protection": "product responsibility",
    "digital_responsibility": "responsible technology and AI", "communities": "community relations",
    "governance_board_pay": "board effectiveness and pay", "business_ethics": "business conduct",
    "tax_accounting": "tax transparency", "shareholder_rights": "shareholder rights", "other": "other topics",
}  # fmt: skip
_TYPE_TEXT = {
    "transparency": "Ask the company to disclose its approach and report progress on {t}.",
    "operational": "Ask the company to change day-to-day practice and show measurable steps on {t}.",
    "strategic": "Ask the company to set a board-approved strategy and targets on {t}.",
}
_FOLLOW_TEXT = {
    "transparency": "Follow-up: ask the company to publish the progress data it promised on {t}, with dates.",
    "operational": "Follow-up: ask the company to show the practice changes made since our last request on {t}.",
    "strategic": "Follow-up: ask the board to confirm the targets it set on {t} and how it will report against them.",
}
_RESULT_BY_LEVEL = {
    "1": ["not_achieved", "deterioration"], "2": ["not_achieved", "partially_achieved"],
    "3": ["partially_achieved", "achieved"], "4A": ["achieved"], "4B": ["achieved"], "5": ["achieved"],
}  # fmt: skip
_OUTCOME = {
    "achieved": "The company published the requested commitment and reported against it.",
    "partially_achieved": "The company met part of the request and set a date for the rest.",
    "not_achieved": "The company did not change its position during the engagement.",
    "deterioration": "The company reduced its disclosure on the topic during the engagement.",
}  # fmt: skip
_EVIDENCE = {
    "1": "No sign that the engagement influenced the outcome.",
    "2": "The change may have happened without the engagement; no link can be shown.",
    "3": "The change followed our meeting, and the company's reply refers to the request.",
    "4A": "The company's own report and a call note point to the engagement as a cause.",
    "4B": "The company confirmed in writing that the request led to the change, and the public filing shows it.",
    "5": "The company publicly credited the investor dialogue in its annual report.",
}  # fmt: skip
_SUMMARY = {
    "email": "Sent an email with the request and a short evidence note.",
    "letter": "Sent a letter to the chair setting out the request.",
    "call": "Call with investor relations on progress against the request.",
    "meeting": "Meeting with the responsible executive to review the request.",
    "agm_intervention": "Raised the topic at the annual general meeting.",
    "resolution_filed": "Filed a shareholder resolution on the topic.",
    "other": "Logged a note on the company's response.",
}  # fmt: skip
_LEVELS = [("1", 30), ("2", 30), ("3", 25), ("4A", 6), ("4B", 6), ("5", 3)]
_ROLES = [("bilateral", 40), ("lead", 15), ("active_support", 25), ("passive_support", 20)]
_RECEPT = [("very_good", 15), ("good", 30), ("neutral", 25), ("insufficient", 20), ("refusal", 10)]
_ACTIVITY = [("email", 30), ("call", 25), ("meeting", 25), ("letter", 10), ("agm_intervention", 7), ("other", 3)]


def select_companies(xlsx: Path, n: int) -> list[tuple[str, str, str]]:
    """(isin, name, sector) of the n heaviest distinct `Aktien` rows; header on worksheet row 4."""
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    rows = list(wb.worksheets[0].iter_rows(min_row=4, values_only=True))
    head = {h: i for i, h in enumerate(rows[0])}
    equities = [r for r in rows[1:] if r[head["Type of Security"]] == "Aktien" and r[head["ISIN"]]]
    equities.sort(key=lambda r: -(r[head["Weighting"]] if isinstance(r[head["Weighting"]], (int, float)) else 0))
    seen: dict[str, tuple[str, str, str]] = {}
    for r in equities:
        seen.setdefault(r[head["ISIN"]], (r[head["ISIN"]], r[head["Name"]], r[head["Industry Classification"]]))
    return list(seen.values())[:n]


def _iso(d: datetime) -> str:
    return d.isoformat()


def _pick(rng: random.Random, weighted: list[tuple[str, int]]) -> str:
    return rng.choices([v for v, _ in weighted], [w for _, w in weighted])[0]


def _company_batch(rng: random.Random, seed: int, isin: str, name: str, sector: str, batch: dict[str, list[dict]]) -> None:
    key = f"s{seed}:isin_{isin}"
    themes = SECTOR_THEMES.get(sector, _FALLBACK)
    n_obj = rng.randint(3, 5)
    first = _pick(rng, themes)
    chosen = [first]
    if n_obj >= 4 and rng.random() < 0.3:
        chosen.append(_pick(rng, [t for t in themes if t[0] != first] or _FALLBACK))
        if chosen[1] == first:
            chosen.pop()
    positions = [i % len(chosen) for i in range(n_obj)]  # objective i goes to this engagement
    in_eng: dict[int, list[str]] = {}  # engagement index -> objective external_ids so far
    candidates = [i for i in range(n_obj) if positions[:i].count(positions[i])]  # not first in its engagement
    follows = set(rng.sample(candidates, min(1 if n_obj < 5 else 2, len(candidates))))
    start = {}
    role = {}
    for e, theme in enumerate(chosen):
        role[e] = _pick(rng, _ROLES)
        start[e] = BASE + timedelta(days=rng.randint(0, 400))
        pillar = "E" if theme in _PILLAR["E"] else "S" if theme in _PILLAR["S"] else "G"
        batch["engagements"].append({
            "external_id": f"{key}:{theme}", "company_id": f"isin_{isin}", "isin": isin, "company_name": name, "theme": theme,
            "fir_theme": theme, "esg_pillars": [pillar], "engager_role": role[e], "started_at": _iso(start[e]),
            "rationale": f"{name} is a large holding with open questions on {_LABEL[theme]}; we want a clear, dated commitment.",
            "status": "open", "severity": rng.choice(["low", "medium", "high"]),
        })  # fmt: skip
    for i in range(n_obj):
        e = positions[i]
        theme = chosen[e]
        ext = f"{key}:{theme}:{len(in_eng.setdefault(e, []))}"
        start[e] += timedelta(days=rng.randint(45, 90)) if in_eng[e] else timedelta(0)
        began = start[e]
        otype = rng.choice(list(_TYPE_TEXT))
        closed = rng.random() < 0.6
        level = _pick(rng, _LEVELS[:3] if role[e] == "passive_support" else _LEVELS) if closed else None
        result = rng.choice(_RESULT_BY_LEVEL[level]) if closed else None
        ended = began + timedelta(days=rng.randint(30, 200))
        row = {
            "external_id": ext, "engagement_external_id": f"{key}:{theme}",
            "follows_external_id": rng.choice(in_eng[e]) if i in follows else None,
            "description": (_FOLLOW_TEXT if i in follows else _TYPE_TEXT)[otype].format(t=_LABEL[theme]), "objective_type": otype,
            "status": "closed" if closed else rng.choice(["initiated", "in_progress"]), "result": result,
            "receptiveness": _pick(rng, _RECEPT), "escalated": rng.random() < 0.2, "started_at": _iso(began),
            "target_date": (began + timedelta(days=365)).date().isoformat(), "closed_at": _iso(ended) if closed else None,
            "outcome": _OUTCOME[result] if closed else None, "influence_level": level,
            "influence_evidence": _EVIDENCE[level] if closed else None, "evidence_url": None,
        }  # fmt: skip
        in_eng[e].append(ext)
        batch["objectives"].append(row)
        end = ended if closed else began + timedelta(days=120)
        for a in range(rng.randint(1, 8)):
            kind = "meeting" if a == 0 else _pick(rng, _ACTIVITY)
            batch["activities"].append({
                "external_id": f"{ext}:{a}", "engagement_external_id": f"{key}:{theme}", "objective_external_id": ext,
                "occurred_at": _iso(began if a == 0 else began + (end - began) * rng.random()), "activity_type": kind,
                "interaction_type": "advocacy_pressure" if row["escalated"] and a else "informational", "is_initiation": a == 0,
                "summary": _SUMMARY[kind], "doc_ref": None, "logged_by": "demo-seed",
            })  # fmt: skip


def _purge(s, prefix: str) -> None:
    """All mock_voice_seed rows when any carries another seed's prefix (children first)."""
    stale = s.scalar(select(StwEngagementModel.engagement_id).where(StwEngagementModel.source == SOURCE, ~StwEngagementModel.external_id.startswith(prefix)).limit(1))
    if stale is None:
        return
    for model in (StwActivityModel, StwObjectiveModel, StwCommitmentModel, StwTransitionModel, StwEngagementModel, StwEventModel):
        if model is StwObjectiveModel:  # follows_objective_id points at objectives of the same source
            s.query(model).filter(model.source == SOURCE).update({"follows_objective_id": None})
        s.execute(delete(model).where(model.source == SOURCE))
    used = select(StwEngagementModel.company_id).union(select(StwContactModel.company_id))
    s.execute(delete(StwCompanyModel).where(StwCompanyModel.source == SOURCE, StwCompanyModel.company_id.not_in(used)))


def seed_demo(dsn: str, n: int = 400, seed: int = 7, xlsx: Path = MSCI_WORLD) -> dict[str, int]:
    picked = select_companies(xlsx, n)
    with transaction(dsn) as s:
        missing = [isin for isin, _, _ in picked if resolve_ref(s, f"ISIN:{isin}") is None]
    if missing:
        print("run arp showcase load first", file=sys.stderr)
        raise SystemExit(1)
    rng = random.Random(seed)
    batch: dict[str, list[dict]] = {"engagements": [], "objectives": [], "activities": []}
    for isin, name, sector in picked:
        _company_batch(rng, seed, isin, name, sector, batch)
    with transaction(dsn) as s:
        _purge(s, f"s{seed}:")
    report = intake_engagements(batch, dsn, SOURCE)
    if report.rejected:  # a bug in this module, not in the user's input
        raise RuntimeError(f"seed rows rejected: {report.rejected[:3]}")
    return {k: len(v) for k, v in batch.items()} | {"created": report.created, "updated": report.updated, "unchanged": report.unchanged}
