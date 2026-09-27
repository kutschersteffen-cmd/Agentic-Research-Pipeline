from __future__ import annotations

from collections import defaultdict

from arp.schemas.transition_plan import TransitionPlanAssessmentRecord, Verdict
from arp.storage.run_store import RunStore

"""CLTI: the house transition-plan score, read off the 64-indicator
transition plan assessment (see docs/STEWARDSHIP_WORKFLOW_PLAN.md #3).
Versioned by the assessment run that produced it -- nothing is stored
here, every read goes back to the transition_plan runs' results."""

INDICATOR_COUNT = 64


def clti_score(record: TransitionPlanAssessmentRecord) -> float:
    """Share of the 64 indicators disclosed (verdict YES)."""
    return record.disclosed_count / INDICATOR_COUNT


def load_assessments(run_store: RunStore) -> dict[str, list[TransitionPlanAssessmentRecord]]:
    """Every transition plan assessment per company, oldest first."""
    by_company: dict[str, list[TransitionPlanAssessmentRecord]] = defaultdict(list)
    for manifest in run_store.list_runs("transition_plan"):
        for row in run_store.read_jsonl(run_store.results_path(manifest.run_id)):
            record = TransitionPlanAssessmentRecord.model_validate(row)
            by_company[record.company_id].append(record)
    for history in by_company.values():
        history.sort(key=lambda r: r.generated_at)
    return dict(by_company)


def latest_assessment(run_store: RunStore, company_id: str) -> TransitionPlanAssessmentRecord | None:
    history = load_assessments(run_store).get(company_id)
    return history[-1] if history else None


def clti_summary(record: TransitionPlanAssessmentRecord) -> str:
    """Plain-text CLTI block for dossiers and trigger details: the score,
    the walk/talk split, and the indicators not disclosed -- those are the
    engagement's concrete asks."""
    missing = [i for i in record.indicators if i.verdict == Verdict.NO]
    lines = [
        f"CLTI {clti_score(record):.2f} ({record.disclosed_count}/{INDICATOR_COUNT} indicators disclosed; "
        f"walk {record.walk_disclosed_count}/{record.walk_total_count}, talk {record.talk_disclosed_count}/{record.talk_total_count}; "
        f"report year {record.report_year or 'n/a'}, assessment run {record.run_id}).",
    ]
    if missing:
        lines.append("Not disclosed:")
        lines.extend(f"- #{i.number} [{i.category.value}] {i.question}" for i in missing)
    return "\n".join(lines)
