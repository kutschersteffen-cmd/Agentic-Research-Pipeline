import asyncio
import hashlib
import json

import pytest

from arp.llm.base import LLMUsage
from arp.pageindex import tree as T


class FakeLLM:
    def __init__(self, starts, title="P", raise_on_tree=False):
        self.starts, self.title, self.raise_on_tree, self.calls = starts, title, raise_on_tree, 0

    async def complete_structured(self, *, system, prompt, output_model, **_):
        self.calls += 1
        if self.raise_on_tree:
            raise RuntimeError("boom")
        if output_model is T.SectionList:
            secs = [{"title": f"{self.title}{s}" if self.title == "P" else self.title, "start_page": s, "level": lvl}
                    for s, lvl in self.starts]
            return T.SectionList(sections=secs), LLMUsage()
        return T.Summary(summary="sum"), LLMUsage()


def build(pages, starts):
    return asyncio.run(T.build_tree(pages, FakeLLM(starts)))[0]


def ranges(nodes):
    return [(n.title, n.start_page, n.end_page) for n in nodes]


def test_one_section_per_page():
    assert ranges(build(["a", "b", "c"], [(1, 1), (2, 1), (3, 1)])) == [("P1", 1, 1), ("P2", 2, 2), ("P3", 3, 3)]


def test_front_matter():
    assert ranges(build(["a", "b", "c"], [(2, 1), (3, 1)]))[0] == ("Front matter", 1, 1)


def test_leaves_cover_all_pages():
    tree = build(["x"] * 6, [(1, 1), (2, 2), (4, 2), (5, 1)])
    covered = [p for leaf in T.leaves(tree) for p in range(leaf.start_page, leaf.end_page + 1)]
    assert covered == [1, 2, 3, 4, 5, 6]
    assert tree[0].start_page == 1 and tree[0].end_page == 4 and len(tree[0].children) == 3


def test_bad_starts_clamped():
    assert ranges(build(["a", "b", "c"], [(5, 1), (2, 1), (2, 1), (99, 1)])) == [
        ("Front matter", 1, 1), ("P2", 2, 2), ("P5", 3, 3)]


def test_empty_text():
    assert ranges(build(["", "", ""], [])) == [("Front matter", 1, 3)]


@pytest.fixture
def pdf(tmp_path, monkeypatch):
    p = tmp_path / "f.pdf"
    p.write_bytes(b"one")
    monkeypatch.setattr(T, "page_texts", lambda _p: ["a", "b", "c"])
    return p


def _cache(p):
    return json.loads((p.parent / f"{p.name}.pageindex.json").read_text())


def test_cache_reused(pdf):
    asyncio.run(T.load_or_build_tree(pdf, FakeLLM([(1, 1)])))
    tree, _ = asyncio.run(T.load_or_build_tree(pdf, FakeLLM([], raise_on_tree=True)))
    assert tree[0].title == "P1"
    assert _cache(pdf)["sha256"] == hashlib.sha256(b"one").hexdigest()


def test_cache_rebuilt_on_change(pdf):
    asyncio.run(T.load_or_build_tree(pdf, FakeLLM([(1, 1)])))
    pdf.write_bytes(b"two")
    tree, _ = asyncio.run(T.load_or_build_tree(pdf, FakeLLM([(1, 1)], title="Changed")))
    assert _cache(pdf)["sha256"] == hashlib.sha256(b"two").hexdigest()
    assert all(n.title == "Changed" for n in tree)


def test_cache_rebuilt_on_prompt_version(pdf):
    asyncio.run(T.load_or_build_tree(pdf, FakeLLM([(1, 1)])))
    c = pdf.parent / f"{pdf.name}.pageindex.json"
    data = json.loads(c.read_text())
    data["prompt_version"] = "old"
    c.write_text(json.dumps(data))
    tree, _ = asyncio.run(T.load_or_build_tree(pdf, FakeLLM([(1, 1)], title="Changed")))
    assert all(n.title == "Changed" for n in tree)
