import copy
import json
import os
import re

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.research.indirect_exposure.factory import sectors
from arp.research.indirect_exposure.migrate import (
    UnknownIcioCode,
    convert_document,
    convert_parts,
    convert_theme,
    icio_sectors,
)
from arp.research.indirect_exposure.migrate import icio_sectors as S
from arp.schemas.value_chain import LinkRule
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.taxonomy_store import TaxonomyStore


def test_sectors_count_and_first():
    assert len(sectors()) == 163
    assert sectors()[0] == "Cultivation of paddy rice"
    assert not any(re.search(r" \(\d+\)$", s) for s in sectors())


def test_icio_sectors_b07():
    s = icio_sectors("B07")
    assert len(s) == 8 and "Mining of uranium and thorium ores" in s
    assert s == sorted(s)


def test_icio_sectors_split_code():
    s = icio_sectors("D_GEN_REN")
    assert len(s) == 7 and all(n.startswith("Production of electricity by") for n in s)


def test_unknown_code():
    with pytest.raises(UnknownIcioCode) as e:
        icio_sectors("ZZZ")
    assert e.value.code == "ZZZ"


def test_convert_theme_key_order():
    theme = {"activities": [{"activity_id": "a1", "name": "n", "core_isic_codes": ["B07"], "source_citation": None}]}
    assert convert_theme(theme) is True
    assert list(theme["activities"][0]) == ["activity_id", "name", "core_sectors", "source_citation"]
    assert theme["activities"][0]["core_sectors"] == icio_sectors("B07")
    assert convert_theme(theme) is False


def test_convert_unmapped():
    theme = {"activities": [], "standards_mapping": {"unmapped_isic_codes": ["B07"]}}
    assert convert_theme(theme) is True
    assert theme["standards_mapping"] == {"unmapped_sectors": icio_sectors("B07")}


def test_convert_parts():
    parts = [{"icio_code": "B07", "share": 0.4}, {"icio_code": "D_GEN_REN", "share": 0.6}]
    assert convert_parts("split", parts) == [
        {"sectors": icio_sectors("B07"), "share": 0.4},
        {"sectors": icio_sectors("D_GEN_REN"), "share": 0.6},
    ]
    assert convert_parts("nodes", [{"region": "DE", "sector": "Copper production", "share": 1}]) is None
    assert convert_parts("split", [{"sectors": ["x"], "share": 1}]) is None


def test_convert_document_taxonomy_and_bare_theme():
    act = {"activity_id": "a1", "core_isic_codes": ["B07"]}
    tax = {"theme": {"activities": [dict(act)]}}
    assert convert_document(tax) is True
    assert tax["theme"]["activities"][0]["core_sectors"] == icio_sectors("B07")
    bare = {"activities": [dict(act)]}
    assert convert_document(bare) is True
    assert "core_isic_codes" not in bare["activities"][0]


def test_convert_parts_llm_like_split():
    assert convert_parts("llm", [{"icio_code": "B07", "share": 1}]) == [{"sectors": icio_sectors("B07"), "share": 1}]


def test_convert_theme_unknown_code():
    with pytest.raises(UnknownIcioCode):
        convert_theme({"activities": [{"core_isic_codes": ["ZZZ"]}]})


def test_convert_document_bare_run_theme():
    theme = {"activities": [{"activity_id": "a1", "name": "n", "core_isic_codes": ["B07"]}]}
    assert convert_document(theme) is True
    assert theme["activities"][0]["core_sectors"] == icio_sectors("B07")


runner = CliRunner()
DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
C1 = {"kind": "split", "parts": [{"icio_code": "B07", "share": 0.4}, {"icio_code": "D_GEN_REN", "share": 0.6}], "set_by": "a", "set_at": "t"}
C2 = {"kind": "nodes", "parts": [{"region": "DE", "sector": "Copper production", "share": 1}], "set_by": "a", "set_at": "t"}


def _doc(version: int, **extra) -> dict:
    return {
        "taxonomy_id": "t1", "name": "T", "version": version, "derivation_method": "manual", "source_notes": "",
        "status": "draft", "ratified_by": None, "ratified_at": None, "based_on_version": None, "created_at": "t",
        "theme": {"name": "x", "activities": [
            {"id": "a1", "name": "A1", "core_isic_codes": ["B07"], "standards_mapping": {"unmapped_isic_codes": ["B07"]}},
            {"id": "a2", "name": "A2", "core_isic_codes": []},
        ]},
        **extra,
    }


