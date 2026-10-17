from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from arp.checks.rules import rule_sentence
from arp.schemas.rules import FieldRule
from tests.rules_fixtures import schema_f

ENTRIES = json.loads((Path(__file__).parent / "fixtures" / "rule_sentences.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("entry", ENTRIES, ids=[f"{e['rule']['rule_id']}-{i}" for i, e in enumerate(ENTRIES)])
def test_sentences_match_fixture(entry: dict) -> None:  # AC-31
    rule = TypeAdapter(FieldRule).validate_python(entry["rule"])
    assert rule_sentence(rule, entry["field_id"], schema_f()) == entry["sentence"]
