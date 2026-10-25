# Theme context brief: why now, early evidence, affected sectors (step 1)

Status: draft, 2026-10-25.

Builds on the theme dossier spec (`2026-10-25-theme-dossier-design.md`, PR #226), which derives step 1
(**Spot**) from the candidate's status only. This spec adds the step's context brief and says how the dossier
shows it. Step 3 (the research note, `2026-10-25-theme-research-note-design.md`) is separate: it reads new,
owner-approved authoritative sources after the taxonomy is ratified. The brief reads only what the Emerging
Themes run already collected.

## Owner decisions (2026-10-25)

1. Every Emerging Themes candidate gets a **context brief** answering three questions: **why now**, **the early
   evidence**, **which sectors are affected**.
2. **Fact-based.** The brief rests only on the candidate's existing evidence: its grounded quotes, its
   contradiction quotes, its corporate actions (the tags' action types and the SEC CapEx/R&D cross-check).
   Every statement cites the evidence it rests on. No marketing claims, no outside knowledge.
3. **Written during the run, before the decision.** The brief exists when the owner decides to promote,
   reject or disconfirm. **Promote is the only sign-off for step 1.** The brief has no approval of its own.
4. **Sectors are ISIC.** A company with an ISIC code is counted under its standard ISIC industry. A company
   without one gets no guessed sector; the brief describes the **activities** the evidence shows it doing,
   **both per company and grouped by shared activity**.
5. Approach A (below): facts computed in code, one model call for the wording.

## Intent

The candidate card today shows scores and up to eight quotes. To decide whether a candidate is worth a taxonomy,
the owner needs a short reading of it: what changed recently, what the evidence actually says, and where in the
economy it lands. The brief gives that reading, and every line of it can be checked against a quote or a number
the run already holds.

## Goals

- Every candidate produced after release carries a brief, shown on its card in Emerging Themes.
- Every number on screen comes from code. Every sentence the model writes cites at least one evidence item
  from the candidate's own evidence and is dropped otherwise.
- Sectors use ISIC Rev.4 division names; companies without an ISIC code are described by activity.
- The dossier of a promoted candidate shows the same brief under step 1.

## Non-goals

- New sources, web searches or fetching (step 3 does that).
- Changing how candidates are detected, scored, gated, named or promoted.
- Backfilling briefs for candidates from earlier runs.
- An approval, edit or rewrite action on the brief.
- The model assigning ISIC codes.
- Measuring the brief's wording on a golden set. The owner's promote decision is the check; acceptance rows
  use a stand-in model.

## Anti-goals

- A sentence in the brief that cites no evidence item of the candidate.
- A number in a model-written sentence that is not in a quote the sentence cites.
- A sector shown for a company whose universe entry has no ISIC code.
- A candidate lost because its brief failed.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **Facts computed in code; one model call per candidate writes neutral, cited sentences and the activity lines and groups.** Uncited sentences are dropped. | Reads like a brief; numbers stay code-only; one extra model call per candidate. The model can word things loosely but cannot cite a source that does not exist. | **Chosen by the owner** |
| B | No model: lists and numbers only; activities grouped by the scanner's exact tag labels. | Cheapest, nothing to drift; reads like a table; near-duplicate labels split into separate groups. | Rejected |
| C | Model writes the whole brief; each sentence's quote checked by grounding, as in step 3. | Richest prose; the only option where a number or a sector could come from the model rather than the data. | Rejected |

## The brief

Stored on the candidate as a new field `context_brief` (`EmergingThemeCandidate.context_brief`, nullable), so
`GET /api/emerging-themes/runs/{run_id}/candidates` returns it with no new endpoint. Candidates written before
release have `context_brief` null.

```
context_brief:
  status: "written" | "failed"
  error: null | "brief wording failed"
  written_at: ISO-8601 UTC
  facts: {first_seen, last_seen, independent_sources, company_count, velocity, breadth, persistence,
          novelty, materiality, contradiction, action_counts}
  evidence: [evidence item]
  companies: [{company_id, name, isic_division}]
  why_now: [statement]
  early_evidence: [statement]
  sectors: [{isic_division, label, company_ids, evidence_ids}]
  activities: {by_company: [{company_id, activity, evidence_ids}],
               groups: [{activity, company_ids, evidence_ids}],
               unclassified_company_ids: [company_id]}
  dropped_statements: int
statement: {text, evidence_ids}
```

### Evidence items (code)

The brief's evidence pool, numbered `E1`, `E2`, … in this order:

1. `kind` `quote`: one per entry of `corroborating_sources`, in that order.
2. `kind` `quote`: for each candidate company without an ISIC division (see Sectors) that no item from 1
   covers, its first grounded member tag in member-tag order, as a citation. A company with no grounded tag of
   its own gets none. These items are one per mention (two companies whose first tag is the same mention share
   one item) and are ordered by member-tag order.
3. `kind` `counter`: one per entry of `contradiction_evidence`, in that order.
4. `kind` `financials`: one per entry of `xbrl_corroboration`, in that order.

A `quote` or `counter` item holds `evidence_id`, `kind`, `mention_id`, `source_type`, `title`, `url`,
`published_at` (from the mention, nullable), `quote`, `action_type` (of the tag the citation came from) and
`company_ids` (the companies that mention resolved to). A `financials` item holds `evidence_id`, `kind`,
`company_id`, `capex_pct_change`, `rnd_pct_change`. An item "covers" a company when its `company_ids` (or
`company_id`) contains it.

**Company order.** Every list of companies in the brief (`companies`, a sector's or group's `company_ids`,
`by_company`, `unclassified_company_ids`) follows `candidate_sectors_companies` order (today sorted by
`company_id`).

### Facts (code)

- `first_seen`, `last_seen`: earliest and latest `published_at` date (`YYYY-MM-DD`) over the `quote` and
  `counter` items; null when none has one.
- `independent_sources`: the existing `independent_source_count` over the cluster's member tags.
- `company_count`: length of `candidate_sectors_companies`.
- `velocity`, `breadth`, `persistence`, `novelty`, `materiality`, `contradiction`: copied from the candidate.
- `action_counts`: `{capex, hiring, orders, capacity, partnership}`, the number of the cluster's member tags with
  each action type.

### Sectors (code)

A company's ISIC division is the first two characters of its universe entry's `isic_code` when both are digits
and the division is in the ISIC Rev.4 division list; otherwise it has none. The list ships as
`backend/arp/emerging_themes/reference/isic4_divisions.csv` (`division,title`, the 88 official UN ISIC Rev.4
division titles, e.g. `27,Manufacture of electrical equipment`).

`companies` lists every company in `candidate_sectors_companies` with its universe `name` and `isic_division`
(null when none, or when the company is not in the run's universe).

`sectors`: one entry per division held by at least one candidate company. `label` is the division title,
`company_ids` the companies in it (in `candidate_sectors_companies` order), `evidence_ids` every item covering
one of them, in pool order. Sorted by number of companies, descending, then by division ascending.

### Statements and activities (one model call)

After a candidate passes the existing gates and its SEC cross-check and company roles are attached, one model
call receives the theme name, description, the evidence pool with ids, and the companies without an ISIC
division with the ids of the items covering each. It returns `why_now`, `early_evidence`, `by_company` and
`groups`. The system prompt asks for short, neutral, factual sentences, no promotional language, no forecast or
figure the quotes do not state, and no restating of the facts block (code shows those).

Code then checks the output, in this order. Every dropped statement, activity line or group adds 1 to
`dropped_statements`.

1. **Statements** (`why_now`, `early_evidence`): ids not in the pool are removed; a statement left with no id
   is dropped. A statement containing a number (a match of `\d+(?:[.,]\d+)?`) that is not a substring of the
   `quote` of any `quote` or `counter` item it cites is dropped.
2. **By company:** a line is dropped when its company is not a candidate company without an ISIC division, when
   an earlier line already named that company, or when none of its ids is an item covering that company (ids
   that are not are removed). Kept lines are put in company order.
3. **Groups:** `company_ids` are reduced to companies with a kept by-company line, in company order; a group left with fewer than
   two companies is dropped. A group's `evidence_ids` are the union of its companies' by-company ids, in pool
   order (the model's ids for groups are ignored).
4. `unclassified_company_ids`: candidate companies without an ISIC division and without a kept by-company line,
   in `candidate_sectors_companies` order.

If the model call raises, `status` is `failed`, `error` `brief wording failed`, the four model lists are empty,
`unclassified_company_ids` holds every company without an ISIC division, and evidence, facts, companies and
sectors are still filled. The candidate is saved either way; the run does not fail.

## Screens

### Emerging Themes candidate card

A **Context brief** section, open by default, above the decision buttons:

- **Why now**: a facts line `Mentions <first_seen> to <last_seen> · <independent_sources> independent sources ·
  <company_count> companies · velocity <velocity, 2 decimals>` (the date part reads `Mention dates unknown` when
  both are null), a line `Corporate actions: capex 1, orders 1` listing non-zero counts in the order capex,
  hiring, orders, capacity, partnership (`Corporate actions: none` when all are zero), then the `why_now`
  sentences.
- **Early evidence**: the `early_evidence` sentences, then the evidence items as a numbered list: quotes with
  source title, date and link; `counter` items prefixed `Counter-evidence:`; `financials` items as
  `<company name>: CapEx +25.0%, R&D n/a (SEC filings)` (signed, one decimal, `n/a` for null).
- **Affected sectors**: one line per sector, `<label> (ISIC <division>): <company names>`; then, when any
  company has no ISIC division, **Activities (no ISIC code)**: each group as `<activity>: <company names>`,
  then each by-company line as `<company name>: <activity>`, then `Not classified: <names>` when
  `unclassified_company_ids` is not empty.
- Each sentence and activity line ends with citation markers `[n]` (the `n` of `E<n>`); a marker scrolls to and
  highlights that item in the Early evidence list.
- `Dropped for lack of a cited source: <n>` when `dropped_statements` > 0.
- `failed`: the line `The brief's wording failed; facts, evidence and sectors are shown.` in place of the
  sentences.
- `context_brief` null: the section reads `No context brief: this run predates briefs.`

### Dossier step 1

`GET /api/dossiers/{id}` gains a top-level `context_brief`: the origin candidate's brief, or null (origin
`topic`, candidate missing, or candidate without a brief). Step 1's `state`, `detail` and `href` are unchanged.
The dossier page shows the brief under step 1 with the same component as the candidate card, collapsed behind
**Show context brief**; for origin `candidate` with a null brief it shows `No context brief: this run predates
briefs.`; for origin `topic` nothing.

## My calls (owner to confirm with the acceptance table)

1. **Stored on the candidate**, not a new record: the brief is a snapshot of the run's evidence, written once,
   like the candidate itself.
2. **ISIC divisions (two digits)**, not sections (too coarse: most themes would read "Manufacturing") nor the
   ICIO industry list (divisions 24 and 30 map to two industries there).
3. **Numbers in sentences must appear in a cited quote.** The scores and dates are shown by code, so the model
   never needs to write them.
4. **Groups need two companies**; a one-company group would repeat its by-company line.
5. **One extra evidence quote per company without ISIC** when none of the eight shown quotes covers it, so
   every such company can have a cited activity.
6. **A failed wording call keeps the candidate** and shows the code-built parts, like the existing SEC and role
   steps.
7. **No setting to switch the brief off.**
8. **One company order everywhere** (`candidate_sectors_companies`), so lists never depend on the model's order.
9. **Built after the dossier, one PR**, rather than splitting the dossier rows into a second spec.

## Constraints

- **Built after the dossier**, in one PR: rows AC-18 to AC-20, AC-29, AC-30 and AC-33 need the dossier's store
  and API, and the holdout job runs every row of this spec on the PR.
- Stand-ins: holdout and evaluator rows need the run to take a fixed mention source, clustering and model
  output, as the research-note spec's rows do. If the app has no such switch when the test-writer starts, that
  is a factory question for the owner, not a reason to change these rows.
- Repo checks; API contract regenerated and committed if the candidate or dossier response types change.
- Golden-set CI is not triggered (no change under `arp/extraction`, `arp/llm`, `arp/grounding.py`).

## Left to the builder

Prompt wording, where in `arp/emerging_themes/` the brief code lives, component structure and visual design
within DESIGN.md.

## Acceptance

Fixture: an Emerging Themes run executed through `execute_emerging_themes_run` with a stand-in mention source,
clustering replaced by a stand-in that puts every tag in one BIRTH cluster, company roles off, and a stand-in
model with fixed output per call (extraction, naming, brief). Universe: `acme` (Acme, `isic_code` `2720`),
`beta` (Beta, `2710`), `gamma` (Gamma, no code), `delta` (Delta, no code). Mentions, one tag each, all grounded,
distinct URLs `https://n.test/1` … `/5`:

| Mention | `published_at` | Resolves to | Action | Contradiction | Quote |
|---|---|---|---|---|---|
| m1 | 2026-09-01 | acme | capex | none | `Acme will invest $2bn in a cell plant.` |
| m2 | 2026-09-05 | beta | orders | none | `Beta ordered 40 electrolysers.` |
| m3 | 2026-09-10 | gamma | capacity | none | `Gamma doubled cell output.` |
| m4 | 2026-09-15 | delta, gamma | partnership | none | `Delta partners with Gamma on cell supply.` |
| m5 | 2026-09-20 | acme | other | delay | `Acme delayed its second line to 2028.` |

SEC stand-in: `acme` CapEx +25.0, R&D null; others none. So the pool is E1–E5 (quotes m1–m5), E6 (counter, m5),
E7 (financials, acme). Brief stand-in returns: `why_now` `[{"text": "Companies report spending on cell plants.",
ids ["E1"]}, {"text": "Orders reached 90 units.", ids ["E2"]}, {"text": "Demand is booming.", ids ["E99"]}]`;
`early_evidence` `[{"text": "Acme delayed its second line.", ids ["E6"]}]`; `by_company` `[{gamma, "Expanding
battery-cell output", ["E3"]}, {delta, "Supplying cells through a partnership", ["E4"]}, {acme, "Building a
plant", ["E1"]}]`; `groups` `[{"Battery-cell manufacturing", [gamma, delta, acme]}]`. Users `ana` (analyst),
`vic` (viewer).

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | the fixture run, completed | `GET /api/emerging-themes/runs/{run_id}/candidates` | 1 candidate; `context_brief.status` `written`; `error` null; `written_at` an ISO-8601 timestamp | holdout |
| AC-2 | AC-1 | read `context_brief.evidence` | 7 items, ids `E1`–`E7` in order; kinds `quote` ×5, `counter`, `financials`; E1's `quote` `Acme will invest $2bn in a cell plant.`, `url` `https://n.test/1`, `published_at` starting `2026-09-01`, `action_type` `capex`; E4's `company_ids` `delta`, `gamma`; E6's `quote` `Acme delayed its second line to 2028.`; E7 `company_id` `acme`, `capex_pct_change` 25.0, `rnd_pct_change` null | holdout |
| AC-3 | AC-1 | read `context_brief.facts` | `first_seen` `2026-09-01`; `last_seen` `2026-09-20`; `independent_sources` 5; `company_count` 4; `action_counts` `{capex: 1, hiring: 0, orders: 1, capacity: 1, partnership: 1}`; `velocity` equal to the candidate's `signal_velocity` | holdout |
| AC-4 | AC-1 | read `context_brief.sectors` | exactly 1 entry: `isic_division` `27`, `label` `Manufacture of electrical equipment`, `company_ids` `["acme", "beta"]`, `evidence_ids` `["E1", "E2", "E5", "E6", "E7"]` | holdout |
| AC-5 | the fixture with `beta`'s `isic_code` `3510` | run, read `sectors` | exactly 2 entries in order: division `27` `Manufacture of electrical equipment` with `company_ids` `["acme"]`, `evidence_ids` `["E1", "E5", "E6", "E7"]`; division `35` `Electricity, gas, steam and air conditioning supply` with `company_ids` `["beta"]`, `evidence_ids` `["E2"]` | holdout |
| AC-6 | AC-1 | read `why_now` and `early_evidence` | `why_now` exactly `[{text: "Companies report spending on cell plants.", evidence_ids: ["E1"]}]`; `early_evidence` exactly `[{text: "Acme delayed its second line.", evidence_ids: ["E6"]}]` | holdout |
| AC-7 | AC-1 | read `activities` | `by_company` exactly, in order, delta `Supplying cells through a partnership` `["E4"]`, gamma `Expanding battery-cell output` `["E3"]`; `groups` exactly `[{activity: "Battery-cell manufacturing", company_ids: ["delta", "gamma"], evidence_ids: ["E3", "E4"]}]`; `unclassified_company_ids` `[]` | holdout |
| AC-8 | AC-1 | read `dropped_statements` | 3 | holdout |
| AC-9 | AC-1 | read `companies` | in order: `acme` `Acme` `27`, `beta` `Beta` `27`, `delta` `Delta` null, `gamma` `Gamma` null | holdout |
| AC-10 | the fixture; brief stand-in's `by_company` returns only gamma | run, read `activities` | `groups` `[]`; `unclassified_company_ids` `["delta"]`; `dropped_statements` 3 (two statements, the one-company group) | holdout |
| AC-11 | the fixture; brief stand-in returns delta citing `["E1"]` | run, read `activities.by_company` | no delta line; `unclassified_company_ids` `["delta"]` | holdout |
| AC-12 | the fixture; `gamma`'s `isic_code` `X9` and `delta`'s `0012` | run, read the brief | `companies` gamma and delta `isic_division` null; `sectors` holds only division `27` | holdout |
| AC-13 | the fixture; brief stand-in raises | run completes | 1 candidate; `context_brief.status` `failed`; `error` `brief wording failed`; `why_now`, `early_evidence`, `by_company`, `groups` `[]`; `unclassified_company_ids` `["delta", "gamma"]`; `evidence` 7 items; `sectors` 1 entry; run status `completed` | holdout |
| AC-14 | the fixture plus acme mentions a1–a6 (new URLs, one acme capex tag each); member-tag order m1, m2, a1–a6, m3, m4, m5 | run, read `evidence` | `corroborating_sources` has 8 entries (m1, m2, a1–a6); the pool has 12 items: E1–E8 those quotes, E9 `quote` m3 with `company_ids` `["gamma"]`, E10 `quote` m4 with `company_ids` `["delta", "gamma"]`, E11 `counter` m5, E12 `financials` acme | holdout |
| AC-15 | the fixture with no `published_at` on any mention | run, read `facts` | `first_seen` null; `last_seen` null | holdout |
| AC-16 | the fixture; brief stand-in's `why_now` adds `{"text": "Acme will invest $2bn.", ids ["E1"]}` | run, read `why_now` | that sentence is kept; `dropped_statements` 3 | holdout |
| AC-17 | a run written before release (candidate rows with no `context_brief` key) | `GET .../candidates` | 200; that candidate's `context_brief` null | holdout |
| AC-18 | AC-1's candidate promoted by `ana` | `GET /api/dossiers/{dossier_id}` | `context_brief` equals the candidate's brief; step 1 `done`, detail `promoted: <reason sent>` | holdout |
| AC-19 | a dossier with origin `topic` | `GET /api/dossiers/{id}` | `context_brief` null | holdout |
| AC-20 | AC-17's candidate promoted | `GET /api/dossiers/{dossier_id}` | `context_brief` null; step 1 `done` | holdout |
| AC-21 | caller `vic`, AC-1 | `GET .../candidates` | 200 with `context_brief` | holdout |
| AC-22 | AC-1 in the running app | open Emerging Themes, view the candidate | **Context brief** open with headings `Why now`, `Early evidence`, `Affected sectors` in order; facts line `Mentions 2026-09-01 to 2026-09-20 · 5 independent sources · 4 companies · velocity <signal_velocity to 2 decimals>`; `Corporate actions: capex 1, orders 1, capacity 1, partnership 1`; sentence `Companies report spending on cell plants. [1]` | evaluator |
| AC-23 | AC-22 | read Early evidence | `Acme delayed its second line. [6]`; 7 numbered items; item 6 starts `Counter-evidence:`; item 7 reads `Acme: CapEx +25.0%, R&D n/a (SEC filings)` | evaluator |
| AC-24 | AC-22 | read Affected sectors | `Manufacture of electrical equipment (ISIC 27): Acme, Beta`; **Activities (no ISIC code)** with `Battery-cell manufacturing: Delta, Gamma`, `Delta: Supplying cells through a partnership [4]`, `Gamma: Expanding battery-cell output [3]`; no `Not classified` line | evaluator |
| AC-25 | AC-22 | click marker `[6]` | item 6 of the Early evidence list is scrolled into view and highlighted | evaluator |
| AC-26 | AC-22 | read the brief's end | `Dropped for lack of a cited source: 3` | evaluator |
| AC-27 | AC-13 in the running app | view the candidate | `The brief's wording failed; facts, evidence and sectors are shown.`; the sectors line is shown; `Not classified: Delta, Gamma` | evaluator |
| AC-28 | AC-17 in the running app | view the candidate | `No context brief: this run predates briefs.` | evaluator |
| AC-29 | AC-18 in the running app | open the dossier page, click **Show context brief** | the brief appears under step 1 with the same three headings and AC-22's facts line | evaluator |
| AC-30 | a topic-origin dossier in the running app | open it | no **Show context brief** and no brief text | evaluator |

Must not change:
- AC-31: the candidate's other fields (`theme_name`, scores, `corroborating_sources`, `contradiction_evidence`,
  `xbrl_corroboration`, `status`) are the same with and without the brief stand-in raising. Checked by: holdout.
- AC-32: promote, reject and disconfirm return the same status codes as before; a second promote is still 400.
  Checked by: holdout.
- AC-33: dossier step 1 states and details are as the dossier spec's AC-2, AC-15 and AC-19 require. Checked by:
  holdout.
- AC-34: a cluster failing the independent-source or action-score gate still produces no candidate and makes no
  brief model call. Checked by: holdout.
