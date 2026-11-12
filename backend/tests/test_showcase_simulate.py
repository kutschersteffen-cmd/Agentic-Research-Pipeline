"""`arp showcase simulate`: the simulated ESG dataset for the public holdings files
(spec showcase-portfolio-data, PR 1). Rules on small invented holdings first, then the
committed dataset recomputed from its own text."""

from __future__ import annotations

import csv
import hashlib
import math
import shutil
import statistics
from collections import Counter, defaultdict

import openpyxl
import pytest
from typer.testing import CliRunner

from arp.cli.showcase import showcase_app
from arp.config import REPO_ROOT
from arp.showcase import simulate as sim

HOLDINGS = REPO_ROOT / "data" / "holdings"
SIMULATED = REPO_ROOT / "data" / "simulated"
SHARES = [f"{activity}_revenue_pct" for activity in sim.ACTIVITIES]
GRADE_LABELS = {"A": "Leader", "B": "Credible", "C": "Gaps", "D": "Emerging", "E": "Not credible", "F": "Disqualified"}


def line(file, isin, name, country="Germany", label="Finanzen", weight=0.001):
    return {"file": file, "isin": isin, "name": name, "country": country, "label": label, "weight": weight}


def simulate(lines, overrides=()):
    return {row["isin"]: row for row in sim.simulate(lines, list(overrides))}


def override(isin, name, activity, share="0.95", reason="test"):
    return {"isin": isin, "name": name, "activity": activity, "share": share, "reason": reason}


def without_identity(row):
    return {k: v for k, v in row.items() if k not in ("isin", "company_id", "files")}


# --- rules, on invented holdings ---------------------------------------------------------------


def test_keys_that_share_an_isin_are_one_company_and_same_name_in_two_countries_are_two():
    rows = simulate(
        [
            line("MSCI_World", "DE0001", "SAP", weight=0.01),
            line("MSCI_World", "US0001", "EQT", "United States"),
            line("MSCI_World", "US0002", "Eqt", "United States"),  # a second share class: same key, whatever the case
            line("MSCI_Europe", "SE0001", "EQT", "Sweden"),
            line("DAX", "DE0001", "SAP SE", weight=0.1),  # another key, linked by the ISIN
            line("DAX", "DE0002", "SAP SE", weight=0.1),  # so this ISIN is the same company too
        ]
    )
    assert list(rows) == sorted(rows) == ["DE0001", "DE0002", "SE0001", "US0001", "US0002"]
    assert rows["DE0001"]["name"] == rows["DE0002"]["name"] == "SAP"  # the first line in file order names the company
    assert without_identity(rows["DE0001"]) == without_identity(rows["DE0002"])
    assert without_identity(rows["US0001"]) == without_identity(rows["US0002"])
    assert without_identity(rows["US0001"]) != without_identity(rows["SE0001"])
    assert rows["DE0001"]["files"] == "MSCI_World;DAX"
    assert rows["DE0002"]["files"] == "DAX"
    assert rows["DE0002"]["company_id"] == "isin_DE0002"
    assert {row["data_status"] for row in rows.values()} == {"simulated"}
    assert all(list(row) == sim.COLUMNS and "" not in row.values() for row in rows.values())


def test_a_label_outside_the_list_fails_naming_it_except_in_dax_and_euro_stoxx():
    with pytest.raises(ValueError, match="Raumfahrt"):
        simulate([line("MSCI_World", "DE0001", "A", label="Raumfahrt")])
    with pytest.raises(ValueError, match="Raumfahrt"):
        simulate([line("AI_Big_Data", "DE0001", "A", label="Raumfahrt")])
    rows = simulate([line("DAX", "DE0001", "A", label="Raumfahrt"), line("EURO_STOXX_50", "DE0002", "B", label="Finanzdienstleister")])
    assert {row["sector"] for row in rows.values()} == {"Unknown"}  # DAX and EURO STOXX 50 labels are never used


def test_peer_group_is_the_first_gics_label_that_is_not_unknown_then_the_ai_label():
    rows = simulate(
        [
            line("MSCI_World", "DE0001", "A", label="unbekannt"),
            line("SP500", "DE0001", "A", label="Energie"),
            line("MSCI_EM", "DE0001", "A", label="Finanzen"),
            line("AI_Big_Data", "DE0001", "A", label="Technology"),
            line("AI_Big_Data", "DE0002", "B", label="Telecommunications", weight=0.5),
            line("MSCI_Europe", "DE0003", "C", label=""),
            line("AI_Big_Data", "DE0003", "C", label="unknown"),
            line("MSCI_Europe", "DE0004", "D", label="Gesundheitswesen"),
            line("MSCI_EM", "DE0005", "E", label="Kommunikationsdienste"),
        ]
    )
    sectors = ["Energy", "Communication Services", "Unknown", "Health Care", "Communication Services"]
    assert [rows[isin]["sector"] for isin in sorted(rows)] == sectors


