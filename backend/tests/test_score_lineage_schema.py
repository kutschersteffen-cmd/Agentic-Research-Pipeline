"""Score lineage, schema: required criteria, the no_score_rows setting, and published rows written before them."""

import pytest
from pydantic import ValidationError

from arp.decision.diffing import describe_changes
from arp.schemas.decision import Criterion, MechanismConfig, PublishedRow


def test_old_config_loads_with_include_and_nothing_required():
    config = MechanismConfig.model_validate(
        {"framework_id": "fw_old", "criteria": [{"column": "x", "dimension_id": "d"}]}
    )
    assert config.no_score_rows == "include"
    assert [c.required for c in config.criteria] == [False]


def test_ac_11_required_is_refused_in_levels_mode():
    with pytest.raises(ValidationError) as exc:
        MechanismConfig(mode="levels", criteria=[Criterion(column="x", dimension_id="d", required=True)])
    assert "required" in str(exc.value)


def test_ac_22_changing_no_score_rows_is_audited():
    v1 = MechanismConfig(framework_id="fw_s")
    v2 = v1.model_copy(update={"no_score_rows": "exclude", "version": 2})
    entries = [e for e in describe_changes(v1, v2, by="Ann") if e.item == "Rows with no score"]
    assert len(entries) == 1
    assert entries[0].origin == "human"


def test_published_row_from_before_has_no_criteria():
    row = PublishedRow.model_validate({"entity_id": "A", "name": "A"})
    assert row.criteria is None
    assert row.reasons == []
