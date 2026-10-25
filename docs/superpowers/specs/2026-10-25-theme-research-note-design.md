# Theme research note: source plan, approval, cited note (step 3)

Status: approved by the owner, 2026-10-25.

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
- Measuring the real model's source classification or wording on a golden set. The owner's plan approval and
  note approval are the checks on model quality; acceptance rows use stand-ins.

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
- item: `item_id` (`itm_` + 12 hex, never reused), `title` (a longer title from the model is truncated to its
  first 120 characters), `text`,
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
proposed again). A new round after an approved one starts with copies of the previous round's sources, keeping
their `source_id`, `added_by` and `file`, then the model's new proposals after them, skipping any URL already
present.

The run searches the web (the existing `WebSearchClient`) with queries built from the taxonomy's theme name
and description, aimed at each category (e.g. `<theme> IEA report`, `<theme> OECD`, `<theme> official
statistics`, `<theme> central bank`, `<theme> journal article`). The model then classifies each result into
one of the four categories or `none`, and for each kept result writes `publisher`, `why` and `how`. Results
classified `none` are discarded. At most 12 sources are proposed: the first 12 kept results in search
order. The round becomes `proposed`; zero sources
is a valid outcome. A failed run sets `proposal_failed`.

### 2. Edit and approve the plan

While `plan_status` is `proposed`, the owner can remove sources, add their own (title, publisher, url,
category, why, how; all required; category must be one of the four) and approve. Approval needs at least one
source and freezes the list.

A file can be uploaded to a source while the round's note is null, `write_failed` or `rejected`. Accepted by
file extension: `.pdf`, `.html`, `.htm`, `.txt`; anything else is 415. Size limit: the existing
`max_upload_bytes`. A second upload replaces the first.

### 3. Write the note (background run, type `theme_research_note`)

Allowed when the plan is `approved` and the note is null, `write_failed` or `rejected` (a rewrite replaces the
rejected note; its `item_id`s are not reused). For each approved source: the uploaded file's text if there is
a file, else the fetched URL text (`fetch_source_text`). Sources with no text go to `unread_sources`. If no
source has text, the note is `write_failed` with `error` `no approved source could be read`.

