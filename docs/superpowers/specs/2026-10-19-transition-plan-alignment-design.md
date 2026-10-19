# Transition plan alignment: plan actions against barriers, capex credibility

Date: 2026-10-19
Status: draft for the owner's approval

## Intent

The transition barrier matrix rates, per sector and region, whether the conditions for
decarbonisation are in place (`docs/superpowers/specs/2026-10-17-transition-barrier-rule-book-design.md`).
Its rule book tags every criterion with the decarbonisation actions it limits, so that a company's
plan can be read against it. This project does that reading, one company at a time, and adds a
check on whether the company's money follows its plan.

Two questions per company:

- **A. Plan actions vs barriers.** What does the plan say the company will do, when, where, and
  under which assumptions? For each action and region: which barrier criteria limit it, how they
  are rated today, and how the plan's assumptions (for example its assumed carbon price) compare
  with the barrier evidence.
- **B. Capex credibility.** How much of its capex (and, for heavy industry and transport, its R&D)
  goes to low-carbon assets, measured against the sector benchmark ACT publishes, and does it
  breach an IEA NZE milestone?

Both results belong to the central company profile. The figures they rest on are ordinary company
facts: extracted with a quote and page, reviewed in the existing review queue, versioned, and shown
in the company viewer page. The methodology choices behind B are researched and cited in
`docs/CAPEX_ALIGNMENT_METHODOLOGY_RESEARCH.md`; this spec cites its sections rather than repeating
them.

## Goals

1. **Scope.** Companies whose ISIC code falls in one of the nine transition-barrier sectors (Power &
   Utilities, Steel, Cement, Chemicals, Critical Minerals & Mining, Aviation, Shipping, Heavy-Duty
   Road Transport, Oil & Gas Upstream), from the platform's existing company universe.
2. **Capex facts.** For the reporting year (RY) and the planned next year (RY+1): total capex,
   low-carbon capex amount and share. For RY: carbon-intensive capex where disclosed. For RY and
   RY−1: total R&D, low-carbon R&D (amount and share) and early-stage low-carbon R&D. Plus the
   redline facts (new unabated coal, new long-lead-time oil and gas projects). All are company
   facts with quotes.
3. **Capex score.** ACT Core D01.a's RY/RY+1 rule gives one share; code scores it as
   min(share / sector benchmark, 1). The R&D tests and redlines are shown next to it.
4. **A benchmarks file**, curated, cited and owner-signed like the barrier rule book, holds the
   sector benchmarks, R&D tests, redlines, ISIC scope, the ACT lever wording per rule-book action,
   and which barrier fact each plan assumption is compared with.
5. **Plan actions.** Each decarbonisation action in a transition plan or sustainability report is
   extracted with its status, year, region, GHG saving and funding, each with a quote and page, and
   classified to a rule-book action id. Operating regions (EU, US, China) are extracted as facts.
6. **Barrier match.** For each action × region, every barrier criterion that names the action, with
   its current rating and evidence. Each stated assumption appears next to the matching barrier
   figure, with the gap computed by code.
7. **ACT B02 tests** per action (B02.b timeframe, B02.c GHG saving, B02.d investment linked to the
   action) and B02.a for the plan.
8. **A Transition section** on the existing company page shows all of it, with a source for every
   number.

## Non-goals

- Locked-in emissions (needs asset-level data; research 13.4).
- ACT performance, narrative or trend scores; ACT Core letter grades; E01 and F01 trajectory tests;
  low-carbon patents (research 13.4).
- Portfolio or ETF aggregation (research 8.3, 9.3 item 7).
- WBA scores as a cross-check, the WBA Data Explorer and the undocumented WBA JSON feed (research
  9.3 item 8).
- Sectors outside the matrix (aluminium, autos as a car sector, agriculture). Adding one is data
  work in the matrix first.
- Changing the barrier rule book, its ratings, the 64-indicator transition plan assessment, or the
  green and EU Taxonomy presets.
- Editing benchmarks in the app. The file changes by pull request with a version bump the owner signs.

## Anti-goals (a failure even if it works)

- A threshold, factor or band that no cited source publishes (the uploaded template's 0.75 ×
  required, 10 pp red line and maturity ladder are the example; research 8.1, 8.3).
- The model outputs a score, ratio, rating, B02 result, gap or benchmark.
- A number shown on the Transition section that has no source a reader can open.
- Taxonomy-eligible but not aligned capex counted as low-carbon (ACT Core p.59; research 12.2.2).
- A missing figure shown as zero, or a missing redline fact shown as "not breached".
- A barrier rating or a bundled barrier data file changes because of this project.

## Current state (what this builds on)

Paths are under `backend/arp/` unless they start with `frontend/` or `docs/`.

- **Barrier matrix.** `transition_barrier/data/rule_book.json` (version 2): `actions` per sector (9
  sectors, 30 action ids such as `steel.h2_dri`), 35 criteria each naming the actions it limits, and
  a `conversions` table. `GET /api/transition-barrier/scores` and `GET /cells/{code}/{region}` give a
  cell's current rating (`basis` `hand_rated` or `derived`), evidence and, for derived cells, the
  counted values with citations. Regions: `schemas/transition_barrier.py::Region` (European Union,
  United States, China). Fingerprint and signing: `transition_barrier/rule_book.py`.
- **Field pipeline.** Presets (`presets/registry.py::PRESETS`) define `FieldDefinition`s
  (`schemas/datapoints.py`); a `DataPointSchema` can limit itself to ISIC prefixes
  (`sector_codes`, checked in `planning/applicability.py`). Extraction runs extract → verify →
  ground (`grounding.py::ground_citations`), queues items for review (run type `extraction`),
  and approved values become `company_facts` keyed by company, field, `period_end` and `basis`, with
  citations (`db/models.py`, `db/importer.py`). Statuses: `approved`, `auto_accepted`, `edited`,
  `pending_review`, `held`.
- **Existing capex fields.** `presets/green.py` (`capex_total`, `green_capex_total`,
  `green_capex_share_pct`, …) keeps nuclear and gas out of green; `presets/eu_taxonomy.py`
  (`eut_capex_aligned_pct`, `eut_capex_total_amount`). Neither has a planned year, a carbon-intensive
  amount or low-carbon R&D (research 9.1, 13.4).
- **Transition plan assessment.** `transition_plan/` and `presets/transition_plan.py`: 64 boolean
  indicators. No per-action records (research 13.4).
- **Company page.** `db/company_view.py` (summary, facts, fact trail with citations),
  `api/routers/companies.py` (`GET /companies/{ref}`, `/companies/{ref}/facts`,
  `/facts/{id}/trail`), `frontend/src/pages/Company.tsx` (summary, Facts table, trail drawer, a
  citation opens the stored PDF at its page).

## Design

### 1. Scope

A company is in scope when its `isic_code` starts with a prefix listed for a sector in the
benchmarks file. That sector is the company's matrix sector. Without an ISIC code, or with one no
sector lists, the Transition section says why (section 6). Both new presets set `sector_codes` to
the union of the listed prefixes, so the existing applicability check keeps them off other
companies.

