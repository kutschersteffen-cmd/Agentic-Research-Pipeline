"""A synthetic transition plan run, for trying Decision Studio and the results
screens without documents or an LLM.

Every verdict is made up: no document is read and nothing is cited, so no
citation is grounded. The run says so in its manifest (`params.synthetic`)
and in every answer. It goes through the same batch runner as a real run,
so its files, review queue and manifest look exactly like one.
"""

from __future__ import annotations

import random

from arp.llm.base import LLMUsage
from arp.orchestration.batch_runner import run_company_batch
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef
from arp.schemas.transition_plan import IndicatorAssessment, Verdict, WalkOrTalk
from arp.storage.run_store import RunStore
from arp.transition_plan.company_assessment import _summarize
from arp.transition_plan.indicators import load_indicators
from arp.transition_plan.pipeline import TransitionPlanAssessmentResult

SYNTHETIC_ANSWER = "Synthetic sample verdict: no document was read and nothing is cited."

# (company, chance of YES on a walk indicator, on a talk indicator).
# Fictional names; the profiles span leader to non-discloser, plus a
# company that talks far more than it walks.
DEMO_COMPANIES: list[tuple[CompanyRef, float, float]] = [
    (CompanyRef(company_id="DEMO-NWU", name="Northwind Utilities", sector="Utilities", country="Germany"), 0.85, 0.95),
    (CompanyRef(company_id="DEMO-ALS", name="Alpine Steel", sector="Materials", country="Austria"), 0.55, 0.80),
    (CompanyRef(company_id="DEMO-BMR", name="Baltic Maritime", sector="Industrials", country="Denmark"), 0.45, 0.60),
    (CompanyRef(company_id="DEMO-HGE", name="Helios Green Energy", sector="Utilities", country="Spain"), 0.75, 0.70),
    (CompanyRef(company_id="DEMO-PCO", name="Promise Consumer Goods", sector="Consumer Staples", country="France"), 0.15, 0.90),
    (CompanyRef(company_id="DEMO-CPC", name="Cascade Petrochemicals", sector="Energy", country="Netherlands"), 0.20, 0.35),
    (CompanyRef(company_id="DEMO-IRB", name="Iron Ridge Mining", sector="Materials", country="Australia"), 0.10, 0.15),
    (CompanyRef(company_id="DEMO-QSL", name="Quiet Shell Ltd", sector="Financials", country="United Kingdom"), 0.0, 0.0),
]


def demo_record(company: CompanyRef, walk_p: float, talk_p: float, run_id: str, rng: random.Random):
    indicators = []
    for ind in load_indicators():
        draw = rng.random()
        p = walk_p if ind.walk_or_talk == WalkOrTalk.WALK else talk_p
        verdict = Verdict.NA if draw > 0.95 else Verdict.YES if rng.random() < p else Verdict.NO
        confidence = round(rng.uniform(0.55, 0.95), 2) if verdict != Verdict.NA else 0.0
        indicators.append(
            IndicatorAssessment(
                number=ind.number,
                identifier=ind.identifier,
                category=ind.category,
                walk_or_talk=ind.walk_or_talk,
                question=ind.question,
                verdict=verdict,
                answer=SYNTHETIC_ANSWER,
                confidence=confidence,
                # A few low-confidence verdicts, so the review queue has something in it.
                needs_review=verdict != Verdict.NA and confidence < 0.58,
            )
        )
    return _summarize(
        company,
        run_id,
        {"indicators": indicators, "company_sector": company.sector, "company_location": company.country, "report_year": "2025"},
    )


async def seed_demo_run(run_store: RunStore, seed: int = 7) -> str:
    """Writes a new, finished transition plan run over DEMO_COMPANIES and
    returns its id. Deterministic for a given seed."""
    companies = [c for c, _, _ in DEMO_COMPANIES]
    profile = {c.company_id: (w, t) for c, w, t in DEMO_COMPANIES}
    rngs = {c.company_id: random.Random(f"{seed}:{c.company_id}") for c in companies}
    run_id = (
        JobManager(run_store)
        .create_run("transition_plan", {"synthetic": True, "seed": seed}, len(companies), model="synthetic")
        .run_id
    )

    async def _worker(company: CompanyRef) -> TransitionPlanAssessmentResult:
        walk_p, talk_p = profile[company.company_id]
        record = demo_record(company, walk_p, talk_p, run_id, rngs[company.company_id])
        return TransitionPlanAssessmentResult(record, LLMUsage(), 0.0)

    await run_company_batch(
        run_id,
        companies,
        run_store=run_store,
        worker=_worker,
        result_to_json=lambda r: r.record.model_dump(mode="json"),
        review_items=lambda c, r: [(c.company_id, r.record.model_dump(mode="json"))] if r.record.needs_review else [],
        cost_usd=lambda r: 0.0,
        concurrency=1,
    )
    return run_id
