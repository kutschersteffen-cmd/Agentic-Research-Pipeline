import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from arp.cli.taxonomy import taxonomy_app
from arp.schemas.authority_taxonomy import Criterion, Definition, SectorCode, SourceCitation, Technology, Threshold, merge_key
from arp.schemas.taxonomy import Taxonomy
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.taxonomy_store import TaxonomyStore

FIXTURES = Path(__file__).parent / "fixtures" / "authority_taxonomy"
NEW_ACTIVITY_FIELDS = {
    "value_chain_role": "core", "criteria": [], "citations": [], "out_of_scope_citations": [], "sector_codes": [],
}
NEW_THEME_FIELDS = {"scope": "", "technologies": [], "definitions": [], "thresholds": [], "checklist_report": {}}


def test_old_taxonomy_json_loads():
    taxonomy = Taxonomy.model_validate_json((FIXTURES / "saved_taxonomy_old.json").read_text())
    for field, default in NEW_THEME_FIELDS.items():
        assert getattr(taxonomy.theme, field) == default
    for activity in taxonomy.theme.activities:
        for field, default in NEW_ACTIVITY_FIELDS.items():
            assert getattr(activity, field) == default


def test_merge_key():
    assert merge_key("Electrolyser stack manufacturing") == merge_key("electrolyser-stack  manufacturing")
    assert merge_key("Co-generation") == merge_key("Cogeneration")


def test_new_fields_round_trip():
    cite = SourceCitation(quote="q", source_url="https://e.org")
    activity = ActivityDefinition(
        name="A", in_scope_description="x", out_of_scope_description="y", value_chain_role="upstream",
        criteria=[Criterion(text="c", citations=[cite])], citations=[cite], out_of_scope_citations=[cite],
        sector_codes=[SectorCode(system="NACE", code="C28", origin="source")],
    )
    theme = ThemeDefinition(
        name="T", description="d", activities=[activity], scope="s", technologies=[Technology(name="n", citations=[cite])],
        definitions=[Definition(term="t", text="x", citations=[cite])], thresholds=[Threshold(text="t")],
        checklist_report={"a": {"b": "found"}},
    )
    assert ThemeDefinition.model_validate_json(theme.model_dump_json()) == theme


def test_invalid_value_chain_role_raises():
    with pytest.raises(ValidationError):
        ActivityDefinition(name="A", in_scope_description="x", out_of_scope_description="y", value_chain_role="downstream")


def test_show_unchanged(tmp_path):
    d = tmp_path / "tax_a"
    d.mkdir()
    (d / "v1.json").write_text((FIXTURES / "saved_taxonomy_old.json").read_text())
    (d / "latest.json").write_text('{"latest_version": 1}')
    store = TaxonomyStore(tmp_path)
    with patch("arp.cli.taxonomy._taxonomy_store", lambda: store):
        result = CliRunner().invoke(taxonomy_app, ["show", "tax_a"])
    assert result.exit_code == 0
    shown = json.loads(result.stdout)
    # The only difference from main is the new fields, all at their defaults.
    for key, default in NEW_THEME_FIELDS.items():
        assert shown["theme"].pop(key) == default
    for activity in shown["theme"]["activities"]:
        for key, default in NEW_ACTIVITY_FIELDS.items():
            assert activity.pop(key) == default
    assert shown == json.loads((FIXTURES / "expected_main" / "show_stdout.json").read_text())
