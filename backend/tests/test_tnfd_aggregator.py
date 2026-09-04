from arp.extraction.tnfd_aggregator import build_tnfd_record
from arp.extraction.tnfd_extractor_agent import DisclosureDraft, SectorMetricDraft, TNFDExtractionDraft
from arp.extraction.tnfd_verifier_agent import TNFDVerifierOutput
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.schemas.tnfd import ReviewFlag

_QUOTE = "The Board reviews nature-related risks quarterly as part of its risk oversight process."
_DOC = SourceDocument(company_id="acme", doc_type=DocType.SUSTAINABILITY_REPORT, title="Sustainability Report", full_text=_QUOTE)
_DOCS = {_DOC.doc_id: _DOC}
_CITATION = Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=_QUOTE)


def _agreeing_verifier(**overrides) -> TNFDVerifierOutput:
    defaults = dict(
        disclosures_agree=True,
        core_global_metrics_agree=True,
        sector_metrics_agree=True,
        sector_leap_considerations_agree=True,
        general_requirements_agree=True,
        confidence=0.9,
    )
    defaults.update(overrides)
    return TNFDVerifierOutput(**defaults)


def _draft(**overrides) -> TNFDExtractionDraft:
    defaults = dict(confidence=0.9)
    defaults.update(overrides)
    return TNFDExtractionDraft(**defaults)


def test_missing_recommendations_lists_the_twelve_not_disclosed():
    draft = _draft(
        disclosures=[
            DisclosureDraft(recommendation_id="governance.A", disclosed=True, summary="Board oversight described.", summary_citations=[_CITATION]),
            DisclosureDraft(recommendation_id="strategy.A", disclosed=False),
        ]
    )
    record, _ = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, _agreeing_verifier(), _DOCS, 0.9, 0.5)

    assert len(record.missing_recommendations) == 12
    assert "governance.A" not in [r.value for r in record.missing_recommendations]
    assert "strategy.A" not in [r.value for r in record.missing_recommendations]


def test_disclosed_without_summary_is_flagged_and_forces_review():
    draft = _draft(
        disclosures=[DisclosureDraft(recommendation_id="governance.A", disclosed=True, summary=None)]
    )
    record, needs_review = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, _agreeing_verifier(), _DOCS, 0.9, 0.5)

    assert ReviewFlag.disclosure_claimed_without_supporting_chunk in record.disclosures[0].review_flags
    assert needs_review is True


def test_conflicting_materiality_across_pillars_is_flagged():
    draft = _draft(
        disclosures=[
            DisclosureDraft(recommendation_id="governance.A", disclosed=True, summary="x", summary_citations=[_CITATION], materiality_basis="single"),
            DisclosureDraft(recommendation_id="strategy.A", disclosed=True, summary="y", summary_citations=[_CITATION], materiality_basis="double"),
        ]
    )
    record, needs_review = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, _agreeing_verifier(), _DOCS, 0.9, 0.5)

    assert ReviewFlag.conflicting_materiality_across_pillars in record.record_review_flags
    assert needs_review is True


def test_sector_metric_known_registry_core_flag_mismatch_is_flagged():
    # OG.C1.0 is a core metric per SECTOR_METRIC_REGISTRY, but the extractor
    # claims it's not core -- registry disagreement, not a hard rejection.
    draft = _draft(
        sector_metrics=[
            SectorMetricDraft(
                sector_name="oil_and_gas", sector_guidance_status="final", sector_guidance_version="2023-10",
                metric_no="OG.C1.0", is_core_sector_metric=False, metric_name="Site location in Indigenous territories",
                citations=[_CITATION],
            )
        ]
    )
    record, needs_review = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, _agreeing_verifier(), _DOCS, 0.9, 0.5)

    assert ReviewFlag.metric_core_flag_mismatch in record.sector_metrics[0].review_flags
    assert needs_review is True


def test_sector_metric_no_not_in_registry_is_flagged():
    draft = _draft(
        sector_metrics=[
            SectorMetricDraft(
                sector_name="oil_and_gas", sector_guidance_status="final", sector_guidance_version="2023-10",
                metric_no="OG.NOTREAL.0", is_core_sector_metric=False, metric_name="Made-up metric",
                citations=[_CITATION],
            )
        ]
    )
    record, _ = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, _agreeing_verifier(), _DOCS, 0.9, 0.5)

    assert ReviewFlag.metric_no_not_in_registry in record.sector_metrics[0].review_flags


