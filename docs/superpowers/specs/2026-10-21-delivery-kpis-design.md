# Sector delivery KPIs

Status: approved by the owner, 2026-10-21 (approval covers the §1 values for benchmarks v3).

## Intent

The Transition section shows what a company *plans*: targets, actions, capex, phase-outs. Delivery KPIs
show what it is *already doing* on the one or two figures that matter most for its sector, such as a
cement maker's alternative-fuel share or an airline's SAF share. Each KPI shows the **actual number** next
to a **range** taken from ACT or a 1.5 °C pathway. There is no score and no ACT level name, and nothing
is added to a total (research `docs/ACT_PLAN_ASSESSMENT_RESEARCH.md` §13.5; transport ranges from
`docs/TRANSPORT_KPI_BENCHMARKS_RESEARCH.md`).

Owner decisions (2026-10-21):
- every sector that has a KPI;
- ranges for transport from a current source instead of ACT's chart;
- no ACT classification, only the range and the actual number;
- a KPI with no figure shows `not disclosed`;
- layout option A: one "Delivery KPIs" part.

## Goals

- Six sectors get delivery KPIs: Cement, Chemicals, Oil & Gas Upstream, Heavy-Duty Road Transport
  (makers and operators apart), Aviation and Shipping. Nine KPIs in all (§1).
- Each KPI shows:
  - the latest counted figure, its year and its trail;
  - the range, as text with its source, and a marker for where the figure sits;
  - the listed plan actions of the matching lever, with their barrier ratings.
- The model extracts the figures, every one goes through review, and code builds the rest.

## Non-goals

- ACT bands, levels or scores, and any total.
- Planned figures. This covers OG 2.6's Y+5 and AU 4.4's planned sales; only the latest actual is
  shown.
- KPIs for Steel, Power & Utilities and Critical Minerals & Mining. Their ACT KPIs need plant-level data,
  and mining has no ACT method (research §13.5).
- Tonnages and the CH 4.3 weighting.
- Changes to any earlier result.

## Anti-goals

- A range that cannot be traced to a printed number on a cited page.
- A KPI row silently missing: no figure shows `not disclosed`.
- The model computing a range, a position or a match.

## Current state

- `benchmarks.json` v2 (signed 2026-10-20) has per-sector blocks: `isic_prefixes`, `capex`, and
  optionally `rnd_tests` and `redlines`. `GET /api/transition-alignment/benchmarks` returns them.
  `arp transition-alignment benchmarks validate` and `sign` check and sign the file.
- `GET /api/companies/{ref}/transition` returns:
  - `capex` and redlines;
  - `actions[]`, each with a `key`, an `action_id` (the lever id, e.g. `steel.h2_dri`) and `barriers[]`;
  - targets, coverage, phase-outs and flags.
- Lever ids in the barrier data include `cement.alt_fuels`, `chem.low_carbon_h2`, `hdt.bev_trucks`,
  `hdt.fcev_trucks`, `avi.hefa_saf`, `avi.e_saf`, `avi.advanced_bio_saf`, `shp.green_fuels` and
  `shp.alt_fuel_vessels`. There is no lever for oil and gas CCS.

## Design

### 1. The nine KPIs (benchmarks file v3)

Each sector block gains `delivery_kpis`, a list in the order below. A KPI may carry its own
`isic_prefixes`, a subset of the sector's, which splits makers from operators. `points` is the range
after 0%: a value with an optional year.

