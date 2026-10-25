# Theme research note: source plan, approval, cited note (step 3)

Status: draft, 2026-10-25.

Builds on the theme dossier spec (`2026-10-25-theme-dossier-design.md`, PR #226). That spec shows step 3 as
`not_built`; this spec replaces that with a real derivation and builds the step.

## Intent

After a theme's taxonomy is ratified (step 2) and before companies are found (step 4), the owner wants a
fact-based note on the theme as a whole: its risks and opportunities, why it matters financially for
companies, its growth potential, and the economic and financial channels through which it reaches company
results. The note must come only from authoritative sources the owner has approved, and every statement in it
must be traceable to a quote in one of them. The note's risks and opportunities are the input to step 5
(position and standards, a later spec).

## Owner decisions (2026-10-25)

1. Authoritative sources only, from a **closed list of four categories**: intergovernmental agency, government
   or official statistics, central bank or regulator, academic research. Think tanks, non-profit initiatives,
   industry bodies, consultancies, media, company and fund publications are never proposed and cannot be
   added.
2. The model proposes a source list, each source with **why** to use it and **how**. The owner edits and
   approves the list before anything is written.
3. The note is written only from the approved sources. **Every statement carries a verbatim quote** from one of
   them, checked by the existing grounding check; a statement without a grounded quote is dropped.
4. A source the app cannot fetch (paywall, broken link) can get an **uploaded file**. An approved source that
   can be neither fetched nor read from an upload is skipped, and the note lists it.
5. **Two approvals, one person each**: the source plan, then the written note. Step 3 is done only when the
   note is approved. No four-eyes.
6. Approach A: a research record attached to the dossier (below).

## Goals

- From a dossier with a ratified taxonomy, the owner can have sources proposed, edit the list, attach files,
  approve it, have the note written, and approve or reject the note, all from one screen.
- The note has five fixed sections and every item in it cites at least one approved source with a grounded
  quote.
- The dossier's step 3 shows the live state of this work, derived on read.
- Step 5 can read the latest approved note's risk and opportunity items by stable id.

## Non-goals

- Step 5, or anything that consumes the note beyond exposing it.
- Changing taxonomy research or the taxonomy authority-source feature it reuses code from.
- Judging source quality beyond the category (no scoring, no ranking shown to the owner).
- Editing the note's text by hand. A wrong note is rejected and rewritten.

## Anti-goals

- A statement in the note that no approved source supports.
- A note written from a source the owner did not approve.
- A source outside the four categories reaching the note.

## Approaches

| | Approach | Trade-off | |
|---|---|---|---|
| A | **Research record per dossier** (file store, like the dossier), holding rounds of plan → approval → note → approval; two background runs, "propose sources" and "write note". | One new record type; history kept per round; the dossier finds "the" approved note directly. | **Chosen by the owner** |
| B | Plan and note as outputs of runs in the run store; approvals through the generic review queue. | Less new storage; the dossier has to search runs for the approved note, history is scattered. | Rejected |
| C | One agent run that pauses for each approval. | Most automated; a run paused for days fits badly, as the dossier spec found. | Rejected |

All three reuse the existing pieces in `arp/research/taxonomy_sources/` (`discovery.py` web search,
`fetch.py` fetch and text extraction) and `arp/grounding.py` (`ground_citations`).

## The record

One research record per dossier, stored as a JSON file next to the dossier's (`runs_dir/_dossiers/`, written
atomically). It holds `dossier_id` and a list of **rounds**, numbered from 1. A round holds:

- `round` (int), `taxonomy_version` (the latest ratified version when the round started);
- `plan_status`: `proposing`, `proposal_failed`, `proposed`, `approved`;
- `proposal_run_id`, `plan_approved_by` (display name), `plan_approved_at` (ISO-8601 UTC);
- `sources`: list of source entries (below);
- `note`: null, or the note (below);
- `note_run_id` (nullable).

GET also returns `approved_round`: the highest round whose note is `approved`, or null.

### Source entry

- `source_id` (`src_` + 12 hex), `title`, `publisher`, `url`;
- `category`: one of `intergovernmental`, `official_statistics`, `central_bank_regulator`, `academic`;
- `why` (why this source is relevant to the theme), `how` (which note sections it feeds and what to take from
  it), both non-blank;
- `added_by`: `model` or the adding user's display name;
- `file`: null, or `{filename, uploaded_by, uploaded_at}` for an uploaded copy.

On screen the categories read `Intergovernmental agency`, `Government or official statistics`,
`Central bank or regulator`, `Academic research`.

