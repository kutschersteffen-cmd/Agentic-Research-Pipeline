# Consistency flags

Status: draft for owner approval, 2026-10-21.

## Intent

ACT's narrative assessment asks an analyst whether a transition plan contradicts itself (ACT
Framework v2.1, "Consistency and credibility", pp.61–64). Five of those questions can be answered in
code from facts the platform already holds (research `docs/ACT_PLAN_ASSESSMENT_RESEARCH.md` §13.3).
This change shows them as **flags** at the top of the company page's Transition section: warnings with
the ACT question, the facts behind them and their sources. Flags never combine into a score.

Owner decisions (2026-10-21): flags 2, 3, 4, 5 and 7 of research §13.3; layout option A (one
"Consistency" part at the top of the Transition section).

## Goals

- Compute five flags in code from counted facts, for in-scope companies.
- Show each flag's state (`raised`, `clear`, `not checked`), its text, the ACT page and the facts
  that decided it; every fact opens its trail.

## Non-goals

- Flag 1 (non-mature technology without R&D) and flag 6 (pay rewards growth): need data not held.
- The residual-emissions half of flag 7 (no residual-emissions fact exists).
- A score or count used anywhere else; new extraction fields; any change to existing results.

## Anti-goals

- A flag raised on missing data it needs to *read* (e.g. no net-zero answer) — that is `not checked`.
  Only the flags whose ACT wording is about an absence ("does not report any low-carbon CapEx",
  "doesn't have any plan to … phase out") treat a missing fact as part of the condition.
- The model deciding a flag.

## Current state

