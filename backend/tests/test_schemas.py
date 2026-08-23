import pytest
from pydantic import ValidationError

from arp.schemas.arbitration import ArbitrationContribution, ArbitrationResult
from arp.schemas.common import Citation, DocType, JobStatus, RunManifest
from arp.schemas.datapoints import DataPointSchema, ExtractedField, FieldDataType, FieldDefinition
from arp.schemas.results_diff import MatchDiffEntry, ResultsDiff
from arp.schemas.thematic import ActivityDefinition, ActivityTier, CompanyMatch, CompanyRole, ExposureEstimate, LifecycleStage, MatchVerdict


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


def test_activity_definition_defaults_core_tier_and_unapproved():
    activity = ActivityDefinition(
        name="EV manufacturing",
        in_scope_description="Designs/manufactures battery electric vehicles.",
        out_of_scope_description="Traditional ICE-only vehicle manufacturing.",
    )
    assert activity.tier == ActivityTier.CORE
    assert activity.lifecycle_stage is None
    assert activity.criticality_flag is False
    assert activity.human_approved is False


def test_human_approved_requires_source_citation():
    with pytest.raises(ValidationError):
        ActivityDefinition(
            name="EV manufacturing",
            in_scope_description="Designs and manufactures battery electric vehicles for consumer and fleet markets.",
            out_of_scope_description="Traditional ICE-only vehicle manufacturing.",
            human_approved=True,
        )


def test_human_approved_requires_substantive_rationale():
    citation = Citation(doc_id="d1", doc_type=DocType.OTHER, quote="Manufactures battery electric vehicles.")
    with pytest.raises(ValidationError):
        ActivityDefinition(
            name="EV manufacturing",
            in_scope_description="Makes BEVs.",  # under 15 words
            out_of_scope_description="Traditional ICE-only vehicle manufacturing.",
            source_citation=citation,
            human_approved=True,
        )


def test_human_approved_succeeds_with_citation_and_real_rationale():
    citation = Citation(doc_id="d1", doc_type=DocType.OTHER, quote="Manufactures battery electric vehicles.")
    activity = ActivityDefinition(
        name="EV manufacturing",
        in_scope_description="Designs and manufactures battery electric vehicles for consumer and fleet markets, "
        "including the powertrains and battery packs used in them.",
        out_of_scope_description="Traditional ICE-only vehicle manufacturing.",
        source_citation=citation,
        human_approved=True,
        tier=ActivityTier.CORE,
        lifecycle_stage=LifecycleStage.COMMERCIALIZATION,
    )
    assert activity.human_approved is True
    restored = ActivityDefinition.model_validate_json(activity.model_dump_json())
    assert restored == activity


def test_company_match_arbitration_defaults_to_none():
    match = CompanyMatch(
        company_id="c1", name="Acme Motors", activity_id="act1", activity_name="EV manufacturing",
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.SIGNIFICANT, confidence=0.8,
        adjudicator_rationale="x",
    )
    assert match.arbitration is None


def test_arbitration_result_roundtrips_json():
    result = ArbitrationResult(
        composite_score=0.62,
        methods_disagree=False,
        disagreement_spread=0.21,
        mid_band=True,
        contributions=[ArbitrationContribution(method="qualitative_debate", signal=0.6, weight=0.6, detail="significant")],
        rationale="Combined 1 signal(s): qualitative_debate (0.60, weight 0.60). Composite 0.62.",
    )
    restored = ArbitrationResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_company_match_company_role_defaults_to_none():
    match = CompanyMatch(
        company_id="c1", name="Acme Motors", activity_id="act1", activity_name="EV manufacturing",
        verdict=MatchVerdict.INCLUDE, exposure_estimate=ExposureEstimate.SIGNIFICANT, confidence=0.8,
        adjudicator_rationale="x", company_role=CompanyRole.PURE_PLAYER,
    )
    assert match.company_role == CompanyRole.PURE_PLAYER
    restored = CompanyMatch.model_validate_json(match.model_dump_json())
    assert restored == match


def test_results_diff_roundtrips_json():
    diff = ResultsDiff(
        run_id_a="run_a", run_id_b="run_b", added=["c3:act1"], dropped=["c1:act1"],
        verdict_changed=[
            MatchDiffEntry(
                key="c2:act1", company_id="c2", activity_id="act1", change="verdict_changed",
                old_verdict=MatchVerdict.EXCLUDE, new_verdict=MatchVerdict.INCLUDE, old_confidence=0.5, new_confidence=0.9,
            )
        ],
        confidence_changed=[], unchanged_count=3,
    )
    restored = ResultsDiff.model_validate_json(diff.model_dump_json())
    assert restored == diff