| Sector (ISIC) | id | Label | Field | points | levers | cite |
|---|---|---|---|---|---|---|
| Cement (2394) | `alt_fuel_share` | Alternative-fuel share of kiln heat | `tc_alt_fuel_share_pct` | 30 | `cement.alt_fuels` | `ACT Cement v2.0, CEM 2.4a, p.50` |
| Chemicals (201) | `nh3_electrolytic` | Electrolytic share of ammonia | `tc_nh3_electrolytic_pct` | 50 | `chem.low_carbon_h2` | `ACT Chemicals, CH 4.3, p.77` |
| Chemicals (201) | `meoh_electrolytic` | Electrolytic share of methanol | `tc_meoh_electrolytic_pct` | 75 | `chem.low_carbon_h2` | `ACT Chemicals, CH 4.3, p.77` |
| Chemicals (201) | `electrolysis_lc_power` | Low-carbon power share of electrolysis | `tc_electrolysis_lc_power_pct` | 90 | `chem.low_carbon_h2` | `ACT Chemicals, CH 4.3, p.77` |
| Oil & Gas Upstream (061, 062) | `ccs_capex_share` | CCS, CCUS and CDR share of capex | `tc_ccs_capex_share_pct` | 5 | — | `ACT Oil & Gas, OG 2.6, pp.57–58; benchmark p.126` |
| Heavy-Duty Road Transport, makers (2910) | `zev_sales_share` | Zero-emission share of truck sales | `tc_zev_sales_share_pct` | 37 (2030), 65 (2035), 100 (2050) | `hdt.bev_trucks`, `hdt.fcev_trucks` | `IEA Net Zero Roadmap 2023, p.93` |
| Heavy-Duty Road Transport, operators (4923) | `fleet_lc_share` | Low-carbon share of truck fleet | `tc_fleet_lc_share_pct` | 95 (2040) | `hdt.bev_trucks`, `hdt.fcev_trucks` | `Mission Possible Partnership, Making Zero-Emissions Trucking Possible (2022), p.42` |
| Aviation (511) | `saf_share` | Sustainable aviation fuel share of jet fuel | `tc_saf_share_pct` | 11 (2030), 26 (2035), 70 (2050) | `avi.hefa_saf`, `avi.e_saf`, `avi.advanced_bio_saf` | `IEA Net Zero Roadmap 2023, p.94` |
| Shipping (501, 502) | `ship_lc_fuel_share` | Low-emission fuel share of ship energy | `tc_ship_lc_fuel_share_pct` | 19 (2030), 36 (2035), 85 (2050) | `shp.green_fuels`, `shp.alt_fuel_vessels` | `IEA Net Zero Roadmap 2023, p.94` |

Where the numbers come from:
- **ACT's band tops:** CEM 2.4a puts its top band at "over 30%". CH 4.3 puts its top bands at above
  50% (ammonia), above 75% (methanol) and more than 90% (low-carbon power). OG 2.6's benchmark is
  5% (OG p.126).
- **The IEA values** are verified rows of the Net Zero Roadmap 2023 milestone tables. The aviation
  and shipping values are our sums of the fuel rows on p.94, and the file says so in a `note`.
- **The operator value** is MPP's "95% of all trucks on the road by 2040" (p.42), which is a fleet
  share.

Approving this spec approves these values. The builder signs v3 with
`benchmarks sign --approved-by kutschersteffen-cmd`.

`benchmarks validate` adds four checks, each failing with one error line:
- a KPI field is in the delivery-KPI preset (§2) and its applicability covers the KPI's ISIC prefixes;
- a KPI's `isic_prefixes` are a subset of its sector's;
- `points` is non-empty, values are in (0, 100] and rise, and years rise;
- `cite` contains a page reference matching the regular expression `\bpp?\.\s?\d`.

### 2. Extraction

A new preset `sch_transition_delivery_kpis` adds the nine fields:
- Each is a percentage, 0–100, with one value per fiscal year under its `period_end`.
- Each is `high_risk`, so it goes to review.
- Each applies only to its KPI's ISIC prefixes.

Extraction instructions:
- `tc_alt_fuel_share_pct`: share of kiln thermal energy from alternative fuels, biomass included,
  CCS/CCU excluded (CEM 2.C, p.49).
