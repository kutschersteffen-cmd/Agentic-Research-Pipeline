# Spec: a credibility framework from an indicator list

Source: *What makes a climate transition plan credible?*, Stewardship Committee deck, 17 Sep 2026
(slides 5, 14, 16, 20, 21, 42–48). Referred to below as "the deck".

## Goal

An analyst uploads a list of indicators, one row per indicator, and gets a Decision Studio
framework without loading any company data. Applied later to a company table (one row per
company, one column per indicator, scores 0–3), it reproduces the deck's headline test and
grade.

## Indicator list (CSV, TSV or Excel; header row; column names case-insensitive)

| Column | Required | Meaning | Default |
|---|---|---|---|
| `id` | yes | Indicator id, e.g. `A3`. Must equal the company-table column that holds its score. Unique. | — |
| `name` | yes | Label, e.g. `Medium-term GHG target`. | — |
| `group` | yes | Dimension, e.g. `Ambition & targets`. Becomes a cluster. | — |
| `weight` | no | Weight within its group, ≥ 0. | `1` |
| `group_weight` | no | The group's weight; the first non-blank value in a group counts. | `1` |
| `scale` | no | `min-max`, whole numbers. | `0-3` |
| `direction` | no | `higher` or `lower` is better. | `higher` |
| `critical` | no | `yes` marks a red-flag indicator. | `no` |
| `question` | no | The question it answers, e.g. `Q2`. | blank |
| `view_<name>` | no | Relevance 0–3 of the indicator to view `<name>`, e.g. `view_Disclosure`. | `0` |
| `kind` | no | `indicator`, or `event` for an outlook flag (scored yes/no per company, not part of the score). | `indicator` |
| `outlook` | events only | `Negative` or `Watch`: what a Yes on this event sets. | — |

Missing or blank scores count as the bottom of the scale ("0 = absent", deck slide 5).

## Plain framework (any list)

- Levels mode, `level_min`/`level_max` from `scale` (all indicators must share one scale).
- One level criterion per indicator: the score is the level (`lower` direction: `max − score`).
- Clusters from `group`, criterion weight from `weight`, cluster weight from `group_weight`.
- Cut-points pinned; tiers `Tier 1`…`Tier 4` until the analyst sets them.
- Every derived choice carries an audit entry: stage `Indicator list`, origin `derived`.

## Credibility preset (deck)

Applies when the list has exactly five questions; they are taken in order Q1…Q5 (sorted by the
`question` label). Percentages use the scale maximum M (3 in the deck).

1. **Question level** = mean score of its indicators ÷ M × 100.
2. **Answer** (slide 14): `Yes` if every indicator = M; `No` if any indicator ≤ 1 or missing;
   otherwise `Partly`.
3. **Verdict**: any `No` → `Not credible`; all `Yes` → `Credible`; otherwise `Partly credible`.
   Tie-break keeps the counts of `No` and `Yes`.
4. **Class tree** (slide 16), first match:
   Q1 < 50 → E · any critical = 0 → D · Q2 ≥ 60 and Q3 ≥ 60 → A if Q5 ≥ 70, else B ·
   exactly one of Q2, Q3 ≥ 60 → C · otherwise D.
5. **Red-flag cap** (slides 16, 20): ≥ 2 criticals at 0 → D · 1 critical at 0 → C ·
   ≥ 2 criticals ≤ 1 → C · 1 critical ≤ 1 → B · otherwise A.
6. **Grade** = the worse of class and cap. Tiers: 1 `A Credible`, 2 `B Credible, gaps`,
   3 `C Partial`, 4 `D Not credible`, 5 `E Opaque`.
7. **Outlook** (slide 47): any `Negative` event = Yes → `Negative`; else any `Watch` event = Yes →
   `Watch`; else `Stable`.
8. **Action** (slide 48):
   D or E with Negative → `Escalate: voting sanctions, support climate resolutions` ·
   D or E otherwise → `Escalate: formal engagement, 12-month milestones` ·
   C → `Engage intensively; review in 12 months` ·
   A with Stable → `Maintain: best-practice reference` · A otherwise → `Maintain + targeted ask` ·
   B with Stable → `Engage: routine` · B otherwise → `Engage on flagged issue`.
9. **Views** (slide 5), when `view_*` columns exist: view % = Σ(weight × score) ÷ (M × Σ weight) × 100
   over indicators with weight > 0. Reported per company, not used in the grade.
10. Each company's note reads `<verdict> (<n> No, <n> Yes) · Outlook <outlook> · <action>`.

## Acceptance (deck appendix A–D, slides 42–45)

The deck's 27 indicators with their groups, questions (slide 14) and criticals
A3 A6 B3 C1 D2 G2, plus two events (`targets_weakened` Negative, `new_fossil_capacity` Watch),
applied to Shell / RWE / Enel:

| | Verdict | No / Yes | Grade | Outlook | Action |
|---|---|---|---|---|---|
| Shell | Not credible | 4 / 0 | D | Negative | Escalate: voting sanctions, support climate resolutions |
| RWE | Partly credible | 0 / 0 | B | Watch | Engage on flagged issue |
| Enel | Partly credible | 0 / 1 | A | Watch | Maintain + targeted ask |

Event values: Shell `targets_weakened` Yes; RWE and Enel `new_fossil_capacity` Yes (slide 21).

## Not in this spec

Eight aggregation models and the ensemble, named weight sets, view-based detailed tree,
alignment × credibility buckets, feasibility axis, sector modules, portfolio / voting / escalation
policy (Steward Workflow and Index Construction already read published tiers), and a pivot for
indicator-per-row *company* data.