The sectors are the barrier matrix's nine (owner decision 2026-10-19). Bundled prefixes (ISIC
Rev.4; **builder's call**, the owner can narrow): Power & Utilities `351`;
Oil & Gas Upstream `061`, `062`; Chemicals `201`; Steel `241`; Cement `2394`; Critical Minerals &
Mining `07`; Aviation `511`; Shipping `501`, `502`; Heavy-Duty Road Transport `2910`, `4923`.

**Runs are on demand only** (owner decision 2026-10-19). A person starts a run of one or both
presets for one company or for one sector through the existing `POST /api/extraction/start` (the
custom-schema profile, with the preset's schema id); for a sector, the in-scope companies of that
sector are passed as its `companies`. There is no backfill and no schedule.

### 2. The benchmarks file

`transition_alignment/data/benchmarks.json`, in a directory named by a new setting
`ARP_TRANSITION_ALIGNMENT_DATA_DIR` (default: the bundled one; tests point it at a fixture). Sketch
(field names beyond these are the builder's call):

```json
{
  "version": 1, "fingerprint": "<sha256>", "history": [{"version": 1, "approved_by": "...", "approved_at": "..."}],
  "licence_note": "Internal, non-commercial use, with citation (owner decision 2026-10-19).",
  "sectors": {
    "Steel": {
      "isic_prefixes": ["241"],
      "capex": {"value": 80, "unit": "%", "method": "ACT Core D01.a, generic row",
                "source": {"title": "ACT Core methodology", "url": "...", "page": "62"}, "licence": "..."},
      "rnd_tests": [
        {"id": "lc_share", "label": "Low-carbon share of R&D", "numerator": "tc_lowcarbon_rnd",
         "denominator": "tc_rnd_total", "value": 80, "unit": "%", "source": {...}},
        {"id": "early_stage", "label": "Early-stage share of low-carbon R&D", "numerator": "tc_lowcarbon_rnd_early",
         "denominator": "tc_lowcarbon_rnd", "value": 65, "unit": "%", "source": {...}}
      ],
      "redlines": [{"id": "stl_bf", "label": "No new blast furnace without CCS or a near-zero route",
                    "fact": "tc_new_blast_furnace",
                    "source": {"title": "owner-defined (2026-10-19)", "rationale": "..."}}]
    }
  },
  "act_levers": {"steel.scrap_eaf": {"wording": "...", "source": {...}}, "steel.h2_dri": null},
  "assumptions": {
    "carbon_price": {"label": "Assumed carbon price", "unit": "USD/tCO2",
                     "barrier_facts": ["STL-R1.price", "CEM-R1.price", "PWR-R1.price"]},
    "h2_cost": {"label": "Assumed hydrogen cost", "unit": "USD/kg H2",
                "barrier_facts": ["STL-T1.h2_cost", "CHM-T1.lc_cost"]}
  }
}
```

Every redline names a boolean field of the capex preset (`fact`) and a source.

**Content of version 1** (the owner's decisions, each figure cited in the file):

| Sector | Capex benchmark | Source (research section) | R&D tests | Redline |
|---|---|---|---|---|
| Power & Utilities | 95% | ACT Core p.62, ACT Electricity pp.50–51 (12.2.2, 13.2.2) | none | `pwr_coal` "No new unabated coal plants", IEA NZE 2023 p.81 (5) |
| Oil & Gas Upstream | 77% | ACT Core p.62 (12.2.2) | none | `ogu_new_projects` "No new long-lead-time conventional oil and gas projects approved after 2023", IEA NZE 2023 p.76 (5, 8.2) |
| Chemicals | 77% | ACT Core p.62 | none | none |
| Heavy-Duty Road Transport | 80% | ACT Core p.62, automotive row; ACT Auto pp.38–41 (10.6) | none | none |
| Steel | 80% | ACT Core p.62, generic row; ACT Generic p.47 (13.2.2) | low-carbon share of R&D 80%; early-stage share of low-carbon R&D 65% (ACT Iron & Steel pp.75–76; 10.6) | `stl_bf` "No new blast furnace without CCS or a near-zero route", owner-defined (2026-10-19) |
| Cement | 80% | as Steel | low-carbon R&D ÷ total capex 5% (ACT Cement pp.51–53; 10.6) | none |
| Aviation | 80% | as Steel | low-carbon share of R&D 80% (ACT Transport v2.1 pp.57–58; 10.6) | none |
| Shipping | 80% | as Steel | as Aviation | none |
| Critical Minerals & Mining | 80% | as Steel | none | none |

`stl_bf` is an owner-defined redline (owner decision 2026-10-19), evaluated like the others. IEA
NZE 2023 has no such milestone (research 8.2), so its source reads `owner-defined (2026-10-19)`,
with the rationale: a new blast furnace locks in coal-based ironmaking for decades. Relining or
rebuilding an existing furnace at the same capacity is not new build.

Notes on this table, each the **builder's call** for the owner to check:

- The oil and gas redline uses the NZE 2023 wording (p.76), not the 2021 "no new fields" wording
  (research 8.2 notes the cut-off moved).
- Coal phase-out dates (NZE 2023 p.92) are milestones, not capex redlines, and are not included.
- Aviation and shipping use the 80% R&D test, not its 50% variant for mostly-subcontracted
  operators. Mining gets no R&D test. Steel's two R&D tests are shown side by side, not combined
  (ACT's 50/50 weighting of GE 3.1 is a sector-score weight, which is a non-goal).
- Heavy-Duty Road Transport uses the ACT Core automotive row (also 80%).

**ACT lever wording.** `act_levers` maps every action id of the active rule book to the ACT
Core lever wording and page from research 13.4(a), or to `null` where ACT Core has none
(`steel.h2_dri`, `steel.ccus`, `min.new_supply`). It is a mapping, not a rename: rule-book ids and
labels stay as they are.

**What counts as low-carbon** (the extraction definition of every low-carbon field): ACT's
definition, so nuclear and CCS/CCUS count (owner decision; research 9.3 item 4). EU
Taxonomy-aligned spending counts; eligible-but-not-aligned never does; a company's own definition
counts only if it says what it includes (ACT Core p.59). `presets/green.py` keeps its own
definition: the new fields are separate fields.

**Versioning and validation.** Fingerprint and `sign` work exactly as for the barrier rule book
(spec 2026-10-17 section 1, Versioning; reuse its code). `arp transition-alignment benchmarks
validate [--data-dir <dir>]` and the app loader check the file against the capex preset and the
**active** barrier data directory (`ARP_TRANSITION_BARRIER_DATA_DIR`). The validator prints every
error, one per line, and exits 1 if there is any; the app refuses to start, naming the first.

**Sectors and actions** (**builder's call (controller)**): the nine matrix sector names are a fixed
list in code; a unit test checks it equals the sectors of the **bundled** `criteria_schema.json`.
A benchmarks sector must be on that list. Every sector of the active directory's criteria needs an
entry; extra listed sectors are allowed. Action ids are checked against the active rule book's
`actions`: `act_levers` covers every one of them and names no other. So a fixture directory with
only Steel criteria works with a benchmarks file holding Steel, Power and Cement. Errors:

1. `Sector not in the transition-barrier matrix: <name>` (not on the fixed list);
   `Missing benchmarks entry: <sector>` (a sector of the active criteria);
2. `<sector>: capex benchmark has no source`; `<sector>: R&D test '<id>' has no source`;
   `<sector>: redline '<id>' has no source`;
3. `<sector>: unknown field '<field id>'` (an R&D test or redline naming a field the capex preset
   lacks);
4. `ISIC prefix '<p>' is in two sectors` (also when one prefix starts with another);
5. `No ACT lever entry for action: <id>`; `Unknown action in act_levers: <id>`;
6. `Assumption '<id>' names unknown barrier fact '<code>.<fact>'`;
   `Assumption '<id>' is in <unit>, '<code>.<fact>' is in <unit>`;
7. `Benchmarks content changed but version is still <n>`.

On success: `Benchmarks v<version>: OK, <n> sectors, <r> redlines`.

### 3. Capex facts and the D01.a score (Part B)

**Preset `sch_transition_capex`.** One value per fiscal year disclosed (`period_end` = fiscal year end),
amounts in the reporting currency with the unit as in `green.py` (`EUR million`). Every field is
high-risk (blind verification), like the green preset.

**Currency** (**builder's call (controller)**): capex, R&D and action amounts stay in the company's
reporting currency with their unit and are never converted. Shares and ratios are currency-free.
A share is computed from amounts only when both have the same unit; B02.d compares needed and
allocated only within one unit (section 5). The one conversion in this project is the barrier rule
book's existing `conversions` table, used only to put a plan assumption in a barrier fact's unit
(section 4).

| Field id | Type | Definition (abridged) |
|---|---|---|
| `tc_capex_total` | currency amount | Total capex for the year, the denominator the company uses with its low-carbon share |
| `tc_capex_denominator` | enum `eu_taxonomy`, `cash_flow`, `other` | Which total that is (research 9.1 item 4) |
| `tc_lowcarbon_capex` | currency amount | Low-carbon capex, definition in section 2 |
| `tc_lowcarbon_capex_share_pct` | percentage | Low-carbon capex share as disclosed |
| `tc_capex_total_planned` | currency amount | Total capex planned for a future year |
| `tc_lowcarbon_capex_planned` | currency amount | Low-carbon capex planned for a future year |
| `tc_lowcarbon_capex_share_pct_planned` | percentage | Planned low-carbon share for a future year |
| `tc_carbon_intensive_capex` | currency amount | Capex on fossil or carbon-intensive assets (CA100+ 6.1.b; research 9.1 item 1) |
| `tc_rnd_total` | currency amount | Total R&D spend |
| `tc_lowcarbon_rnd` | currency amount | R&D on low-carbon technologies |
| `tc_lowcarbon_rnd_share_pct` | percentage | Low-carbon share of R&D as disclosed (new) |
| `tc_lowcarbon_rnd_early` | currency amount | Low-carbon R&D on early-stage (not yet mature) technology |
| `tc_new_unabated_coal` | boolean | The company builds, approves or plans a new unabated coal plant |
| `tc_new_blast_furnace` | boolean | The company builds, approves or plans new blast furnace capacity without CCS or a near-zero route; relining or rebuilding an existing furnace at the same capacity is not new build |
| `tc_new_oil_gas_project` | boolean | The company approved a new long-lead-time conventional oil or gas project after 2023 |

Planned values are separate fields rather than a new `basis`, so a later report's actual figure for
the same year never replaces a plan. **Builder's call.**

**Which facts count.** A fact counts when it is current (`valid_to` null) and its status is
`approved`, `auto_accepted` or `edited`. Pending and held facts are ignored.

**Reporting year.** RY is the latest fiscal year with a counted `tc_capex_total`,
`tc_lowcarbon_capex` or `tc_lowcarbon_capex_share_pct`. RY+1 is the next fiscal year; RY−1 the one
before.

**The share for a year.** The disclosed share if counted; otherwise the low-carbon amount ÷ total
for that year, when both are counted and have the same unit (`computed from amounts`). Disclosed
wins when both exist. **Builder's call.** For RY+1 the same, from the planned fields.

**D01.a year rule** (owner decision; ACT Core p.61; research 9.3 item 8):

| RY share | RY+1 share | Share used | `rule` |
|---|---|---|---|
| known | none | RY | `Only RY known: RY used` |
| known | higher | RY+1 | `RY+1 higher: RY+1 used` |
| known | equal | RY | `RY+1 equal: RY used` |
| known | lower | (RY + RY+1) ÷ 2 | `RY+1 lower: average of RY and RY+1` |
| none | any | not scored | `not_scored` = `No reporting-year low-carbon capex share` |

**Score** = min(share used ÷ sector benchmark, 1), continuous (owner decision, research 13.4(c);
ACT Core bands are not used). Display follows the barrier rule book (at most two decimals, rounded
half up on the decimal value, trailing zeros dropped: `0.25`, `0.13`, `1`).

**R&D tests.** Each test's ratio = numerator ÷ denominator for a year (the disclosed
`tc_lowcarbon_rnd_share_pct` stands in for the `lc_share` ratio when counted). RY is the capex
reporting year above; R&D has no reporting year of its own. Years combine with the
same rule shifted back one year (ACT Core p.61): RY is required (`not_scored` =
`No reporting-year R&D figures`); `Only RY known: RY used`; `RY higher: RY used`;
`RY equal: RY used`; `RY lower: average of RY-1 and RY`. Score = min(ratio ÷ test value, 1).

**Redlines.** Status per redline: `breached` (its fact counted as Yes), `not breached` (counted
as No), `no disclosure` (no counted fact).

### 4. Plan actions, regions and assumptions (Part A)

**Preset `sch_transition_plan_actions`**, read from transition plans and sustainability reports. A plan
holds many actions, so the action fields repeat: the facts of one action share one `basis` value
(for example `action:3`) and have no `period_end`. How the list is extracted, and how one action's
facts are keyed and reviewed together, is the builder's call; the values pass the existing quote
checks and go through the existing review queue and publish path, so each is an ordinary company
fact with a citation and versions.

| Field id | Type | Definition (abridged) |
|---|---|---|
| `ta_action_text` | string | The action as the plan states it: one specific measure, technology or asset (vague intentions are not actions; ACT Core p.34) |
| `ta_action_id` | enum: the company's sector's rule-book action ids, plus `other` | Classification of the action |
| `ta_action_status` | enum `implemented`, `planned` | |
| `ta_action_year` | number (year) | Year the action is (or was) in operation; none if not stated |
| `ta_action_region` | enum `European Union`, `United States`, `China`, `other` | Where the action takes place, if stated |
| `ta_action_ghg_saving` | number, unit `tCO2e/yr`, `MtCO2e/yr` or `%` | Quantified saving the plan links to this action |
| `ta_action_capex_needed` | currency amount | Investment the action needs |
| `ta_action_capex_allocated` | currency amount | Funds allocated or approved for it |
| `ta_operates_eu`, `ta_operates_us`, `ta_operates_cn` | boolean | The company owns or operates production sites, plants, fleets or fields in that region |
| `ta_assumed_carbon_price` | number, unit `<currency>/tCO2` | A carbon price the plan assumes; `basis` `region:<Region>` or `region:any`; `period_end` 31 Dec of the year it applies to, if stated |
| `ta_assumed_h2_cost` | number, unit `<currency>/kg H2` | A hydrogen cost the plan assumes; keyed as above |

A classification outside the enum is refused like any enum value, with reason
`Unknown action id '<id>'`. The model classifies; code checks the id.

**Which plan counts** (**builder's call (controller)**): actions come only from the company's most
recent transition plan document, by as-of (publication) date; on a tie, the one uploaded last.
Action facts from older plans or from other documents are not counted: they appear only in the fact
trail. No de-duplication across documents.

**Order.** Actions are listed by document, then page, then order on the page. Barrier entries and
assumption comparisons are listed by region (European Union, United States, China), then criterion
code.

**Operating regions** are the regions whose `ta_operates_*` fact counts as Yes, in Region order.

**Action regions.** An action with a counted `ta_action_region` in the three regions is matched in
that region only; with `other`, in none. An action without one is matched in every operating region
(**builder's call**). With no operating region either, the action shows the note
`No operating region disclosed` and no barriers.

**Barrier match.** For each action with a rule-book id and each of its regions: every criterion
whose `actions` names that id, with the cell's current `rating`,
`basis` and `evidence` from the barrier API, and, for a derived cell, the counted `values[]` of its
current ratified result with their citations. The match reads the barrier API's data only; it never
derives, ratifies or writes anything there.

**Assumptions vs evidence.** For each counted assumption, each barrier fact the benchmarks file
lists for its kind is compared when its criterion names one of the company's actions, in: the
assumption's region if stated, else every region of those actions. Each comparison shows:

- `assumption`: the value in the barrier fact's unit, converted with the rule book's `conversions`
  table (its rate-choice rule, with the assumption's document as-of date), followed by the
  extracted value in brackets when converted: `97.2 USD/tCO2 (90 EUR/tCO2)`;
- `evidence`: `<value shown> (<document title>, p. <page>)` for each counted value of that fact in
  the cell's current result, joined with `, `; for a hand-rated cell
  `hand-rated, no figure: <cell evidence>`; for a derived cell without a counted value
  `no counted value`;
- `gap` = assumption − evidence, with sign and unit (`+25.2 USD/tCO2`, `-3 USD/kg H2`), only when
  there is exactly one evidence value; otherwise null. No judgement word is attached.

An assumption that cannot be converted shows `assumption` null and the conversion reason from the
rule book (`Unit not convertible: …`).

### 5. B02 tests (Part A)

Code computes these from the action's counted facts (owner decision for B02.d; ACT Core pp.32–37;
research 13.2.3, 13.4(b)):

| Test | Per action | `met` | `text` |
|---|---|---|---|
| B02.b timeframe | status `implemented` | true | `implemented (<year>)`, or `implemented` without a year |
| | planned, year ≤ 2030 | true | `near term (<year>)` |
| | planned, year ≥ 2031 | true | `long term (<year>)` |
| | planned, no year | false | `No timeframe: ignored` |
| B02.c saving | saving counted | true | `<value> <unit>`, e.g. `3.5 MtCO2e/yr` |
| | none | false | `No quantified GHG saving` |
| B02.d investment | needed and allocated both counted, same unit | true | `<needed> needed, <allocated> allocated`, e.g. `1500 EUR million needed, 600 EUR million allocated` |
| | both counted, units differ | false | `Needed and allocated in different currencies` |
| | only one counted | false | `No split of funds needed and allocated` |
| | neither | false | `No funding stated` |

B02.d's "clear link between the action and the money" is met by construction: the amounts are
extracted as attributes of that action, each with its own quote, and a reviewer approves them.

**B02.a** for the plan: met when at least 3 actions are `implemented` and at least 1 `planned` action
has a timeframe; actions with `No timeframe: ignored` are not counted. Text:
`met: <i> implemented, <p> planned with a timeframe` or
`not met: <i> implemented, <p> planned with a timeframe (needs 3 and 1)`. ACT's "4 considered for a
new plan" variant is not applied (**builder's call**; the platform cannot tell a new plan).

### 6. The Transition section

A new section on `frontend/src/pages/Company.tsx`, after the summary, fed by
`GET /api/companies/{ref}/transition`. Layout is the builder's call, following `DESIGN.md`. It shows:

- **Out of scope:** only `Not in scope: <reason>`, where reason is
  `ISIC <code> is not in a transition-barrier sector` or `No ISIC code`.
- **Capex check:** the share used and its rule, the benchmark with method and citation, the ratio,
  the RY and RY+1 shares and amounts, carbon-intensive capex, each R&D test, each redline with its
  status, and the licence note. Headline text:
  `Low-carbon capex <share used>% vs benchmark <benchmark>%: <ratio shown>`, or
  `Capex not scored: <reason>`.
- **Plan actions:** per action its text, rule-book id and ACT lever wording (or
  `No ACT Core lever wording`), status, timeframe, region; per region the matched criteria with
  rating and evidence; the B02 results; B02.a for the plan.
- **Assumptions vs evidence:** each comparison with assumption, evidence and gap.
- **Sources:** every number that comes from a company fact opens that fact's trail (the existing
  drawer and PDF viewer); every barrier figure opens its barrier citation.

The existing Facts table lists the new facts like any other.

### 7. Interfaces

CLI under `arp transition-alignment`:

- `benchmarks validate [--data-dir <dir>]`, `benchmarks sign --approved-by <name> [--data-dir <dir>]`;
- `golden --cases <file> --documents-dir <dir> --min-precision <x> --min-coverage <y>`: prints
  `precision <p>, coverage <c>` and exits 0 only when both meet their minimum (section 8).

API:

- `GET /api/transition-alignment/benchmarks`: `version`, `licence_note`, and per sector `sector`,
  `isic_prefixes`, `capex` (`value`, `unit`, `method`, `citation`, `licence`), `rnd_tests[]`,
  `redlines[]` (`id`, `label`, `fact`, `citation`).
- `GET /api/companies/{ref}/transition`, response fields (the names the acceptance rows read):
  - `in_scope`, `reason` (null when in scope), `sector`, `benchmarks_version`, `rule_book_version`;
  - `capex`: `reporting_year`, `share_ry` and `share_ry1` (each null or `value`, `source`
    `disclosed` or `computed from amounts`, `fact_ids[]`), `share_used`, `rule`, `benchmark`
    (`value`, `method`, `citation`), `ratio`, `ratio_shown`, `not_scored`, `amounts[]` (`field_id`,
    `year`, `shown`, `fact_id`, `citation`), `rnd_tests[]` (`id`, `label`, `used`, `rule`,
    `benchmark`, `ratio_shown`, `not_scored`), `redlines[]` (`id`, `status`, `text`, `citation`);
  - `regions[]`; `actions[]`: `key`, `action_id`, `act_lever` (null or `wording`, `citation`),
    `text`, `status`, `year`, `region`, `citation`, `timeframe`, `b02` (`b`, `c`, `d`, each `met`,
    `text`), `barriers[]` (`code`, `region`, `rating`, `basis`, `evidence`, `values[]`), `note`;
  - `b02a` (`met`, `text`); `assumptions[]`: `kind`, `region`, `year`, `citation`, `comparisons[]`
    (`code`, `region`, `assumption`, `evidence`, `gap`).
- A `citation` for a company fact reads `<document title> p.<page>`, as the Facts table's source
  label does.

Request/response model changes follow the API contract steps in `.claude/CLAUDE.md`.

### 8. Golden set

Two sets, labels drafted by the builder and checked by the owner before phase 3 merges:

- **Capex fields:** at least 40 values from at least 10 annual or sustainability reports across at
  least 5 of the nine sectors, including at least 5 planned-year values, 5 R&D values and 3 cases
  where only taxonomy-eligible capex is disclosed (correct answer: `not_found` for
  `tc_lowcarbon_capex`). Run with the existing `arp golden-set precision --schema sch_transition_capex`.
- **Plan actions:** at least 30 actions from at least 8 plans across at least 5 sectors. Each case:
  `{document, action_id, status, year, region, page}`. A counted action is correct when its
  `action_id`, `status`, `year` and `region` equal the label and its page equals the label's.
  precision = correct counted actions ÷ counted actions; coverage = labelled actions matched by a
  counted action ÷ labelled actions, where a labelled action is matched by a counted action from the
  same document and page with the same `action_id` (status, year and region may differ). Format and location as in the barrier spec section 8. The
  minimum precision is 0.9, not 0.95, because a case is correct only when four attributes all
  match (**builder's call**).

CI runs both when a PR touches `arp/transition_alignment` or the two presets (the golden-set
trigger list in CI gains these paths).

### 9. Build order

Each phase is one pull request.

1. **Benchmarks and capex.** Benchmarks file, validator, `sign`, `/benchmarks`; `sch_transition_capex`
   preset; scope; D01.a, R&D tests, redlines; `/companies/{ref}/transition` with `capex`; the
   Transition section's capex part. The owner signs benchmarks version 1 here.
2. **Plan actions.** `sch_transition_plan_actions` preset and list extraction, classification check,
   regions, barrier match, assumptions vs evidence, B02; the rest of the section.
3. **Golden sets** and the CI trigger.

## Constraints

- The model extracts values, quotes and classifications. It never outputs a score, ratio, rating,
  B02 result, gap, benchmark or redline status.
- Precision first: "not scored" or "no disclosure" beats a wrong figure that counts.
- Tests make no network and no model calls (`FakeLLMClient`, stubbed fetch).
- The owner checks golden-set labels.
- At most three agent PRs in flight (`.claude/skills/steward/SKILL.md`).

## Left to the builder

- Module layout, table names, JSON field names beyond the sketch.
- How the action list is extracted and how one action's facts are keyed and reviewed together.
- Prompts, retrieval settings, the fields' full extraction instructions.
- Screen layout and wording beyond the strings in this spec.
- The fixture documents' wording, as long as the quotes and pages below hold.
- Every item marked **builder's call** above, which the owner checks at approval.

## Acceptance

Each section names its phase (section 9). Until HOLDOUT_TOKEN is set, holdout rows run as unit and
are listed as owed in the PR.

### Fixtures

**Barrier data directory F-TA**: criteria `STL-T1` then `STL-R1`; rule book version 7, signed, whose
`actions` hold Steel only (`steel.h2_dri`, `steel.scrap_eaf`, `steel.ccus`), with conversion EUR →
USD 1.08 (2025). F-TA is the active barrier directory (`ARP_TRANSITION_BARRIER_DATA_DIR`) in every
row unless a row says "the bundled data directory", including AC-3 to AC-8.

- `STL-T1` names `steel.h2_dri`; fact `h2_cost` "Renewable hydrogen cost" (USD/kg H2); `H` =
  `h2_cost <= 2`, `M` = `h2_cost <= 7` (as parameters).
- `STL-R1` names all three actions; facts as the barrier spec's fixture (`price` "Effective carbon
  price", `applies`, `levy`).
- Hand ratings, all `L`, `last_verified` 2026-08-14, with evidence:

  | Cell | Evidence |
  |---|---|
  | `STL-R1` European Union | `EU ETS price below the cost gap.` |
  | `STL-R1` United States | `No federal carbon price applies to steel.` |
  | `STL-R1` China | `National ETS price too low to matter.` |
  | `STL-T1` European Union | `Hydrogen cost above breakeven.` |
  | `STL-T1` United States | `Hydrogen cost well above breakeven.` |
  | `STL-T1` China | `No renewable hydrogen supply at scale.` |

- Ratified in setup through the barrier API, so these become the current ratings: `STL-R1`
  European Union `H` from `price` 72 (D1 "EU ETS Market Report 2026", p. 12), `applies` Yes, `levy`
  Yes; `STL-T1` European Union `M` from `h2_cost` 6 (D5 "Hydrogen Cost Review 2026", p. 7).

**Benchmarks fixture BM** (`ARP_TRANSITION_ALIGNMENT_DATA_DIR`), version 3, signed, valid against
F-TA: sectors Steel (prefix `241`, capex 80%, R&D tests `lc_share` 80% and `early_stage` 65%,
redline `stl_bf` on `tc_new_blast_furnace`, source `owner-defined (2026-10-19)`), Power & Utilities (prefix `351`, 95%, redline `pwr_coal` on
`tc_new_unabated_coal`, source "Net Zero Roadmap 2023" p. 81) and Cement (prefix `2394`, 80%, R&D
test `capex_share` = `tc_lowcarbon_rnd` ÷ `tc_capex_total`, 5%). `act_levers`: `steel.scrap_eaf` →
`More scrap, process efficiency, zero-GHG power` (ACT Core p.110), `steel.h2_dri` and `steel.ccus` →
null. Assumptions: `carbon_price` (USD/tCO2) → `STL-R1.price`; `h2_cost` (USD/kg H2) →
`STL-T1.h2_cost`.

**Companies:** C "Fixture Steel AG" (ISIC `2410`, fiscal year end 12-31); P "Fixture Power plc"
(`3510`); K "Fixture Cement SA" (`2394`); Q "Fixture Foods SA" (`1050`); N "Fixture Holdings Ltd"
(no ISIC code).

**Documents** (PDF): P1 "Fixture Steel Transition Plan 2025" (transition plan, as-of 2026-03-31);
P2 "Fixture Steel Annual Report 2025" (annual report, as-of 2026-03-31); P3 "Fixture Steel
Transition Plan 2023" (transition plan, as-of 2024-03-31); P4 "Fixture Power Annual Report 2025"
(as-of 2026-03-31); P5 "Fixture Foods Report 2025" (as-of 2026-03-31).

| Doc | Page | Quote | Facts |
|---|---|---|---|
| P2 | 3 | `We operate steelworks in Germany, Sweden, the United States and China.` | C: `ta_operates_eu`, `_us`, `_cn` Yes |
| P2 | 44 | `Total capital expenditure was EUR 1,000 million in 2025.` | C: `tc_capex_total` 2025 = 1000 EUR million |
| P2 | 45 | `Low-carbon capital expenditure was EUR 120 million, 12% of total capex.` | C: `tc_lowcarbon_capex` 2025 = 120 EUR million; `tc_lowcarbon_capex_share_pct` 2025 = 12 |
| P2 | 46 | `Capital expenditure on blast furnace relining was EUR 300 million.` | C: `tc_carbon_intensive_capex` 2025 = 300 EUR million |
| P2 | 47 | `Green capex was 15% of total capex.` | C: `green_capex_share_pct` 2025 = 15 |
| P2 | 48 | `We are not building any new blast furnace capacity.` | C: `tc_new_blast_furnace` No (the p. 46 relining is not new build) |
| P2 | 50 | `R&D spending was EUR 50 million, of which EUR 30 million on low-carbon technologies and EUR 15 million on early-stage low-carbon technologies.` | C, 2025: `tc_rnd_total` 50, `tc_lowcarbon_rnd` 30, `tc_lowcarbon_rnd_early` 15 (EUR million) |
| P2 | 51 | `In 2024 R&D spending was EUR 40 million, of which EUR 20 million on low-carbon technologies and EUR 12 million on early-stage low-carbon technologies.` | C, 2024: 40, 20, 12 |
| P1 | 12 | `We will commission a 2 Mt hydrogen-based DRI plant in Sweden by 2028.` | action A1: `steel.h2_dri`, planned, 2028, European Union |
| P1 | 13 | `The DRI project needs EUR 1,500 million, of which EUR 600 million is approved.` | A1 needed 1500, allocated 600 EUR million |
| P1 | 14 | `The DRI plant will cut emissions by 3.5 MtCO2e a year.` | A1 saving 3.5 MtCO2e/yr |
| P1 | 15 | `Our electric arc furnace in Ohio has run on scrap since 2022.` | action A2: `steel.scrap_eaf`, implemented, 2022, United States |
| P1 | 16 | `We are studying carbon capture at our Tianjin plant.` | action A3: `steel.ccus`, planned, no year, China |
| P1 | 17 | `Since 2023 we recover waste heat at our Duisburg plant.` | action A4: `other`, implemented, 2023, European Union (published only where a row says so) |
| P1 | 18 | `We plan capital expenditure of EUR 1,100 million in 2026, of which 20% is low-carbon.` | C: `tc_capex_total_planned` 2026 = 1100; `tc_lowcarbon_capex_share_pct_planned` 2026 = 20 |
| P1 | 19 | `Our Ohio plant has used renewable electricity since 2024.` | action A5: `other`, implemented, 2024, United States (published only where a row says so) |
| P1 | 20 | `Our plan assumes a carbon price of EUR 90/tCO2 in the EU by 2030.` | C: `ta_assumed_carbon_price` 90 EUR/tCO2, `region:European Union`, 2030 |
| P1 | 21 | `We assume renewable hydrogen at USD 3/kg.` | C: `ta_assumed_h2_cost` 3 USD/kg H2, `region:any` |
| P3 | 5 | `We will build a coke oven gas recovery unit by 2025.` | action A6: `other`, planned, 2025, European Union (published only where a row says so) |
| P4 | 9 | `We started building a 600 MW unabated coal plant in 2025.` | P: `tc_new_unabated_coal` Yes (published only where a row says so) |
| P5 | 8 | `Capital expenditure was EUR 200 million.` | Q: `capex_total` 2025 = 200 EUR million |

**Defaults**, unless a row says otherwise: every fact in the table not marked "only where a row
says so" is a published company fact (status `approved`, with its citation), seeded in the test
database; the extraction stub returns `not_found`; requests are
`GET /api/companies/<company>/transition`. A row's Given replaces only the facts it names; "no X"
means X has no counted fact.

**Snapshot S**: `backend/tests/fixtures/transition_alignment/presets_main.json`, recorded from `main`
at the phase 1 branch point: for each of `sch_green_lowcarbon`, `sch_eu_taxonomy`,
`sch_esg_remuneration` and `transition_plan_indicators` (the `PRESETS` keys in
`backend/arp/presets/registry.py`), every field's `field_id`, `data_type`, `version`, `high_risk`
and `extraction_instructions`.

### Benchmarks file (phase 1)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| ~~AC-1~~ | | | Retired: the open-redline count is gone; replaced by AC-66. | |
| AC-66 | the bundled data directory (barrier and benchmarks) | `arp transition-alignment benchmarks validate` | exit 0; prints `Benchmarks v<version in benchmarks.json>: OK, 9 sectors, 3 redlines` | holdout |
| AC-2 | the bundled data directory | `GET /api/transition-alignment/benchmarks` | `capex.value` is 95 for Power & Utilities, 77 for Oil & Gas Upstream and Chemicals, 80 for the other six sectors; each has a `citation` naming its page | holdout |
| AC-3 | BM with Steel's capex `source` removed | `benchmarks validate --data-dir BM` | exit 1; output contains `Steel: capex benchmark has no source` | holdout |
| AC-4 | BM with a sector `Aluminium` added | `benchmarks validate --data-dir BM` | exit 1; output contains `Sector not in the transition-barrier matrix: Aluminium` | holdout |
| AC-5 | BM with Cement's prefix changed to `24` | `benchmarks validate --data-dir BM` | exit 1; output contains `ISIC prefix '24' is in two sectors` | holdout |
| AC-6 | BM with the Steel capex value changed to 75 and not signed | `benchmarks validate --data-dir BM` | exit 1; output contains `Benchmarks content changed but version is still 3` | holdout |
| AC-7 | BM with `steel.ccus` removed from `act_levers` | `benchmarks validate --data-dir BM` | exit 1; output contains `No ACT lever entry for action: steel.ccus` | holdout |
| AC-8 | BM with `h2_cost` listing `STL-R1.price` | `benchmarks validate --data-dir BM` | exit 1; output contains `Assumption 'h2_cost' is in USD/kg H2, 'STL-R1.price' is in USD/tCO2` | holdout |
| ~~AC-56~~ | | | Retired: the open-redline count is gone; replaced by AC-67. | |
| AC-67 | AC-6's BM | `benchmarks sign --approved-by owner --data-dir BM`, then `benchmarks validate --data-dir BM` | `version` 4; the last `history` entry has `version` 4 and `approved_by` `owner`; validate exits 0 and prints `Benchmarks v4: OK, 3 sectors, 2 redlines` | holdout |
| AC-57 | AC-3's BM | the API starts | startup fails with an error containing `Steel: capex benchmark has no source` | holdout |
| AC-64 | BM with an `act_levers` entry `pwr.renewables` (not in F-TA's rule book) | `benchmarks validate --data-dir BM` | exit 1; output contains `Unknown action in act_levers: pwr.renewables` | holdout |

### Capex check (phase 1)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-9 | the defaults | request for C | `in_scope` true; `sector` `Steel`; `capex.reporting_year` 2025; `share_used` 20; `rule` `RY+1 higher: RY+1 used`; `benchmark.value` 80; `ratio_shown` `0.25` | holdout |
| AC-10 | `tc_lowcarbon_capex_share_pct_planned` 2026 = 8 | request for C | `share_used` 10; `rule` `RY+1 lower: average of RY and RY+1`; `ratio_shown` `0.13` | holdout |
| AC-11 | no `tc_lowcarbon_capex_share_pct_planned` | request for C | `share_used` 12; `rule` `Only RY known: RY used`; `ratio_shown` `0.15` | holdout |
| AC-12 | no `tc_lowcarbon_capex_share_pct` (2025) | request for C | `share_ry.value` 12; `share_ry.source` `computed from amounts` | holdout |
| AC-13 | no 2025 `tc_lowcarbon_capex_share_pct`, `tc_lowcarbon_capex` or `tc_capex_total` (other 2025 facts kept) | request for C | `ratio` null; `not_scored` `No reporting-year low-carbon capex share` | holdout |
| AC-14 | P with `tc_lowcarbon_capex_share_pct` 2025 = 97 | request for P | `benchmark.value` 95; `ratio_shown` `1` | holdout |
| AC-15 | the defaults | request for C | `amounts[]` holds `tc_carbon_intensive_capex` 2025 with `shown` `300 EUR million` and `citation` `Fixture Steel Annual Report 2025 p.46`, and `tc_capex_total_planned` 2026 with `shown` `1100 EUR million` | holdout |
| AC-16 | the defaults | request for C | `rnd_tests` `lc_share`: `used` 60, `rule` `RY higher: RY used`, `ratio_shown` `0.75`; `early_stage`: `used` 55, `rule` `RY lower: average of RY-1 and RY`, `ratio_shown` `0.85` | holdout |
| AC-17 | K with `tc_lowcarbon_rnd` 2025 = 40 EUR million and `tc_capex_total` 2025 = 1000 EUR million | request for K | `rnd_tests` `capex_share`: `used` 4, `rule` `Only RY known: RY used`, `ratio_shown` `0.8` | holdout |
| AC-61 | C with no 2025 R&D facts (the 2024 R&D facts and the 2025 capex facts kept) | request for C | `capex.reporting_year` 2025; `rnd_tests` `lc_share` and `early_stage` each have `not_scored` `No reporting-year R&D figures` | holdout |
| ~~AC-18~~ | | | Retired: `stl_bf` is now a defined redline (owner, 2026-10-19); replaced by AC-65. | |
| AC-65 | the defaults | request for C | `redlines` = one entry: `id` `stl_bf`, `status` `not breached`, `citation` `Fixture Steel Annual Report 2025 p.48` | holdout |
| AC-19 | P with `tc_new_unabated_coal` Yes published from P4 p. 9 | request for P | redline `pwr_coal` `status` `breached`, `citation` `Fixture Power Annual Report 2025 p.9` | holdout |
| AC-20 | P with no `tc_new_unabated_coal` | request for P | redline `pwr_coal` `status` `no disclosure` | holdout |
| AC-21 | the defaults; the model client raises on any call | request for C | HTTP 200; `ratio_shown` `0.25` | holdout |
| AC-22 | Q | request for Q | `in_scope` false; `reason` `ISIC 1050 is not in a transition-barrier sector`; `capex` and `actions` absent or empty | holdout |
| AC-58 | N | request for N | `in_scope` false; `reason` `No ISIC code` | holdout |
| AC-23 | C with no 2025 capex facts; the extraction stub returns `tc_lowcarbon_capex_share_pct` 12 for 2025 from P2 p. 45 with its quote | an extraction run of `sch_transition_capex` for C, then its review item is approved | `GET /companies/C/facts?field_id=tc_lowcarbon_capex_share_pct` lists one row, `period_end` 2025-12-31, value 12, status `approved`, `source_label` `Fixture Steel Annual Report 2025 p.45` | holdout |

### Plan actions, barriers and B02 (phase 2)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-24 | the defaults | request for C | `regions` `["European Union", "United States", "China"]`; `actions` lists exactly A1, A2, A3 in that order (P1 pages 12, 15, 16), with `action_id` `steel.h2_dri`, `steel.scrap_eaf`, `steel.ccus` and citations `Fixture Steel Transition Plan 2025 p.12`, `p.15`, `p.16` | holdout |
| AC-25 | the defaults | request for C | A1 `barriers` = `STL-R1` European Union `H` `derived`, then `STL-T1` European Union `M` `derived`; the `STL-R1` entry's `values[]` includes 72 USD/tCO2 citing EU ETS Market Report 2026 p. 12 | holdout |
| AC-26 | the defaults | request for C | A2 `barriers` = exactly one: `STL-R1` United States `L` `hand_rated`, `evidence` `No federal carbon price applies to steel.` | holdout |
| AC-27 | A1 has no `ta_action_region` | request for C | A1 `barriers`, in order: `STL-R1` European Union `H` `derived`; `STL-T1` European Union `M` `derived`; `STL-R1` United States `L` `hand_rated` `No federal carbon price applies to steel.`; `STL-T1` United States `L` `hand_rated` `Hydrogen cost well above breakeven.`; `STL-R1` China `L` `hand_rated` `National ETS price too low to matter.`; `STL-T1` China `L` `hand_rated` `No renewable hydrogen supply at scale.` | holdout |
| AC-28 | no `ta_operates_*` facts; A1 has no `ta_action_region` | request for C | `regions` `[]`; A1 `barriers` `[]`, `note` `No operating region disclosed` | holdout |
| AC-29 | the defaults | request for C | A2 `act_lever.wording` `More scrap, process efficiency, zero-GHG power`; A1 `act_lever` null | holdout |
| AC-30 | the extraction stub classifies the p. 12 action as `steel.foo` | an extraction run of `sch_transition_plan_actions` for C | the action's review item shows reason `Unknown action id 'steel.foo'`; no `ta_action_id` fact `steel.foo` is published | holdout |
| AC-62 | A6 published from P3 (an older plan) | request for C | `actions` lists exactly A1, A2, A3; `GET /facts/<A6's ta_action_id fact>/trail` still returns that fact | holdout |
| AC-31 | the defaults | request for C | the carbon-price assumption has exactly one comparison: `code` `STL-R1`, `region` `European Union`, `assumption` `97.2 USD/tCO2 (90 EUR/tCO2)`, `evidence` `72 USD/tCO2 (EU ETS Market Report 2026, p. 12)`, `gap` `+25.2 USD/tCO2` | holdout |
| AC-32 | the defaults | request for C | the hydrogen assumption has exactly one comparison: `STL-T1` European Union, `assumption` `3 USD/kg H2`, `gap` `-3 USD/kg H2` | holdout |
| AC-33 | A1 has no `ta_action_region` | request for C | the hydrogen assumption's comparisons, in order, are for `STL-T1` European Union, United States, China; the United States one has `evidence` `hand-rated, no figure: Hydrogen cost well above breakeven.` and `gap` null | holdout |
| AC-34 | the defaults | request for C | A1 `b02`: `b` met `near term (2028)`; `c` met `3.5 MtCO2e/yr`; `d` met `1500 EUR million needed, 600 EUR million allocated` | holdout |
| AC-35 | the defaults | request for C | A2 `b02`: `b` met `implemented (2022)`; `c` not met `No quantified GHG saving`; `d` not met `No funding stated` | holdout |
| ~~AC-36~~ | | | Retired: two outcomes in one row; split into AC-49 and AC-50. | |
| AC-49 | the defaults | request for C | A3 `b02.b` not met, `text` `No timeframe: ignored` | holdout |
| AC-50 | the defaults | request for C | `b02a` not met, `text` `not met: 1 implemented, 1 planned with a timeframe (needs 3 and 1)` | holdout |
| AC-59 | A4 and A5 also published | request for C | `b02a` met, `text` `met: 3 implemented, 1 planned with a timeframe` | holdout |
| AC-60 | A1's `ta_action_year` = 2035 | request for C | A1 `b02.b` met, `text` `long term (2035)` | holdout |
| AC-37 | A1 has no `ta_action_capex_allocated` | request for C | A1 `b02.d` not met, `text` `No split of funds needed and allocated` | holdout |
| AC-63 | A1's `ta_action_capex_allocated` = 650 USD million | request for C | A1 `b02.d` not met, `text` `Needed and allocated in different currencies` | holdout |

### Extraction quality (phase 3)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-38 | a cases file of 4 action cases; the stub returns one counted action per case from the case's document and page with its `action_id`; 3 match every label, the fourth has a wrong `year` | `arp transition-alignment golden --cases <it> --documents-dir <dir> --min-precision 0.95 --min-coverage 0.5` | prints `precision 0.75, coverage 1`; exits 1 | holdout |
| AC-39 | the plan-action golden set (section 8), labels checked by the owner | `arp transition-alignment golden --cases <set> --documents-dir <dir> --min-precision 0.9 --min-coverage 0.5` | exits 0 | golden |
| AC-40 | the capex golden set (section 8), labels checked by the owner | `arp golden-set precision --schema sch_transition_capex --cases <set> --documents-dir <dir> --min-precision 0.95` | exits 0 | golden |

### In the running app (phase 1: AC-51, AC-52, AC-44; phase 2: AC-53 to AC-55, AC-43)

The app runs with F-TA, BM, the defaults seeded, and P1 and P2 stored as C's documents. F-TA and
BM together pass validation, so the app starts.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| ~~AC-41~~ | | | Retired: two outcomes in one row; split into AC-51 and AC-52. | |
| AC-51 | none | open C's company page | the Transition section shows `Low-carbon capex 20% vs benchmark 80%: 0.25` | evaluator |
| AC-52 | none | in C's Transition section, click the 12% RY share | P2 opens at page 45 | evaluator |
| ~~AC-42~~ | | | Retired: three outcomes in one row; split into AC-53, AC-54 and AC-55. | |
| AC-53 | none | open C's company page | the hydrogen DRI action shows region European Union with STL-R1 `H` and STL-T1 `M` | evaluator |
| AC-54 | none | open C's company page | the hydrogen DRI action's B02.d reads `1500 EUR million needed, 600 EUR million allocated` | evaluator |
| AC-55 | none | open C's company page | the carbon-price comparison shows gap `+25.2 USD/tCO2` | evaluator |
| AC-43 | none | in C's Transition section, click the 72 USD/tCO2 barrier figure | the barrier citation opens EU ETS Market Report 2026 at page 12 | evaluator |
| AC-44 | none | open Q's company page | the Transition section reads `Not in scope: ISIC 1050 is not in a transition-barrier sector` | evaluator |

### Must not change (every phase from 1; AC-46 from phase 2)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-45 | the defaults; then an extraction run of `sch_transition_capex` for C whose stub returns `not_found` | `GET /companies/C/facts?field_id=green_capex_share_pct` | exactly one row: `period_end` 2025-12-31, value 15, status `approved`, `source_label` `Fixture Steel Annual Report 2025 p.47` | holdout |
| AC-46 | F-TA after setup | AC-24 to AC-35 and AC-49 to AC-63 run, then `GET /api/transition-barrier/scores` and `GET /cells/STL-R1/European Union` | equal to the responses before the run; every file in F-TA is byte-identical | holdout |
| AC-47 | snapshot S | the four presets in S are built from `PRESETS` | every field's `field_id`, `data_type`, `version`, `high_risk` and `extraction_instructions` equal S; `PRESETS` holds exactly those four keys plus `sch_transition_capex` and `sch_transition_plan_actions` | unit |
| AC-48 | Q; extraction runs of `sch_transition_capex` and `sch_transition_plan_actions` requested for Q | `GET /companies/Q/facts` | exactly one row: `capex_total`, `period_end` 2025-12-31, value 200, status `approved`, `source_label` `Fixture Foods Report 2025 p.8` | holdout |

Must not change: existing company facts (AC-45, AC-48), barrier ratings and files (AC-46), the
existing presets (AC-47).

## Decisions recorded

All 2026-10-19, by the owner unless marked.

- **Scope:** companies in the transition-barrier sectors, from the existing universe, by sector
  classification (the owner's call, open to narrowing). Implemented as ISIC prefixes (builder's
  call, section 1).
- **Part A:** extract actions, timing and assumptions with quote and page; classify to rule-book
  ids; map ids to ACT lever wording without renaming; operating regions among EU, US, China; every
  criterion naming the action, with rating and evidence; assumptions shown against barrier
  evidence; ACT B02.a–d per action.
- **B02.d** is the test for investment linked to an action (research 9.3 item 8(d)).
- **Part B:** store low-carbon capex share and amount for RY and RY+1, carbon-intensive capex where
  disclosed, and a low-carbon R&D share (new field); D01.a RY/RY+1 rule (research 9.3 item 8(c));
  continuous score min(share / benchmark, 1) instead of ACT Core bands.
- **Benchmarks:** power 95%, oil and gas 77%, chemicals 77%, autos 80% (ACT Core); other sectors
  ACT's generic 80% and its R&D tests; IEA NZE milestones as redlines (plus `stl_bf`, below); nuclear and CCS/CCUS count as
  low-carbon; held in a curated, cited, owner-signed file.
- **Licence:** internal, non-commercial use; benchmark data used with citation (research 9.3 item 1).
- **Surface:** facts are ordinary company facts through the existing review queue; a Transition
  section on the existing company page.
- **Not used:** the WBA JSON feed; Data Explorer registration deferred; WBA scores later at most.
- **Out:** locked-in emissions, ACT narrative and trend scores, E01/F01, patents, portfolio and ETF
  aggregation, the uploaded template's maturity ladder and invented thresholds.
- **Standing rules:** the model never outputs a score, rating or benchmark; precision first; tests
  make no network or model calls; the owner checks golden-set labels.
- **Builder's calls by the controller (2026-10-19):** fixed sector list checked against the bundled
  criteria, action ids against the active rule book (section 2); only the most recent transition
  plan counts for actions (section 4); amounts stay in the reporting currency, no FX on amounts
  (section 3).
- **Run mode:** on demand only, for one company or one sector, through the existing run start
  path; no backfill, no schedule (section 1).
- **Sectors:** the barrier matrix's nine sectors, confirmed by the owner (section 1).
- **Steel redline `stl_bf`:** kept as an owner-defined redline, evaluated like the others, though
  IEA NZE 2023 has no such milestone (section 2; research 8.2).
