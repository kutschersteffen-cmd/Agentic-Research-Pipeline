# Plan delivery checks: target progress, abatement coverage, phase-out, scenario carbon price

Status: draft for owner approval, 2026-10-20.

## Intent

Transition plan alignment phases 1–2 test whether a company's **money and actions** line up with its
plan (capex vs benchmark, B02 per action, barriers per region). They do not test whether the plan
**is being delivered** or **adds up**. ACT publishes code-computable rules for four of those gaps
(research `docs/ACT_PLAN_ASSESSMENT_RESEARCH.md` §13.1, 13.2, 13.4, 13.7; owner picked these four
on 2026-10-20):

1. **Target progress (ACT GE 1.4):** did the company meet its past targets, and is it on track for
   the running ones?
2. **Abatement coverage (ACT Core B02.c):** do the plan's listed actions add up to the target gap?
3. **Phase-out commitment (ACT GE 9.2 dim. 3, ACT Core D02.a):** how much of the high-carbon
   business is committed to phase out, and by when?
4. **Scenario carbon price (ACT GE 5.3):** how does the plan's assumed carbon price compare with
   the IEA Net Zero (NZE) scenario price?

All four extend the existing Transition section and `GET /api/companies/{ref}/transition`.

## Goals

- Extract targets (with base year and base-year emissions) and phase-out commitments from
  transition plans, as ordinary company facts with quote and page, through the existing review queue.
- Compute the four results in code from counted facts, with ACT's formulas and bands, citing the
  ACT page for each rule.
- Show them in the Transition section; every company figure opens its fact.

## Non-goals

- GE 1.1/1.2 target alignment against a sector pathway, E01, F01 (later).
- Consistency flags (research §13.3), sector delivery KPIs (§13.5), governance (§13.6).
- Scope 3 progress: targets covering scope 3 are extracted and shown but progress is computed for
  scope 1+2 only (scope 3 series are too often restated or partial). **Builder's call (controller).**
