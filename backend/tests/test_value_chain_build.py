import csv
import json
import zipfile

import numpy as np
import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.research.value_chain.build import material_key, split_material
from tests.value_chain_fixture import MATERIAL, MATERIALS, write_fixture_f

runner = CliRunner()


def build(tmp_path, label=None):
    out = tmp_path / "vc"
    args = ["io", "build-full", str(write_fixture_f(tmp_path)), "--out", str(out)]
    res = runner.invoke(app, args + (["--label", label] if label else []))
    assert res.exit_code == 0, res.output
    return out


def broken_fixture(tmp_path, kind):
    src = write_fixture_f(tmp_path)
    dst = tmp_path / "broken" / src.name
    dst.parent.mkdir()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for name in zin.namelist():
            text = zin.read(name).decode()
            if kind == "drop_z" and name == "Z.txt":
                continue
            if kind == "unknown_sector":
                text = text.replace("Mining of copper ores and concentrates", "Not a sector")
            if kind == "bad_cell" and name == "Z.txt":
                lines = text.splitlines(keepends=True)
                cells = lines[3 + 1].split("\t")  # DE.2 row
                cells[2 + 1] = "abc"
                lines[3 + 1] = "\t".join(cells)
                text = "".join(lines)
            zout.writestr(name, text)
    return dst


def test_build_fixture_prints_counts_and_setting(tmp_path):  # AC-1
    out = tmp_path / "vc"
    res = runner.invoke(app, ["io", "build-full", str(write_fixture_f(tmp_path)), "--out", str(out)])
    assert res.exit_code == 0
    assert res.stdout.splitlines()[:2] == [f"6 nodes (3 sectors × 2 regions) -> {out}", f"ARP_VALUE_CHAIN_DIR={out}"]


def test_manifest(tmp_path):  # AC-1b
    m = json.loads((build(tmp_path) / "manifest.json").read_text())
    assert (m["edition"], m["exiobase_version"], m["year"]) == ("exiobase-IOT_2022_ixi", "3.11.2", 2022)
    assert (m["n_regions"], m["n_sectors"], m["n_nodes"]) == (2, 3, 6)
    assert len(m["source_sha256"]) == 64 and m["built_at"].endswith("Z")


def test_matrices(tmp_path):
    d = build(tmp_path)
    L = np.load(d / "L.npy")
    G = np.load(d / "G.npy")
    A = np.load(d / "A.npy")
    # archive order: DE.1, DE.2, DE.3, CN.1, CN.2, CN.3
    assert round(L[1, 4], 4) == 0.0336 and round(L[5, 4], 4) == 0.1572 and round(G[1, 2], 4) == 0.279
    assert L.dtype == np.float64 and L[0, 0] == 1.0 and not L[0, [1, 2, 4, 5]].any()  # zero-output node isolated
    assert A.dtype == G.dtype == np.float64 and A.shape == (6, 6) and A[4, 4] == 0.2 and A[1, 2] == 0.1 and not A[:, 0].any()


def test_nodes_csv(tmp_path):
    rows = list(csv.DictReader((build(tmp_path) / "nodes.csv").open()))
    assert [r["node_id"] for r in rows] == ["DE.1", "DE.2", "DE.3", "CN.1", "CN.2", "CN.3"]
    de2 = next(r for r in rows if r["node_id"] == "DE.2")
    assert de2["goods"] == "true" and float(de2["ghg_t_per_meur"]) == 5 and float(de2["va_share"]) == 0.3
    assert (de2["region"], de2["sector_no"], float(de2["energy_tj_per_meur"]), float(de2["jobs_per_meur"])) == ("DE", "2", 0.1, 10)
    de1 = next(r for r in rows if r["node_id"] == "DE.1")
    assert de1["output_meur"] in ("0", "0.0") and de1["ghg_t_per_meur"] == ""
    de3 = next(r for r in rows if r["node_id"] == "DE.3")
    assert de3["goods"] == "false" and float(de3["va_share"]) == 0.5
    cn3 = next(r for r in rows if r["node_id"] == "CN.3")
    assert round(float(cn3["ghg_t_per_meur"]), 4) == 0.27  # 1000 kg CH4 agriculture x 27 / 1000 / 100


@pytest.mark.parametrize("break_it", ["drop_z", "unknown_sector", "bad_cell"])
def test_broken_archive_exits_1_and_writes_nothing(tmp_path, break_it):  # Review Focus 2
    res = runner.invoke(app, ["io", "build-full", str(broken_fixture(tmp_path, break_it)), "--out", str(tmp_path / "vc")])
    assert res.exit_code == 1 and len(res.stderr.strip().splitlines()) == 1 and not (tmp_path / "vc").exists()
    assert not list(tmp_path.glob(".vc.building"))


def test_rebuild_replaces_directory(tmp_path):  # Review Focus 3 (disk side)
    d = build(tmp_path)
    (d / "stale.txt").write_text("x")
    build(tmp_path, label="second")
    assert not (d / "stale.txt").exists() and json.loads((d / "manifest.json").read_text())["edition"] == "second"