def test_size_is_the_summed_weight_in_the_first_index_times_its_assumed_market_cap():
    rows = simulate(
        [
            line("SP500", "US0001", "A", weight=0.5),  # looked up after MSCI EM
            line("MSCI_EM", "US0001", "A", weight=0.001),
            line("MSCI_EM", "US0002", "A", weight=0.002),  # share class: weights add up
            line("MSCI_EM", "US0003", "B", weight=None),  # N/A in MSCI EM, so the next index sizes it
            line("DAX", "US0003", "B", weight=0.01),
            line("MSCI_World", "US0004", "C", weight=0.0001),
            line("MSCI_World", "US0005", "D", weight=None),  # no weight anywhere: the median of the others
            line("AI_Big_Data", "US0006", "E", label="Financials", weight=0.9),  # AI weights never size a company
        ]
    )
    # Financials: EV factor 1.0, EV-to-sales 3
    assert rows["US0001"]["climate_evic_eur_m"] == rows["US0002"]["climate_evic_eur_m"] == "25500.00"  # 0.003 x 8,500,000
    assert rows["US0001"]["climate_revenue_eur_m"] == "8500.00"
    assert rows["US0003"]["climate_evic_eur_m"] == "19000.00"  # 0.01 x 1,900,000
    assert rows["US0004"]["climate_evic_eur_m"] == "7500.00"  # 0.0001 x 75,000,000
    assert rows["US0005"]["climate_evic_eur_m"] == rows["US0006"]["climate_evic_eur_m"] == "19000.00"  # median of 25500, 19000, 7500


def test_a_company_without_a_weight_and_without_sized_peers_fails():
    with pytest.raises(ValueError, match="Financials"):
        simulate([line("MSCI_World", "US0001", "A", weight=None)])


def test_ev_factor_and_ev_to_sales_follow_the_sector_table():
    rows = simulate([line("MSCI_World", "US0001", "A", label="Versorgungsunternehmen", weight=0.001)])
    assert rows["US0001"]["climate_evic_eur_m"] == "120000.00"  # 75,000 x 1.6
    assert rows["US0001"]["climate_revenue_eur_m"] == "42857.14"  # / 2.8


def test_grades_split_a_peer_group_10_20_30_25_10_5_and_never_go_back_up():
    lines = [line("MSCI_World", f"DE{i:04d}", f"BANK {i}") for i in range(20)]
    lines += [line("MSCI_World", f"FR{i:04d}", f"UTILITY {i}", label="Versorgungsunternehmen") for i in range(7)]
    rows = simulate(lines)
    banks = [r for r in rows.values() if r["sector"] == "Financials"]
    assert Counter(r["transition_grade"] for r in banks) == {"A": 2, "B": 4, "C": 6, "D": 5, "E": 2, "F": 1}
    utilities = [r for r in rows.values() if r["sector"] == "Utilities"]  # floors of 0.7, 2.1, 4.2, 5.95, 6.65
    assert Counter(r["transition_grade"] for r in utilities) == {"B": 2, "C": 2, "D": 1, "E": 1, "F": 1}
    for group in (banks, utilities):
        ordered = sorted(group, key=lambda r: (-float(r["transition_score"]), r["isin"]))
        assert [r["transition_grade"] for r in ordered] == sorted(r["transition_grade"] for r in ordered)
    assert {(r["transition_grade"], r["transition_grade_label"]) for r in banks} == set(GRADE_LABELS.items())


def test_a_peer_group_of_one_scores_from_its_e_score_alone_and_is_grade_f():
    row = simulate([line("MSCI_World", "DE0001", "A")])["DE0001"]
    assert float(row["transition_score"]) == pytest.approx(0.5 + 0.2 * float(row["esg_e_score"]) / 10, abs=0.0001)
    assert (row["transition_grade"], row["transition_grade_label"], row["lct_category"]) == ("F", "Disqualified", "neutral")


