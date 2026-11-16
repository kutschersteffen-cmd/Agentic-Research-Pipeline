import pytest

from arp.schemas.taxonomy import DerivationMethod, TaxonomyStatus
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.taxonomy_store import TaxonomyStore


def _theme(name="Electrification") -> ThemeDefinition:
    return ThemeDefinition(
        name=name,
        description="",
        activities=[ActivityDefinition(name="EV manufacturing", in_scope_description="x", out_of_scope_description="y")],
    )


def test_create_writes_v1_as_draft(tmp_path):
    store = TaxonomyStore(tmp_path)
    taxonomy = store.create("Electrification", _theme(), DerivationMethod.LLM_DRAFT, "freeform draft")
    assert taxonomy.version == 1
    assert taxonomy.status == TaxonomyStatus.DRAFT
    assert taxonomy.based_on_version is None

    loaded = store.get(taxonomy.taxonomy_id)
    assert loaded == taxonomy


def test_new_version_increments_and_links_to_prior(tmp_path):
    store = TaxonomyStore(tmp_path)
    v1 = store.create("Electrification", _theme(), DerivationMethod.LLM_DRAFT)
    edited_theme = _theme("Electrification (edited)")
    v2 = store.new_version(v1.taxonomy_id, edited_theme, DerivationMethod.MANUAL, "tightened scope")

    assert v2.version == 2
    assert v2.based_on_version == 1
    assert v2.theme.name == "Electrification (edited)"
    # get() with no version returns the latest
    assert store.get(v1.taxonomy_id) == v2
    # but v1 is still retrievable and unmodified
    assert store.get(v1.taxonomy_id, version=1) == v1


def test_new_version_unknown_taxonomy_raises(tmp_path):
    store = TaxonomyStore(tmp_path)
    with pytest.raises(ValueError):
        store.new_version("tax_does_not_exist", _theme(), DerivationMethod.MANUAL)


def test_list_versions_sorted(tmp_path):
    store = TaxonomyStore(tmp_path)
    v1 = store.create("Electrification", _theme(), DerivationMethod.LLM_DRAFT)
    store.new_version(v1.taxonomy_id, _theme(), DerivationMethod.MANUAL)
    store.new_version(v1.taxonomy_id, _theme(), DerivationMethod.MANUAL)

    versions = store.list_versions(v1.taxonomy_id)
    assert [t.version for t in versions] == [1, 2, 3]


def test_list_all_returns_latest_per_taxonomy(tmp_path):
    store = TaxonomyStore(tmp_path)
    a = store.create("Electrification", _theme(), DerivationMethod.LLM_DRAFT)
    store.new_version(a.taxonomy_id, _theme(), DerivationMethod.MANUAL)
    store.create("AI Infrastructure", _theme("AI Infrastructure"), DerivationMethod.LLM_DRAFT)

    latest = {t.name: t.version for t in store.list_all()}
    assert latest == {"Electrification": 2, "AI Infrastructure": 1}


def test_ratify_sets_status_and_metadata_without_bumping_version(tmp_path):
    store = TaxonomyStore(tmp_path)
    taxonomy = store.create("Electrification", _theme(), DerivationMethod.LLM_DRAFT)
    ratified = store.ratify(taxonomy.taxonomy_id, taxonomy.version, "jane.analyst")

    assert ratified.status == TaxonomyStatus.RATIFIED
    assert ratified.ratified_by == "jane.analyst"
    assert ratified.ratified_at is not None
    assert ratified.version == taxonomy.version  # ratifying is not a new version

    reloaded = store.get(taxonomy.taxonomy_id)
    assert reloaded.status == TaxonomyStatus.RATIFIED


def test_ratify_unknown_version_raises(tmp_path):
    store = TaxonomyStore(tmp_path)
    taxonomy = store.create("Electrification", _theme(), DerivationMethod.LLM_DRAFT)
    with pytest.raises(ValueError):
        store.ratify(taxonomy.taxonomy_id, 99, "jane.analyst")


def test_get_missing_taxonomy_returns_none(tmp_path):
    store = TaxonomyStore(tmp_path)
    assert store.get("tax_nope") is None
