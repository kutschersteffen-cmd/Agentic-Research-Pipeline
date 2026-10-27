import pytest

from arp.config import Settings
from arp.research.indirect_exposure.factory import SAMPLE_DIR, resolve_indirect_exposure_model


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(anthropic_api_key="fake", cache_dir=tmp_path / "cache", **{"value_chain_dir": None, **overrides})


def test_resolve_indirect_exposure_model_returns_none_when_unconfigured(tmp_path):
    assert resolve_indirect_exposure_model(_settings(tmp_path)) is None


def test_resolve_indirect_exposure_model_use_sample(tmp_path):
    model = resolve_indirect_exposure_model(_settings(tmp_path), use_sample=True)
    assert model is not None
    assert model.edition_label == "sample"


def test_resolve_indirect_exposure_model_use_sample_wins_over_configured_build(tmp_path):
    model = resolve_indirect_exposure_model(_settings(tmp_path, value_chain_dir=tmp_path / "missing"), use_sample=True)
    assert model.edition_label == "sample"


def test_resolve_indirect_exposure_model_reads_value_chain_dir(tmp_path):
    model = resolve_indirect_exposure_model(_settings(tmp_path, value_chain_dir=SAMPLE_DIR))
    assert model is not None
    assert model.edition_label == "sample"
    assert len(model.output) == 32 and (model.output > 0).all()


def test_resolve_indirect_exposure_model_raises_when_not_built(tmp_path):
    with pytest.raises(ValueError, match="value chain not built"):
        resolve_indirect_exposure_model(_settings(tmp_path, value_chain_dir=tmp_path))
