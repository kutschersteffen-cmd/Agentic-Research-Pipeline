import pytest
from pydantic import ValidationError

from arp.schemas.common import Citation, DocType, JobStatus, RunManifest
from arp.schemas.datapoints import DataPointSchema, ExtractedField, FieldDataType, FieldDefinition
from arp.schemas.thematic import ActivityDefinition, ExposureEstimate, MatchVerdict


def test_citation_defaults_ungrounded_until_checked():
    c = Citation(doc_id="d1", doc_type=DocType.OTHER, quote="hello")
    assert c.grounded is False


def test_run_manifest_defaults_to_pending():
    m = RunManifest(run_id="r1", run_type="theme")
    assert m.status == JobStatus.PENDING
    assert m.completed_count == 0


def test_verdict_enum_coerces_from_string():
    assert MatchVerdict("include") == MatchVerdict.INCLUDE
    with pytest.raises(ValueError):
        MatchVerdict("maybe")


def test_extracted_field_confidence_bounds_enforced():
    field = ExtractedField(field_id="f1", field_name="green_capex", value=1.0, confidence=0.5)
    assert field.confidence == 0.5
    with pytest.raises(ValidationError):
        ExtractedField(field_id="f1", field_name="green_capex", value=1.0, confidence=1.5)


def test_field_definition_requires_name_and_type():
    with pytest.raises(ValidationError):
        FieldDefinition(name="x")  # missing data_type/description/extraction_instructions


def test_data_point_schema_holds_fields():
    schema = DataPointSchema(
        name="Green Capex",
        fields=[
            FieldDefinition(
                name="green_capex_usd_m",
                description="Green capex in USD millions",
                data_type=FieldDataType.CURRENCY_AMOUNT,
                extraction_instructions="Find the disclosed green capex figure.",
            )
        ],
    )
    assert len(schema.fields) == 1
    assert schema.fields[0].data_type == FieldDataType.CURRENCY_AMOUNT


def test_activity_definition_roundtrips_json():
    activity = ActivityDefinition(
        name="EV manufacturing",
        in_scope_description="Designs/manufactures battery electric vehicles.",
        out_of_scope_description="Traditional ICE-only vehicle manufacturing.",
        seed_keywords=["electric vehicle", "EV"],
    )
    restored = ActivityDefinition.model_validate_json(activity.model_dump_json())
    assert restored == activity


def test_exposure_estimate_values():
    assert set(e.value for e in ExposureEstimate) == {"pure_play", "significant", "minor", "none"}
