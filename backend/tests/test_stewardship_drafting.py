from __future__ import annotations

import pytest

from arp.schemas.engagement import CorrespondenceType, EscalationStage, InteractionType, MilestoneStage
from arp.stewardship import drafting
from arp.stewardship.policies import PolicyStore
from arp.stewardship.style import check, load_blocklist
from arp.storage.engagement_store import EngagementStore

BLOCKLIST = load_blocklist()


def test_style_check_flags_whole_phrases_with_their_place_and_never_changes_the_text():
    text = "Dear Chair,\nThanks to our  engagement you are now Paris-aligned. We controlled nothing."
    flags = check(text, BLOCKLIST)
    assert [(f["match"], f["line"], f["category"]) for f in flags] == [
        ("Thanks to our  engagement", 2, "overclaiming"),
        ("Paris-aligned", 2, "regulated_term"),
    ]  # "We controlled" is not "we control"
    assert text[flags[0]["start"] : flags[0]["end"]] == flags[0]["match"]


def test_blocklist_is_a_versioned_policy_that_rejects_bad_entries(tmp_path):
    store = PolicyStore(tmp_path)
    with pytest.raises(ValueError, match="category"):
        store.save("phrase_blocklist", {"phrases": [{"phrase": "x", "category": "rude"}]}, "", "Designer", {})
    with pytest.raises(ValueError, match="Duplicate"):
        store.save(
            "phrase_blocklist",
            {"phrases": [{"phrase": "X", "category": "other"}, {"phrase": "x", "category": "other"}]},
            "",
            "D",
            {},
        )


@pytest.fixture
def setup(tmp_path):
    engagements = EngagementStore(tmp_path / "e")
    _, issue = engagements.open_issue("ACME", "Acme", theme="climate_transition")
    return drafting.DraftStore(tmp_path / "s"), engagements, issue


def _create(setup, text, **kw):
    store, engagements, issue = setup
    return drafting.create(
        store,
        engagements,
        BLOCKLIST,
        company_id="ACME",
        issue_id=issue.issue_id,
        type=CorrespondenceType.LETTER,
        text=text,
        created_by="Writer",
        **kw,
    )


def test_interaction_type_is_proposed_from_wording_and_ladder_step(setup):
    assert _create(setup, "We would welcome a call on your transition plan.")["interaction_type"] == "informational"
    pressure = _create(setup, "Unless the board sets a target, we will vote against the chair.")
    assert pressure["interaction_type"] == "advocacy_pressure" and "unless" in pressure["proposed_because"].lower()
    store, engagements, issue = setup
    engagements.set_escalation_stage("ACME", issue.issue_id, EscalationStage.WRITTEN_ESCALATION_TO_BOARD, "Lead")
    assert _create(setup, "Please find our letter attached.")["interaction_type"] == "advocacy_pressure"
    overridden = _create(setup, "A plain note.", interaction_type=InteractionType.OTHER)
    assert (overridden["interaction_type"], overridden["proposed_interaction_type"]) == ("other", "advocacy_pressure")


def test_outreach_is_approved_by_a_second_person_before_it_is_sent_and_logged(setup):
    store, engagements, issue = setup
    draft = _create(setup, "Thanks to our engagement last year, we would like to follow up.")
    with pytest.raises(ValueError, match="approved"):
        drafting.mark_sent(store, engagements, draft["draft_id"], "Writer")
    with pytest.raises(ValueError, match="Four-eyes"):
        drafting.approve(store, draft["draft_id"], "writer", "fine")
    with pytest.raises(ValueError, match="style flags"):
        drafting.approve(store, draft["draft_id"], "Lead")
    drafting.approve(store, draft["draft_id"], "Lead", "Quoting the client's own wording")
    sent = drafting.mark_sent(store, engagements, draft["draft_id"], "Writer")
    assert sent["status"] == "sent"
    [issue_now] = engagements.get("ACME").issues
    [entry] = issue_now.correspondence
    assert (entry.interaction_type, entry.doc_ref) == (InteractionType.INFORMATIONAL, f"draft:{draft['draft_id']}")
    assert issue_now.milestone_stage == MilestoneStage.CONTACTED
    with pytest.raises(ValueError):
        drafting.update(store, engagements, BLOCKLIST, draft["draft_id"], updated_by="Writer", text="changed")


def test_editing_an_approved_draft_sends_it_back_and_the_editor_cannot_approve(setup):
    store, engagements, _ = setup
    draft = _create(setup, "A neutral note.")
    drafting.approve(store, draft["draft_id"], "Lead")
    edited = drafting.update(store, engagements, BLOCKLIST, draft["draft_id"], updated_by="Lead", text="A neutral note, edited.")
    assert edited["status"] == "draft" and "approved_by" not in edited
    with pytest.raises(ValueError, match="Four-eyes"):
        drafting.approve(store, draft["draft_id"], "Lead")


def test_the_checkpoint_can_retag_and_still_approve(setup):
    store, engagements, _ = setup
    draft = _create(setup, "A neutral note.")
    drafting.update(
        store, engagements, BLOCKLIST, draft["draft_id"], updated_by="Lead", interaction_type=InteractionType.ADVOCACY_PRESSURE
    )
    approved = drafting.approve(store, draft["draft_id"], "Lead")
    assert (approved["status"], approved["interaction_type"]) == ("approved", "advocacy_pressure")
    retagged = drafting.update(
        store, engagements, BLOCKLIST, draft["draft_id"], updated_by="Lead", interaction_type=InteractionType.OTHER
    )
    assert retagged["status"] == "draft"  # a change after approval needs a new approval