- `tc_nh3_electrolytic_pct` and `tc_meoh_electrolytic_pct`: share of ammonia or methanol tonnes
  made with electrolysis-based hydrogen (CH p.76).
- `tc_electrolysis_lc_power_pct`: share of electrolysis power from low-carbon sources (CH p.77).
- `tc_ccs_capex_share_pct`: CDR, CCS and CCUS capex as a share of total capex, with enhanced oil
  recovery excluded (OG p.57).
- `tc_zev_sales_share_pct`: battery-electric and fuel-cell trucks as a share of truck units sold;
  plug-in hybrids do not count (AU p.119).
- `tc_fleet_lc_share_pct`: low-carbon vehicles as a share of the fleet. An ICE vehicle counts in
  proportion to its low-carbon fuel share, and only with a supply contract and verification (TR
  p.54).
- `tc_saf_share_pct`: SAF and synthetic fuel as a share of jet fuel energy, under the same contract
  condition (TR p.54).
- `tc_ship_lc_fuel_share_pct`: biofuels, hydrogen, ammonia and low-emission methanol as a share of
  fuel energy, under the same contract condition.

### 3. Response

`TransitionOut.delivery_kpis[]`, in §1 order, for the KPIs whose ISIC prefixes match the company's
ISIC code. Each entry has:

| key | content |
|---|---|
| `id`, `label`, `field_id`, `cite` | from §1 |
| `value` | the counted fact (status approved, auto-accepted or edited, as elsewhere in `/transition`) of `field_id` with the latest `period_end`; ties go to the lowest fact id, as in capex; null when there is none |
| `year` | that fact's `period_end` year; otherwise null |
| `fact_ids` | that fact's id; otherwise `[]` |
| `range_text` | `0% → ` then each point as `<v>%`, with ` (<year>)` when it has a year, joined with ` → ` |
| `position_pct` | `min(value / last point, 1) × 100`, rounded to 1 decimal; null without a value |
| `action_keys` | the `key` of every entry in `actions` whose `action_id` is in the KPI's levers, in `actions` order |

`TransitionOut.delivery_kpis_note` is set only for an in-scope company with no KPI:
`No delivery KPI for this sector.` Otherwise it is null. Out of scope, `delivery_kpis` is `[]` and the note
is null.

`BenchmarksOut.sectors[].delivery_kpis[]` gives each KPI's `id`, `label`, `field_id`, `isic_prefixes`,
`range_text`, `levers` and `cite`. A sector without KPIs gives `[]`.

### 4. Page (option A)

A **Delivery KPIs** part sits after the last of the capex, R&D and redline parts the company shows, and before **Plan actions**. It is a table with the
columns `KPI | Actual | Year | Range | Action · barrier`:
- **Actual:** the value as `<n>%` in a fact button that opens the fact's trail, or a muted
  `not disclosed`.
- **Year:** the year, or `—`.
- **Range:** the `range_text`, a bar with a marker at `position_pct` (decorative, `aria-hidden`), then
  the muted `cite`. With no value, the bar has no marker.
- **Action · barrier:** for each action in `action_keys`, its `action_id`, then each of its barrier
  rows as `<region> <rating>`, using the rating chip `Plan actions` already uses. With no action
  it shows `—`.

A company with only `delivery_kpis_note` shows the heading and the note. The page uses existing classes
and tokens only, and no horizontal page scroll at 390 px wide (the table scrolls inside its box, as the
other tables do).

## Constraints

- Code builds every range, position and match.
- Tests make no network or model calls.
- The benchmarks file stays the single source of ranges.

## Left to the builder

Module layout, the shape of the validator's messages beyond "one line per error", and UI details within
`DESIGN.md`.

## Acceptance

### Fixtures (added)

Each is seeded only when a row asks, so earlier fixtures and results stay the same. Every fixture fact is
published (approved). "FY2025" means `period_end` 2025-12-31. C (Fixture Steel AG, ISIC 2410, in scope) and
Q (Fixture Foods SA, ISIC 1050, out of scope) are the existing fixtures of the earlier specs; K is Fixture
Cement SA (ISIC 2394) and P8 is its document `Fixture Cement Report 2025`.

