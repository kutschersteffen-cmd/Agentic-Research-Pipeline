"""Regression guards (AC-19..19d): existing taxonomy commands still produce what `main` produced
before the authority-taxonomy schema change. Expected outputs: fixtures/authority_taxonomy/expected_main/README.md."""
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from arp.cli.taxonomy import taxonomy_app
from arp.research.taxonomy_sources.activity_merge import _MergedActivityDraft, _MergedActivityDraftList
from arp.research.taxonomy_sources.authority_extraction import _AuthorityActivityDraft, _AuthorityActivityDraftList
from arp.research.taxonomy_sources.compare import _ComparisonDraft, _DuplicatePairDraft
from arp.storage.taxonomy_store import TaxonomyStore
from tests.test_authority_taxonomy_schema import NEW_ACTIVITY_FIELDS, NEW_THEME_FIELDS

FIXTURES = Path(__file__).parent / "fixtures" / "authority_taxonomy"
EXPECTED = FIXTURES / "expected_main"
URL = "https://example.org/hydrogen.html"
SOURCE_TEXT = "Hydrogen sector overview note electrolyser stack manufacturing, defined as building electrolyser stacks, is key."


def _expected(name: str) -> str:
    return (EXPECTED / name).read_text()


def _normalise(text: str, extra: dict[str, str] | None = None) -> str:
    """Ids (tax_/act_/theme_/doc_ + 12 hex) -> numbered placeholders, ISO timestamps -> <TS>."""
    seen: dict[str, str] = {}

    def number(m: re.Match) -> str:
        return seen.setdefault(m.group(0), f"{m.group(1)}_{len(seen_by_prefix(seen, m.group(1))) + 1:04d}")

    def seen_by_prefix(s, prefix):
        return [k for k in s if k.startswith(prefix + "_")]

    text = re.sub(r"\b(tax|act|theme|doc)_[0-9a-f]{12}\b", number, text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?", "<TS>", text)
    for k, v in (extra or {}).items():
        text = text.replace(k, v)
    return text


def _strip_new_defaults(saved: dict) -> dict:
    """New schema fields must sit at their defaults; drop them so the rest compares exactly."""
    theme = saved["theme"]
    for key, default in NEW_THEME_FIELDS.items():
        assert theme.pop(key) == default
    for activity in theme["activities"]:
        for key, default in NEW_ACTIVITY_FIELDS.items():
            assert activity.pop(key) == default
    return saved


def _seed(store_dir: Path) -> None:
    old = json.loads((FIXTURES / "saved_taxonomy_old.json").read_text())
    b = json.loads(json.dumps(old))
    b.update(taxonomy_id="tax_b", name="B")
    b["theme"].update(theme_id="theme_b", name="B")
    for act, aid, name in zip(b["theme"]["activities"], ("act_fixed3", "act_fixed4"), ("Electric vehicle production", "Battery recycling"), strict=True):
        act.update(activity_id=aid, name=name)
    for tid, data in (("tax_a", old), ("tax_b", b)):
        d = store_dir / tid
        d.mkdir(parents=True)
        (d / "v1.json").write_text(json.dumps(data))
        (d / "latest.json").write_text('{"latest_version": 1}')


@pytest.fixture
def cli(tmp_path, fake_llm):
    store = TaxonomyStore(tmp_path / "taxonomies")
    (tmp_path / "taxonomies").mkdir()

    def run(args, script):
        llm = fake_llm(script)

        async def fake_fetch(url, user_agent, timeout=20.0):
            return SOURCE_TEXT

        with (
            patch("arp.cli.taxonomy._taxonomy_store", lambda: store),
            patch("arp.cli._shared._taxonomy_store", lambda: store),
            patch("arp.cli.taxonomy.get_settings", lambda: SimpleNamespace(discovery_user_agent="test")),
            patch("arp.cli.taxonomy.build_llm_client", lambda s: llm),
            patch("arp.research.taxonomy_sources.authority.fetch_source_text", fake_fetch),
        ):
            result = CliRunner().invoke(taxonomy_app, args)
        assert result.exit_code == 0, result.output
        return result

    run.store_dir = tmp_path / "taxonomies"
    return run


def test_create_authority_source_unchanged(cli):
    draft = _AuthorityActivityDraftList(activities=[_AuthorityActivityDraft(
        name="Electrolyser stack manufacturing", in_scope_description="Building electrolyser stacks.",
        out_of_scope_description="Selling hydrogen.", seed_keywords=["electrolyser"],
        source_quote="electrolyser stack manufacturing, defined as building electrolyser stacks",
    )])
    result = cli(
        ["create", "Hydrogen", "--description", "H2 theme", "--method", "authority_source", "--authority-url", URL],
        {_AuthorityActivityDraftList.__name__: [draft]},
    )
    assert _normalise(result.stdout) == _expected("create_stdout.txt")
    saved_file = next(cli.store_dir.glob("tax_*/v1.json"))
    saved = _strip_new_defaults(json.loads(_normalise(saved_file.read_text())))
    assert saved == json.loads(_expected("create_saved_v1.json"))


def test_compare_unchanged(cli):
    _seed(cli.store_dir)
    draft = _ComparisonDraft(likely_duplicates=[_DuplicatePairDraft(
        activity_a_id="act_fixed1", activity_b_id="act_fixed3", similarity_note="Both EV manufacturing.")])
    result = cli(["compare", "tax_a", "tax_b"], {_ComparisonDraft.__name__: [draft]})
    assert result.stdout == _expected("compare_stdout.json")


def test_merge_unchanged(cli, tmp_path):
    _seed(cli.store_dir)
    draft = _MergedActivityDraftList(
        activities=[
            _MergedActivityDraft(name="EV manufacturing", in_scope_description="x", out_of_scope_description="y"),
            _MergedActivityDraft(name="Grid modernization", in_scope_description="x", out_of_scope_description="y"),
        ],
        merge_notes="Kept both.",
    )
    out = tmp_path / "merged.json"
    result = cli(["merge", "tax_a", "tax_b", "--name", "Merged", "--out", str(out)], {_MergedActivityDraftList.__name__: [draft]})
    assert result.stdout.replace(str(out), "<OUT>") == _expected("merge_stdout.txt")
    theme = _strip_new_defaults({"theme": json.loads(_normalise(out.read_text()))})["theme"]
    assert theme == json.loads(_expected("merge_out_theme.json"))


def test_ratify_unchanged(cli):
    _seed(cli.store_dir)
    result = cli(["ratify", "tax_a", "--by", "Owner"], {})
    assert result.stdout == _expected("ratify_stdout.txt")
    saved = _strip_new_defaults(json.loads(_normalise((cli.store_dir / "tax_a" / "v1.json").read_text())))
    assert saved == json.loads(_expected("ratify_saved_v1.json"))