- Intensity targets (ACT Core A01.b: financial intensity not accepted; physical intensity needs
  activity data we don't have). Extracted targets are absolute only.

## Anti-goals

- The model never outputs a ratio, score, band or gap.
- A missing input never becomes 0%: it gives "not scored" with a reason.
- No change to the existing presets' fields (AC-47) or to phase 1–2 results (regression rows).

## Current state

- `sch_transition_plan_actions` (phase 2): plan actions, operating regions, assumptions; list rows
  keyed by `basis`, every list row goes to review (`unverified_list_item`).
- `transition_plan_indicators` (existing preset, must not change): `tp_h_target_pct`,
  `tp_h_target_year` (one "nearest 2030" target, no base year), and the emissions series
  `tp_h_scope1_emissions`, `tp_h_scope2_emissions`, `tp_h_scope3_emissions` (tCO2e per period,
  scope 2 market-based where both are given).
- Benchmarks file v1 (owner-signed): sectors, capex, R&D tests, redlines, `act_levers`,
  `assumptions` (barrier fact mapping).
- `actions.py` `score_plan` → `PlanOut`; router fills `TransitionOut`.

## Design

### 1. New fields in `sch_transition_plan_actions`

Added to the preset (preset fields stay version 1; the preset's schema version increases).
Same applicability (the nine sectors), same list extraction from the latest-plan pipeline branch
(one model call per transition-plan document now also returns targets and phase-outs), every row to
review.

| Field id | Type | Definition (abridged) |
|---|---|---|
| `ta_target_scope` | enum `S1+2`, `S1+2+3` | Scopes the absolute target covers |
| `ta_target_pct` | percentage | Absolute reduction from the base year |
| `ta_target_year` | number (year) | |
| `ta_target_base_year` | number (year) | |
| `ta_target_base_emissions` | number, unit `tCO2e` or `MtCO2e` | Base-year emissions for the target's scopes, as the plan states them |
| `ta_target_set_year` | number (year) | Year the target was set or published; if not stated, the plan document's as-of year (**builder's call**) |
| `ta_phaseout_activity` | string | The high-carbon activity committed to phase out |
| `ta_phaseout_share_pct` | percentage | Share of that activity committed (capacity, production or revenue, as stated) |
| `ta_phaseout_year` | number (year) | Year the phase-out completes |
| `ta_phaseout_method` | enum `closure`, `conversion`, `sale` | |

Targets share basis `target:<doc>:<page>:<n>`, phase-outs `phaseout:<doc>:<page>:<n>` (as P3 of
phase 2). Only the latest transition plan counts for targets and phase-outs, by primary-citation
document (as phase 2 P2). Intensity targets are not extracted.

### 2. Emissions series

`E(year)` for a target of scope `S1+2` = counted `tp_h_scope1_emissions` + counted
`tp_h_scope2_emissions` for fiscal year `year` (R4 keying of phase 1). Both must be counted for that
year, else `E(year)` is missing. **RY** = latest year with `E` present.

Base-year emissions come from `ta_target_base_emissions` (converted to tCO2e: `MtCO2e` × 1,000,000);
`E(base_year)` from the series is not used for the base (the plan's own base, as ACT's formula uses
the target's base).

### 3. Target progress (ACT GE 1.4, GE pp.31–34)

Numbers: `ratio` is shown with `fmt_number` (half up to 2 decimals, trailing zeros dropped); each
target `score` is rounded half up to 2 decimals before display and before any mean.

For each counted target (latest plan), in this order of checks, the first that applies gives
`score` null and its `reason`:
1. scope `S1+2+3` → `Scope 3 target: progress not computed`;
2. no counted `ta_target_pct`, `ta_target_year` or `ta_target_base_year` → `Incomplete target`;
3. no base emissions → `No base-year emissions`;
4. neither past nor running (below) → `Target year <y> neither past nor running`;
5. `E(year)` needed but missing → `No emissions for <year>`.

`kind` is `past` or `running` when the window rule places it, else null (rule 1 or 2 also gives null).
`T = E_base × (1 − pct/100)`.

- **Past** (RY − 10 ≤ target year ≤ RY, inclusive): `a = (E_base − E(target_year)) / (E_base − T)`.
  Score: `a ≥ 1` → 100; `0.5 < a < 1` → `100 × (2a − 1)`; else 0. `ratio` = a.
- **Running** (set year ≤ RY − 1 and target year ≥ RY + 1): `a_RY = (E_base − E(RY)) / (E_base − T)`,
  `time = (RY − set_year) / (target_year − set_year)`, `p = a_RY / time`.
  Score: `min(max(p, 0), 1) × 100`. `ratio` = p. A target whose set year is not stated uses the plan
  document's as-of year (**builder's call**); if that is not ≤ RY − 1 the target is neither past nor
  running.
- **Overall** (ACT weights 25/75), over **scored** targets only: `0.25 × mean(past) + 0.75 × mean(running)`;
  a kind with no scored target is skipped and the other kind's mean is used alone (**builder's call**);
  no scored target → `target_progress` null. Text `Target progress <score>% (ACT GE 1.4)`.

### 4. Abatement coverage (ACT Core B02.c, Core p.37; Framework p.61)

Target used: the scored-or-unscored `running` S1+2 target with the earliest target year (ties: the
earlier page in the plan). None → `coverage` has `reason` `No running target`, `percent` null.
That target without base emissions → `reason` `No base-year emissions`, `percent` null.
`gap = E_base × pct / 100` (tCO2e/yr).

Each listed action (phase 2's latest-plan actions) is summed or not, with one reason, checked in
order: no saving → `No quantified saving`; `%` saving → `Saving in % not summed`; no year →
`No year`; year after the target year → `After the target year`. Summed savings convert
`MtCO2e/yr` × 1,000,000.

No summed action → `percent` null, `reason` `No summable action`. Otherwise
`percent = covered / gap × 100` and text
`Listed actions cover <percent>% of the <year> target gap (<covered> of <gap> MtCO2e/yr)`, numbers in
MtCO2e/yr with `fmt_number`. No band and no score: ACT gives none.

### 5. Phase-out commitment (ACT GE 9.2 dim. 3, GE pp.139–140; ACT Core D02.a, Core p.66)

RY here = the plan document's as-of year (**builder's call**: the phase-out is a plan commitment).
Per counted phase-out (latest plan):
- No counted share → `score` null, `reason` `No share stated`; no counted year → `score` null,
  `reason` `No year stated`.
