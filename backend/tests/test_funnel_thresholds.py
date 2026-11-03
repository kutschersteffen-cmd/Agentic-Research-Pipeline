import json

from arp.config import Settings
from arp.research.funnel_thresholds import thresholds_for
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ActivityDefinition, FunnelRecord, ThemeDefinition
from arp.storage.taxonomy_store import TaxonomyStore

D = {"k1": 25, "k2": 6, "t_rerank": 1.5, "t_entail": 0.8}


def _write(tmp_path, data):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(data))
    return p


def test_activity_without_contrast_statements_loads():  # AC-16
    a = ActivityDefinition(name="x", in_scope_description="i", out_of_scope_description="o")
    assert a.contrast_statements == []


def test_saved_taxonomy_version_keeps_contrast_statements(tmp_path):
    act = ActivityDefinition(name="x", in_scope_description="i", out_of_scope_description="o", contrast_statements=["c1"])
    store = TaxonomyStore(tmp_path)
    t = store.create("t", ThemeDefinition(name="t", description="", activities=[act]), DerivationMethod.MANUAL)
    assert store.get(t.taxonomy_id, 1).theme.activities[0].contrast_statements == ["c1"]


def test_packaged_default():
    assert thresholds_for("anything") == D


def test_theme_entry_overrides(tmp_path):  # AC-13 (data side)
    p = _write(tmp_path, {"default": D, "t1": {"t_rerank": 5.0}})
    assert thresholds_for("t1", p) == {**D, "t_rerank": 5.0}


def test_unknown_theme_uses_default(tmp_path):  # AC-14
    p = _write(tmp_path, {"default": {**D, "t_rerank": 5.0}})
    assert thresholds_for("t2", p)["t_rerank"] == 5.0


def test_funnel_record_keys():  # AC-17 (shape)
    assert set(FunnelRecord.model_fields) == {"passed", "rerank_max", "entail_positive", "entail_negatives",
                                              "best_passage", "best_doc_id", "passages_scored", "thresholds", "models"}


def test_setting_defaults_off():
    assert Settings().models_universe_funnel_enabled is False