def test_equal_scores_are_graded_by_smallest_isin(monkeypatch):
    monkeypatch.setattr(sim, "_draw", lambda key, label, low=0.0, high=1.0: (low + high) / 2)  # every company alike
    lines = [line("MSCI_World", f"DE{i:04d}", f"BANK {i}") for i in reversed(range(20))]
    lines.append(line("MSCI_World", "DE0000B", "BANK 19"))  # a second ISIN: the company sorts by its smallest
    rows = simulate(lines)
    assert len({r["transition_score"] for r in rows.values()}) == 1
    assert "".join(rows[isin]["transition_grade"] for isin in sorted(rows)) == "AABBBBCCCCCCDDDDDEEF" + "A"
    assert rows["DE0019"]["transition_grade"] == rows["DE0000B"]["transition_grade"] == "A"


def test_tobacco_and_the_two_flags_come_only_from_overrides_and_apply_to_every_isin_of_the_company():
    lines = [line("MSCI_World", f"US{i:04d}", f"STAPLES {i}", label="Basiskonsumgüter") for i in range(60)]
    lines += [line("MSCI_World", "US9001", "SMOKES", label="Basiskonsumgüter"), line("MSCI_EM", "US9002", "SMOKES", label="Basiskonsumgüter")]
    plain = simulate(lines)
    assert {r["tobacco_revenue_pct"] for r in plain.values()} == {"0.0000"}
    assert {(r["controversial_weapons"], r["norms_violation"]) for r in plain.values()} == {("false", "false")}
    assert {r["coal_revenue_pct"] for r in plain.values()} == {"0.0000"}  # Consumer Staples does not do coal
    assert any(float(r["alcohol_revenue_pct"]) > 0 for r in plain.values())  # but 8 % of it sells alcohol
    assert all(r["alcohol_revenue_pct"] == "0.0000" or 0.05 <= float(r["alcohol_revenue_pct"]) <= 0.40 for r in plain.values())

    rows = simulate(
        lines,
        [
            override("US9002", "SMOKES", "tobacco", "0.9"),
            override("US9001", "SMOKES", "alcohol", "0.3"),
            override("US9001", "SMOKES", "controversial_weapons", "1"),
            override("US0001", "STAPLES 1", "norms_violation", "1"),
        ],
    )
    for isin in ("US9001", "US9002"):
        assert (rows[isin]["tobacco_revenue_pct"], rows[isin]["alcohol_revenue_pct"]) == ("0.9000", "0.3000")
        assert (rows[isin]["controversial_weapons"], rows[isin]["norms_violation"]) == ("true", "false")
    assert (rows["US0001"]["controversial_weapons"], rows["US0001"]["norms_violation"]) == ("false", "true")
    assert rows["US0002"] == plain["US0002"]  # an override touches nobody else


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (override("XX0000", "A", "tobacco"), "XX0000"),
        (override("DE0001", "Another name", "tobacco"), "Another name"),
        (override("DE0001", "A", "tobacco", reason=" "), "reason"),
        (override("DE0001", "A", "smoking"), "smoking"),
        (override("DE0001", "A", "tobacco", share="0.49"), "0.5 to 1.0"),
        (override("DE0001", "A", "oil", share="0.91"), "0.3 to 0.9"),
        (override("DE0001", "A", "norms_violation", share="0.5"), "1.0 to 1.0"),
        (override("DE0001", "A", "tobacco", share="most"), "most"),
    ],
)
def test_a_bad_override_row_fails_naming_the_problem(row, message):
    with pytest.raises(ValueError, match=f"overrides row 2.*{message}"):
        simulate([line("MSCI_World", "DE0001", "A")], [row])


def test_two_different_shares_for_one_company_and_activity_fail():
    lines = [line("MSCI_World", "DE0001", "A"), line("MSCI_World", "DE0002", "A")]
    simulate(lines, [override("DE0001", "A", "tobacco", "0.6"), override("DE0002", "A", "tobacco", "0.6")])
    with pytest.raises(ValueError, match="overrides row 3.*second"):
        simulate(lines, [override("DE0001", "A", "tobacco", "0.6"), override("DE0002", "A", "tobacco", "0.7")])


def test_the_range_bounds_of_an_override_share_are_allowed():
    rows = simulate([line("MSCI_World", "DE0001", "A")], [override("DE0001", "A", "tobacco", "0.5"), override("DE0001", "A", "oil", "0.9")])
    assert (rows["DE0001"]["tobacco_revenue_pct"], rows["DE0001"]["oil_revenue_pct"]) == ("0.5000", "0.9000")


