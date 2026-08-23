import numpy as np
import pytest

from arp.research.indirect_exposure.exiobase_loader import build_icio_from_long_format, load_sample_exiobase
from arp.research.indirect_exposure.icio_loader import load_sample_icio


def test_sample_exiobase_loads_and_is_consistent():
    exio = load_sample_exiobase()
    n = len(exio.codes)
    assert n == 10
    assert exio.matrix.shape == (n, n)
    assert set(exio.labels.keys()) == set(exio.codes)
    assert set(exio.total_output.keys()) == set(exio.codes)


def test_aggregating_sample_exiobase_matches_sample_icio_matrix():
    """The bundled EXIOBASE sample is the same illustrative economy as the
    OECD-ICIO sample, re-expressed as region-resolved long-format flows --
    aggregating it back should reproduce the exact same matrix, proving the
    group-and-sum arithmetic is correct."""
    exio = load_sample_exiobase()
    icio = load_sample_icio()
    assert exio.codes == icio.codes
    np.testing.assert_allclose(exio.matrix, icio.matrix)


def test_long_format_flows_across_multiple_regions_are_summed(tmp_path):
    (tmp_path / "industries.csv").write_text("isic_code,label,total_output\nA,Industry A,100\nB,Industry B,100\n")
    (tmp_path / "flows.csv").write_text(
        "supplier_isic_code,user_isic_code,value,supplier_region,user_region\n"
        "A,B,10,EU,EU\n"
        "A,B,15,ROW,ROW\n"
        "B,A,5,EU,EU\n"
    )
    icio = build_icio_from_long_format(tmp_path / "flows.csv", tmp_path / "industries.csv")
    assert icio.matrix[icio.index_of("A"), icio.index_of("B")] == 25
    assert icio.matrix[icio.index_of("B"), icio.index_of("A")] == 5


def test_unmapped_supplier_code_in_flows_raises(tmp_path):
    (tmp_path / "industries.csv").write_text("isic_code,label,total_output\nA,Industry A,100\n")
    (tmp_path / "flows.csv").write_text("supplier_isic_code,user_isic_code,value\nZZZ,A,10\n")
    with pytest.raises(ValueError, match="unmapped supplier"):
        build_icio_from_long_format(tmp_path / "flows.csv", tmp_path / "industries.csv")


def test_unmapped_user_code_in_flows_raises(tmp_path):
    (tmp_path / "industries.csv").write_text("isic_code,label,total_output\nA,Industry A,100\n")
    (tmp_path / "flows.csv").write_text("supplier_isic_code,user_isic_code,value\nA,ZZZ,10\n")
    with pytest.raises(ValueError, match="unmapped user"):
        build_icio_from_long_format(tmp_path / "flows.csv", tmp_path / "industries.csv")


def test_missing_required_flows_column_raises(tmp_path):
    (tmp_path / "industries.csv").write_text("isic_code,label,total_output\nA,Industry A,100\n")
    (tmp_path / "flows.csv").write_text("supplier_isic_code,user_isic_code\nA,A\n")  # missing `value`
    with pytest.raises(ValueError, match="missing required column"):
        build_icio_from_long_format(tmp_path / "flows.csv", tmp_path / "industries.csv")
