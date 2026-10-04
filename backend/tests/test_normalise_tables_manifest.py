import shutil

import pytest

from arp.normalise.tables_manifest import TABLES, check_manifest, table_versions

NAMES = ["units_v1", "scale_v1", "fx_v1", "basis_v1", "locale_v1", "green_categories_v1"]


def test_manifest_lists_all_tables():
    assert sorted(table_versions()) == sorted(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_manifest_hash_matches_table(name):
    assert check_manifest(TABLES, {name: table_versions()[name]}) == []


def test_manifest_version_matches_filename():
    assert table_versions()["units_v1"]["version"] == 1
    bad = {"units_v1": {**table_versions()["units_v1"], "version": 2}}
    assert "version" in check_manifest(TABLES, bad)[0]


def test_changed_table_without_bump_fails(tmp_path):
    for n in NAMES:
        shutil.copy(TABLES / f"{n}.csv", tmp_path)
    with open(tmp_path / "fx_v1.csv", "a", encoding="utf8") as f:
        f.write("XXX,2020,1.0,test\n")
    problems = check_manifest(tmp_path, table_versions())
    assert len(problems) == 1 and problems[0].startswith("fx_v1")
