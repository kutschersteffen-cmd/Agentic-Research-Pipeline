from arp.research.authority_taxonomy.checklist import INDEX_RULES_CHECKLIST
from arp.research.authority_taxonomy.extract import IndexRuleItem, IndexRulesDraft, StatedRule, extract_source

DOC = ("Index methodology.\n\nEligibility. Companies must have a minimum free-float market capitalisation of "
       "USD 500 million at the review date.\n\nWeighting. No constituent may exceed 8 % of the index.")
SENTENCE = "Companies must have a minimum free-float market capitalisation of USD 500 million at the review date."
_ELIGIBILITY = [i for i in INDEX_RULES_CHECKLIST if i.key == "eligibility"]


def test_checklist_keys():
    assert [i.key for i in INDEX_RULES_CHECKLIST] == ["eligibility", "selection", "weighting", "caps", "rebalance"]


async def test_index_rule_quote_is_document_span(fake_llm):
    # the model's quote differs in spacing and case; the stored quote is what the document says
    off = SENTENCE.replace(" USD 500", "  usd 500")
    llm = fake_llm({"IndexRulesDraft": [IndexRulesDraft(rules=[IndexRuleItem(text=off, quote=off)])]})
    out = await extract_source("m.txt", DOC, theme_name="fund", scope="", value_chain=False, llm=llm,
                               checklist=_ELIGIBILITY)
    assert out.rules == [StatedRule(kind="eligibility", text=off, quote=SENTENCE, source="m.txt")]
    assert out.report == {"eligibility": "found"}


async def test_changed_number_does_not_ground(fake_llm):
    off = SENTENCE.replace("500", "600")
    llm = fake_llm({"IndexRulesDraft": [IndexRulesDraft(rules=[IndexRuleItem(text=off, quote=off)])]})
    out = await extract_source("m.txt", DOC, theme_name="fund", scope="", value_chain=False, llm=llm,
                               checklist=_ELIGIBILITY)
    assert out.rules == []


async def test_ungrounded_rule_dropped(fake_llm):  # AC-46
    q = "Companies must be headquartered on the Moon."
    llm = fake_llm({"IndexRulesDraft": [IndexRulesDraft(rules=[IndexRuleItem(text=q, quote=q)])]})
    out = await extract_source("m.txt", DOC, theme_name="fund", scope="", value_chain=False, llm=llm,
                               checklist=_ELIGIBILITY)
    assert out.rules == []
    assert out.report == {"eligibility": "not_in_source"}
