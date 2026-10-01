# Frameworks from an indicator list

Start with a list of indicators, one row per indicator, and Decision Studio builds a framework
from it. You don't need any company data to do this. Upload the list under **Data → Build a
framework from an indicator list** (or `POST /api/decision/mechanisms/from-indicators`). The
framework is saved as a draft template. Apply it to a company table later: one row per company,
one column per indicator id.

Example files: [`example-framework/credibility/indicators.csv`](example-framework/credibility/indicators.csv)
(the Stewardship Committee deck's 27 indicators and two events) and
[`companies.csv`](example-framework/credibility/companies.csv) (Shell, RWE, Enel).

[`example-framework/transition-plan/indicators.csv`](example-framework/transition-plan/indicators.csv)
lists the pipeline's 64 transition-plan indicators (`backend/arp/transition_plan/data/indicators.json`)
on a `0-1` scale, grouped by category, with *walk* indicators weighted 2 and *talk* indicators 1.
The ids match the `Ind_<identifier>_Disclosed` columns that a transition-plan run export produces
(**One Yes/No column per indicator**), so the framework applies to a real run as is. `Yes` reads
as 1 and `No` or a blank as 0. [`companies.csv`](example-framework/transition-plan/companies.csv)
has five synthetic companies. With the placeholder tiers, Leader AG lands in Tier 1, Mid Corp and
Talker SA (talk-heavy) in Tier 2, and Laggard plc and Blank Co in Tier 4.

To test against a real run instead, make a synthetic one: **Data → Or build it from a finished run →
Create a sample run** (or `arp transition-plan seed-demo`, or `POST /api/transition-plan/demo/seed`).
It writes a finished transition-plan run over 8 fictional companies with made-up verdicts, no
documents and no LLM calls (`params.synthetic` is true). Build the table with **One Yes/No column per
indicator** ticked, then apply the framework above (or import the same framework, already built, from
[`framework.json`](example-framework/transition-plan/framework.json) under **From a framework file**): Northwind Utilities lands in Tier 1, Quiet Shell
Ltd in Tier 4.

## The list

CSV, TSV or Excel. The first row is the header, and column names are case-insensitive.

| Column | Required | Meaning | Default |
|---|---|---|---|
| `id` | yes | Indicator id, e.g. `A3`. It must equal the company-table column that holds the score, and it must start with a letter. Unique. | — |
| `name` | yes | Label, e.g. `Medium-term GHG target`. | — |
| `group` | yes | Dimension, e.g. `Ambition & targets`. Becomes a cluster. | — |
| `weight` | no | Weight within its group, 0 or more. | `1` |
| `group_weight` | no | The group's weight. The first non-blank value in a group counts. | `1` |
| `scale` | no | `min-max`, whole numbers. All indicators share one scale. | `0-3` |
| `direction` | no | `higher` or `lower` is better. | `higher` |
| `critical` | no | `yes` marks a red-flag indicator. | `no` |
| `question` | no | The question it answers, e.g. `Q2`. | blank |
| `view_<name>` | no | Relevance (0–3) of the indicator to view `<name>`, e.g. `view_Disclosure`. | `0` |
| `kind` | no | `indicator`, or `event` for an outlook flag: Yes/No per company, and not part of the score. | `indicator` |
| `outlook` | events only | `Negative` or `Watch`: what a Yes on this event sets. | — |

A bad row is refused with its row number, e.g. `Indicator list row 3: 'direction' must be higher or
lower`. Nothing is saved in that case.

## What you get for any list

- Levels mode on the list's scale. Each indicator's score is its level. For a `lower` indicator the
  level is flipped: level = max + min − score.
- **A blank or missing score counts as the bottom of the scale** (0 = absent).
- One cluster per group, weighted by `weight` and `group_weight`. Example: Shell's *Ambition &
  targets* scores are 2, 2, 0, 2, 2, 1, 2, so the cluster score is 11 / 7 = 1.57.
- Four placeholder tiers, `Tier 1`…`Tier 4`, on evenly spaced cut-points (0–3 scale: 2.25, 1.5,
  0.75). Name them before you ratify.
- Every derived choice appears in the audit log under the stage *Indicator list*.

## The credibility preset

When the list names **exactly five questions**, the framework also grades each company the way the
deck does. With any other number of questions, the audit log says the preset was skipped. The
questions are taken in sorted order (Q1…Q5), and M is the top of the scale (3).

1. **Question %** = mean level of its indicators ÷ M × 100.
2. **Answer**:
   - `Yes` if every indicator is at M.
   - `No` if any indicator is at 1 or below. A blank counts as 0, so it also gives `No`.
   - `Partly` otherwise.
3. **Verdict**:
   - Any `No` → `Not credible`.
   - All `Yes` → `Credible`.
   - Otherwise → `Partly credible`.
4. **Class tree**, first match wins:

   | Condition | Class |
   |---|---|
   | Q1 < 50 | E |
   | Any critical indicator = 0 | D |
   | Q2 ≥ 60 and Q3 ≥ 60 | A if Q5 ≥ 70, else B |
   | Exactly one of Q2, Q3 ≥ 60 | C |
   | Otherwise | D |

5. **Red-flag cap**:

   | Critical indicators | Cap |
   |---|---|
   | 2 or more at 0 | D |
   | 1 at 0 | C |
   | 2 or more at 1 or below | C |
   | 1 at 1 or below | B |
   | Otherwise | A |

6. **Grade** = the worse of the class and the cap. Tiers: `A Credible`, `B Credible, gaps`,
   `C Partial`, `D Not credible`, `E Opaque`.
7. **Outlook**:
   - Any `Negative` event at Yes → `Negative`.
   - Otherwise, any `Watch` event at Yes → `Watch`.
   - Otherwise → `Stable`.
8. **Action**:

   | Grade | Outlook | Action |
   |---|---|---|
   | D or E | Negative | Escalate: voting sanctions, support climate resolutions |
   | D or E | Watch or Stable | Escalate: formal engagement, 12-month milestones |
   | C | any | Engage intensively; review in 12 months |
   | A | Stable | Maintain: best-practice reference |
   | A | Watch or Negative | Maintain + targeted ask |
   | B | Stable | Engage: routine |
   | B | Watch or Negative | Engage on flagged issue |

9. **Views** (only when the list has `view_*` columns): view % = Σ(relevance × level) ÷
   (M × Σ relevance) × 100. The view % is shown per company but does not affect the grade.
10. Each company's note reads `<verdict> (<n> No, <n> Yes) · Outlook <outlook> · <action>`.

All of this lives in the framework's rule graph (calculated columns `q1_pct`…, `q1_answer`…,
`no_count`, `yes_count`, `verdict`, `tree_class`, `cap_class`, `grade`, `outlook`, `action`,
`note`, `view_<name>_pct`), so you can read and edit it in the Rules tab like any other rule.

### The deck, reproduced

The two example files give:

| | Verdict | No / Yes | Grade | Outlook | Action |
|---|---|---|---|---|---|
| Shell | Not credible | 4 / 0 | D | Negative | Escalate: voting sanctions, support climate resolutions |
| RWE | Partly credible | 0 / 0 | B | Watch | Engage on flagged issue |
| Enel | Partly credible | 0 / 1 | A | Watch | Maintain + targeted ask |

If the company table is missing an indicator column (e.g. `C1`), the result lists it under
`missing_columns`.

## Not covered

- Aggregation models and the ensemble
- Named weight sets
- The view-based detailed tree
- Alignment × credibility buckets
- The feasibility axis
- Sector modules
- Indicator-per-row *company* data (a pivot)