def test_foreign_directory_is_refused_and_left_intact(tmp_path):
    d = tmp_path / "vc"
    d.mkdir()
    (d / "precious.txt").write_text("x")
    res = runner.invoke(app, ["io", "build-full", str(write_fixture_f(tmp_path)), "--out", str(d)])
    assert res.exit_code == 1 and len(res.stderr.strip().splitlines()) == 1 and "not a build-full output" in res.stderr
    assert (d / "precious.txt").read_text() == "x" and not list(tmp_path.glob(".vc.*"))


@pytest.mark.parametrize("out", [".", ".."])
def test_out_naming_cwd_or_its_parent_is_refused(tmp_path, monkeypatch, out):
    zip_path = write_fixture_f(tmp_path)
    cwd = tmp_path / "work"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    res = runner.invoke(app, ["io", "build-full", str(zip_path), "--out", out])
    assert res.exit_code == 1 and len(res.stderr.strip().splitlines()) == 1 and zip_path.exists()


def test_failed_rebuild_keeps_previous_build(tmp_path):
    d = build(tmp_path)
    res = runner.invoke(app, ["io", "build-full", str(broken_fixture(tmp_path, "bad_cell")), "--out", str(d)])
    assert res.exit_code == 1 and json.loads((d / "manifest.json").read_text())["n_nodes"] == 6


# Material extraction, spec 2026-10-27-product-recipes-design.md (project 1)


def build_mat(tmp_path, material):
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "vc"
    res = runner.invoke(app, ["io", "build-full", str(write_fixture_f(tmp_path, material)), "--out", str(out)])
    return res, out


def last_err_line(res):
    return [ln for ln in res.stderr.splitlines() if ln.strip()][-1]


def test_material_key_and_split():
    assert material_key("Metal Ores - Other non-ferrous metal ores (incl. PGM)") == "metal_ores_other_non_ferrous_metal_ores_incl_pgm"
    assert split_material("Metal Ores - Copper ores") == ("Metal Ores", "Copper ores")
    assert split_material("Peat") == ("Other", "Peat")


def test_materials_written(tmp_path):  # AC-1, AC-32
    res, out = build_mat(tmp_path, {**MATERIAL, "Domestic Extraction Used - Peat": [0, 0, 0, 0]})
    assert res.exit_code == 0, res.output
    materials = json.loads((out / "materials.json").read_text())
    assert materials[:-1] == MATERIALS
    assert materials[-1] == {"key": "peat", "label": "Peat", "group": "Other"}
    m, total = np.load(out / "material_m.npy"), np.load(out / "material_M.npy")
    live = [1, 2, 4, 5]  # DE.2, DE.3, CN.2, CN.3; DE.1 and CN.1 have x = 0
    assert list(m[2, live]) == [400, 0, 1000, 0]
    assert list(total[2, live].round(4)) == [452.4104, 71.6934, 1283.0655, 192.8307]
    assert list(total[3, live].round(4)) == [60.2596, 42.3362, 76.6378, 70.7664]
    assert not m[:, [0, 3]].any() and not total[:, [0, 3]].any()


def test_no_material_no_files(tmp_path):  # AC-11, AC-24, AC-33
    res0, out0 = build_mat(tmp_path / "f0", None)
    res1, out1 = build_mat(tmp_path / "f", MATERIAL)
    for res, out in ((res0, out0), (res1, out1)):
        assert res.exit_code == 0, res.output
        assert res.stdout.splitlines() == [f"6 nodes (3 sectors × 2 regions) -> {out}", f"ARP_VALUE_CHAIN_DIR={out}"]
    assert not {"materials.json", "material_m.npy", "material_M.npy"} & {p.name for p in out0.iterdir()}
    assert (out0 / "nodes.csv").read_bytes() == (out1 / "nodes.csv").read_bytes()
    manifests = [json.loads((o / "manifest.json").read_text()) for o in (out0, out1)]
    for mf in manifests:
        del mf["built_at"], mf["source_sha256"]
    assert manifests[0] == manifests[1]


def test_material_without_rows_fails(tmp_path):  # AC-17
    res, out = build_mat(tmp_path, {"Unused Domestic Extraction - Metal Ores - Copper ores": [999, 999, 999, 999]})
    assert res.exit_code != 0
    assert last_err_line(res) == "material/F.txt: no row starts with 'Domestic Extraction Used - '"
    assert not out.exists()


def test_key_collision_fails(tmp_path):  # AC-31
    rows = list(MATERIAL.items())
    rows.insert(4, ("Domestic Extraction Used - Metal Ores - Copper-ores", [0, 0, 0, 0]))
    res, out = build_mat(tmp_path, dict(rows))
    assert res.exit_code != 0
    assert last_err_line(res) == "material/F.txt: two rows share the key 'metal_ores_copper_ores'"
