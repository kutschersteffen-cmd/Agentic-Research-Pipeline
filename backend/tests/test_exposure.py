import numpy as np

from arp.config import Settings
from arp.research.indirect_exposure.exposure import compute_indirect_exposure
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.indirect_exposure.migrate import icio_sectors

# Sector names standing in for the ICIO codes / ISIC divisions these tests used
COPPER_ORES = "Mining of copper ores and concentrates"  # B07, ISIC 07
MACHINERY = "Manufacture of electrical machinery and apparatus n.e.c."  # C27, ISIC 27
RETAIL = "Retail trade, except of motor vehicles and motorcycles; repair of personal and household goods"  # G
COMPUTER = "Computer and related activities"  # ISIC 62
C27 = set(icio_sectors("C27"))


def _sample_model():
    return resolve_indirect_exposure_model(Settings(), use_sample=True)


def _model(codes: list[str], flows: np.ndarray | None = None) -> LeontiefModel:
    """One node per sector in one region, output 1000 each; `flows` is Z (supplier x user)."""
    n = len(codes)
    x = np.full(n, 1000.0)
    a = (flows if flows is not None else np.zeros((n, n))) / x
    return LeontiefModel(
        codes=codes, edition_label="test", leontief_inverse=np.linalg.inv(np.eye(n) - a),
        output=x, regions=np.array(["DE"] * n), code_nodes={c: np.array([i]) for i, c in enumerate(codes)},
        ghg_t_per_meur=np.zeros(n),
    )


def test_exposure_values_are_bounded_and_sum_shares_correctly():
    model = _sample_model()
    result = compute_indirect_exposure("acme", COPPER_ORES, model, C27, "test-sample")
    assert result is not None
    assert 0.0 <= result.upstream_exposure <= 1.0
    assert 0.0 <= result.downstream_exposure <= 1.0
    assert result.core_sector is False
    assert result.isic_label == COPPER_ORES


def test_core_sector_self_reference_has_high_exposure():
    """A company IN the core sector should show much higher self-referential
    exposure than an unrelated industry, since L's diagonal dominates."""
    model = _sample_model()
    core_result = compute_indirect_exposure("acme_core", MACHINERY, model, C27, "test-sample")
    other_result = compute_indirect_exposure("acme_other", RETAIL, model, C27, "test-sample")
    assert core_result.core_sector is True
    assert other_result.core_sector is False
    assert core_result.upstream_exposure > other_result.upstream_exposure
    assert core_result.downstream_exposure > other_result.downstream_exposure


def test_isolated_industry_has_zero_exposure_to_unrelated_core():
    """An industry with no flows to/from anyone else only reaches itself in
    L, so its exposure to a core set that excludes it should be exactly 0.
    """
    flows = np.zeros((3, 3))
    flows[0, 1] = 500  # industry X feeds Y; Z is fully isolated
    model = _model(["X", "Y", "Z"], flows)
    result = compute_indirect_exposure("acme_z", "Z", model, {"X"}, "isolated-test")
    assert result.upstream_exposure == 0.0
    assert result.downstream_exposure == 0.0


def test_unknown_company_industry_returns_none():
    model = _sample_model()
    assert compute_indirect_exposure("acme", "not-a-code", model, C27, "test-sample") is None


def test_unresolvable_core_codes_returns_none():
    model = _sample_model()
    assert compute_indirect_exposure("acme", COPPER_ORES, model, {"not-a-core-code"}, "test-sample") is None


def test_critical_input_true_for_bundled_critical_code():
    model = _model([COPPER_ORES, MACHINERY, COMPUTER])
    result = compute_indirect_exposure("acme", COPPER_ORES, model, {MACHINERY}, "test")  # ISIC 07 mining -- on the bundled registry
    assert result.critical_input is True


def test_critical_input_false_for_noncritical_code():
    model = _model([COPPER_ORES, MACHINERY, COMPUTER])
    result = compute_indirect_exposure("acme", COMPUTER, model, {MACHINERY}, "test")  # IT services -- not on the registry
    assert result.critical_input is False


def test_critical_sectors_param_overrides_bundled_default():
    """An explicit critical_sectors set -- not the real bundled registry --
    should determine critical_input, so tests aren't coupled to the
    registry's actual contents."""
    model = _model([COPPER_ORES, MACHINERY, COMPUTER])
    result = compute_indirect_exposure("acme", COMPUTER, model, {MACHINERY}, "test", critical_sectors={COMPUTER})
    assert result.critical_input is True
    result2 = compute_indirect_exposure("acme", COPPER_ORES, model, {MACHINERY}, "test", critical_sectors=set())
    assert result2.critical_input is False
