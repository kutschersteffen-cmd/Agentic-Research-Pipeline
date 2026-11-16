"""rfp-approved-answers-first-design: approved answers first, the second model's check, the comparison (unit rows)."""

from __future__ import annotations

from sqlalchemy import update

from arp.db import models as m
from arp.db.session import transaction
from arp.rfp.draft import Cited, DraftOut, FactCheck
from tests import rfp_fixtures as fx
from tests import test_rfp_api as api
from tests.test_rfp_api import FIRM, Standin, _entry_id, _import

env = api.env  # the fixture

Q_FIRM = "Please describe your firm."
ASSET = "Example AM is an independent asset manager founded in 2004."


def d_asset(**kw) -> DraftOut:
    return DraftOut(answer=ASSET, citations=[Cited(entry_id=_entry_id(FIRM), quote="founded in 2004")], **kw)


def one_question(env, question, draft, check=None):
    """A project from rfp_one.xlsx whose one question the stand-in drafts with `draft`; returns the question's JSON."""
    env.llm = Standin(questions=[("RFP!A1", question, "RFP!B1")], drafts={question: draft} if draft else None)
    env.llm.check = check or FactCheck()
    r = env.as_("alice").post("/api/rfp/projects", data={"investor": "Pension Fund"},
                              files={"file": ("rfp_one.xlsx", fx.rfp_one_xlsx(question))})
    assert r.status_code == 200, r.text
    env.run_jobs()
    project = env.as_("bob").get(f"/api/rfp/projects/{r.json()['id']}").json()
    assert project["run_status"] == "done"
    return project["questions"][0] | {"project_id": project["id"]}


def put_answer(env, q, answer):
    r = env.as_("bob").put(f"/api/rfp/projects/{q['project_id']}/questions/{q['id']}", json={"answer": answer})
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["questions"] if x["id"] == q["id"])


def unchanged(env, tmp_path, check=None):
    _import(tmp_path)
    return one_question(env, Q_FIRM, DraftOut(use_entry=_entry_id(FIRM)), check)


def no_source(q):
    return (q["status"], q["answer"]) == ("no source", "")


# --- drafting -----------------------------------------------------------------------------------


def test_ac_1_use_entry_copies_the_approved_answer(env, tmp_path):
    q = unchanged(env, tmp_path)
    assert (q["status"], q["answer"]) == ("drafted", FIRM)


def test_ac_2_unchanged_answer_fields(env, tmp_path):
    q = unchanged(env, tmp_path)
    assert (q["base_entry_id"], q["kept_share"], q["document_priority"]) == (_entry_id(FIRM), 100, 0)
    assert q["segments"] == [{"text": FIRM, "change": "kept"}]


def test_ac_3_use_entry_source_is_the_whole_answer(env, tmp_path):
    q = unchanged(env, tmp_path)
    assert [(s["kind"], s["entry_id"], s["quote"]) for s in q["sources"]] == [("entry", _entry_id(FIRM), FIRM)]


def test_ac_4_use_entry_unknown_id(env, tmp_path):
    _import(tmp_path)
    assert no_source(one_question(env, Q_FIRM, DraftOut(use_entry=999999)))


def test_ac_5_changed_answer_kept_share(env, tmp_path):
    _import(tmp_path)
    q = one_question(env, Q_FIRM, d_asset())
    assert (q["status"], q["base_entry_id"], q["kept_share"]) == ("drafted", _entry_id(FIRM), 90)


def test_ac_6_changed_answer_segments(env, tmp_path):
    _import(tmp_path)
    q = one_question(env, Q_FIRM, d_asset())
    assert q["segments"] == [{"text": "Example AM is an independent", "change": "kept"}, {"text": "asset", "change": "added"},
                             {"text": "manager founded in 2004.", "change": "kept"}]


def test_ac_9_missing_parts(env, tmp_path):
    _import(tmp_path)
    assert no_source(one_question(env, Q_FIRM, d_asset(missing=["the firm's size"])))


def test_ac_10_second_model_unsupported(env, tmp_path):
    _import(tmp_path)
    assert no_source(one_question(env, Q_FIRM, d_asset(), FactCheck(unsupported=["asset manager"])))


def test_ac_11_second_model_unanswered(env, tmp_path):
    assert no_source(unchanged(env, tmp_path, FactCheck(unanswered=["the firm's size"])))


def test_ac_47_unsupported_fails_an_unchanged_answer(env, tmp_path):
    assert no_source(unchanged(env, tmp_path, FactCheck(unsupported=["x"])))


