import pytest

from arp.config import Settings
from arp.research.indirect_exposure.factory import (
    build_exiobase_model,
    build_leontief_model,
    resolve_indirect_exposure_model,
)


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(anthropic_api_key="fake", cache_dir=tmp_path / "cache", **overrides)


def test_build_leontief_model_returns_none_when_unconfigured(tmp_path):
    assert build_leontief_model(_settings(tmp_path)) is None


def test_build_leontief_model_use_sample(tmp_path):
    model = build_leontief_model(_settings(tmp_path), use_sample=True)
    assert model is not None
    assert model.edition_label == "sample"


def test_build_exiobase_model_returns_none_when_unconfigured(tmp_path):
    assert build_exiobase_model(_settings(tmp_path)) is None


def test_build_exiobase_model_use_sample(tmp_path):
    model = build_exiobase_model(_settings(tmp_path), use_sample=True)
    assert model is not None
    assert model.edition_label == "exiobase-sample"


def test_resolve_indirect_exposure_model_returns_none_when_unconfigured(tmp_path):
    assert resolve_indirect_exposure_model(_settings(tmp_path)) is None


def test_resolve_indirect_exposure_model_raises_when_both_sample_flags_set(tmp_path):
    with pytest.raises(ValueError):
        resolve_indirect_exposure_model(_settings(tmp_path), use_sample_icio=True, use_sample_exiobase=True)


def test_resolve_indirect_exposure_model_use_sample_icio(tmp_path):
    model = resolve_indirect_exposure_model(_settings(tmp_path), use_sample_icio=True)
    assert model is not None
    assert model.edition_label == "sample"


def test_resolve_indirect_exposure_model_use_sample_exiobase(tmp_path):
    model = resolve_indirect_exposure_model(_settings(tmp_path), use_sample_exiobase=True)
    assert model is not None
    assert model.edition_label == "exiobase-sample"


def test_resolve_indirect_exposure_model_prefers_icio_when_both_configured(tmp_path):
    industries = tmp_path / "industries.csv"
    industries.write_text("isic_code,label,total_output\nA,Industry A,100\n")
    icio_matrix = tmp_path / "icio_matrix.csv"
    icio_matrix.write_text(",A\nA,0\n")
    flows = tmp_path / "flows.csv"
    flows.write_text("supplier_isic_code,user_isic_code,value\nA,A,0\n")

    settings = _settings(
        tmp_path,
        icio_matrix_path=icio_matrix,
        icio_industries_path=industries,
        icio_edition_label="real-icio",
        exiobase_flows_path=flows,
        exiobase_industries_path=industries,
        exiobase_edition_label="real-exiobase",
    )
    model = resolve_indirect_exposure_model(settings)
    assert model is not None
    assert model.edition_label == "real-icio"


def test_resolve_indirect_exposure_model_falls_back_to_exiobase(tmp_path):
    industries = tmp_path / "industries.csv"
    industries.write_text("isic_code,label,total_output\nA,Industry A,100\n")
    flows = tmp_path / "flows.csv"
    flows.write_text("supplier_isic_code,user_isic_code,value\nA,A,0\n")

    settings = _settings(
        tmp_path,
        exiobase_flows_path=flows,
        exiobase_industries_path=industries,
        exiobase_edition_label="real-exiobase",
    )
    model = resolve_indirect_exposure_model(settings)
    assert model is not None
    assert model.edition_label == "real-exiobase"
