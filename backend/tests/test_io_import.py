import asyncio
import csv
import zipfile
from fractions import Fraction

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import Settings
from arp.llm.base import LLMUsage
from arp.research.indirect_exposure.company_mapper import resolve_company_isic
from arp.research.indirect_exposure.exposure import compute_indirect_exposure
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.research.indirect_exposure.io_import import REFERENCE_DIR, industry_list
from arp.schemas.common import CompanyRef

CODES = [c for c, *_ in industry_list()]
SECTORS = [r["exiobase_sector"] for r in csv.DictReader((REFERENCE_DIR / "exiobase_ixi_to_icio2025.csv").open())]
runner = CliRunner()


def _icio_fixture(path, *, hfce_d="5"):
    labels = [f"{r}_{c}" for r in ("DEU", "CHN") for c in CODES]
    flows = {("DEU_C26", "CHN_C27"): "10", ("CHN_C26", "DEU_C27"): "5", ("DEU_D", "DEU_C26"): "2"}
    out = {"DEU_C26": "100", "CHN_C26": "50", "DEU_C27": "40", "CHN_C27": "60", "DEU_D": "30"}
    hfce = {"DEU_C27": "20", "CHN_C27": "10", "DEU_D": hfce_d}
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["V1", *labels, "DEU_HFCE", "CHN_GFCF", "OUT"])
        for row in labels:
            cells = [flows.get((row, col), "0") for col in labels]
            w.writerow([row, *cells, hfce.get(row, "0"), "50" if row == "DEU_C27" else "0", out.get(row, "1")])
        for row in ("TLS", "VA", "OUT"):
            w.writerow([row, *["7"] * (len(labels) + 3)])
    return path


def _exiobase_fixture(path, *, with_f=True):
    b = lambda k: SECTORS[k - 1]  # noqa: E731
    keys = [(r, s) for r in ("AT", "WA") for s in SECTORS]
    z = {(("AT", b(87)), ("WA", b(88))): 10, (("WA", b(89)), ("AT", b(88))): 5,
         (("AT", b(108)), ("AT", b(87))): 2, (("AT", b(100)), ("AT", b(87))): 3}
    x = {("AT", b(87)): 100, ("WA", b(89)): 50, ("AT", b(88)): 40, ("WA", b(88)): 60, ("AT", b(108)): 30, ("AT", b(100)): 20}
    cats = ["Final consumption expenditure by households",
            "Final consumption expenditure by non-profit organisations serving households (NPISH)",
            "Final consumption expenditure by government", "Gross fixed capital formation",
            "Changes in inventories", "Changes in valuables", "Exports: Total (fob)"]
    ycols = [(r, c) for r in ("AT", "WA") for c in cats]
    y = {(("AT", b(88)), ("AT", cats[0])): 30, (("AT", b(88)), ("WA", cats[3])): 50,
         (("AT", b(108)), ("AT", cats[0])): 5, (("WA", b(89)), ("AT", cats[5])): 4, (("AT", b(87)), ("AT", cats[6])): 999}
    stressors = {"CO2 - combustion - air": {("AT", b(100)): 2000}, "CH4 - combustion - air": {("AT", b(87)): 10},
                 "CO2 - waste - biogenic - air": {("AT", b(87)): 500}, "SO2 - combustion - air": {("AT", b(87)): 123}}
    line = lambda cells: "\t".join(str(c) for c in cells) + "\n"  # noqa: E731
    zt = line(["region", "", *(r for r, _ in keys)]) + line(["sector", "", *(s for _, s in keys)])
    zt += line(["region", "sector", *[""] * len(keys)])
    zt += "".join(line([*k, *(z.get((k, c), 0) for c in keys)]) for k in keys)
    xt = line(["region", "sector", "indout"]) + "".join(line([*k, x.get(k, 0)]) for k in keys)
    yt = line(["region", "", *(r for r, _ in ycols)]) + line(["category", "", *(c for _, c in ycols)])
    yt += line(["region", "sector", *[""] * len(ycols)])
    yt += "".join(line([*k, *(y.get((k, c), 0) for c in ycols)]) for k in keys)
    ft = line(["region", *(r for r, _ in keys)]) + line(["sector", *(s for _, s in keys)])
    ft += "".join(line([name, *(v.get(k, 0) for k in keys)]) for name, v in stressors.items())
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Z.txt", zt)
        zf.writestr("x.txt", xt)
        zf.writestr("Y.txt", yt)
        if with_f:
            zf.writestr("air_emissions/F.txt", ft)
    return path


def _rows(path):
    return list(csv.DictReader(path.open()))