def _write(path, doc) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def _snapshot(tdir, store) -> dict:
    files = {str(p): p.read_bytes() for p in sorted(tdir.rglob("*")) if p.is_file()}
    return {"files": files, "rules": {k: v.model_dump() for k, v in store.list_link_rules().items()}}


def _install(tmp_path, monkeypatch, store):
    tdir = tmp_path / "taxonomies"
    (tdir / "t1").mkdir(parents=True)
    _write(tdir / "t1" / "v1.json", _doc(1, status="ratified", ratified_by="bob", ratified_at="2026-01-01T00:00:00Z"))
    _write(tdir / "t1" / "v2.json", _doc(2, based_on_version=1))
    (tdir / "t1" / "latest.json").write_text('{"version": 2}')
    (tdir / "t1" / "notes.txt").write_text("core_isic_codes stray")
    monkeypatch.setattr("arp.cli._shared._taxonomy_store", lambda: TaxonomyStore(tdir))
    monkeypatch.setattr("arp.cli._shared._portfolio_store", lambda: store)
    store.save_link_rule("company:c1", LinkRule(**C1))
    store.save_link_rule("company:c2", LinkRule(**C2))
    return tdir


@pytest.fixture
def m(tmp_path, monkeypatch):
    store = PortfolioStore(tmp_path / "pf")
    return _install(tmp_path, monkeypatch, store), store


def _run(*args):
    return runner.invoke(app, ["io", "migrate-exiobase", *args])


def _load(tdir, n):
    return json.loads((tdir / "t1" / f"v{n}.json").read_text())


def test_taxonomies_converted(m):  # AC-1, 2, 3, 55, 56, 57
    tdir, store = m
    before = _load(tdir, 1)
    assert _run().exit_code == 0
    for n in (1, 2):
        a1, a2 = _load(tdir, n)["theme"]["activities"]
        assert a1["core_sectors"] == S("B07") and a2["core_sectors"] == []
        assert "core_isic_codes" not in a1 and "core_isic_codes" not in a2
    v1 = _load(tdir, 1)
    assert all(v1[k] == before[k] for k in ("status", "ratified_by", "ratified_at"))
    assert v1["theme"]["activities"][0]["standards_mapping"] == {"unmapped_sectors": S("B07")}
    v2 = _load(tdir, 2)
    assert (v2["version"], v2["based_on_version"]) == (2, 1)
    assert not (tdir / "t1" / "v3.json").exists()


def test_links_converted_and_stdout(m):  # AC-4, 5, 6
    tdir, store = m
    c2 = store.get_link_rule("company:c2").model_dump()
    res = _run()
    assert res.exit_code == 0
    assert res.stdout == "taxonomy t1 v1\ntaxonomy t1 v2\nlink company:c1\n3 changed\n"
    assert store.get_link_rule("company:c1").parts == [{"sectors": S("B07"), "share": 0.4}, {"sectors": S("D_GEN_REN"), "share": 0.6}]
    assert store.get_link_rule("company:c2").model_dump() == c2


def test_idempotent(m):  # AC-7, 59
    tdir, store = m
    _run()
    snap = _snapshot(tdir, store)
    res = _run()
    assert (res.exit_code, res.stdout) == (0, "0 changed\n")
    assert _snapshot(tdir, store) == snap


def test_dry_run(m):  # AC-8
    tdir, store = m
    snap = _snapshot(tdir, store)
    res = _run("--dry-run")
    assert (res.exit_code, res.stdout) == (0, "taxonomy t1 v1\ntaxonomy t1 v2\nlink company:c1\n3 changed\n")
    assert _snapshot(tdir, store) == snap


def test_unknown_code_aborts_without_writing(m):  # AC-9, 10
    tdir, store = m
    bad = copy.deepcopy(C1)
    bad["parts"][1]["icio_code"] = "ZZZ"
    store.save_link_rule("company:c1", LinkRule(**bad))
    snap = _snapshot(tdir, store)
    res = _run()
    assert res.exit_code == 1 and res.stderr == "unknown ICIO code 'ZZZ' in link company:c1\n"
    assert _snapshot(tdir, store) == snap