- `transition_plan_indicators` preset: boolean questions, including `A_ambition_3` ("Does the
  company report a company-wide net zero GHG emissions target?") and `A_offsetting_13` ("If carbon
  credits and offsets are reported to be used by the company, does the company explicitly state that
  it will use them exclusively for residual unabatable emissions or beyond value chain mitigation
  support?").
- `GET /api/companies/{ref}/transition` already returns: capex facts and redlines (phase 1), actions
  with regions and operating regions (phase 2), targets, coverage and phase-outs (delivery checks).

## Design

### 1. The five flags

Facts are counted facts; booleans read as in the existing presets (Yes/No). Each flag has a `state`:
`raised`, `clear` or `not checked` (with `reason`). Order on the page and in the response is the
order below.

| id | Title | Raised when | Not checked when | ACT cite |
|---|---|---|---|---|
| `no_lowcarbon_capex` | Falling emissions claimed, no low-carbon capex | a running target is listed in `targets` **and** RY has no counted `tc_lowcarbon_capex` > 0 and no counted `tc_lowcarbon_capex_share_pct` > 0 (RY of phase 1's capex). No running target → clear. | a running target exists but RY is undefined (no capex fact at all) → `No capex reporting year` | `ACT Framework p.64` |
| `net_zero_no_phaseout` | Net zero without phase-out | `A_ambition_3` = Yes **and** `phaseouts` is empty. `A_ambition_3` = No → clear. | no counted `A_ambition_3` → `No net-zero answer` | `ACT Framework pp.61–62` |
| `expansion_vs_net_zero` | Expansion against net zero | Decided in this order: no counted `A_ambition_3` → not checked `No net-zero answer`; `A_ambition_3` = No → clear; no redline in the sector → not checked `No redline for this sector`; a redline `breached` → raised; else a redline with status `no disclosure` → not checked `No redline disclosure`; else clear. | (see the order) | `ACT Framework p.62` |
| `regions_left_out` | Regions left out | ≥ 2 operating regions, and at least one operating region has no listed action whose regions include it, while another has one | fewer than 2 operating regions → `Fewer than two operating regions` | `ACT Framework p.61` |
| `offsets_emphasised` | Offsets emphasised | `A_offsetting_13` = No | no counted `A_offsetting_13` → `No offsets answer` | `ACT Framework p.62; ACT Core p.26` |

An action's regions are those phase 2 matches it in (its own region, else every operating region;
`other` → none).

`fact_ids` per flag (the same for `raised` and `clear`; empty when `not checked`; ascending fact id
within each group): `no_lowcarbon_capex` the counted `ta_target_*`
facts of the earliest running target (`[]` when there is none); `net_zero_no_phaseout` the `A_ambition_3` fact; `expansion_vs_net_zero` the `A_ambition_3`
fact then each breached redline's fact; `regions_left_out` the counted `ta_operates_*` facts in region
order; `offsets_emphasised` the `A_offsetting_13` fact.

### 2. Texts (exact)

Raised text, with values from the facts:
- `no_lowcarbon_capex`: `<year> target −<pct>%` (earliest running target), then
  ` and actions saving <covered> MtCO2e/yr` when coverage summed any action, then
  `, but no low-carbon capex disclosed for <RY>.`
- `net_zero_no_phaseout`: `Net-zero target reported, but no phase-out commitment disclosed.`
- `expansion_vs_net_zero`: `Net-zero target reported, but redline breached: <redline label>.`
  (several: labels joined with `; `).
- `regions_left_out`: `Operates in <regions with no action>, but no listed action covers it.`
  (`covers them` for several; regions joined with ` and ` in region order).
- `offsets_emphasised`: `Does not state that credits are used only for residual emissions.`

Clear text: `No flag.` Not-checked text: the reason. Header line:
`Consistency: <n> of 5 checks raise a flag` (n = raised count); when none is raised,
`Consistency: no check raises a flag`.

### 3. Interfaces

`TransitionOut.flags[]`: `id`, `title`, `state`, `text`, `cite`, `fact_ids[]` (§1); `TransitionOut.flags_header`: string. Out of scope: `flags` `[]`,
`flags_header` null. Computed in a pure function in `transition_alignment/flags.py` from the already
built `TransitionOut` parts plus the two indicator facts.

### 4. Page (option A)

A **Consistency** box at the top of the Transition section, before capex: the header line, then each
raised flag (title, text, cite, a "facts" link per fact opening its trail), then one muted line
`No flag: <titles of clear flags joined with "; ">` and one `Not checked: <title> (<reason>)` per
not-checked flag. A line is omitted when it would list no flag.
Existing classes only, as earlier phases.

## Constraints

Code computes every flag; tests make no network or model calls; must not change any earlier result.

## Left to the builder

Module layout; UI details within `DESIGN.md`.

## Acceptance

### Fixtures (added)

C gains published facts: `A_ambition_3` Yes (P1 p.25, quote `We aim to reach net zero across our
operations by 2050.`) and `A_offsetting_13` No (P1 p.26, quote `We will use carbon credits to help
meet our 2030 target.`). K gains published `A_ambition_3` Yes (only where a row says so). All earlier
fixtures (phase 1–2, delivery checks) stay.

### Rows

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-130 | the defaults | request for C | `flags` as (`id`, `title`) in order: (`no_lowcarbon_capex`, `Falling emissions claimed, no low-carbon capex`), (`net_zero_no_phaseout`, `Net zero without phase-out`), (`expansion_vs_net_zero`, `Expansion against net zero`), (`regions_left_out`, `Regions left out`), (`offsets_emphasised`, `Offsets emphasised`) | holdout |
| AC-150 | the defaults | request for C | `cite` in the same order: `ACT Framework p.64`, `ACT Framework pp.61–62`, `ACT Framework p.62`, `ACT Framework p.61`, `ACT Framework p.62; ACT Core p.26` | holdout |
| AC-131 | the defaults | request for C | `offsets_emphasised` `state` `raised`, `text` `Does not state that credits are used only for residual emissions.` | holdout |
| AC-132 | the defaults | request for C | the other four flags have `state` `clear`, `text` `No flag.` | holdout |
| AC-133 | the defaults | request for C | `flags_header` `Consistency: 1 of 5 checks raise a flag` | holdout |
| AC-134 | no 2025 `tc_lowcarbon_capex` and no 2025 `tc_lowcarbon_capex_share_pct` | request for C | `no_lowcarbon_capex` `state` `raised`, `text` `2030 target −30% and actions saving 3.5 MtCO2e/yr, but no low-carbon capex disclosed for 2025.` | holdout |
| ~~AC-135~~ | | | Retired before approval: the actions-only text cannot occur (coverage needs a running target). | |
| AC-136 | as AC-134, and no counted target | request for C | `no_lowcarbon_capex` `state` `clear` | holdout |
| AC-151 | as AC-134, and A1's `ta_action_year` = 2031 | request for C | `no_lowcarbon_capex` `text` `2030 target −30%, but no low-carbon capex disclosed for 2025.` | holdout |
| AC-137 | no phase-out fact | request for C | `net_zero_no_phaseout` `state` `raised`, `text` `Net-zero target reported, but no phase-out commitment disclosed.` | holdout |
| AC-138 | no `A_ambition_3` fact | request for C | `net_zero_no_phaseout` `state` `not checked`, `text` `No net-zero answer`, `fact_ids` `[]` | holdout |
| AC-152 | no `A_ambition_3` fact | request for C | `expansion_vs_net_zero` `state` `not checked`, `text` `No net-zero answer` | holdout |
| AC-139 | `tc_new_blast_furnace` Yes | request for C | `expansion_vs_net_zero` `state` `raised`, `text` `Net-zero target reported, but redline breached: No new blast furnace without CCS or a near-zero route.` | holdout |
| AC-153 | no `tc_new_blast_furnace` fact | request for C | `expansion_vs_net_zero` `state` `not checked`, `text` `No redline disclosure` | holdout |
| AC-140 | A3's `ta_action_region` = `European Union` | request for C | `regions_left_out` `state` `raised`, `text` `Operates in China, but no listed action covers it.` | holdout |
| AC-141 | `ta_operates_eu` Yes; no counted `ta_operates_us` or `ta_operates_cn` | request for C | `regions_left_out` `state` `not checked`, `text` `Fewer than two operating regions` | holdout |
| AC-142 | `A_offsetting_13` Yes | request for C | `offsets_emphasised` `state` `clear` | holdout |
| AC-154 | `A_offsetting_13` Yes | request for C | `flags_header` `Consistency: no check raises a flag` | holdout |
| AC-155 | no `A_offsetting_13` fact | request for C | `offsets_emphasised` `state` `not checked`, `text` `No offsets answer` | holdout |
| AC-143 | the defaults | request for Q | `flags` `[]`, `flags_header` null | holdout |
| AC-144 | the defaults; the model client raises | request for C | HTTP 200, `flags_header` `Consistency: 1 of 5 checks raise a flag` | holdout |
| AC-145 | the defaults | `GET /api/facts/<id>/trail` for the one id in `offsets_emphasised.fact_ids` | `fact_ids` has exactly one id; the trail returns 200 and its field is `A_offsetting_13` | holdout |
| AC-146 | none | open C's company page | the Consistency box is the first part of the Transition section, before the capex headline | evaluator |
| AC-156 | none | open C's company page | the box header reads `Consistency: 1 of 5 checks raise a flag` | evaluator |
| AC-147 | none | open C's company page | the box shows `Offsets emphasised`, `Does not state that credits are used only for residual emissions.` and `ACT Framework p.62; ACT Core p.26` | evaluator |
| AC-148 | none | open C's company page | the box shows `No flag: Falling emissions claimed, no low-carbon capex; Net zero without phase-out; Expansion against net zero; Regions left out` | evaluator |
| AC-157 | no `A_ambition_3` fact | open C's company page | the box shows `Not checked: Net zero without phase-out (No net-zero answer)` | evaluator |
| AC-149 | none | in the box, click the offsets flag's facts link | the fact trail opens at P1 p.26 | evaluator |
| AC-158 | `tc_new_blast_furnace` Yes | request for C | `expansion_vs_net_zero.fact_ids` is exactly [the `A_ambition_3` fact id, the `tc_new_blast_furnace` fact id] (ids resolved by `field_id` from `/facts`) | holdout |
| AC-159 | A3's `ta_action_region` = `European Union` | request for C | `regions_left_out.fact_ids` is exactly the ids of the `ta_operates_eu`, `ta_operates_us`, `ta_operates_cn` facts, in that order | holdout |
| AC-165 | the defaults | request for C | `net_zero_no_phaseout.fact_ids` is exactly [the `A_ambition_3` fact id] | holdout |
| AC-166 | the defaults | request for C | `no_lowcarbon_capex.fact_ids` is exactly the ids of T1's six `ta_target_*` facts, ascending (resolved by `field_id` and basis from `/facts`) | holdout |
| AC-160 | K's `A_ambition_3` Yes published | request for K | `expansion_vs_net_zero` `state` `not checked`, `text` `No redline for this sector` | holdout |
| AC-161 | A1's, A2's and A3's `ta_action_region` all `European Union` | request for C | `regions_left_out` `text` `Operates in United States and China, but no listed action covers them.` | holdout |
| AC-162 | `A_ambition_3` No; `tc_new_blast_furnace` Yes | request for C | `net_zero_no_phaseout` and `expansion_vs_net_zero` both `state` `clear`, `text` `No flag.` | holdout |
| AC-164 | no counted `tc_capex_total`, `tc_lowcarbon_capex` or `tc_lowcarbon_capex_share_pct` fact of any year for C | request for C | `no_lowcarbon_capex` `state` `not checked`, `text` `No capex reporting year` | holdout |
| AC-163 | `A_offsetting_13` Yes | open C's company page | the box shows no `Not checked:` line | evaluator |

Must not change: every earlier row (phases 1–2 AC-2 to AC-71, delivery checks AC-72 to AC-129).

## Decisions recorded

- 2026-10-21, owner: flags 2, 3, 4, 5, 7; option A.
- Builder's calls (controller): state `not checked` for missing inputs a flag reads; flag 2 and 3
  treat absence as the condition, as ACT's wording does; flag 7 checks only `A_offsetting_13`.