def test_second_model_sees_question_sources_and_draft(env, tmp_path):
    prompts = []
    _import(tmp_path)
    check = FactCheck()

    class Recording(Standin):
        async def complete_structured(self, *, system, prompt, output_model, **kw):
            if output_model is FactCheck:
                prompts.append(prompt)
            return await super().complete_structured(system=system, prompt=prompt, output_model=output_model, **kw)

    env.llm = Recording(questions=[("RFP!A1", Q_FIRM, "RFP!B1")], drafts={Q_FIRM: d_asset()})
    env.llm.check = check
    env.as_("alice").post("/api/rfp/projects", data={"investor": "P"}, files={"file": ("rfp_one.xlsx", fx.rfp_one_xlsx(Q_FIRM))})
    env.run_jobs()
    assert prompts == [f"Question: {Q_FIRM}\n\nSources:\n\n[E{_entry_id(FIRM)}] {FIRM}\n\nDraft: {ASSET}"]


def test_citation_to_an_entry_not_shown_fails_the_step(env, tmp_path):
    _import(tmp_path)
    draft = DraftOut(answer=ASSET, citations=[Cited(entry_id=999999, quote="founded in 2004")])
    assert no_source(one_question(env, Q_FIRM, draft))


def test_citation_with_neither_id_fails_the_step(env, tmp_path):
    _import(tmp_path)
    assert no_source(one_question(env, Q_FIRM, DraftOut(answer=ASSET, citations=[Cited(quote="founded in 2004")])))


def test_citation_with_both_ids_fails_the_step(env, tmp_path):
    _import(tmp_path)
    draft = DraftOut(answer=ASSET, citations=[Cited(entry_id=_entry_id(FIRM), document_id=1, quote="founded in 2004")])
    assert no_source(one_question(env, Q_FIRM, draft))


def test_base_entry_id_names_a_cited_entry_or_falls_back_to_the_first(env, tmp_path):
    _import(tmp_path)
    q = one_question(env, Q_FIRM, d_asset(base_entry_id=999999))
    assert q["base_entry_id"] == _entry_id(FIRM)


# --- what the API returns -----------------------------------------------------------------------


def test_ac_7_edit_keeps_the_base_entry(env, tmp_path):
    q = put_answer(env, unchanged(env, tmp_path), ASSET)
    assert (q["status"], q["base_entry_id"], q["kept_share"]) == ("edited", _entry_id(FIRM), 90)


def test_ac_8_hand_written_answer_has_no_base(env, tmp_path):
    _import(tmp_path)
    q = put_answer(env, one_question(env, Q_FIRM, None), "We do not lend securities.")
    assert (q["base_entry_id"], q["kept_share"], q["segments"], q["document_priority"]) == (None, None, [], None)


def test_ac_14_source_without_kind_reads_as_entry(env, tmp_path):
    _import(tmp_path)
    q = one_question(env, Q_FIRM, None)
    with transaction() as s:
        s.execute(update(m.RfpQuestion).where(m.RfpQuestion.id == q["id"])
                  .values(sources=[{"entry_id": _entry_id(FIRM), "quote": "x"}]))
    r = env.as_("bob").get(f"/api/rfp/projects/{q['project_id']}")
    assert r.status_code == 200
    assert [s["kind"] for s in r.json()["questions"][0]["sources"]] == ["entry"]


def test_ac_45_removed_word_segments(env, tmp_path):
    q = put_answer(env, unchanged(env, tmp_path), "Example AM is an manager founded in 2004.")
    assert q["kept_share"] == 89
    assert q["segments"] == [{"text": "Example AM is an", "change": "kept"}, {"text": "independent", "change": "removed"},
                             {"text": "manager founded in 2004.", "change": "kept"}]


def test_ac_58_rounds_half_up(env, tmp_path):
    q = put_answer(env, unchanged(env, tmp_path), "Example AM has been managing money for pension funds.")
    assert q["kept_share"] == 13


def test_base_entry_retired_still_compares(env, tmp_path):
    q = unchanged(env, tmp_path)
    assert env.as_("bob").post(f"/api/rfp/library/{_entry_id(FIRM)}/retire").status_code == 200
    q = env.as_("bob").get(f"/api/rfp/projects/{q['project_id']}").json()["questions"][0]
    assert (q["base_entry_id"], q["kept_share"]) == (_entry_id(FIRM), 100)
