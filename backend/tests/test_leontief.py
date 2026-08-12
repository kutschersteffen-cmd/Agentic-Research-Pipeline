import numpy as np
import pytest

from arp.research.indirect_exposure.icio_loader import ICIOData, load_sample_icio
from arp.research.indirect_exposure.leontief import (
    build_model,
    build_or_load_model,
    compute_leontief_inverse,
    compute_technical_coefficients,
)


def _two_industry_icio() -> ICIOData:
    # A supplies 20 to B's production; B supplies 50 to A's production.
    matrix = np.array([[0.0, 50.0], [20.0, 0.0]])
    return ICIOData(
        codes=["A", "B"],
        labels={"A": "Industry A", "B": "Industry B"},
        total_output={"A": 100.0, "B": 200.0},
        matrix=matrix,
    )


def test_technical_coefficients_are_column_normalized():
    icio = _two_industry_icio()
    a = compute_technical_coefficients(icio)
    # column A (index 0): inputs from B (20) / total_output[A] (100)
    assert a[1, 0] == pytest.approx(0.2)
    assert a[0, 0] == 0.0
    # column B (index 1): inputs from A (50) / total_output[B] (200)
    assert a[0, 1] == pytest.approx(0.25)


def test_leontief_inverse_matches_hand_computation():
    icio = _two_industry_icio()
    a = compute_technical_coefficients(icio)
    leontief_inverse = compute_leontief_inverse(a)
    # det(I - A) = 1*1 - (-0.25)*(-0.2) = 0.95
    expected = np.array([[1.0, 0.25], [0.2, 1.0]]) / 0.95
    np.testing.assert_allclose(leontief_inverse, expected, rtol=1e-9)


def test_leontief_inverse_satisfies_its_own_definition():
    """L(I - A) = I is what "Leontief inverse" means -- check the property
    itself rather than only a specific hand-computed case."""
    icio = load_sample_icio()
    a = compute_technical_coefficients(icio)
    leontief_inverse = compute_leontief_inverse(a)
    n = a.shape[0]
    np.testing.assert_allclose(leontief_inverse @ (np.eye(n) - a), np.eye(n), atol=1e-8)


def test_leontief_diagonal_is_at_least_one():
    icio = load_sample_icio()
    model = build_model(icio, "test")
    assert (model.leontief_inverse.diagonal() >= 1.0 - 1e-9).all()


def test_build_or_load_model_uses_cache(tmp_path):
    icio = load_sample_icio()
    m1 = build_or_load_model(icio, "cache-test", tmp_path)
    cache_files = list(tmp_path.glob("*.npz"))
    assert len(cache_files) == 1

    m2 = build_or_load_model(icio, "cache-test", tmp_path)
    np.testing.assert_allclose(m1.leontief_inverse, m2.leontief_inverse)
    assert m2.codes == m1.codes