- **Share points** (70%): share ≤ 25 → 0; > 25 and ≤ 50 → 25; > 50 and ≤ 75 → 50; > 75 and ≤ 95 → 75;
  > 95 → 100.
- **Date points** (30%): year ≥ RY+21 → 0; RY+16 to RY+20 → 25; RY+11 to RY+15 → 50; RY+6 to RY+10 → 75;
  ≤ RY+5 → 100.
- Score = `0.7 × share points + 0.3 × date points`. The points per band are ours (ACT names five
  maturity levels without numbers); the page shows `Band points are ours, not ACT's (ACT GE pp.139–140)`.
- Method `sale`: `note` `Sale, not closure: ACT counts this negatively (GE p.139)`.
- **Sector timeline (ACT Core D02.a)**: Power & Utilities 2040 (Core p.66 "2030/40"; the later year,
  **builder's call**), Shipping 2040, Heavy-Duty Road Transport 2035; others
  `No ACT Core sector timeline`. ACT asks for a phase-out of the whole high-emitting business, so only a
  share > 95 can meet it: `Meets the ACT Core timeline (<year>)` when share > 95 and year ≤ the
  timeline year; otherwise `Does not meet the ACT Core timeline (<year>)`.
- No counted phase-out: `phaseouts` `[]`; the page shows `No phase-out commitment disclosed`.

### 6. Scenario carbon price (ACT GE 5.3, GE p.89–90)

The benchmarks file gains a `scenario_prices` block (bundled file v2, owner-signed at PR review). It
is required in the bundled data directory and validated in any file that has the key; a file without
the key passes (**builder's call**: older signed files stay valid). It holds per region group, a source (title, page, URL, licence) and prices by year. Source: IEA, World
Energy Outlook 2024, Annex B, Table B.2 "CO2 prices for electricity, industry and energy production in
selected regions by scenario", p.329, USD (2023) per tonne CO2, CC BY 4.0. NZE rows used:

| Region group | 2030 | 2035 | 2040 | 2050 |
|---|---|---|---|---|
| Advanced economies with net zero pledges (all OECD except Mexico) | 140 | 180 | 205 | 250 |
| Selected EMDE with net zero pledges (China, India, Indonesia, Brazil, South Africa) | 90 | 125 | 160 | 200 |

Region mapping: European Union and United States → `advanced economies`; China → `selected EMDE`.
Validator lines (added to the benchmarks rules, exact): `Scenario prices: <group> has no source`,
`Scenario prices: missing`, `Scenario prices: unknown region group '<group>'`.

Carbon-price assumptions only (hydrogen assumptions get `scenario` `[]`). For each counted carbon-price
assumption, one entry per region: its stated region, or each operating region for `region:any`.
`assumption` is shown exactly as in the phase 2 comparison (converted to USD with the rule book's
conversions, original in brackets). Scenario price: the table value for that year; between table
years, linear interpolation; no year → `reason` `No scenario price for (no year)`; before 2030 or after
2050 → `No scenario price for <year>`; an assumption that cannot be converted → the phase 2
conversion reason. `scenario` = `<price> USD/tCO2 (IEA NZE <year>, <region group>)`,
`gap` = assumption − scenario, signed as in phase 2 (`+` when > 0, `-` when < 0); a zero gap is shown
as `0 USD/tCO2`; null with any reason.

### 6a. ACT cites shown on the page (exact)

Targets part: `ACT GE 1.4, GE pp.31–34`. Abatement coverage part: `ACT Core B02.c, Core p.37`.
Phase-out part: `ACT GE 9.2, GE pp.139–140; ACT Core D02.a, Core p.66`. Assumptions scenario column:
`ACT GE 5.3, GE pp.89–90; IEA WEO 2024 Table B.2, p.329`.

### 7. Interfaces

`TransitionOut` gains:
- `targets[]`: `key`, `scope`, `pct`, `year`, `base_year`, `base_emissions_shown`, `kind`
  (`past`, `running`, null), `ratio` (string, `fmt_number`, or null), `score` (number or null), `reason`,
  `citation`, `fact_ids[]`;
- `target_progress`: null or `score`, `text`;
- `coverage`: null or `target_key`, `percent`, `text`, `actions[]` (`key`, `saving_shown`,
  `summed`, `reason`), `reason`;
- `phaseouts[]`: `key`, `activity`, `share`, `year`, `method`, `share_points`, `date_points`,
  `score`, `reason`, `timeline_text`, `note`, `citation`, `fact_ids[]`;
- `assumptions[].scenario[]`: `region`, `year`, `scenario`, `assumption`, `gap`, `reason`.

`GET /api/transition-alignment/benchmarks` serves `scenario_prices` (per group: `group`, `citation`, `prices` by year).

### 8. Transition section

Three new parts after Plan actions: **Targets** (table per target plus the overall line),
**Abatement coverage** (one line plus the action list), **Phase-out** (table). The Assumptions table
gains a Scenario column group. Figures open their facts; ACT page cites shown in muted text.

## Constraints

- Model extracts only; code computes every number shown.
- Precision first; tests make no network or model calls.
- Owner signs benchmarks v2 (the scenario prices) at PR review.

## Left to the builder

Module layout, prompts, field instructions and keywords, UI layout within `DESIGN.md`, items marked
**builder's call**.

## Acceptance

### Fixtures (added to phase 2's)

Company C gains, as published facts (`approved`):

| Doc | Page | Quote | Facts |
|---|---|---|---|
| P2 | 52 | `Scope 1 emissions were 17.5 MtCO2e and scope 2 emissions 0.5 MtCO2e in 2025.` | `tp_h_scope1_emissions` 2025 = 17,500,000; `tp_h_scope2_emissions` 2025 = 500,000 |
| P2 | 53 | `In 2023 scope 1 emissions were 18 MtCO2e and scope 2 emissions 0.5 MtCO2e.` | 2023: 18,000,000 and 500,000 |
| P1 | 22 | `We will cut scope 1 and 2 emissions by 30% by 2030 from 20 MtCO2e in 2019; we set this target in 2021.` | target T1: `S1+2`, 30, 2030, base 2019, base 20 MtCO2e, set 2021 |
| P1 | 23 | `Our earlier target, set in 2020, was a 10% cut in scope 1 and 2 emissions by 2023 from 20 MtCO2e in 2019.` | target T0: `S1+2`, 10, 2023, base 2019, base 20 MtCO2e, set 2020 |
| P1 | 24 | `We will close two of our four blast furnaces by 2035.` | phase-out O1: `blast furnace steelmaking`, 50, 2035, `closure` |
| P7 | 4 | `We will close all our coal plants by 2038.` | P: phase-out O2: `coal power`, 100, 2038, `closure` (only where a row says so) |

New document P7 "Fixture Power Transition Plan 2025" (transition plan, as-of 2026-03-31), stored for P.
RY for C is 2025 (emissions); the plan RY for phase-outs is 2026 (P1 and P7 as-of).

**Benchmarks fixture BM-S** (a separate directory, version 4, signed, valid against F-TA): BM v3 plus
`scenario_prices` with the two NZE rows of section 6. BM stays as it is (no `scenario_prices` key), so
AC-3 to AC-8 and AC-67 behave as before. Rows AC-84 to AC-87 and AC-95 to AC-97 use BM-S.

**Snapshot S2**: `backend/tests/fixtures/transition_alignment/plan_actions_main.json`, recorded from
`main` at this spec's branch point: every phase-2 field of `sch_transition_plan_actions` with
`field_id`, `data_type`, `version`, `high_risk`, `extraction_instructions`.

### Rows

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-72 | the defaults | request for C | `targets` keys in order T1 (citation `Fixture Steel Transition Plan 2025 p.22`), T0 (`p.23`) | holdout |
| AC-90 | the defaults | request for C | T0 `kind` `past`, `ratio` `0.75`, `score` 50 | holdout |
| AC-91 | the defaults | request for C | T1 `kind` `running`, `ratio` `0.75`, `score` 75 | holdout |
| AC-73 | the defaults | request for C | `target_progress.text` `Target progress 68.75% (ACT GE 1.4)` | holdout |
| AC-74 | no 2023 `tp_h_scope2_emissions` fact | request for C | T0 `score` null, `reason` `No emissions for 2023` | holdout |
| AC-122 | no 2023 `tp_h_scope2_emissions` fact | request for C | `target_progress.text` `Target progress 75% (ACT GE 1.4)` | holdout |
| AC-75 | T1 has no `ta_target_base_emissions` | request for C | T1 `score` null, `reason` `No base-year emissions` | holdout |
| AC-92 | T1 has no `ta_target_base_emissions` | request for C | `target_progress.text` `Target progress 50% (ACT GE 1.4)` | holdout |
| AC-123 | T1 has no `ta_target_base_emissions` | request for C | `coverage.reason` `No base-year emissions` | holdout |
| AC-76 | T1's scope = `S1+2+3` | request for C | T1 `kind` null, `score` null, `reason` `Scope 3 target: progress not computed` | holdout |
| AC-93 | T1's target year = 2035 and set year = 2026 | request for C | T1 `kind` null, `reason` `Target year 2035 neither past nor running` | holdout |
| AC-94 | T1 has no `ta_target_pct` | request for C | T1 `score` null, `reason` `Incomplete target` | holdout |
| AC-99 | T1 has no `ta_target_set_year` | request for C | T1 `kind` null, `reason` `Target year 2030 neither past nor running` (set year defaults to P1's as-of year 2026, which is not ≤ RY − 1 = 2024) | holdout |
| AC-100 | T1's base emissions stated as 20,000,000 tCO2e | request for C | T1 `ratio` `0.75`, `score` 75 | holdout |
| AC-77 | the defaults | request for C | `coverage.text` `Listed actions cover 58.33% of the 2030 target gap (3.5 of 6 MtCO2e/yr)` | holdout |
| AC-101 | the defaults | request for C | `coverage.actions`: A1 `summed` true; A2 `summed` false, `reason` `No quantified saving`; A3 `summed` false, `reason` `No quantified saving` | holdout |
| AC-78 | A1's year = 2031 | request for C | A1 `summed` false, `reason` `After the target year` | holdout |
| AC-124 | A1's year = 2031 | request for C | `coverage.percent` null, `coverage.reason` `No summable action` | holdout |
| AC-102 | A1's saving = 10 `%` | request for C | A1 `reason` `Saving in % not summed` | holdout |
| AC-79 | no counted target | request for C | `coverage.reason` `No running target` | holdout |
| AC-103 | no counted target | request for C | `targets` `[]` and `target_progress` null | holdout |
| AC-80 | the defaults | request for C | O1 `share_points` 25, `date_points` 75, `score` 40 | holdout |
| AC-104 | the defaults | request for C | O1 `timeline_text` `No ACT Core sector timeline` | holdout |
| AC-81 | O2 published | request for P | O2 `share_points` 100, `date_points` 50, `score` 85 | holdout |
| AC-105 | O2 published | request for P | O2 `timeline_text` `Meets the ACT Core timeline (2040)` | holdout |
| AC-106 | O2 published with share 50 | request for P | O2 `timeline_text` `Does not meet the ACT Core timeline (2040)` | holdout |
| AC-107 | O1's year = 2031 | request for C | O1 `date_points` 100 | holdout |
| AC-108 | O1's share = 25, then 26 | request for C | `share_points` 0, then 25 | holdout |
| AC-109 | O1's share = 95, then 96 | request for C | `share_points` 75, then 100 | holdout |
| AC-110 | O1's year = 2046, then 2047 | request for C | `date_points` 25, then 0 | holdout |
| AC-82 | O1's method = `sale` | request for C | O1 `note` `Sale, not closure: ACT counts this negatively (GE p.139)` | holdout |
| AC-111 | O1 has no `ta_phaseout_share_pct` | request for C | O1 `score` null, `reason` `No share stated` | holdout |
| AC-83 | no phase-out fact | request for C | `phaseouts` `[]` | holdout |
| AC-112 | no phase-out fact | open C's company page | the Phase-out part reads `No phase-out commitment disclosed` | evaluator |
| AC-84 | the defaults, BM-S | request for C | the carbon-price assumption's `scenario` is one entry: `region` `European Union`, `year` 2030, `scenario` `140 USD/tCO2 (IEA NZE 2030, advanced economies)`, `assumption` `97.2 USD/tCO2 (90 EUR/tCO2)`, `gap` `-42.8 USD/tCO2` | holdout |
| AC-85 | BM-S; the carbon-price assumption's year = 2045 | request for C | `scenario` `227.5 USD/tCO2 (IEA NZE 2045, advanced economies)` | holdout |
| AC-86 | BM-S; the carbon-price assumption has no year | request for C | its entry has `scenario` null, `gap` null, `reason` `No scenario price for (no year)`, `assumption` `97.2 USD/tCO2 (90 EUR/tCO2)` | holdout |
| AC-95 | BM-S; the carbon-price assumption's year = 2028 | request for C | its entry has `reason` `No scenario price for 2028` | holdout |
| AC-96 | BM-S; the carbon-price assumption = 90 USD/tCO2, `region:China`, 2030 | request for C | `scenario` `90 USD/tCO2 (IEA NZE 2030, selected EMDE)`, `gap` `0 USD/tCO2` | holdout |
| AC-97 | BM-S, the defaults | request for C | the hydrogen assumption's `scenario` `[]` | holdout |
| AC-87 | BM-S with the advanced-economies source removed | `arp transition-alignment benchmarks validate` | exit 1; output contains `Scenario prices: advanced economies has no source` | holdout |
| AC-113 | the bundled data directories | `GET /api/transition-alignment/benchmarks` | `scenario_prices` has `advanced economies` 2030/2035/2040/2050 = 140/180/205/250 and `selected EMDE` = 90/125/160/200, each `citation` containing `p.329` | holdout |
| AC-88 | the defaults minus T1 and T0 (owner, 2026-10-20); an extraction run of `sch_transition_plan_actions` for C whose stub returns T1 from P1 p.22 | `GET /api/companies/C/facts?field_id=ta_target_pct` | one row, value 30, status `pending_review` | holdout |
| AC-125 | same as AC-88 | `GET /api/companies/C/facts` for the six `ta_target_*` fields | all six rows have the same `basis` | holdout |
| AC-114 | the defaults minus T1 (T0 kept); the extraction run of AC-88 | request for C | `targets` lists T0 only | holdout |
| AC-115 | the defaults minus O1; a run whose stub returns O1 from P1 p.24 | `GET /api/companies/C/facts?field_id=ta_phaseout_year` | one row, value 2035, status `pending_review` | holdout |
| AC-116 | P6 stored (AC-71's world) | request for C | `targets` `[]` and `phaseouts` `[]` | holdout |
| AC-117 | the defaults; the model client raises on any call | request for C | HTTP 200, `target_progress.text` `Target progress 68.75% (ACT GE 1.4)` | holdout |
| AC-118 | snapshot S2 | the phase-2 fields of `sch_transition_plan_actions` are built | every field's `field_id`, `data_type`, `version`, `high_risk`, `extraction_instructions` equal S2 | unit |
| AC-89 | none | open C's company page | the Targets part shows `Target progress 68.75% (ACT GE 1.4)` | evaluator |
| AC-119 | none | open C's company page | the Abatement coverage part shows the AC-77 text | evaluator |
| AC-120 | none | in C's Targets part, click T1's 30% | P1 opens at page 22 | evaluator |
| AC-121 | none | open C's company page | the Phase-out part shows `Band points are ours, not ACT's (ACT GE pp.139–140)` | evaluator |
| AC-126 | none | open C's company page | the Abatement coverage part shows `ACT Core B02.c, Core p.37` | evaluator |
| AC-127 | none | open C's company page | the Phase-out part shows `ACT GE 9.2, GE pp.139–140; ACT Core D02.a, Core p.66` | evaluator |
| AC-128 | none | open C's company page | the Assumptions part shows `ACT GE 5.3, GE pp.89–90; IEA WEO 2024 Table B.2, p.329` | evaluator |
| AC-129 | none | in C's Phase-out part, click O1's 2035 | P1 opens at page 24 | evaluator |

Must not change: every phase 1 and 2 row (AC-2 to AC-71, AC-43 to AC-55), including AC-31's
barrier comparison, AC-46 (barrier files and ratings), AC-47 (the four snapshot presets), AC-48;
AC-118 (the phase-2 plan-action fields).

## Decisions recorded

- 2026-10-20, owner: build research items 13.1, 13.2, 13.4, 13.7; IEA NZE as the scenario price
  source; skip further questions.
- Builder's calls (controller), marked above: scope 1+2 progress only; set year defaults to the plan
  as-of year; overall score with one missing dimension; earliest running target for coverage;
  power timeline 2040; phase-out RY = plan as-of year; band points 0/25/50/75/100.