### Note

- `status`: `writing`, `write_failed`, `written`, `approved`, `rejected`;
- `sections`: an object with exactly these keys, in this order: `risks`, `opportunities`,
  `financial_relevance`, `growth_potential`, `transmission_channels`. Each is a list of items;
- item: `item_id` (`itm_` + 12 hex, never reused), `title` (at most 120 characters), `text`,
  `channel` (`economic` or `financial` for `transmission_channels` items, null elsewhere), `citations`:
  non-empty list of `{source_id, quote, page}` (`page` set by grounding for PDFs, else null);
- `unread_sources`: list of `{source_id, reason}` with reason `fetch failed` or `no text extracted`;
- `dropped_items` (int): items the model wrote that had no grounded citation;
- `written_at`, `approved_by`, `approved_at`, `rejected_by`, `rejected_at`, `reject_reason`, `error` (set when
  `write_failed`).

## How it works

### 1. Propose sources (background run, type `theme_research_sources`)

Allowed when the dossier has a taxonomy with a ratified version, and there is no round yet or the latest
round's note is `approved` (that starts a new round), or the latest round is `proposal_failed` (that round is
proposed again). A new round after an approved one starts with the previous round's approved sources, marked
`added_by` as before, and the model's new proposals added after them, skipping any URL already present.

The run searches the web (the existing `WebSearchClient`) with queries built from the taxonomy's theme name
and description, aimed at each category (e.g. `<theme> IEA report`, `<theme> OECD`, `<theme> official
statistics`, `<theme> central bank`, `<theme> journal article`). The model then classifies each result into
one of the four categories or `none`, and for each kept result writes `publisher`, `why` and `how`. Results
classified `none` are discarded. At most 12 sources are proposed. The round becomes `proposed`; zero sources
is a valid outcome. A failed run sets `proposal_failed`.

### 2. Edit and approve the plan

While `plan_status` is `proposed`, the owner can remove sources, add their own (title, publisher, url,
category, why, how; all required; category must be one of the four) and approve. Approval needs at least one
source and freezes the list.

A file can be uploaded to a source while the round's note is null, `write_failed` or `rejected` (PDF, HTML or
plain text, under the existing `max_upload_bytes` limit). A second upload replaces the first.

### 3. Write the note (background run, type `theme_research_note`)

Allowed when the plan is `approved` and the note is null, `write_failed` or `rejected` (a rewrite replaces the
rejected note; its `item_id`s are not reused). For each approved source: the uploaded file's text if there is
a file, else the fetched URL text (`fetch_source_text`). Sources with no text go to `unread_sources`. If no
source has text, the note is `write_failed` with `error` `no approved source could be read`.

The model receives only the readable approved sources' text, labelled by `source_id`, plus the theme name and
description, and returns items per section, each with citations. The system prompt asks for neutral,
fact-based statements (no promotional language, no forecasts the sources do not make) and for each risk and
opportunity to state the mechanism. Each citation is checked with `ground_citations` against its source's text
(threshold 0.92, as in authority extraction); ungrounded citations are removed, a citation naming a
`source_id` that is not an approved source is removed, and an item left with no citation is dropped and
counted in `dropped_items`. The note becomes `written`.

### 4. Approve or reject the note

`written` → approve (sets `approved_by`, `approved_at`) or reject with a non-blank reason. Rejecting sends the
round's `plan_status` back to `proposed`, so the owner can change the sources and approve again, then rewrite.

## API

Under `/api/dossiers/{dossier_id}/research`, behind `authorize`: viewer reads, analyst writes and approves
(the same role that ratifies taxonomies). Unknown dossier → 404 `unknown dossier '<id>'`. Every refused
transition below is a 409 with the `detail` given.

- `GET` → `{dossier_id, approved_round, rounds}`; `rounds` is `[]` before the first proposal.
- `POST /propose` → 202 `{run_id, round}`. 409 `ratify a taxonomy first`; 409 `round <n> is in progress`.
- `POST /sources` `{title, publisher, url, category, why, how}` → 200, the new source. 422 on a blank field or
  a category outside the four. 409 `the source plan is not open for edits`.
- `DELETE /sources/{source_id}` → 200. 404 `unknown source '<id>'`. 409 as above.
- `POST /sources/{source_id}/file` (multipart `file`) → 200, the source. 413 over the limit; 415 for anything
  but PDF, HTML or plain text; 404 unknown source; 409 `the note is already written`.