def test_a_company_without_a_country_fails():
    with pytest.raises(ValueError, match="NOWHERE.*no country"):
        simulate([line("MSCI_World", "DE0001", "NOWHERE", country=None)])


def test_draws_are_stable_and_depend_on_key_and_value_name():
    assert sim._draw("SAP|Germany", "intensity") == pytest.approx(0.9083601463, abs=1e-9)
    assert sim._draw("SAP|Germany", "intensity", 10, 20) == pytest.approx(19.083601463, abs=1e-8)
    assert sim._draw("SAP|Germany", "green") != sim._draw("SAP|Germany", "intensity") != sim._draw("SAP|France", "intensity")


# --- the files -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def holdings():
    return sim.read_holdings(HOLDINGS)


@pytest.fixture(scope="module")
def dataset():
    with (SIMULATED / "esg_simulated.csv").open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def companies(dataset):
    """Dataset rows grouped by company: rows whose name and country agree."""
    groups = defaultdict(list)
    for row in dataset:
        groups[(row["name"], row["country"])].append(row)
    return list(groups.values())


def test_read_holdings_keeps_equity_lines_only_with_english_countries(holdings):
    assert len({h["isin"] for h in holdings}) == 2538
    assert Counter(h["file"] for h in holdings) == {
        "MSCI_World": 1252,
        "SP500": 504,
        "MSCI_Europe": 388,
        "MSCI_EM": 1186,
        "AI_Big_Data": 100,
        "EURO_STOXX_50": 52,
        "DAX": 40,
    }
    assert [h["file"] for h in holdings] == sorted((h["file"] for h in holdings), key=sim.FILE_ORDER.index)
    assert holdings[0] == {
        "file": "MSCI_World",
        "isin": "US0378331005",
        "name": "APPLE",
        "country": "United States",
        "label": "Informationstechnologie",
        "weight": 0.0561893777,
    }
    assert {h["country"] for h in holdings} <= set(sim.COUNTRY.values())
    assert {"South Korea", "South Africa", "United States", "Czech Republic"} <= {h["country"] for h in holdings}
    assert sum(h["weight"] is None for h in holdings) == 15  # N/A weights are kept, without a number