def test_unknown_code_in_taxonomy_names_version(m):
    tdir, store = m
    d = _doc(2, based_on_version=1)
    d["theme"]["activities"][0]["core_isic_codes"] = ["ZZZ"]
    _write(tdir / "t1" / "v2.json", d)
    res = _run()
    assert res.exit_code == 1 and res.stderr == "unknown ICIO code 'ZZZ' in taxonomy t1 v2\n"
    assert "core_isic_codes" in (tdir / "t1" / "v1.json").read_text()


def test_file_mode(m, tmp_path):  # AC-11, 60, 61, 12, 13
    tdir, store = m
    f = tmp_path / "theme.json"
    _write(f, {"name": "x", "activities": [{"id": "a1", "name": "A", "core_isic_codes": ["B07"]}]})
    snap = _snapshot(tdir, store)
    res = _run("--file", str(f))
    assert (res.exit_code, res.stdout) == (0, f"file {f}\n1 changed\n")
    act = json.loads(f.read_text())["activities"][0]
    assert act["core_sectors"] == S("B07") and "core_isic_codes" not in act
    assert _snapshot(tdir, store) == snap
    # AC-13: a copy of unmigrated v1 ends byte-identical to what the full run writes
    copy_v1 = tmp_path / "v1.json"
    copy_v1.write_bytes((tdir / "t1" / "v1.json").read_bytes())
    assert _run("--file", str(copy_v1)).exit_code == 0
    _run()
    assert copy_v1.read_bytes() == (tdir / "t1" / "v1.json").read_bytes()


def test_latest_and_stray_files_untouched(m):  # Review Focus 3
    tdir, _ = m
    _run()
    assert (tdir / "t1" / "latest.json").read_text() == '{"version": 2}'
    assert (tdir / "t1" / "notes.txt").read_text() == "core_isic_codes stray"


@pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")
def test_postgres_store(tmp_path, monkeypatch):  # AC-58
    from arp.storage.postgres import ensure_schema
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore
    from tests.postgres_helpers import reset_postgres_tables

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    try:
        store = PostgresPortfolioStore(DSN, PortfolioStore(tmp_path / "pg-files"))
        _install(tmp_path, monkeypatch, store)
        assert _run().exit_code == 0
        assert store.get_link_rule("company:c1").parts == [{"sectors": S("B07"), "share": 0.4}, {"sectors": S("D_GEN_REN"), "share": 0.6}]
    finally:
        reset_postgres_tables(DSN)


@pytest.mark.parametrize("code", ["B09", "C21", "C301", "H53", "J58T60"])
def test_icio_codes_without_sectors_map_to_nothing(code):  # owner decision 2026-11-05
    assert icio_sectors(code) == []


def test_activity_with_unmatched_icio_code_gets_no_sectors():
    theme = {"activities": [{"name": "n", "core_isic_codes": ["C21"]}]}
    assert convert_theme(theme) is True
    assert theme["activities"][0]["core_sectors"] == []


def test_digit_codes_convert_through_nace():  # owner decision 2026-11-05: old hand-supplied ISIC Rev.4 codes
    assert icio_sectors("07") == [
        "Mining of aluminium ores and concentrates", "Mining of copper ores and concentrates", "Mining of iron ores",
        "Mining of lead, zinc and tin ores and concentrates", "Mining of nickel ores and concentrates",
        "Mining of other non-ferrous metal ores and concentrates", "Mining of precious metal ores and concentrates",
        "Mining of uranium and thorium ores",
    ]
    assert "Aluminium production" in icio_sectors("2420")
    with pytest.raises(UnknownIcioCode):
        icio_sectors("00")


def test_activity_with_both_keys_keeps_the_union():
    theme = {"activities": [{"name": "n", "core_sectors": ["Mining of iron ores", "Aluminium production"], "core_isic_codes": ["B07"]}]}
    assert convert_theme(theme) is True
    act = theme["activities"][0]
    assert act["core_sectors"] == sorted({"Aluminium production", *S("B07")}) and "core_isic_codes" not in act


def test_file_mode_non_object_json(m, tmp_path):
    f = tmp_path / "list.json"
    f.write_text("[1, 2]")
    res = _run("--file", str(f))
    assert (res.exit_code, res.stdout) == (0, "0 changed\n")
    assert f.read_text() == "[1, 2]"