- `POST /plan/approve` → 200, the round. 409 `add at least one source`; 409 `the source plan is not open for
  edits`.
- `POST /note` → 202 `{run_id}`. 409 `approve the source plan first`; 409 `the note is already written`.
- `POST /note/approve` → 200, the round. `POST /note/reject` `{reason}` → 200; 422 when `reason` is missing or
  blank. Both 409 `there is no written note` unless the note is `written`.

All write endpoints act on the latest round. A shelved dossier refuses every write with 409 `dossier is
shelved`.

## Dossier step 3 (replaces "always `not_built`")

Let `R` be the latest round, `L` the taxonomy's latest ratified version. In order, the first that applies:

| Condition | State | Detail |
|---|---|---|
| no ratified taxonomy version | `not_started` | `ratify a taxonomy first` |
| no round | `not_started` | `propose sources` |
| `R` `proposing` | `running` | `proposing sources` |
| `R` `proposal_failed` | `failed` | `source proposal failed` |
| `R` `proposed`, note `rejected` | `waiting` | `note rejected: <reason>` |
| `R` `proposed`, 0 sources | `waiting` | `add sources` |
| `R` `proposed` | `waiting` | `approve <n> sources` |
| note null | `waiting` | `write the note` |
| note `writing` | `running` | `writing note` |
| note `write_failed` | `failed` | `note failed: <error>` |
| note `written` | `waiting` | `approve the note` |
| note `approved` | `done` | `note r<round> approved by <name>` |

When the state is `done` and `L` > `R.taxonomy_version`, the detail gains ` · older than v<L>` and the state
is `waiting`, as step 4 does. `href`: `null` in the first row, else `#/themes/<dossier_id>/research`.

`current_step` in `GET /api/dossiers` now counts step 3 like any other step.

### Dossier spec rows this changes