def test_the_command_regenerates_the_committed_dataset_byte_for_byte(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # relative default paths resolve against the repo root, not the working directory
    result = CliRunner().invoke(showcase_app, ["simulate", "--out", str(tmp_path / "out.csv")])
    assert result.exit_code == 0, result.output
    assert "2538" in result.output
    assert (tmp_path / "out.csv").read_bytes() == (SIMULATED / "esg_simulated.csv").read_bytes()
    assert b"\r" not in (tmp_path / "out.csv").read_bytes()


def test_the_command_exits_1_naming_an_unknown_label(tmp_path):
    copy = tmp_path / "holdings"
    shutil.copytree(HOLDINGS, copy)
    wb = openpyxl.load_workbook(copy / "MSCI_World.xlsx")
    header = [c.value for c in wb.worksheets[0][4]]
    wb.worksheets[0].cell(row=5, column=header.index("Industry Classification") + 1).value = "Raumfahrt"
    wb.save(copy / "MSCI_World.xlsx")
    result = CliRunner().invoke(showcase_app, ["simulate", "--holdings-dir", str(copy), "--out", str(tmp_path / "out.csv")])
    assert result.exit_code == 1
    assert "Raumfahrt" in result.stderr
    assert not (tmp_path / "out.csv").exists()


def test_the_command_exits_1_when_a_holdings_file_is_missing(tmp_path):
    result = CliRunner().invoke(showcase_app, ["simulate", "--holdings-dir", str(tmp_path), "--out", str(tmp_path / "out.csv")])
    assert result.exit_code == 1
    assert "MSCI_World.xlsx" in result.stderr


def test_readme_says_simulated_on_line_1_and_the_ai_file_is_the_one_the_spec_names():
    assert (SIMULATED / "README.md").read_text(encoding="utf-8").splitlines()[0] == (
        "SIMULATED DATA. Not real ESG data. Generated by arp showcase simulate."
    )
    assert hashlib.sha256((HOLDINGS / "AI_Big_Data.xlsx").read_bytes()).hexdigest() == (
        "f7df310918dd8243af970b33e3dcd757f255b0b16edc19b226f74d08ad2eb5bd"
    )


def test_dataset_rows_and_companies(dataset, companies, holdings):
    isins = [row["isin"] for row in dataset]
    assert isins == sorted({h["isin"] for h in holdings})
    assert list(dataset[0]) == sim.COLUMNS
    assert len(companies) == 2530
    for row in dataset:
        assert row["data_status"] == "simulated" and row["company_id"] == f"isin_{row['isin']}"
        assert row["sector"] in sim.SECTOR_TABLE and "" not in row.values()
    for rows in companies:
        assert len({tuple(without_identity(row).items()) for row in rows}) == 1


def test_dataset_climate_values_are_consistent_and_inside_the_sector_table(dataset):
    for row in dataset:
        scope12 = float(row["climate_scope1_tco2e"]) + float(row["climate_scope2_tco2e"])
        intensity = float(row["climate_carbon_intensity"])
        (low, high), scope1_share, (s3_low, s3_high), (green_low, green_high), ev_factor, ev_to_sales = sim.SECTOR_TABLE[row["sector"]]
        assert low <= intensity <= high, row["isin"]
        assert green_low <= float(row["climate_green_revenue_pct"]) <= green_high, row["isin"]
        assert row["ghg_intensity"] == row["climate_carbon_intensity"]
        assert float(row["green_revenue_pct"]) == pytest.approx(float(row["climate_green_revenue_pct"]) / 100, abs=1e-9)
        if scope12 >= 100:
            assert scope12 / float(row["climate_revenue_eur_m"]) == pytest.approx(intensity, rel=0.005), row["isin"]
            assert float(row["climate_scope1_tco2e"]) / scope12 == pytest.approx(scope1_share, rel=0.005), row["isin"]
            assert s3_low * 0.995 <= float(row["climate_scope3_tco2e"]) / scope12 <= s3_high * 1.005, row["isin"]
        if float(row["climate_evic_eur_m"]) >= 100:
            assert float(row["climate_evic_eur_m"]) / float(row["climate_revenue_eur_m"]) == pytest.approx(ev_to_sales, rel=0.005)
    medians = {
        sector: statistics.median(float(r["climate_carbon_intensity"]) for r in dataset if r["sector"] == sector) for sector in sim.SECTOR_TABLE
    }
    for heavy in ("Utilities", "Energy", "Materials"):
        for light in ("Information Technology", "Financials", "Health Care"):
            assert medians[heavy] > 5 * medians[light]


def test_dataset_largest_msci_world_company_is_sized_from_its_weight(dataset, holdings):
    world = Counter()
    for h in holdings:
        if h["file"] == "MSCI_World" and h["weight"] is not None:
            world[(h["name"], h["country"])] += h["weight"]
    (name, country), weight = world.most_common(1)[0]
    row = next(r for r in dataset if (r["name"], r["country"]) == (name, country))
    assert float(row["climate_evic_eur_m"]) == pytest.approx(weight * 75_000_000 * sim.SECTOR_TABLE[row["sector"]][4], rel=0.01)


def test_dataset_scores_and_controversy(dataset, companies):
    for row in dataset:
        e, s, g = (float(row[f"esg_{pillar}_score"]) for pillar in "esg")
        mean = 4.5 if row["sector"] in ("Utilities", "Energy", "Materials") else 6.0
        assert mean - 2.5 <= e <= mean + 2.5 and 3.5 <= s <= 8.5 and 3.5 <= g <= 8.5
        assert float(row["esg_score"]) == pytest.approx((e + s + g) / 3, abs=0.01)
        assert 0.80 <= float(row["esg_trend"]) <= 1.20
        assert row["controversy_level"] in list("012345")
        assert row["severe_controversy"] == ("true" if row["controversy_level"] == "5" else "false")
    share = {level: n / len(companies) for level, n in Counter(rows[0]["controversy_level"] for rows in companies).items()}
    for level, expected in {"0": 0.60, "1": 0.20, "2": 0.12, "3": 0.05, "4": 0.02, "5": 0.01}.items():
        assert share[level] == pytest.approx(expected, abs=0.02)


def test_dataset_controversial_revenue_follows_sectors_and_overrides(dataset):
    overrides = sim.read_overrides(SIMULATED / "activity_overrides.csv")
    key_of_isin = {row["isin"]: (row["name"], row["country"]) for row in dataset}
    overridden = {(key_of_isin[o["isin"]], o["activity"]): float(o["share"]) for o in overrides}
    for row in dataset:
        key = (row["name"], row["country"])
        for activity, (by_sector, _range) in sim.ACTIVITIES.items():
            share = float(row[f"{activity}_revenue_pct"])
            if (key, activity) in overridden:
                assert share == overridden[(key, activity)]
            elif share > 0:
                low, high = by_sector[row["sector"]][1]  # KeyError: a share where the sector does not do the activity
                assert low <= share <= high
        for flag in sim.OVERRIDE_FLAGS:
            assert row[flag] == ("true" if (key, flag) in overridden else "false")
    energy = [r for r in dataset if r["sector"] == "Energy"]
    assert 0.6 < sum(float(r["oil_revenue_pct"]) > 0 for r in energy) / len(energy) < 0.95  # 80 % by draw, plus overrides


def test_overrides_copy_names_from_the_files_and_cover_the_spec_list(holdings):
    overrides = sim.read_overrides(SIMULATED / "activity_overrides.csv")
    in_files = {(h["isin"], h["name"]) for h in holdings}
    named = defaultdict(set)
    for o in overrides:
        assert (o["isin"], o["name"]) in in_files and o["reason"].strip()
        named[o["activity"]].add(o["isin"])
    spec = {
        "tobacco": "US7181721090 US02209S1033 GB0002875804 GB0004544929 JP3726800000 KR7033780008 INE154A01025",
        "coal": "INE522F01014 CNE1000002R0 CNE100000767 CNE1000004Q8 CNE000000WV6 INE733E01010 DE0007037129 ZAE000006896 JE00B4T3BW64",
        "weapons": "DE0007030009 US5398301094 US6668071029 US3695501086 GB0002634946 US75513E1010 IT0003856405 FR0000121329 "
        "SE0021921269 DE000HAG0005 NO0013536151 US5024311095 US4464131063 IL0010811243 INE263A01024 INE066F01020 NL0000235190 "
        "FR0000073272 US0970231058 US4385162056",
        "oil": "GB00BP6MXD84 FR0000120271 US30233Q1085 US1667641005 GB0007980591 IT0003132476 NO0010096985 US20825C1045 "
        "AU0000224040 SA14TG012N13 CNE1000003W8 CNE1000007Q1 INE002A01018 RU0007661625",
    }
    spec["gas"] = spec["oil"]
    for activity, isins in spec.items():
        assert set(isins.split()) <= named[activity], activity
    assert named["alcohol"] and named["gambling"]  # brewers, distillers, casino and betting groups


def test_dataset_transition_score_grade_and_category_follow_the_rule(companies):
    by_sector = defaultdict(list)
    for rows in companies:
        by_sector[rows[0]["sector"]].append(rows)
    assert len(by_sector) == 12
    for sector, members in by_sector.items():
        n = len(members)
        first = [rows[0] for rows in members]
        intensities = [float(r["climate_carbon_intensity"]) for r in first]
        greens = [float(r["green_revenue_pct"]) for r in first]
        median_intensity = statistics.median(intensities)
        for row in first:
            p_intensity = sum(v < float(row["climate_carbon_intensity"]) for v in intensities) / (n - 1)
            p_green = sum(v < float(row["green_revenue_pct"]) for v in greens) / (n - 1)
            score = 0.5 * (1 - p_intensity) + 0.3 * p_green + 0.2 * float(row["esg_e_score"]) / 10
            assert float(row["transition_score"]) == pytest.approx(score, abs=0.0001), row["isin"]
            assert float(row["lct_score"]) == pytest.approx(10 * float(row["transition_score"]), abs=0.01)
            if float(row["climate_green_revenue_pct"]) >= 50:
                category = "solutions"
            elif sector in ("Utilities", "Energy", "Materials"):
                category = "asset_stranding" if row["transition_grade"] in "DEF" else "operational_transition"
            elif sector in ("Industrials", "Consumer Discretionary") and float(row["climate_carbon_intensity"]) > median_intensity:
                category = "product_transition"
            else:
                category = "neutral"
            assert row["lct_category"] == category, row["isin"]
            assert row["transition_grade_label"] == GRADE_LABELS[row["transition_grade"]]
        cuts = [math.floor(p * n) for p in (0.10, 0.30, 0.60, 0.85, 0.95)] + [n]
        expected = {g: cut - before for g, cut, before in zip("ABCDEF", cuts, [0, *cuts], strict=False)}
        assert Counter(r["transition_grade"] for r in first) == {g: k for g, k in expected.items() if k}, sector
        ordered = sorted(members, key=lambda rows: (-float(rows[0]["transition_score"]), min(r["isin"] for r in rows)))
        grades = [rows[0]["transition_grade"] for rows in ordered]
        assert grades == sorted(grades), sector
