from __future__ import annotations

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.engagement import (
    EngagementIssue,
    MeetingSummaryDraft,
    MeetingTalkingPoints,
    OutreachLetterDraft,
    ResearchDossier,
)

_LETTER_SYSTEM = """\
You are drafting an investor stewardship outreach letter on behalf of a \
portfolio manager, in the fund's house style. Be specific and evidence- \
based, referencing the dossier's findings rather than generic ESG \
language. State clearly what the fund is asking the company to do or \
respond to. Keep the tone professional and constructive, not adversarial \
-- this is an opening engagement letter, not an escalation. \
Every factual claim about the company must reuse a citation already \
present in the dossier (matching doc_id and an exact quote); do not \
introduce new unsourced claims."""

_TALKING_POINTS_SYSTEM = """\
You are preparing talking points for a portfolio manager ahead of an \
engagement meeting with company management. List concrete objectives for \
the meeting and the specific points to raise, grounded in the dossier. \
Prioritize the issue actually at hand; don't pad with generic ESG \
boilerplate."""

_SUMMARY_SYSTEM = """\
You are drafting a post-meeting summary from notes or a transcript of an \
investor engagement meeting. Extract: a factual summary of what was \
discussed, any commitments the company's representatives explicitly made \
(only ones actually stated -- do not infer commitments that weren't \
stated), and concrete follow-up actions for the fund. This summary will \
be reviewed by a human before any commitment is logged as real, so err on \
the side of precision over inference."""


def _dossier_context(dossier: ResearchDossier) -> str:
    citations = "\n".join(f"- [{c.doc_id}] \"{c.quote}\"" for c in dossier.citations)
    return (
        f"Summary: {dossier.summary}\n"
        f"Controversy context: {dossier.controversy_context}\n"
        f"Peer benchmark notes: {dossier.peer_benchmark_notes}\n"
        f"Engagement history: {dossier.engagement_history_summary}\n"
        f"Citations available for reuse:\n{citations or '(none)'}"
    )


async def draft_outreach_letter(
    company_name: str,
    issue: EngagementIssue,
    dossier: ResearchDossier,
    recipient: str,
    llm: LLMClient,
    house_style_notes: str = "",
) -> tuple[OutreachLetterDraft, LLMUsage]:
    prompt = (
        f"Company: {company_name}\nIssue theme: {issue.theme}\nRecipient: {recipient}\n\n"
        f"Dossier:\n{_dossier_context(dossier)}\n\n"
        + (f"House style notes: {house_style_notes}\n" if house_style_notes else "")
    )
    return await llm.complete_structured(system=_LETTER_SYSTEM, prompt=prompt, output_model=OutreachLetterDraft)


async def draft_talking_points(
    company_name: str, issue: EngagementIssue, dossier: ResearchDossier, llm: LLMClient
) -> tuple[MeetingTalkingPoints, LLMUsage]:
    prompt = f"Company: {company_name}\nIssue theme: {issue.theme}\n\nDossier:\n{_dossier_context(dossier)}"
    return await llm.complete_structured(system=_TALKING_POINTS_SYSTEM, prompt=prompt, output_model=MeetingTalkingPoints)


async def draft_meeting_summary(
    company_name: str, issue: EngagementIssue, notes_or_transcript: str, llm: LLMClient
) -> tuple[MeetingSummaryDraft, LLMUsage]:
    prompt = f"Company: {company_name}\nIssue theme: {issue.theme}\n\nMeeting notes/transcript:\n{notes_or_transcript}"
    return await llm.complete_structured(system=_SUMMARY_SYSTEM, prompt=prompt, output_model=MeetingSummaryDraft)