The model receives only the readable approved sources' text, labelled by `source_id`, plus the theme name and
description, and returns items per section, each with citations. The note is written in one model call
(at most 12 sources, each source's text capped at the existing 60,000 characters), so stand-ins are well
defined. The system prompt asks for neutral,
fact-based statements (no promotional language, no forecasts the sources do not make) and for each risk and
opportunity to state the mechanism. Each citation is checked with `ground_citations` against its source's text
(threshold 0.92, as in authority extraction). `page` is set only for uploaded PDFs, whose page breaks are
kept; fetched text has none, so their citations have `page` null. Ungrounded citations are removed, a citation naming a
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
| note null, or `rejected` with the plan approved again | `waiting` | `write the note` |
| note `writing` | `running` | `writing note` |
| note `write_failed` | `failed` | `note failed: <error>` |
| note `written` | `waiting` | `approve the note` |
| note `approved` | `done` | `note r<round> approved by <name>` |

When the state is `done` and `L` > `R.taxonomy_version`, the detail gains ` · older than v<L>` and the state
is `waiting`, as step 4 does. `href`: `null` in the first row, else `#/themes/<dossier_id>/research`.

`current_step` in `GET /api/dossiers` now counts step 3 like any other step: a `waiting` step 3 (drift
included) makes it 3.

### Dossier spec rows this changes

When this ships, these rows of the dossier spec no longer hold and the owner retires them there:
AC-2 (step 3 becomes `not_started` with `href` null), AC-28 (AC-7's dossier gets `current_step` 3, not 4;
AC-11's gets 3, not null), AC-34 (step 3 reads `Not started`, not `Coming later`). Step 5 stays `not_built`.

## Screen

`#/themes/<dossier_id>/research`, linked from the dossier page's step 3. It shows the latest round:

- **Sources**: a table with title (linked to the URL), publisher, category label, why, how, file (name or an
  **Upload** button) and a remove action while the plan is open; an **Add source** form; **Approve sources**.
  A **Propose sources** button when proposing is allowed.
- **Write note**, once the plan is approved and the note is null, `write_failed` or `rejected`.
- **Note**, once written: the five sections with the headings `Risks`, `Opportunities`,
  `Financial relevance`, `Growth potential`, `Transmission channels`; transmission channel items carry an
  `Economic` or `Financial` tag. Each item shows its title, text and numbered citation markers; a marker opens
  the quote with the source's title, page and link. A line `Not read: <title> (<reason>)` per unread source and
  `Dropped for lack of a checked quote: <n>` when `dropped_items` > 0. **Approve note** and
  **Reject note** (reason required).
- Earlier rounds as a collapsed list, each showing its sources and note read-only.

## What step 5 reads

`GET /api/dossiers/{id}/research`: the round numbered `approved_round`, its `note.sections.risks` and
`note.sections.opportunities`. `item_id`s never change once written.

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
7. **Carried-over sources keep their id and upload**, so a new round can cite the same documents without
   re-uploading.
8. **Page numbers only for uploaded PDFs.** Fetched PDFs get `page` null, so the fetch code shared with the
   taxonomy feature stays unchanged.
9. **The note is written in one model call**, so it is consistent and testable with one stand-in.

## Constraints

- **Depends on the dossier being built** (store, `/api/dossiers`, `#/themes`). The dossier spec is merged as a
  spec only; this is built after it.
- Stand-ins: holdout and evaluator rows need the running app to take a fixed web search, fetch and model
  output, as the Ask ARP spec's rows do. If the app has no such switch when the test-writer starts, that is a
  factory question for the owner, not a reason to change these rows.
- Repo checks; API contract regenerated and committed.
- Golden-set CI is not triggered (no change under `arp/extraction`, `arp/llm`, `arp/grounding.py`).
- Fetching goes through the existing SSRF-guarded `fetch_source_text`.

## Left to the builder

Prompt wording, query templates beyond the
examples, file layout of uploads, component structure and visual design within DESIGN.md.

## Acceptance

Fixture, seeded through the backend's own stores: dossier `D` with taxonomy `tax_a` (v1 ratified by `ana`);
dossier `E` with taxonomy `tax_b` (draft only). The web search, the fetch and the model are replaced by
stand-ins that return the same fixed output on every call; **the evaluator's running app uses the same
stand-ins**. Search stand-in returns 4 results: `IEA World Energy Outlook` (`https://iea.org/weo`), `Eurostat
energy statistics` (`https://ec.europa.eu/eurostat/x`), `Think Tank X brief` (`https://ttx.org/b`), `J. Energy
Econ paper` (`https://doi.org/10.1/x`). Classification stand-in: IEA → `intergovernmental`, Eurostat →
`official_statistics`, Think Tank X → `none`, paper → `academic`. Fetch stand-in: the IEA URL returns text
containing `Grid investment must double by 2030.`; the Eurostat URL returns text containing `Electricity prices
rose 12% in 2023.`; the paper URL's fetch raises an error. Note stand-in returns: a `risks` item citing Eurostat with quote
`Electricity prices rose 12% in 2023.`; an `opportunities` item citing IEA with quote `Grid investment must
double by 2030.`; a `growth_potential` item citing IEA with quote `Demand will triple.` (not in the text); a
`transmission_channels` item with channel `financial` citing IEA with the grounded quote and Eurostat with an
ungrounded quote. "Slow" stand-ins wait 30 s before returning. Users `ana` (analyst), `vic` (viewer).

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `D`, no research | `GET /api/dossiers/D/research` | 200; `rounds` `[]`; `approved_round` null | holdout |
| AC-2 | `D`, no research | `GET /api/dossiers/D` | step 3 `not_started`, detail `propose sources`, `href` `#/themes/D/research` | holdout |
| AC-3 | `E` | `POST /api/dossiers/E/research/propose` | 409, detail `ratify a taxonomy first` | holdout |
| AC-4 | `E` | `GET /api/dossiers/E` | step 3 `not_started`, detail `ratify a taxonomy first`, `href` null | holdout |
| AC-5 | `D` | `POST .../propose` | 202; body `round` 1 and a `run_id` | holdout |
| AC-6 | AC-5, run completed | `GET .../research` | round 1: `plan_status` `proposed`; `taxonomy_version` 1; sources' URLs exactly IEA, Eurostat, paper in that order; categories `intergovernmental`, `official_statistics`, `academic`; each `source_id` matches `^src_[0-9a-f]{12}$`; each `added_by` `model`; each `why` and `how` non-empty | holdout |
| AC-7 | AC-6 | `GET /api/dossiers/D` | step 3 `waiting`, detail `approve 3 sources` | holdout |
| AC-8 | `D`, slow search stand-in | `POST .../propose`, then `GET /api/dossiers/D` within 5 s | step 3 `running`, detail `proposing sources` | holdout |
| AC-9 | AC-6 | `POST .../propose` | 409, detail `round 1 is in progress` | holdout |
| AC-10 | `D`, search stand-in raises | `POST .../propose`, run ends | round 1 `plan_status` `proposal_failed` | holdout |
| AC-11 | AC-10 | `GET /api/dossiers/D` | step 3 `failed`, detail `source proposal failed` | holdout |
| AC-12 | AC-10 | `POST .../propose` | 202, body `round` 1 | holdout |
| AC-13 | AC-6 | `POST .../sources` with `category` `think_tank` (other fields valid) | 422 | holdout |
| AC-14 | AC-6 | `POST .../sources` with `why` `"  "` (other fields valid) | 422 | holdout |
| AC-15 | AC-6, caller `ana` | `POST .../sources` `{title: "ECB bulletin", publisher: "ECB", url: "https://ecb.europa.eu/b", category: "central_bank_regulator", why: "w", how: "h"}` | 200; `source_id` matches `^src_[0-9a-f]{12}$`; `added_by` `ana`; `GET .../research` lists 4 sources | holdout |
| AC-16 | AC-15 | `DELETE .../sources/<ECB id>` | 200; `GET .../research` lists exactly the 3 model sources | holdout |
| AC-17 | AC-6 | `DELETE .../sources/src_000000000000` | 404, detail `unknown source 'src_000000000000'` | holdout |
| AC-18 | AC-6 with all 3 sources deleted | `POST .../plan/approve` | 409, detail `add at least one source` | holdout |
| AC-19 | AC-18 | `GET /api/dossiers/D` | step 3 `waiting`, detail `add sources` | holdout |
| AC-20 | AC-6, caller `ana` | `POST .../plan/approve` | 200; `plan_status` `approved`; `plan_approved_by` `ana`; `plan_approved_at` an ISO-8601 timestamp | holdout |
| AC-21 | AC-20 | `GET /api/dossiers/D` | step 3 `waiting`, detail `write the note` | holdout |
| AC-22 | AC-20 | `POST .../sources` (valid body) | 409, detail `the source plan is not open for edits` | holdout |
| AC-23 | AC-20 | `DELETE .../sources/<IEA id>` | 409, detail `the source plan is not open for edits` | holdout |
| AC-24 | AC-6 | `POST .../note` | 409, detail `approve the source plan first` | holdout |
| AC-25 | AC-20 | `POST .../note`, run completes | note `status` `written`; `risks` 1 item citing Eurostat; `opportunities` 1 item citing IEA; `financial_relevance` `[]`; `growth_potential` `[]`; `transmission_channels` 1 item with `channel` `financial` and exactly 1 citation, IEA's, `page` null; every `item_id` matches `^itm_[0-9a-f]{12}$` | holdout |
| AC-26 | AC-25 | `GET .../research` | note `dropped_items` 1; `unread_sources` `[{source_id: <paper id>, reason: "fetch failed"}]` | holdout |
| AC-27 | AC-25 | `GET /api/dossiers/D` | step 3 `waiting`, detail `approve the note` | holdout |
| AC-28 | AC-20, slow model stand-in | `POST .../note`, then `GET /api/dossiers/D` within 5 s | step 3 `running`, detail `writing note` | holdout |
| AC-29 | AC-20, a one-page PDF containing `Storage costs fell 40%.` uploaded to the paper source; note stand-in adds an `opportunities` item citing the paper with that quote | `POST .../note`, run completes | `opportunities` 2 items; the paper item's citation `page` 1; `unread_sources` `[]` | holdout |
| AC-30 | AC-20, fetch stand-in fails for every URL, no uploads | `POST .../note`, run completes | note `status` `write_failed`, `error` `no approved source could be read` | holdout |
| AC-31 | AC-30 | `GET /api/dossiers/D` | step 3 `failed`, detail `note failed: no approved source could be read` | holdout |
| AC-32 | AC-20; note stand-in also returns a `risks` item citing `src_000000000000` with a quote present in the IEA text | `POST .../note`, run completes | `risks` holds only the Eurostat item; `dropped_items` 2 | holdout |
| AC-33 | AC-25 | `POST .../sources/<paper id>/file` with a PDF | 409, detail `the note is already written` | holdout |
| AC-34 | AC-20 | `POST .../sources/<IEA id>/file` with `x.exe`, 1 KB | 415 | holdout |
| AC-35 | AC-20 | `POST .../sources/<IEA id>/file` with `x.pdf` one byte over `max_upload_bytes` | 413 | holdout |
| AC-36 | AC-25, caller `ana` | `POST .../note/approve` | 200; note `status` `approved`, `approved_by` `ana`, `approved_at` an ISO-8601 timestamp | holdout |
| AC-37 | AC-36 | `GET .../research` | `approved_round` 1 | holdout |
| AC-38 | AC-36 | `GET /api/dossiers/D` | step 3 `done`, detail `note r1 approved by ana` | holdout |
| AC-39 | AC-36 | `GET .../research` twice | the `item_id`s of round 1's `risks` and `opportunities` are identical in both responses and to AC-25's | holdout |
| AC-40 | AC-25 | `POST .../note/reject` with no `reason`; with `{"reason": "  "}` | both 422 | holdout |
| AC-41 | AC-25 | `POST .../note/reject {"reason": "Too thin"}` | 200; note `status` `rejected`; `plan_status` `proposed` | holdout |
| AC-42 | AC-41 | `GET /api/dossiers/D` | step 3 `waiting`, detail `note rejected: Too thin` | holdout |
| AC-43 | AC-41 | `POST .../sources` (valid body) | 200 | holdout |
| AC-44 | AC-41, plan approved again | `GET /api/dossiers/D` | step 3 `waiting`, detail `write the note` | holdout |
| AC-45 | AC-44 | `POST .../note`, run completes | note `status` `written`; no `item_id` equals one from AC-25's note | holdout |
| AC-46 | AC-20 | `POST .../note/approve` | 409, detail `there is no written note` | holdout |
| AC-47 | AC-36 | `POST .../propose`, run completes | 202 with `round` 2; round 2 `plan_status` `proposed`; exactly 3 sources, URLs IEA, Eurostat, paper in that order, the same `source_id`s as round 1, each `added_by` `model`; `approved_round` still 1 | holdout |
| AC-48 | AC-36, then `tax_a` v2 ratified by `bob` | `GET /api/dossiers/D` | step 3 `waiting`, detail `note r1 approved by ana · older than v2` | holdout |
| AC-49 | AC-36 | `GET /api/dossiers` | `D`'s `current_step` is 4 | holdout |
| AC-50 | AC-6 | `GET /api/dossiers` | `D`'s `current_step` is 3 | holdout |
| AC-51 | `D` shelved | `POST .../propose` | 409, detail `dossier is shelved` | holdout |
| AC-52 | AC-6, then `D` shelved | `POST .../sources` (valid body) | 409, detail `dossier is shelved` | holdout |
| AC-53 | AC-25, caller `vic` | `GET .../research`; `POST .../propose`; `POST .../plan/approve`; `POST .../note/approve` | 200; 403; 403; 403 | holdout |
| AC-54 | unknown id | `GET /api/dossiers/dos_000000000000/research` | 404, detail `unknown dossier 'dos_000000000000'` | holdout |
| AC-55 | `D` in the running app | open the dossier page, click step 3's link, click **Propose sources** | the URL is `#/themes/D/research`; after the run, 3 sources with category labels `Intergovernmental agency`, `Government or official statistics`, `Academic research`, each with its why and how | evaluator |
| AC-56 | AC-55 | upload a PDF to the paper source | its file name appears in the paper's file column | evaluator |
| AC-57 | AC-55 | add a source with category `Central bank or regulator`, then remove it | the source appears, then is gone | evaluator |
| AC-58 | AC-55 | click **Approve sources** | the remove actions and the add form are gone; **Write note** appears; the dossier page's step 3 reads `Waiting`, `write the note` | evaluator |
| AC-59 | AC-58, no upload | click **Write note** | after the run: headings `Risks`, `Opportunities`, `Financial relevance`, `Growth potential`, `Transmission channels` in that order; the transmission item tagged `Financial`; `Not read: J. Energy Econ paper (fetch failed)`; `Dropped for lack of a checked quote: 1` | evaluator |
| AC-60 | AC-59 | open the risk item's citation marker | quote `Electricity prices rose 12% in 2023.`, title `Eurostat energy statistics`, a link to `https://ec.europa.eu/eurostat/x` | evaluator |
| AC-61 | AC-59 | click **Reject note** with reason `Too thin` | each source shows a remove action; the **Add source** form and **Approve sources** are visible; the dossier page's step 3 reads `Waiting`, `note rejected: Too thin` | evaluator |
| AC-62 | AC-59 | click **Approve note** | the dossier page's step 3 reads `Done`, `note r1 approved by ana` | evaluator |
| AC-63 | AC-62, then **Propose sources** again | open the research screen | round 1 is listed collapsed; expanding it shows its approved note | evaluator |
| AC-67 | AC-20; fetch stand-in returns `""` for the Eurostat URL | `POST .../note`, run completes | `unread_sources` holds `{source_id: <Eurostat id>, reason: "no text extracted"}` and `{source_id: <paper id>, reason: "fetch failed"}` | holdout |
| AC-68 | AC-6; Eurostat source deleted, plan approved | `POST .../note`, run completes | `risks` `[]`; the transmission item has exactly one citation, IEA's; `dropped_items` 2 | holdout |
| AC-69 | `D`; search stand-in returns 14 results, all classified `intergovernmental` | `POST .../propose`, run completes | round 1 holds exactly 12 sources, the first 12 URLs in search order | holdout |
| AC-70 | AC-20; note stand-in's `risks` item has a 150-character title | `POST .../note`, run completes | that item's `title` is the first 120 characters of the stand-in's title; `dropped_items` 1 | holdout |
| AC-71 | AC-48 | `GET /api/dossiers` | `D`'s `current_step` is 3 | holdout |

Must not change:
- AC-64: `POST /api/taxonomies/discover-sources` and `GET /api/taxonomies/sources/inspect` return the same status
  codes and body keys as before for the same input. Checked by: holdout.
- AC-65: `POST /api/taxonomies` with authority-source URLs returns the same status codes and body keys as before.
  Checked by: holdout.
- AC-66: dossier steps 1, 2 and 4 return the same states and details as the dossier spec's AC-5 to AC-14,
  AC-19 and AC-20 require, and step 5 stays `not_built`. Checked by: holdout.