def test_sector_metric_unregistered_sector_not_validated_against_registry():
    # forestry_pulp_and_paper is a known Sector but has no populated
    # SECTOR_METRIC_REGISTRY entry -- can't validate metric_no either way.
    draft = _draft(
        sector_metrics=[
            SectorMetricDraft(
                sector_name="forestry_pulp_and_paper", sector_guidance_status="final", sector_guidance_version="2023-10",
                metric_no="FP.C1.0", is_core_sector_metric=True, metric_name="Some metric",
                citations=[_CITATION],
            )
        ]
    )
    record, _ = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, _agreeing_verifier(), _DOCS, 0.9, 0.5)

    assert record.sector_metrics[0].review_flags == []


def test_food_and_agriculture_sector_metric_known_registry_matches_cleanly():
    # FA.C1.0 is core per the (provisional) food_and_agriculture registry,
    # and the extractor agrees -- no registry-mismatch flags expected.
    draft = _draft(
        sector_metrics=[
            SectorMetricDraft(
                sector_name="food_and_agriculture", sector_guidance_status="final", sector_guidance_version="2023-10",
                metric_no="FA.C1.0", is_core_sector_metric=True,
                metric_name="Land area under management in or near sensitive locations",
                citations=[_CITATION],
            )
        ]
    )
    record, _ = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, _agreeing_verifier(), _DOCS, 0.9, 0.5)

    assert record.sector_metrics[0].review_flags == []


def test_food_and_agriculture_sector_metric_no_not_in_registry_is_flagged():
    draft = _draft(
        sector_metrics=[
            SectorMetricDraft(
                sector_name="food_and_agriculture", sector_guidance_status="final", sector_guidance_version="2023-10",
                metric_no="FA.NOTREAL.0", is_core_sector_metric=False, metric_name="Made-up metric",
                citations=[_CITATION],
            )
        ]
    )
    record, _ = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, _agreeing_verifier(), _DOCS, 0.9, 0.5)

    assert ReviewFlag.metric_no_not_in_registry in record.sector_metrics[0].review_flags


def test_unmapped_sector_name_is_soft_flagged():
    draft = _draft(
        sector_metrics=[
            SectorMetricDraft(
                sector_name="space_tourism", sector_guidance_status="final", sector_guidance_version="2023-10",
                metric_no=None, is_core_sector_metric=False, metric_name="Some metric",
                citations=[_CITATION],
            )
        ]
    )
    record, _ = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, _agreeing_verifier(), _DOCS, 0.9, 0.5)

    assert ReviewFlag.sector_unmapped_to_sics in record.sector_metrics[0].review_flags


def test_core_global_metric_missing_unit_or_baseline_is_flagged():
    from arp.extraction.tnfd_extractor_agent import CoreGlobalMetricDraft

    draft = _draft(
        core_global_metrics=[
            CoreGlobalMetricDraft(
                category="land_use_change", metric_kind="dependency_impact", metric_name="Land converted",
                value=120.0, unit=None, baseline_year=None, citations=[_CITATION],
            )
        ]
    )
    record, needs_review = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, _agreeing_verifier(), _DOCS, 0.9, 0.5)

    assert ReviewFlag.metric_missing_unit_or_baseline in record.core_global_metrics[0].review_flags
    assert needs_review is True


def test_verifier_disagreement_uses_correction_and_forces_review():
    draft = _draft(
        disclosures=[DisclosureDraft(recommendation_id="governance.A", disclosed=False)]
    )
    corrected = [DisclosureDraft(recommendation_id="governance.A", disclosed=True, summary="Corrected.", summary_citations=[_CITATION])]
    verifier = _agreeing_verifier(disclosures_agree=False, corrected_disclosures=corrected, disclosures_notes="Extractor missed it.")

    record, needs_review = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, verifier, _DOCS, 0.9, 0.5)

    assert record.disclosures[0].disclosed is True
    assert record.disclosures[0].summary == "Corrected."
    assert needs_review is True


def test_low_confidence_forces_review():
    draft = _draft(confidence=0.3)
    verifier = _agreeing_verifier(confidence=0.3)

    _, needs_review = build_tnfd_record("acme", None, "Acme", "run1", "FY2025", draft, verifier, _DOCS, 0.9, 0.6)

    assert needs_review is True
