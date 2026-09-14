import numpy as np

from arp.research.indirect_exposure.exposure import compute_indirect_exposure
from arp.research.indirect_exposure.icio_loader import ICIOData, load_sample_icio
from arp.research.indirect_exposure.leontief import build_model


def _sample_model():
    return build_model(load_sample_icio(), "test-sample")


def test_exposure_values_are_bounded_and_sum_shares_correctly():
    model = _sample_model()
    result = compute_indirect_exposure("acme", "07", model, {"27"}, "test-sample")
    assert result is not None
    assert 0.0 <= result.upstream_exposure <= 1.0
    assert 0.0 <= result.downstream_exposure <= 1.0
    assert result.core_sector is False
    assert result.isic_label == model.labels["07"]


def test_core_sector_self_reference_has_high_exposure():
    """A company IN the core sector should show much higher self-referential
    exposure than an unrelated industry, since L's diagonal dominates."""
    model = _sample_model()
    core_result = compute_indirect_exposure("acme_core", "27", model, {"27"}, "test-sample")
    other_result = compute_indirect_exposure("acme_other", "45", model, {"27"}, "test-sample")
    assert core_result.core_sector is True
    assert other_result.core_sector is False
    assert core_result.upstream_exposure > other_result.upstream_exposure
    assert core_result.downstream_exposure > other_result.downstream_exposure


def test_isolated_industry_has_zero_exposure_to_unrelated_core():
    """An industry with no flows to/from anyone else only reaches itself in
    L, so its exposure to a core set that excludes it should be exactly 0.
    """
    n = 3
    matrix = np.zeros((n, n))
    matrix[0, 1] = 500  # industry X feeds Y; Z is fully isolated
    icio = ICIOData(
        codes=["X", "Y", "Z"],
        labels={"X": "X", "Y": "Y", "Z": "Z"},
        total_output={"X": 1000.0, "Y": 1000.0, "Z": 1000.0},
        matrix=matrix,
    )
    model = build_model(icio, "isolated-test")
    result = compute_indirect_exposure("acme_z", "Z", model, {"X"}, "isolated-test")
    assert result.upstream_exposure == 0.0
    assert result.downstream_exposure == 0.0


def test_unknown_company_industry_returns_none():
    model = _sample_model()
    assert compute_indirect_exposure("acme", "not-a-code", model, {"27"}, "test-sample") is None


def test_unresolvable_core_codes_returns_none():
    model = _sample_model()
    assert compute_indirect_exposure("acme", "07", model, {"not-a-core-code"}, "test-sample") is None


def test_critical_input_true_for_bundled_critical_code():
    model = _sample_model()
    result = compute_indirect_exposure("acme", "07", model, {"27"}, "test-sample")  # 07 is mining -- on the bundled registry
    assert result.critical_input is True


def test_critical_input_false_for_noncritical_code():
    model = _sample_model()
    result = compute_indirect_exposure("acme", "62", model, {"27"}, "test-sample")  # IT services -- not on the registry
    assert result.critical_input is False


def test_critical_codes_param_overrides_bundled_default():
    """An explicit critical_codes set -- not the real bundled registry --
    should determine critical_input, so tests aren't coupled to the
    registry's actual contents."""
    model = _sample_model()
    result = compute_indirect_exposure("acme", "62", model, {"27"}, "test-sample", critical_codes={"62"})
    assert result.critical_input is True
    result2 = compute_indirect_exposure("acme", "07", model, {"27"}, "test-sample", critical_codes=set())
    assert result2.critical_input is False