When this ships, these rows of the dossier spec no longer hold and the owner retires them there:
AC-2 (step 3 becomes `not_started` with `href` null), AC-28 (AC-7's dossier gets `current_step` 3, not 4;
AC-11's gets 3, not null), AC-34 (step 3 reads `Not started`, not `Coming later`). Step 5 stays `not_built`.

## Screen

`#/themes/<dossier_id>/research`, linked from the dossier page's step 3. It shows the latest round:

- **Sources**: a table with title (linked to the URL), publisher, category label, why, how, file (name or an
  **Upload** button) and a remove action while the plan is open; an **Add source** form; **Approve sources**.
  A **Propose sources** button when proposing is allowed.
- **Note**, once written: the five sections with the headings `Risks`, `Opportunities`,
  `Financial relevance`, `Growth potential`, `Transmission channels`; transmission channel items carry an
  `Economic` or `Financial` tag. Each item shows its title, text and numbered citation markers; a marker opens
  the quote with the source's title, page and link. A line `Not read: <title> (<reason>)` per unread source and
  `<n> statements dropped for lack of a checked quote` when `dropped_items` > 0. **Approve note** and
  **Reject note** (reason required).
- Earlier rounds as a collapsed list, each showing its sources and note read-only.

## My calls (owner to confirm with the acceptance table)

1. **Category is the gate, not a score.** The model's classification can be wrong; the owner's plan approval is
   the check. User-added sources declare their category and are not second-guessed.
2. **Analyst role approves**, matching taxonomy ratification. "One approver" means one sign-off, not a new role.
3. **Rejecting the note reopens the plan** rather than offering a separate "rewrite with same sources" path:
   the owner can approve the unchanged list again.
4. **Rounds**: re-researching a done theme starts a new round seeded with the last approved sources; the last
   approved note stays the one step 5 reads until a newer one is approved.
5. **Taxonomy drift** flags step 3 the same way as step 4.
6. **12 proposed sources at most**, so the plan stays reviewable.

## Constraints

- Repo checks; API contract regenerated and committed.
- Golden-set CI is not triggered (no change under `arp/extraction`, `arp/llm`, `arp/grounding.py`).
- Fetching goes through the existing SSRF-guarded `fetch_source_text`.

## Left to the builder

Prompt wording, whether the note is written in one model call or several, query templates beyond the
examples, file layout of uploads, component structure and visual design within DESIGN.md.

## Acceptance

Fixture, seeded through the backend's own stores: dossier `D` with taxonomy `tax_a` (v1 ratified by `ana`);
dossier `E` with taxonomy `tax_b` (draft only). Backend rows replace the web search and the model with
stand-ins that return the same fixed output on every call. Search stand-in returns 4 results: `IEA World
Energy Outlook` (`https://iea.org/weo`), `Eurostat energy statistics` (`https://ec.europa.eu/eurostat/x`),
`Think Tank X brief` (`https://ttx.org/b`), `J. Energy Econ paper` (`https://doi.org/10.1/x`). Classification
stand-in: IEA → `intergovernmental`, Eurostat → `official_statistics`, Think Tank X → `none`, paper →
`academic`. Fetch stand-in: the IEA URL returns text containing `Grid investment must double by 2030.`; the
Eurostat URL returns text containing `Electricity prices rose 12% in 2023.`; the paper URL fails. Note
stand-in returns: a `risks` item citing Eurostat with quote `Electricity prices rose 12% in 2023.`; an
`opportunities` item citing IEA with quote `Grid investment must double by 2030.`; a `growth_potential` item
citing IEA with quote `Demand will triple.` (not in the text); a `transmission_channels` item with channel
`financial` citing IEA with the grounded quote and Eurostat with an ungrounded quote. Users `ana` (analyst),
`vic` (viewer).

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `D`, no research | `GET /api/dossiers/D/research` | 200; `rounds` `[]`; `approved_round` null | holdout |
| AC-2 | `D`, no research | `GET /api/dossiers/D` | step 3 `not_started`, detail `propose sources`, `href` `#/themes/D/research` | holdout |
| AC-3 | `E` | `POST /api/dossiers/E/research/propose` | 409, detail `ratify a taxonomy first`; step 3 of `E` `not_started`, detail `ratify a taxonomy first`, `href` null | holdout |
| AC-4 | `D` | `POST .../propose`, run completes | 202 with `round` 1; then `GET`: round 1 `plan_status` `proposed`, `taxonomy_version` 1, sources' URLs exactly the IEA, Eurostat and paper URLs in that order, categories `intergovernmental`, `official_statistics`, `academic`, each `added_by` `model`, `why` and `how` non-empty | holdout |
| AC-5 | AC-4 | `GET /api/dossiers/D` | step 3 `waiting`, detail `approve 3 sources` | holdout |
| AC-6 | AC-4 | `POST .../propose` again | 409, detail `round 1 is in progress` | holdout |
| AC-7 | search stand-in raises | propose, run ends | round 1 `plan_status` `proposal_failed`; step 3 `failed`, detail `source proposal failed`; a second propose returns 202 with `round` 1 | holdout |
| AC-8 | AC-4 | `POST .../sources` with `category` `think_tank`; again with `why` `"  "` | both 422 | holdout |
| AC-9 | AC-4, caller `ana` | `POST .../sources` `{title: "ECB bulletin", publisher: "ECB", url: "https://ecb.europa.eu/b", category: "central_bank_regulator", why: "w", how: "h"}` | 200; `source_id` matches `^src_[0-9a-f]{12}$`; `added_by` `ana`; `GET` lists 4 sources | holdout |
| AC-10 | AC-9 | `DELETE .../sources/<ECB id>` | 200; `GET` lists the 3 model sources | holdout |
| AC-11 | AC-4 with all sources deleted | `POST .../plan/approve` | 409, detail `add at least one source`; step 3 detail `add sources` | holdout |
| AC-12 | AC-4, caller `ana` | `POST .../plan/approve` | 200; `plan_status` `approved`; `plan_approved_by` `ana`; step 3 `waiting`, detail `write the note` | holdout |
| AC-13 | AC-12 | `POST .../sources` (valid body); `DELETE` a source | both 409, detail `the source plan is not open for edits` | holdout |
| AC-14 | AC-4 | `POST .../note` | 409, detail `approve the source plan first` | holdout |
| AC-15 | AC-12 | `POST .../note`, run completes | note `status` `written`; `risks` has 1 item citing Eurostat; `opportunities` 1 item citing IEA; `growth_potential` `[]`; `financial_relevance` `[]`; `transmission_channels` 1 item with `channel` `financial` and exactly 1 citation (IEA); `dropped_items` 1; `unread_sources` `[{source_id: <paper id>, reason: "fetch failed"}]`; every `item_id` matches `^itm_[0-9a-f]{12}$` | holdout |
| AC-16 | AC-15 | `GET /api/dossiers/D` | step 3 `waiting`, detail `approve the note` | holdout |
| AC-17 | AC-12 with a PDF uploaded to the paper source containing `Storage costs fell 40%.`; note stand-in adds an `opportunities` item citing the paper with that quote | `POST .../note`, run completes | `opportunities` has 2 items; `unread_sources` `[]` | holdout |
| AC-18 | AC-12; fetch stand-in fails for every URL; no uploads | `POST .../note`, run completes | note `status` `write_failed`, `error` `no approved source could be read`; step 3 `failed`, detail `note failed: no approved source could be read` | holdout |
| AC-19 | AC-12; note stand-in cites a `source_id` not in the plan with a quote present in the IEA text | `POST .../note`, run completes | that item is absent from the note; `dropped_items` counts it | holdout |
| AC-20 | AC-15 | `POST .../sources/<paper id>/file` with a PDF | 409, detail `the note is already written` | holdout |
| AC-21 | AC-12 | upload a 1 KB `.exe`; upload a file over `max_upload_bytes` | 415; 413 | holdout |
| AC-22 | AC-15, caller `ana` | `POST .../note/approve` | 200; note `status` `approved`, `approved_by` `ana`; `GET` research has `approved_round` 1; step 3 `done`, detail `note r1 approved by ana` | holdout |
| AC-23 | AC-15 | `POST .../note/reject` without `reason`; with `"  "` | both 422 | holdout |
| AC-24 | AC-15 | `POST .../note/reject {"reason": "Too thin"}` | 200; note `status` `rejected`; `plan_status` `proposed`; step 3 `waiting`, detail `note rejected: Too thin`; adding a source now returns 200 | holdout |
| AC-25 | AC-24, plan approved again | `POST .../note`, run completes | note `status` `written`; no `item_id` equals one from AC-15's note | holdout |
| AC-26 | AC-12 | `POST .../note/approve` | 409, detail `there is no written note` | holdout |
| AC-27 | AC-22 | `POST .../propose`, run completes | 202 with `round` 2; round 2 `plan_status` `proposed`, sources are round 1's 3 approved sources with no duplicate URL; `approved_round` still 1 | holdout |
| AC-28 | AC-22, then `tax_a` v2 ratified by `bob` | `GET /api/dossiers/D` | step 3 `waiting`, detail `note r1 approved by ana · older than v2` | holdout |
| AC-29 | AC-22 | `GET /api/dossiers` | `D`'s `current_step` is 4 | holdout |
| AC-30 | AC-4 | `GET /api/dossiers` | `D`'s `current_step` is 3 | holdout |
| AC-31 | `D` shelved | `POST .../propose`; `POST .../sources` | both 409, detail `dossier is shelved` | holdout |
| AC-32 | caller `vic` | `GET .../research`; `POST .../propose`; `POST .../plan/approve`; `POST .../note/approve` | 200; 403; 403; 403 | holdout |
| AC-33 | unknown id | `GET /api/dossiers/dos_000000000000/research` | 404, detail `unknown dossier 'dos_000000000000'` | holdout |
| AC-34 | AC-4 | `DELETE .../sources/src_000000000000` | 404, detail `unknown source 'src_000000000000'` | holdout |
| AC-35 | the running app, AC-4's dossier | open the dossier page, click step 3's link | `#/themes/D/research` shows the 3 sources with category labels `Intergovernmental agency`, `Government or official statistics`, `Academic research`, each with its why and how | evaluator |
| AC-36 | AC-35 | add a source with category `Central bank or regulator`, remove it, click **Approve sources** | the source appears then disappears; after approval the remove actions and the add form are gone and step 3 on the dossier page reads `Waiting`, `write the note` | evaluator |
| AC-37 | AC-15's dossier | open `#/themes/D/research` | headings `Risks`, `Opportunities`, `Financial relevance`, `Growth potential`, `Transmission channels` in order; the transmission item is tagged `Financial`; `Not read: J. Energy Econ paper (fetch failed)`; `1 statements dropped for lack of a checked quote` | evaluator |
| AC-38 | AC-37 | open the risk item's citation marker | shows quote `Electricity prices rose 12% in 2023.`, title `Eurostat energy statistics` and a link to its URL | evaluator |
| AC-39 | AC-37 | click **Reject note** with reason `Too thin` | the sources table is editable again; the dossier page's step 3 reads `Waiting`, `note rejected: Too thin` | evaluator |
| AC-40 | AC-27's dossier | open the research screen | round 1 is listed collapsed with its approved note readable | evaluator |

Must not change:
- AC-41: the taxonomy authority-source endpoints and the taxonomy research run return the same status codes and
  bodies as before. Checked by: holdout.
- AC-42: dossier steps 1, 2, 4 and 5 derive exactly as in the dossier spec (its AC-5 to AC-14, AC-19, AC-20).
  Checked by: holdout.
