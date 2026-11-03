from arp.research.authority_taxonomy.extract import SourceExtraction
from arp.research.authority_taxonomy.matching import _MatchReviewDraft, _PairVerdict, keywords, match_activities
from arp.schemas.thematic import ActivityDefinition
from tests.conftest import FakeLLMClient
from tests.test_authority_taxonomy_consolidate import _act, _fake, _run


def _ext(url, *names, seeds=None):
    acts = [_act(n, url) for n in names]
    for a in acts:
        a.seed_keywords = list(seeds or [])
    return SourceExtraction(url=url, activities=acts)


def _with_review(*verdicts) -> FakeLLMClient:
    llm = _fake(10)
    llm._script[_MatchReviewDraft.__name__] = [_MatchReviewDraft(pairs=[_PairVerdict(left=i, right=j, same_activity=s, reason="x") for i, j, s in verdicts])]
    return llm


def _matcher_calls(llm):
    return [p for c, p in zip(llm.calls, llm.prompts, strict=True) if c == _MatchReviewDraft.__name__]


def test_keywords_cut_and_ignored():
    a = ActivityDefinition(name="Manufacture of electrolysers and other equipment", in_scope_description="", out_of_scope_description="", seed_keywords=["Electrolysis", "H2"])
    assert keywords(a) == {"electr"}


async def test_ac8a_exact_match_no_model_call(tmp_path):
    llm = _fake(10)
    await _run([_ext("A", "Electrolyser stack manufacturing"), _ext("B", "electrolyser-stack manufacturing")], tmp_path, llm=llm)
    assert _matcher_calls(llm) == []


async def test_ac8b_model_merge(tmp_path):
    llm = _with_review((0, 0, True))
    theme, _ = await _run([_ext("A", "Fuel cell manufacturing"), _ext("B", "Manufacture of fuel cells and other hydrogen-to-power equipment")], tmp_path, llm=llm)
    assert [a.name for a in theme.activities] == ["Fuel cell manufacturing"]
    assert [c.source_url for c in theme.activities[0].citations] == ["A", "B"]


async def test_ac8b2_one_call_with_scope(tmp_path):
    from arp.research.authority_taxonomy.consolidate import consolidate
    from tests.test_authority_taxonomy_consolidate import _settings
    llm = _with_review((0, 0, True))
    exts = [_ext("A", "Fuel cell manufacturing"), _ext("B", "Manufacture of fuel cells and other hydrogen-to-power equipment")]
    await consolidate(exts, theme_name="h", scope="hydrogen equipment", value_chain=False, settings=_settings(tmp_path), llm=llm, value_chain_model=None)
    calls = _matcher_calls(llm)
    assert len(calls) == 1 and "hydrogen equipment" in calls[0]


async def test_ac8c_model_rejects(tmp_path):
    llm = _with_review((0, 0, False))
    names = ["Fuel cell manufacturing", "Manufacture of fuel cells and other hydrogen-to-power equipment"]
    theme, _ = await _run([_ext("A", names[0]), _ext("B", names[1])], tmp_path, llm=llm)
    assert [a.name for a in theme.activities] == names
    assert [len(a.citations) for a in theme.activities] == [1, 1]


async def test_ac8d_no_shared_keyword_no_call(tmp_path):
    llm = _fake(10)
    theme, _ = await _run([_ext("A", "Manufacture of electrolysers"), _ext("B", "Hydrogen storage tanks")], tmp_path, llm=llm)
    assert [len(a.citations) for a in theme.activities] == [1, 1]
    assert _matcher_calls(llm) == []


async def test_ac8e_ac8f_each_activity_matches_once(tmp_path):
    llm = _with_review((0, 0, True), (0, 1, True))
    theme, _ = await _run([_ext("A", "Electrolyser stacks"), _ext("B", "Electrolysis systems", "Electrolyser modules")], tmp_path, llm=llm)
    got = {a.name: [c.source_url for c in a.citations] for a in theme.activities}
    assert got == {"Electrolyser stacks": ["A", "B"], "Electrolyser modules": ["B"]}
    assert theme.activities[0].citations[1].quote == "Electrolysis systems"
    calls = _matcher_calls(llm)
    assert len(calls) == 1 and "Electrolysis systems" in calls[0] and "Electrolyser modules" in calls[0]


async def test_ac8g_seed_keywords_make_candidate(tmp_path):
    llm = _with_review((0, 0, True))
    a = _ext("A", "Stack assembly", seeds=["electrolyser"])
    theme, _ = await _run([a, _ext("B", "Electrolyser production")], tmp_path, llm=llm)
    assert [x.name for x in theme.activities] == ["Stack assembly"]
    assert [c.source_url for c in theme.activities[0].citations] == ["A", "B"]


async def test_match_methods_and_reasons():
    left = [ActivityDefinition(name="Stacks", in_scope_description="", out_of_scope_description="")]
    right = [ActivityDefinition(name="stacks", in_scope_description="", out_of_scope_description="")]
    m = await match_activities(left, right, scope="", llm=FakeLLMClient({}))
    assert [(x.left, x.right, x.method, x.reason) for x in m] == [(0, 0, "exact", "equal merge key")]


async def test_same_key_within_one_source_merged_without_model(tmp_path):
    llm = _fake(10)
    theme, _ = await _run([_ext("A", "Electrolyser stacks", "Electrolyser stacks")], tmp_path, llm=llm)
    assert [a.name for a in theme.activities] == ["Electrolyser stacks"]
    assert len(theme.activities[0].citations) == 2
    assert _matcher_calls(llm) == []
