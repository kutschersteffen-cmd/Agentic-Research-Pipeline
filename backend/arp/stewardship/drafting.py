"""Stage 3 drafting: outreach drafts with an interaction type (E6) and a style
check (E8), approved at the checkpoint (stage 5) before anything is sent.

- The tool *proposes* the interaction type from the text and the engagement's
  ladder step (deterministic; no model), and a person can change it.
- Every draft is approved by someone other than its author. Approving a draft
  with open style flags needs a note saying why they stay.
- Marking a draft sent logs it as correspondence on the engagement, with its
  interaction type; an engagement still at `identified` moves to `contacted`.
  Drafts are never edited after approval: edit means back to draft.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from arp.schemas.common import new_id, now_iso
from arp.schemas.engagement import (
    ESCALATION_ORDER,
    CorrespondenceEntry,
    CorrespondenceType,
    EngagementIssue,
    EscalationStage,
    InteractionType,
    MilestoneStage,
)
from arp.stewardship.style import check
from arp.storage.atomic_io import atomic_write_text
from arp.storage.engagement_store import EngagementStore

# Wording that asks for something under a consequence, or names an escalation lever.
PRESSURE = re.compile(
    r"\b(vote against|voting against|escalat\w*|public(ly)? statement|file (a|an) (shareholder )?resolution|"
    r"co-?file|unless|we expect .{0,60}\bby\b|deadline|consequences?)\b",
    re.IGNORECASE,
)
PRESSURE_STEP = ESCALATION_ORDER.index(EscalationStage.WRITTEN_ESCALATION_TO_BOARD)


def propose_interaction_type(text: str, issue: EngagementIssue) -> tuple[InteractionType, str]:
    """The proposed E6 tag and why. Pressure wording, or an engagement already at
    written escalation to the board or beyond, makes it advocacy/pressure."""
    m = PRESSURE.search(text)
    if m:
        return InteractionType.ADVOCACY_PRESSURE, f"Pressure wording: '{m.group(0)}'"
    if ESCALATION_ORDER.index(issue.escalation_stage) >= PRESSURE_STEP:
        return InteractionType.ADVOCACY_PRESSURE, f"Engagement at {issue.escalation_stage.value.replace('_', ' ')}"
    return InteractionType.INFORMATIONAL, "No pressure wording, engagement below written escalation"


class DraftStore:
    """One JSON file per draft."""

    def __init__(self, root: Path) -> None:
        self.root = root / "drafts"

    def _path(self, draft_id: str) -> Path:
        if not re.fullmatch(r"drf_[a-z0-9]+", draft_id):
            raise KeyError(draft_id)
        return self.root / f"{draft_id}.json"

    def get(self, draft_id: str) -> dict:
        path = self._path(draft_id)
        if not path.exists():
            raise KeyError(draft_id)
        return json.loads(path.read_text())

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        return sorted((json.loads(p.read_text()) for p in self.root.glob("drf_*.json")), key=lambda d: d["created_at"])

    def save(self, draft: dict) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._path(draft["draft_id"]), json.dumps(draft, indent=2, ensure_ascii=False))
        return draft


def _issue(engagements: EngagementStore, company_id: str, issue_id: str):
    record = engagements.get(company_id)
    issue = next((i for i in record.issues if i.issue_id == issue_id), None) if record else None
    if issue is None:
        raise KeyError(f"{company_id}/{issue_id}")
    return record, issue


def create(
    store: DraftStore,
    engagements: EngagementStore,
    blocklist: dict,
    *,
    company_id: str,
    issue_id: str,
    type: CorrespondenceType,
    text: str,
    created_by: str,
    interaction_type: InteractionType | None = None,
) -> dict:
    if not created_by.strip() or not text.strip():
        raise ValueError("A draft needs text and created_by")
    record, issue = _issue(engagements, company_id, issue_id)
    proposed, why = propose_interaction_type(text, issue)
    now = now_iso()
    return store.save(
        {
            "draft_id": new_id("drf"),
            "company_id": company_id,
            "company": record.name,
            "issue_id": issue_id,
            "theme": issue.theme,
            "type": type.value,
            "text": text,
            "proposed_interaction_type": proposed.value,
            "proposed_because": why,
            "interaction_type": (interaction_type or proposed).value,
            "style_flags": check(text, blocklist),
            "status": "draft",
            "created_by": created_by,
            "created_at": now,
            "history": [{"at": now, "by": created_by, "action": "created"}],
        }
    )


def update(
    store: DraftStore,
    engagements: EngagementStore,
    blocklist: dict,
    draft_id: str,
    *,
    updated_by: str,
    text: str | None = None,
    interaction_type: InteractionType | None = None,
) -> dict:
    """Edits the text (an approved draft goes back to draft, and the editor becomes
    an author) or changes the tag (a retag, which the approver may do)."""
    draft = store.get(draft_id)
    if draft["status"] == "sent":
        raise ValueError("A sent draft cannot change")
    if not updated_by.strip():
        raise ValueError("An edit needs updated_by")
    _, issue = _issue(engagements, draft["company_id"], draft["issue_id"])
    if text is not None:
        proposed, why = propose_interaction_type(text, issue)
        draft |= {
            "text": text,
            "style_flags": check(text, blocklist),
            "proposed_interaction_type": proposed.value,
            "proposed_because": why,
        }
    if interaction_type is not None:
        draft["interaction_type"] = interaction_type.value
    if text is not None or draft["status"] == "approved":  # any change to an approved draft needs a new approval
        draft["status"] = "draft"
        draft.pop("approved_by", None)
    action = "edited" if text is not None else "retagged"  # the checkpoint may retag without becoming an author
    draft["history"].append({"at": now_iso(), "by": updated_by, "action": action})
    return store.save(draft)


def approve(store: DraftStore, draft_id: str, approved_by: str, note: str = "") -> dict:
    draft = store.get(draft_id)
    if draft["status"] != "draft":
        raise ValueError(f"Only a draft can be approved (this one is {draft['status']})")
    if not approved_by.strip():
        raise ValueError("Approving needs approved_by")
    authors = {h["by"].strip().lower() for h in draft["history"] if h["action"] in ("created", "edited")}
    if approved_by.strip().lower() in authors:
        raise ValueError("Four-eyes rule: outreach is approved by someone who did not write or edit it")
    if draft["style_flags"] and not note.strip():
        raise ValueError(
            f"{len(draft['style_flags'])} style flags are open: rewrite, or approve with a note saying why they stay"
        )
    draft |= {"status": "approved", "approved_by": approved_by}
    draft["history"].append({"at": now_iso(), "by": approved_by, "action": "approved", "note": note})
    return store.save(draft)


def mark_sent(store: DraftStore, engagements: EngagementStore, draft_id: str, sent_by: str) -> dict:
    draft = store.get(draft_id)
    if draft["status"] != "approved":
        raise ValueError("Only an approved draft can be sent")
    if not sent_by.strip():
        raise ValueError("Sending needs sent_by")
    _, issue = _issue(engagements, draft["company_id"], draft["issue_id"])
    engagements.add_correspondence(
        draft["company_id"],
        draft["issue_id"],
        CorrespondenceEntry(
            type=CorrespondenceType(draft["type"]),
            summary=draft["text"][:2000],
            doc_ref=f"draft:{draft_id}",
            logged_by=sent_by,
            interaction_type=InteractionType(draft["interaction_type"]),
        ),
    )
    if issue.milestone_stage == MilestoneStage.IDENTIFIED:
        engagements.set_milestone_stage(
            draft["company_id"], draft["issue_id"], MilestoneStage.CONTACTED, reason=f"Outreach sent by {sent_by}."
        )
    draft["status"] = "sent"
    draft["history"].append({"at": now_iso(), "by": sent_by, "action": "sent"})
    return store.save(draft)