def _configure(monkeypatch, result):
    assert result.exit_code == 0, result.output
    for line in result.stdout.splitlines()[1:]:
        key, value = line.split("=", 1)
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for key in ("IO_SOURCE", "ICIO_MATRIX_PATH", "ICIO_INDUSTRIES_PATH", "ICIO_EDITION_LABEL",
                "EXIOBASE_FLOWS_PATH", "EXIOBASE_INDUSTRIES_PATH", "EXIOBASE_EDITION_LABEL"):
        monkeypatch.delenv(f"ARP_{key}", raising=False)
    monkeypatch.setenv("ARP_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture
def icio_out(tmp_path):
    out = tmp_path / "icio"
    return runner.invoke(app, ["io", "import-icio", str(_icio_fixture(tmp_path / "icio_fixture.csv")), "--out", str(out)]), out


@pytest.fixture
def exio_out(tmp_path):
    out = tmp_path / "exio"
    zip_path = _exiobase_fixture(tmp_path / "IOT_fixture_ixi.zip")
    return runner.invoke(app, ["io", "import-exiobase", str(zip_path), "--out", str(out)]), out


def _exposure(code, core, country=None):
    model = resolve_indirect_exposure_model(Settings())
    return compute_indirect_exposure("x", code, model, core, "e", country=country)


def test_reference_files():
    rows = list(csv.DictReader((REFERENCE_DIR / "exiobase_ixi_to_icio2025.csv").open()))
    assert len(rows) == 163
    assert [rows[k - 1]["icio_code"] for k in (87, 88, 89, 100, 108, 133, 55, 163)] == ["C26", "C27", "C26", "D", "D", "J62_63", "C17_18", "O"]
    assert len(CODES) == 50 and len(industry_list(split=True)) == 54
    assert len(list(csv.DictReader((REFERENCE_DIR / "ghg_gwp100.csv").open()))) == 23


def test_import_icio(icio_out):
    result, out = icio_out
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == f"50 industries, 2 regions -> {out.resolve()}"
    assert lines[1:] == ["ARP_IO_SOURCE=icio", f"ARP_ICIO_MATRIX_PATH={out.resolve()}/icio_matrix.csv",
                         f"ARP_ICIO_INDUSTRIES_PATH={out.resolve()}/industries.csv", "ARP_ICIO_EDITION_LABEL=icio-icio_fixture"]
    totals = {r["isic_code"]: float(r["total_output"]) for r in _rows(out / "industries.csv")}
    assert [*totals] == CODES
    assert (totals["C26"], totals["C27"], totals["D"], totals["A01"]) == (150, 100, 31, 2)
    matrix = {r["isic_code"]: r for r in _rows(out / "icio_matrix.csv")}
    nonzero = {(i, j): float(v) for i, r in matrix.items() for j, v in r.items() if j != "isic_code" and float(v)}
    assert nonzero == {("C26", "C27"): 15, ("D", "C26"): 2}
    fd = {r["isic_code"]: [float(r[g]) for g in ("households", "government", "investment", "inventories")] for r in _rows(out / "final_demand.csv")}
    assert fd["C27"] == [30, 0, 50, 0] and fd["D"] == [5, 0, 0, 0]
    flows = [tuple(r.values()) for r in _rows(out / "regional_flows.csv")]
    assert flows == [("CN", "C26", "EU", "C27", "5.0"), ("EU", "C26", "CN", "C27", "10.0"), ("EU", "D", "EU", "C26", "2.0")]
    assert len(_rows(out / "regional_output.csv")) == 100


@pytest.mark.parametrize(("edit", "message"), [
    (lambda t: t.replace(",OUT\n", ",X\n", 1), "no OUT column"),
    (lambda t: t.replace("_C24A,", "_C24,").replace("_C24B,", "_C24,"), "missing ICIO industries: C24A, C24B"),
    (lambda t: t.replace("DEU_", "QQQ_"), "region not in region groups: QQQ"),
])
def test_import_icio_errors(tmp_path, edit, message):
    src = _icio_fixture(tmp_path / "f.csv")
    src.write_text(edit(src.read_text()))
    result = runner.invoke(app, ["io", "import-icio", str(src), "--out", str(tmp_path / "out")])
    assert result.exit_code == 1
    assert message in result.stderr and len(result.stderr.splitlines()) == 1
    assert not list((tmp_path / "out").glob("*.csv")) if (tmp_path / "out").exists() else True


def test_import_icio_bad_cell(tmp_path):
    src = _icio_fixture(tmp_path / "f.csv")
    rows = list(csv.reader(src.open()))
    rows[CODES.index("C26") + 1][1 + 50 + CODES.index("C27")] = "x"
    with src.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    result = runner.invoke(app, ["io", "import-icio", str(src), "--out", str(tmp_path / "out")])
    assert result.exit_code == 1 and "row DEU_C26, column CHN_C27: not a number: 'x'" in result.stderr


def test_import_exiobase(exio_out, tmp_path):
    result, out = exio_out
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == f"163 sectors -> 50 industries, 2 regions -> {out.resolve()}"
    totals = {r["isic_code"]: float(r["total_output"]) for r in _rows(out / "industries.csv")}
    assert (totals["C26"], totals["C27"], totals["D"], totals["C21"]) == (150, 100, 50, 0)
    assert [(r["supplier_isic_code"], r["user_isic_code"], float(r["value"])) for r in _rows(out / "exiobase_flows.csv")] == [("C26", "C27", 15), ("D", "C26", 5)]
    fd = {r["isic_code"]: [float(r[g]) for g in ("households", "government", "investment", "inventories")] for r in _rows(out / "final_demand.csv")}
    assert fd["C27"] == [30, 0, 50, 0] and fd["D"] == [5, 0, 0, 0] and fd["C26"] == [0, 0, 0, 4]
    ghg = {r["isic_code"]: float(r["kg_co2e"]) for r in _rows(out / "ghg.csv")}
    assert ghg["D"] == 2000 and ghg["C26"] == pytest.approx(298) and sum(ghg.values()) == pytest.approx(2298)
    assert [tuple(r.values()) for r in _rows(out / "regional_flows.csv")] == [
        ("EU", "C26", "ASIA_OTH", "C27", "10.0"), ("EU", "D", "EU", "C26", "5.0"), ("ASIA_OTH", "C26", "EU", "C27", "5.0")]

    # Re-import without F.txt into the same dir drops the stale ghg.csv (AC-102).
    again = runner.invoke(app, ["io", "import-exiobase", str(_exiobase_fixture(tmp_path / "noF.zip", with_f=False)), "--out", str(out)])
    assert again.exit_code == 0 and not (out / "ghg.csv").exists()


def test_import_exiobase_split(tmp_path):
    out = tmp_path / "split"
    result = runner.invoke(app, ["io", "import-exiobase", str(_exiobase_fixture(tmp_path / "e.zip")), "--out", str(out), "--split-electricity"])
    assert result.stdout.splitlines()[0].startswith("163 sectors -> 54 industries, 2 regions -> ")
    assert [(r["supplier_isic_code"], r["user_isic_code"], float(r["value"])) for r in _rows(out / "exiobase_flows.csv")] == [
        ("C26", "C27", 15), ("D_GEN_REN", "C26", 3), ("D_TD", "C26", 2)]


def test_import_exiobase_errors(tmp_path):
    src = tmp_path / "bad.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("x.txt", "region\tsector\tindout\n")
    result = runner.invoke(app, ["io", "import-exiobase", str(src), "--out", str(tmp_path / "out")])
    assert result.exit_code == 1 and "no Z.txt at the archive root" in result.stderr


def test_status_and_source(monkeypatch, icio_out, exio_out):
    assert runner.invoke(app, ["io", "status"]).stdout == "source: none\n"
    _configure(monkeypatch, icio_out[0])
    _configure(monkeypatch, exio_out[0])
    monkeypatch.delenv("ARP_IO_SOURCE")
    assert runner.invoke(app, ["io", "status"]).stdout.splitlines()[0] == "source: icio"
    monkeypatch.setenv("ARP_IO_SOURCE", "exiobase")
    assert runner.invoke(app, ["io", "status"]).stdout.splitlines() == [
        "source: exiobase", "edition: exiobase-IOT_fixture_ixi", "industries: 50", "final demand: yes", "emissions: yes", "regions: 2"]
    monkeypatch.delenv("ARP_ICIO_MATRIX_PATH")
    monkeypatch.setenv("ARP_IO_SOURCE", "icio")
    result = runner.invoke(app, ["io", "status"])
    assert result.exit_code == 1
    assert "io source icio is not configured: set ARP_ICIO_MATRIX_PATH and ARP_ICIO_INDUSTRIES_PATH" in result.stderr
    monkeypatch.setenv("ARP_IO_SOURCE", "ICIO")
    result = runner.invoke(app, ["io", "status"])
    assert result.exit_code == 1 and "Input should be 'auto', 'icio' or 'exiobase'" in result.stderr


def test_icio_exposure(monkeypatch, icio_out):
    _configure(monkeypatch, icio_out[0])
    assert _exposure("C27", {"C26"}).upstream_exposure == pytest.approx(float(Fraction(25, 192)))
    r = _exposure("C26", {"C27"}, "DE")
    assert r.downstream_exposure == pytest.approx(3 / 23)
    assert r.end_market == pytest.approx({"households": 0.375, "government": 0, "investment": 0.625, "inventories": 0})
    assert list(r.end_market) == ["households", "government", "investment", "inventories"]
    assert r.regional.downstream == pytest.approx(1 / 7)
    assert _exposure("D", {"C27"}).theme_demand_share == pytest.approx(4 / 129)
    assert _exposure("A01", {"C27"}).end_market is None
    r = _exposure("C27", {"C26"}, "de")
    assert r.ghg_direct_t_per_meur is None
    assert r.regional.region == "EU" and r.regional.upstream == pytest.approx(1 / 9)
    assert r.regional.upstream_by_region == pytest.approx({"CN": 1 / 9, "EU": 0}) and list(r.regional.upstream_by_region) == ["CN", "EU"]
    assert _exposure("C27", {"C26"}, "CN").regional.upstream == pytest.approx(50 / 351)
    for country in ("XX", "US", "CN1", None):
        assert _exposure("C27", {"C26"}, country).regional is None


def test_exiobase_exposure(monkeypatch, exio_out):
    _configure(monkeypatch, exio_out[0])
    r = _exposure("C26", {"C27"})
    assert r.end_market == pytest.approx({"households": 0.28125, "government": 0, "investment": 0.46875, "inventories": 0.25})
    assert r.theme_demand_share == pytest.approx(0.75)
    assert r.ghg_direct_t_per_meur == pytest.approx(149 / 75000)
    assert r.ghg_supply_chain_t_per_meur == pytest.approx(0.00332)
    r = _exposure("C27", {"C26"}, "AT")
    assert r.ghg_supply_chain_t_per_meur == pytest.approx(0.000498)
    assert r.regional.upstream_by_region == pytest.approx({"EU": 0, "ASIA_OTH": 1 / 9})
    assert _exposure("C27", {"C26"}, "WA").regional is None


def test_reimport_same_label_rebuilds_cache(monkeypatch, tmp_path, icio_out):
    _configure(monkeypatch, icio_out[0])
    before = _exposure("C27", {"C26"}).upstream_exposure
    src = _icio_fixture(tmp_path / "icio_fixture.csv")
    src.write_text(src.read_text().replace("DEU_D,0,", "DEU_D,9,"))  # new DEU_D -> DEU_A01 flow
    _configure(monkeypatch, runner.invoke(app, ["io", "import-icio", str(src), "--out", str(icio_out[1])]))
    model = resolve_indirect_exposure_model(Settings())
    assert model.leontief_inverse[model.codes.index("D"), model.codes.index("A01")] > 0
    assert _exposure("C27", {"C26"}).upstream_exposure == pytest.approx(before)


class _Stub:
    def __init__(self):
        self.calls = 0

    async def complete_structured(self, *, system, prompt, output_model):
        self.calls += 1
        return output_model(isic_code=None, rationale="stub"), LLMUsage()


@pytest.mark.parametrize(("code", "expected", "calls"), [("26", "C26", 0), ("62", "J62_63", 0), ("24", None, 1), ("2610", None, 1), ("C27", "C27", 0)])
def test_division_lookup(monkeypatch, icio_out, code, expected, calls):
    _configure(monkeypatch, icio_out[0])
    stub = _Stub()
    company = CompanyRef(company_id="x", name="X", isic_code=code)
    assert asyncio.run(resolve_company_isic(company, resolve_indirect_exposure_model(Settings()), stub))[0] == expected
    assert stub.calls == calls


def test_nace_lookup_with_split(monkeypatch, tmp_path):
    out = tmp_path / "split"
    _configure(monkeypatch, runner.invoke(app, ["io", "import-exiobase", str(_exiobase_fixture(tmp_path / "e.zip")), "--out", str(out), "--split-electricity"]))
    model = resolve_indirect_exposure_model(Settings())
    for code, expected in (("35.12", "D_TD"), ("35", None), ("35.11", None)):
        assert asyncio.run(resolve_company_isic(CompanyRef(company_id="x", name="X", isic_code=code), model, _Stub()))[0] == expected
    assert compute_indirect_exposure("x", "D_GEN_REN", model, {"C27"}, "e").ghg_direct_t_per_meur == pytest.approx(0.1)


def test_samples_unchanged():
    for flag in ("use_sample_icio", "use_sample_exiobase"):
        model = resolve_indirect_exposure_model(Settings(io_source="icio" if flag.endswith("exiobase") else "exiobase"), **{flag: True})
        r = compute_indirect_exposure("x", "27", model, {"20"}, "e", country="DE")
        assert (r.upstream_exposure, r.downstream_exposure) == (pytest.approx(0.11052858), pytest.approx(0.01855963))
        assert (r.end_market, r.theme_demand_share, r.ghg_direct_t_per_meur, r.regional) == (None, None, None, None)
