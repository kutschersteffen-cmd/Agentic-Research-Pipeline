# Logic of targets (Q2.1) as a Decision Studio framework

This folder holds the "Logic of targets" sheet, questions Q2.1.1–Q2.1.5, as an importable
framework.

- `framework.json`: import it under **Data → Import a template file**.
- `companies.csv`: a sample table with seven fictional companies, one for each path through the
  logic.
- `build.py`: rebuilds `framework.json`. Run it from `backend/`:
  `PYTHONPATH=. python3 ../docs/decision-studio/example-framework/targets/build.py`

## How a question is answered

Each question takes its answer from the first source that has information. Sources are checked
in this order:

1. SBTi
2. MSCI
3. TPI / CA100+
4. WBA
5. CDP

A source's `Yes` or `No` ends the search. A blank cell means "No info" and passes the question
to the next source. If every source is blank, the answer is `No info`.

### Where the logic lives

The logic is a chain of nodes:

- **Rules tab (3):**
  1. `normalise` (expression): turns each source cell into `Yes`, `No` or `No info`, as
     `<column>_answer`.
  2. `Q2.1.1` … `Q2.1.5` (decision tables): one table per question. Each row is one source, in
     priority order, and the first matching row wins (hit policy *first*). The table writes
     `q2_1_x` (the answer) and `q2_1_x_source` (where it came from). To change the order, move a
     row. To add a source, add a row.
  3. `counts` (expression): the number of `Yes` answers and the note.
  4. `Outcome` (decision table): turns the five answers into one of the five outcomes below.
- **Decision tree tab (5):** `Tier` (decision table) maps each outcome to its tier.

**Step 1, SBTi:** if `sbti_near_term_status` is "Targets set" and `sbti_near_term_target_year`
is between 2029 and 2035, every question is answered `Yes`.

| Question | Step 2: MSCI | Step 3: TPI / CA100+ | Step 4: WBA | Step 5: CDP |
|---|---|---|---|---|
| Q2.1.1 Quantitative GHG targets? | `msci_q2_1_1` | `tpi_q4l2` (TPI Q4L2) | `wba_targets` | `cdp_q2_1_1` |
| Q2.1.2 Interim target 2029–2035? | `msci_q2_1_2` | `ca100_3_1` (Sub-indicator 3.1) | `wba_s12_near_term_aim` | `cdp_q2_1_2` |
| Q2.1.3 Interim targets ≥ 95% of Scope 1+2? | `msci_q2_1_3` | `ca100_3_2a` (Metric 3.2.a) | `wba_s12_covers_95` | `cdp_q2_1_3` |
| Q2.1.4 Scope 3 targets where appropriate? | `msci_q2_1_4` | `ca100_3_1` **or** `wba_s12_near_term_aim` | `wba_s3_material_categories` | `cdp_q2_1_4` |

**Q2.1.5, aligned with 1.5 °C or well below 2 °C?**

- If Step 1 (SBTi) holds: `Yes`.
- Otherwise:
  - `No` if any of Q2.1.1–Q2.1.4 is `No`.
  - `No info` if any of them is `No info`.
  - Otherwise `Yes` if `tpi_cp_alignment_2030` or `tpi_cp_alignment_2035` is "1.5 Degrees" or
    "Below 2 Degrees".
  - `No info` if both TPI columns are blank.
  - `No` in every other case.

Yes/No columns can hold `Yes`, `No`, `true` or `false`. Case doesn't matter, and a blank cell
means no information.

## Filling the MSCI and CDP columns

MSCI and CDP report one row per **target**, but this framework reads one row per **company**. For
these two sources, apply the sheet's per-target test first. Enter `Yes` if any target passes,
`No` if the company has targets but none of them passes, and leave the cell blank if there is no
data.

| Column | Yes if any target… |
|---|---|
| `msci_q2_1_1` | `CBN_TARGET_QUANT_REDUC_NM` = 1, `CBN_TARGET_STATUS` = "Ongoing Target", `CBN_TARGET_YEAR` > 2025 |
| `msci_q2_1_2` | the same, with `CBN_TARGET_YEAR` between 2028 and 2035 |
| `msci_q2_1_3` | is medium-term, `TARGET_CARBON_SCOPE_123_CATEGORY` includes Scope 1 and 2, `TARGET_CARBON_COVERAGE_CATEGORY` = "Company-wide", `TARGET_CARBON_COVERAGE_PCT` ≥ 95% |
| `msci_q2_1_4` | is medium-term, `TARGET_CARBON_SCOPE_123_CATEGORY` includes Scope 3, `TARGET_CARBON_COVERAGE_CATEGORY` = "Company-wide", `TARGET_CARBON_SCOPE_3_CATEGORY` includes the Scope 3 categories material to the sector |
| `cdp_q2_1_1` | CDP 7.53 lists one or more targets |
| `cdp_q2_1_2` | CDP 7.53 lists a target with an end date between 2029 and 2035 |
| `cdp_q2_1_3` | CDP 7.53 lists organisation-wide Scope 1 and 2 targets covering ≥ 95% of base-year emissions |
| `cdp_q2_1_4` | CDP 7.53 lists organisation-wide targets covering the sector's material Scope 3 categories |

## Outcome

Each question is a criterion scored 1 for `Yes` and 0 otherwise. The score is the share of
questions answered `Yes`. The answers set the tier:

| Tier | When |
|---|---|
| 1 Aligned targets | all five `Yes` |
| 2 Targets, alignment not shown | Q2.1.1–Q2.1.4 `Yes`, Q2.1.5 not `Yes` |
| 3 Partial targets | at least one `Yes` |
| 4 No targets | no `Yes`, at least one answer known |
| 5 No information | all five `No info` |

Each company's note lists every answer and the source it came from. For example:

`2/5 Yes · Q2.1.1 Yes (MSCI) · Q2.1.2 No (MSCI) · Q2.1.3 Yes (WBA) · Q2.1.4 No (CDP) · Q2.1.5 No (Q2.1.1-4)`

## Choices the sheet leaves open

These are ruled here and recorded in the framework's audit trail:

1. **A source's `No` ends the search.** The sheet only says what happens after "No info".
2. **All sources blank gives `No info`.** The sheet doesn't say.
3. **For Q2.1.5, "No info" carries through.** If a company has no information on Q2.1.1–Q2.1.4,
   Q2.1.5 is `No info` rather than `No`.
4. **The tiers are not in the sheet.** Rename or regroup them in the Decision tree tab.

## Possible errors in the sheet

These are kept exactly as written:

1. Q2.1.2's MSCI step uses **2028**–2035, while the question and the other sources use 2029–2035.
2. Q2.1.4's Step 3 checks the **medium-term / Scope 1+2** indicators (CA100+ 3.1 or WBA S1+2
   near-term aim), not a Scope 3 indicator.
