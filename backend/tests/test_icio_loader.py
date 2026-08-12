import pytest

from arp.research.indirect_exposure.icio_loader import load_icio, load_sample_icio


def test_sample_icio_loads_and_is_consistent():
    icio = load_sample_icio()
    n = len(icio.codes)
    assert n == 10
    assert icio.matrix.shape == (n, n)
    assert set(icio.labels.keys()) == set(icio.codes)
    assert set(icio.total_output.keys()) == set(icio.codes)
    assert all(v > 0 for v in icio.total_output.values())


def test_index_of_known_and_unknown_code():
    icio = load_sample_icio()
    assert icio.index_of(icio.codes[0]) == 0
    assert icio.index_of("not-a-real-code") is None


def test_mismatched_matrix_column_order_raises(tmp_path):
    (tmp_path / "industries.csv").write_text("isic_code,label,total_output\nA,Industry A,100\nB,Industry B,100\n")
    # matrix header order (B, A) doesn't match industries.csv order (A, B)
    (tmp_path / "icio_matrix.csv").write_text(",B,A\nA,0,10\nB,10,0\n")
    with pytest.raises(ValueError):
        load_icio(tmp_path / "icio_matrix.csv", tmp_path / "industries.csv")


def test_mismatched_matrix_row_label_raises(tmp_path):
    (tmp_path / "industries.csv").write_text("isic_code,label,total_output\nA,Industry A,100\nB,Industry B,100\n")
    (tmp_path / "icio_matrix.csv").write_text(",A,B\nX,0,10\nB,10,0\n")
    with pytest.raises(ValueError):
        load_icio(tmp_path / "icio_matrix.csv", tmp_path / "industries.csv")