- **K** (cement, existing):
  - `tc_alt_fuel_share_pct` 14 % for FY2025, from P8 p.12 (quote
    `Alternative fuels supplied 14% of kiln heat in 2025.`);
  - action K1 from P8 p.9, published like A1–A3: `ta_action_text`
    `We will raise alternative fuels to 30% of kiln heat by 2030.`, `ta_action_id` `cement.alt_fuels`,
    `ta_action_status` `planned`, `ta_action_year` 2030, `ta_action_region` European Union.
- **H** `Fixture Trucks AB` (ISIC 2910) and document P9 (annual report): `tc_zev_sales_share_pct`
  4 % for FY2025, from P9 p.7.
- **X** `Fixture Chemicals NV` (ISIC 2011) and document P10 (annual report):
  - `tc_nh3_electrolytic_pct` 3 % for FY2025, from P10 p.20;
  - `tc_electrolysis_lc_power_pct` 80 % for FY2025, from P10 p.21;
  - no methanol fact.
- **F** `Fixture Freight GmbH` (ISIC 4923): no facts.

The `bm` and `bm_s` fixture benchmark files gain the same `delivery_kpis` blocks.

### Rows

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-167 | K's alt-fuel fact | request for K | `delivery_kpis` has one entry: `id` `alt_fuel_share`, `label` `Alternative-fuel share of kiln heat`, `value` 14, `year` 2025, `range_text` `0% → 30%`, `position_pct` 46.7, `cite` `ACT Cement v2.0, CEM 2.4a, p.50`; `delivery_kpis_note` null | holdout |
| AC-168 | K's alt-fuel fact | `GET /api/facts/<id>/trail` for the one id in `alt_fuel_share.fact_ids` | 200; the field id is `tc_alt_fuel_share_pct`, document P8, page 12 | holdout |
| AC-169 | K's alt-fuel fact and K1 (K's only action) | request for K | `alt_fuel_share.action_keys` equals `[<key of the entry in actions whose action_id is cement.alt_fuels>]` | holdout |
| AC-170 | the defaults (no K delivery fact) | request for K | `alt_fuel_share` has `value` null, `year` null, `fact_ids` `[]`, `position_pct` null, `range_text` `0% → 30%`, `action_keys` `[]` | holdout |
| AC-171 | K's alt-fuel fact changed to 35 | request for K | `alt_fuel_share.value` 35, `position_pct` 100.0 | holdout |
| AC-172 | H's fact | request for H | one entry: `id` `zev_sales_share`, `value` 4, `year` 2025, `range_text` `0% → 37% (2030) → 65% (2035) → 100% (2050)`, `position_pct` 4.0, `cite` `IEA Net Zero Roadmap 2023, p.93` | holdout |
| AC-173 | X's facts | request for X | `id`s in order `nh3_electrolytic`, `meoh_electrolytic`, `electrolysis_lc_power`; `value`s 3, null, 80; `position_pct`s 6.0, null, 88.9; `range_text`s `0% → 50%`, `0% → 75%`, `0% → 90%` | holdout |
| AC-174 | F seeded | request for F | one entry: `id` `fleet_lc_share`, `value` null, `range_text` `0% → 95% (2040)`, `cite` `Mission Possible Partnership, Making Zero-Emissions Trucking Possible (2022), p.42` | holdout |
| AC-175 | the defaults | request for C | `delivery_kpis` `[]`, `delivery_kpis_note` `No delivery KPI for this sector.` | holdout |
| AC-176 | the defaults | request for Q | `delivery_kpis` `[]`, `delivery_kpis_note` null | holdout |
| AC-177 | K's alt-fuel fact; the model client raises on any call | request for K | HTTP 200, `alt_fuel_share.value` 14, `position_pct` 46.7 | holdout |
| AC-178 | the bundled file | `GET /api/transition-alignment/benchmarks` | `version` 3; the Aviation sector's `delivery_kpis` is one entry `saf_share` with `range_text` `0% → 11% (2030) → 26% (2035) → 70% (2050)` and `cite` `IEA Net Zero Roadmap 2023, p.94` | holdout |
| AC-179 | the bundled file | same request | Shipping: one entry `ship_lc_fuel_share`, `range_text` `0% → 19% (2030) → 36% (2035) → 85% (2050)`, `cite` `IEA Net Zero Roadmap 2023, p.94` | holdout |
| AC-180 | the bundled file | same request | Oil & Gas Upstream: one entry `ccs_capex_share`, `range_text` `0% → 5%`, `levers` `[]`, `cite` `ACT Oil & Gas, OG 2.6, pp.57–58; benchmark p.126` | holdout |
| AC-181 | the bundled file | same request | Heavy-Duty Road Transport: `zev_sales_share` with `isic_prefixes` `["2910"]`, then `fleet_lc_share` with `isic_prefixes` `["4923"]` | holdout |
| AC-182 | the bundled file | same request | Steel, Power & Utilities and Critical Minerals & Mining each have `delivery_kpis` `[]` | holdout |
| AC-183 | the bundled file | `arp transition-alignment benchmarks validate` | exit 0; prints `Benchmarks v3: OK, 9 sectors, 3 redlines` | holdout |
| AC-184 | a benchmarks file with Cement's KPI `points` `[{"value": 30}, {"value": 20}]` | `benchmarks validate --data-dir <dir>` | exit code ≠ 0; one output line contains both `Cement` and `alt_fuel_share` | holdout |
| AC-185 | a benchmarks file with Cement's KPI field `tc_unknown_pct` | `benchmarks validate --data-dir <dir>` | exit code ≠ 0, and the output names `tc_unknown_pct` | holdout |
| AC-192 | a benchmarks file with Cement's KPI `isic_prefixes` `["9999"]` | `benchmarks validate --data-dir <dir>` | exit code ≠ 0; one output line contains `alt_fuel_share` | holdout |
| AC-193 | a benchmarks file with Cement's KPI `points` `[{"value": 120}]` | `benchmarks validate --data-dir <dir>` | exit code ≠ 0; one output line contains `alt_fuel_share` | holdout |
| AC-194 | a benchmarks file with Aviation's KPI `points` years 2035 then 2030 | `benchmarks validate --data-dir <dir>` | exit code ≠ 0; one output line contains `saf_share` | holdout |
| AC-195 | a benchmarks file with Cement's KPI `cite` `ACT Cement v2.0` (no page) | `benchmarks validate --data-dir <dir>` | exit code ≠ 0; one output line contains `alt_fuel_share` | holdout |
| AC-204 | a benchmarks file with Cement's KPI `isic_prefixes` `["2395"]` added to the sector's prefixes, while the field applies only to `["2394"]` | `benchmarks validate --data-dir <dir>` | exit code ≠ 0; one output line contains `alt_fuel_share` | holdout |
| AC-205 | a benchmarks file with Cement's KPI `cite` `ACT Cement Corp. v2.0` | `benchmarks validate --data-dir <dir>` | exit code ≠ 0; one output line contains `alt_fuel_share` | holdout |
| AC-206 | two published FY2025 alt-fuel facts for K: 14 (lower fact id), then 16 | request for K | `alt_fuel_share.value` 14, `fact_ids` only the lower id | holdout |
| AC-196 | K's alt-fuel fact for FY2025 (14) plus one for FY2024 (10, P8 p.13) | request for K | `alt_fuel_share.value` 14, `year` 2025, `fact_ids` only the FY2025 fact's id | holdout |
| AC-197 | K's alt-fuel fact left pending review (not published) | request for K | `alt_fuel_share.value` null, `fact_ids` `[]` | holdout |
| AC-198 | K's alt-fuel fact | request for K | each `delivery_kpis` entry has exactly the keys `id`, `label`, `field_id`, `cite`, `value`, `year`, `fact_ids`, `range_text`, `position_pct`, `action_keys` | holdout |
| AC-199 | the bundled file | `GET /api/transition-alignment/benchmarks` | every sector's `isic_prefixes`, `capex`, `rnd_tests` and `redlines` equal those of v2 (as on `main` before this change) | holdout |
| AC-186 | the preset installed | read schema `sch_transition_delivery_kpis` | nine fields, each `high_risk` true, unit `%`, min 0, max 100; `tc_alt_fuel_share_pct` applies to `["2394"]` only and `tc_fleet_lc_share_pct` to `["4923"]` only | holdout |
| AC-187 | K's alt-fuel fact and K1 | open K's company page | a "Delivery KPIs" part sits directly before "Plan actions", with one row: `Alternative-fuel share of kiln heat`, `14%`, `2025`, `0% → 30%`, `cement.alt_fuels` | evaluator |
| AC-200 | K's alt-fuel fact and K1; K1's `barriers` in the response has at least one entry (the `f_ta` fixture rule book gains a criterion naming `cement.alt_fuels` with a European Union rating, without changing any earlier result) | open K's company page and request `/transition` for K | the Action · barrier cell shows `cement.alt_fuels`, then one `<region> <rating>` pair per entry of K1's `barriers` in the response, in that order | evaluator |
| AC-201 | K's alt-fuel fact | open K's company page | the Range cell shows `ACT Cement v2.0, CEM 2.4a, p.50` under the bar | evaluator |
| AC-203 | K's alt-fuel fact | open K's company page | the marker's left offset in the DOM is 46.7% of the bar's width (±1 percentage point) | evaluator |
| AC-188 | K's alt-fuel fact | on K's page, click `14%` | the viewer opens Fixture Cement Report 2025 at page 12 | evaluator |
| AC-189 | X's facts | open X's company page | the methanol row reads `not disclosed` in the Actual column and `—` in the Year column | evaluator |
| AC-202 | X's facts | open X's company page | the methanol row's bar shows no marker | evaluator |
| AC-190 | the defaults | open C's company page | the Transition section shows a "Delivery KPIs" heading followed by `No delivery KPI for this sector.` | evaluator |
| AC-191 | H's fact | open H's company page in a 390 px wide window | no horizontal page scroll; the Delivery KPIs table scrolls inside its box | evaluator |

Must not change: every earlier row (phases 1–2 AC-2 to AC-71, delivery checks AC-72 to AC-129,
consistency flags AC-130 to AC-166).

## Decisions recorded

- 2026-10-21, owner:
  - all sectors with a KPI;
  - transport ranges from a current source;
  - no ACT classification, range and actual number only;
  - `not disclosed` for missing figures;
  - option A.
- Controller's calls, for the owner to check:
  - **No golden-set row.** Extraction quality is guarded by review: every delivery fact is high-risk and
    reviewed before it counts. Golden cases need the `ARP_ANTHROPIC_API_KEY` secret, which is parked with
    phase 3.
  - **Truck operators** use MPP's single 2040 fleet value (95%). This replaces the derived fleet curve
    discussed earlier: it is printed, it is a fleet share, and it needs no model of our own.
  - **Aviation and shipping** use only the IEA series, with no 2040 point, so series are never mixed.
  - **The zero-emission sales share** counts only battery-electric and fuel-cell trucks, as ACT AU
    p.119 does for the company. The IEA path includes plug-in hybrids, so this is conservative.
  - **Only the latest actual figure** is shown. Planned figures are left out.
  - **New preset.** The delivery fields are a new preset, not added to the capex preset, so the capex
    preset and its tests stay unchanged.
