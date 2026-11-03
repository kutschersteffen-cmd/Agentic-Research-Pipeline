# Authority taxonomy agent

Spec slug: `authority-taxonomy-agent`. Status: approved by the owner, 2026-11-03.

## Why

`--method authority_source` reads the first ~20,000 characters of a source (title page, contents, foreword of a
long report), asks for 4–10 activities and keeps one quote per activity. Merging several sources drops the quotes.
It gives no theme description, no technologies or definitions, no sector codes, no value-chain roles, and the user
can neither steer which sources are used nor review the draft before it is saved. The theme run and the extraction
schema need all of that, from sources a person has checked.

## Goals

1. A **taxonomy document** that is the single input for the extraction schema and the theme run: theme
   description, technologies, definitions, activities with in/out boundaries, keywords, criteria, value-chain role
   and sector codes, plus a separate thresholds section. Every item cites a verbatim quote and its source.
2. **Checklist-driven extraction.** The agent checks every selected source against a fixed checklist and records
   for each item `found` (with quote) or `not_in_source`.
3. **User definition prevails.** The user's scope and guidance decide what is in or out; source content outside
   that scope becomes quoted out-of-scope text, never an activity.
4. **Three user checkpoints** in one run that pauses and resumes: at the start, after discovery, after the draft.
5. **An authority-source library** for 10 themes, proposed by the agent and approved by the owner, searched before
   the web.
6. **Value chain on request:** upstream and enabling activities, taken from the sources (bills of materials,
   engineering papers), with sector codes widened through the Value Chain Explorer (EXIOBASE).

## Non-goals

- A frontend screen. This spec delivers the API and CLI; the UI is a separate spec.
- Changing the other derivation methods, `compare`/`merge`, ratification or the theme run.
- Revenue or other thresholds inside activity definitions (owner, 2026-11-03): they are kept in their own section
  for universe building and signals, and nothing in this spec reads them.
- Downloading paywalled documents.

## Anti-goals

- An activity, boundary, definition or threshold without a verbatim quote that passes the grounding check.
- The agent adding a source to the library, or saving a taxonomy, without a user step.
- Reading only the start of a long document.

## Design

### Checklist

A constant `AUTHORITY_CHECKLIST` in `arp/research/authority_taxonomy/checklist.py`, one entry per item, each with a
key and the question put to the source:

| key | asks the source for |
|---|---|
| `theme_description` | a qualitative description of what the theme covers |
| `activities` | the concrete business activities that make up the theme |
| `boundaries` | explicit include / exclude rules |
| `technologies` | the technologies the theme rests on |
| `definitions` | defined terms |
| `sector_codes` | GICS, ISIC or NACE codes the source names |
| `value_chain` | upstream and enabling activities: components, materials, bills of materials, equipment |
| `thresholds` | eligibility thresholds (revenue share, capex share, pure-play rules) |

`value_chain` is skipped when the run was started without `value_chain`.

### Run and checkpoints

A run is a stored record (`RunStore`, run type `authority_taxonomy`) moving through these stages:

1. **Start** (`POST /authority-taxonomy/runs`, `arp taxonomy author start`): theme name, scope text (the user
   definition), optional source guidance (names or URLs, for example "EU Taxonomy only"), `value_chain` true/false.
   The run executes discovery and stops at `awaiting_sources`.
2. **Discovery**: library entries for the theme first, then web search (the existing authority queries plus
   engineering-paper and bill-of-materials queries). With source guidance, only matching candidates. Each candidate
   gets a fetch attempt and is returned with title, URL, source type, a ≤ 80-word summary (from its text, or from
   the search snippet when it can't be fetched), why it was proposed, `fetchable` true/false, and the checklist keys
   it likely covers.
3. **Source choice** (`POST /runs/{id}/sources`, `arp taxonomy author select`): the user picks candidates and may
   add a URL or a local file for a source the agent couldn't fetch. The run extracts and stops at
   `awaiting_review`.
4. **Extraction per source**: the whole fetched text is chunked. For each checklist item the chunks are ranked with
   `select_relevant_chunks` against that item's keywords plus the theme name, and the top chunks go to one LLM call
   per item. Every returned item carries a verbatim quote; quotes failing `ground_citations` are dropped. The user
   scope is in every prompt. The fetch cap is raised from 60,000 to 400,000 characters for this path only.
5. **Consolidation**: items from all sources are merged into one document. A merged item keeps the quotes and
   source URLs of every item it came from. Which items are "the same activity" is decided by the activity matcher
   (below). Sector codes come from the sources plus `map-standards`; with
   `value_chain` on, the core ISIC codes are widened with the top-5 upstream industries per code from the Value
   Chain Explorer's `links`, marked `exiobase` as their origin.
6. **Draft review** (`GET /runs/{id}/draft`, `PUT /runs/{id}/draft`, `arp taxonomy author review`): the user reads
   and edits the draft, then accepts (`POST /runs/{id}/accept`, `arp taxonomy author accept`). Accept saves it as a
   new taxonomy v1, `derivation_method=authority_source`, status `draft` (ratification unchanged), and moves the run
   to `stage=accepted`. Nothing is saved to the Taxonomy Library before accept.

A run in `awaiting_*` waits indefinitely; `DELETE /runs/{id}` cancels it.

### Data model

New optional fields, all defaulting to empty so existing taxonomies load unchanged:

- `ThemeDefinition`: `scope` (user definition), `technologies`, `definitions` (term, text, citations),
  `thresholds` (text, citations), `checklist_report` (per source URL: key → `found` | `not_in_source`).
- `ActivityDefinition`: `value_chain_role` (`core` | `upstream` | `enabling`, default `core`), `criteria`
  (list of text with citations), `citations` (list), `out_of_scope_citations` (list), `sector_codes` (system, code, origin: `source` |
  `map_standards` | `exiobase`).

### Source library

One JSON file per theme in `backend/arp/data/authority_library/<theme_key>.json`, one entry per source: URL,
title, source type (`regulatory_taxonomy`, `agency_report`, `index_methodology`, `standards_body`,
`statistical_classification`, `engineering_paper`), summary, checklist keys covered, `fetchable`, `checked_on`,
`status` (`proposed` | `approved`). Discovery uses only `approved` entries.

- `arp authority-library propose --theme <key>`: the agent runs discovery and writes `proposed` entries.
- `arp authority-library approve --theme <key> --url <url>`: sets `status=approved`, `checked_on` = today.
- `arp authority-library reject --theme <key> --url <url>`: removes the entry from the file.

The 10 themes (owner-approved, 2026-11-03): `hydrogen`, `renewable_power`, `energy_storage`, `electric_vehicles`,
`grid_electrification`, `ai_datacentres`, `water`, `ccus`, `critical_minerals_circular`, `building_efficiency`.

### Activity matcher (amended 2026-11-03, owner: "key words plus some model review")

One function, `match_activities(left, right, *, scope, llm) -> list[Match]`, in
`arp/research/authority_taxonomy/matching.py`, used by consolidation (activities of source A against source B) and
by the golden command (expected activities against the draft). `Match` = left index, right index, `method`
(`exact` | `model`), `reason`.

1. **Exact:** equal merge key (name lower-cased, whitespace and punctuation removed) → match, `method=exact`, no
   model call.
2. **Keyword candidates:** each activity's keywords are the content words of its name plus its `seed_keywords`,
   lower-cased, stop words and generic words (`manufacture`, `manufacturing`, `production`, `equipment`, `of`,
   `and`, `other`, …) removed, each cut to its first 6 letters. A pair is a candidate when it shares ≥ 1 keyword.
   Pairs with no shared keyword are never matched and never sent to the model.
3. **Model review:** all candidate pairs go to one structured LLM call (with the scope), which returns per pair
   `same_activity: bool` and a one-sentence `reason`. Only `same_activity=true` pairs match, `method=model`.
4. Each activity matches at most one other; when several are judged the same, the pair seen first wins.

Matching never invents an activity; an unmatched activity stays separate (consolidation) or counts as missed
(golden).

### Golden command

`arp golden-set authority-taxonomy --case <id>` runs a full run on the case's stored source and scope, accepts the
draft in memory (nothing saved), prints every produced activity name, then one line per expected activity
(`FOUND <expected> = <produced> (<method>: <reason>)` or `MISSED <expected>`), then `grounded_rate=<x> recall=<y>`.
Recall uses the activity matcher. It exits 0 when every activity is grounded and recall ≥ the case's `min_recall`
(rounded to 2 decimals); else 1.
Cases live in `backend/tests/golden/authority_taxonomy/`.

### Pausing (builder's choice of mechanism)

The repository has no LangGraph checkpointer. Stages are stored in the run record and each API call runs the next
stage; a LangGraph checkpointer is not required. Recorded as my call.

## Approaches considered

1. Extend `authority_source` across separate CLI commands: cheaper (~3–4 days), no single run.
2. **A pausing agent run (chosen by the owner)**: one run with three checkpoints, ~6–8 days; the API makes a later
   UI straightforward.
3. Fold into the Taxonomy Researcher agent: ruled out; that agent maintains ratified taxonomies and only proposes.

## Acceptance

All rows run with a fake LLM, a fake search client (fixed results), a frozen clock (`2026-11-10`) and fixture
documents in `backend/tests/fixtures/authority_taxonomy/`, unless stated otherwise. `HOLDOUT_TOKEN` is not set yet,
so rows are `unit` and listed as owed to `holdout` in the PR.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | No run | `POST /authority-taxonomy/runs` with name, scope, `value_chain=false` | 201; body has a non-empty `id` | unit |
| AC-1b | The run from AC-1; fake search returns 3 results | `GET /authority-taxonomy/runs/{id}` | `stage` is `awaiting_sources`; `candidates` has exactly 3 entries | unit |
| AC-2 | Fake search returns URL U with snippet S; fetching U fails | start a run | The candidate for U has `fetchable=false`, `summary == S` and a non-empty `reason` | unit |
| AC-3 | `hydrogen.json` with an `approved` entry A and a `proposed` entry P; fake search returns neither | start a run for theme `hydrogen` | `candidates[0].url == A` | unit |
| AC-3b | As AC-3 | start a run | P is not among the candidate URLs | unit |
| AC-4 | Guidance "EU Taxonomy only"; fake search returns one `ec.europa.eu` URL and one `iea.org` URL | start a run | Every candidate URL host ends in `europa.eu`; the `iea.org` URL is absent | unit |
| AC-5 | Fixture `long_report.txt` where the only electrolyser-manufacturing passage Q starts after character 100,000 | select it and extract | The draft has an activity with a citation whose quote equals Q | unit |
| AC-6 | The fake LLM returns an activity whose quote is not in the source | extract | That activity name is absent from the draft | unit |
| AC-6b | The fake LLM returns a definition and a threshold whose quotes are not in the source | extract | `theme.definitions` and `theme.thresholds` are empty | unit |
| AC-7 | A fixture source with no thresholds | extract | `checklist_report[<url>].thresholds == "not_in_source"` | unit |
| AC-7b | A fixture source defining term T and naming technology G | extract | `theme.definitions` has an entry with `term == T` and ≥ 1 citation | unit |
| AC-7c | As AC-7b | extract | `theme.technologies` has an entry with name G | unit |
| AC-7d | A fixture source containing threshold rule R | extract | `checklist_report[<url>].thresholds == "found"` and `theme.thresholds` has an entry quoting R | unit |
| AC-8 | Two sources A and B each yield "Electrolyser stack manufacturing" (one written "electrolyser-stack manufacturing") | consolidate | Exactly one activity has that merge key; its `citations` has 2 entries with URLs A and B; no matcher LLM call was made | unit |
| AC-8b | Source A yields "Fuel cell manufacturing", source B "Manufacture of fuel cells and other hydrogen-to-power equipment"; the fake LLM judges them the same | consolidate | Exactly one fuel-cell activity, with citations from A and B | unit |
| AC-8c | As AC-8b, but the fake LLM judges them different | consolidate | Two fuel-cell activities | unit |
| AC-8d | Source A yields "Manufacture of electrolysers", source B "Hydrogen storage tanks" (no shared keyword) | consolidate | Two activities; the matcher made no LLM call | unit |
| AC-9 | Scope "manufacture of electrolysers only"; a source passage O describes operating electrolysers to produce hydrogen | extract | No activity name contains "operat" | unit |
| AC-9b | As AC-9 | extract | Some activity's `out_of_scope_citations` contains a quote equal to O | unit |
| AC-10 | `value_chain=true`; the bundled sample IO model; a source with a bill of materials | consolidate | ≥ 1 activity has `value_chain_role` `upstream` or `enabling` | unit |
| AC-10b | As AC-10, an activity with core ISIC code C | consolidate | That activity has exactly 5 `sector_codes` entries with `origin=exiobase` | unit |
| AC-10c | Fixture `power_gen.txt` whose activity `map-standards` maps to ISIC D35 | consolidate | That activity has a `sector_codes` entry `{system: ISIC, code: D35, origin: map_standards}` | unit |
| AC-11 | `value_chain=false` | extract | Every activity has `value_chain_role == "core"` | unit |
| AC-11b | As AC-11 | extract | No `checklist_report` entry has a `value_chain` key | unit |
| AC-12 | A source with the rule R "at least 50 % of revenue from hydrogen" | extract | `theme.thresholds` has an entry with a citation quote equal to R | unit |
| AC-12b | As AC-12 | extract | No activity's in-scope text or criteria contain R | unit |
| AC-13 | A run at `awaiting_review` | `PUT /runs/{id}/draft` with one activity renamed to N | 200; `GET /runs/{id}/draft` shows N | unit |
| AC-13b | As AC-13, after the PUT | `POST /runs/{id}/accept` | 201; `arp taxonomy show <new id>` prints N, `v1`, `authority_source`, `draft` | unit |
| AC-13e | As AC-13b, after accept | `GET /runs/{id}` | `stage` is `accepted` | unit |
| AC-13c | A run at `awaiting_review` (not accepted) | `arp taxonomy list` | The row count equals the count before the run started | unit |
| AC-13d | A run with a local file F added at source choice | extract | The draft has ≥ 1 citation whose source is F | unit |
| AC-14 | A run at `awaiting_sources` | `POST /runs/{id}/accept` | 409; `detail` contains `awaiting_sources` | unit |
| AC-15 | A run at `awaiting_sources`, and one at `awaiting_review` | `DELETE /runs/{id}` on each | 204; `GET` then shows `stage=cancelled` | unit |
| AC-16 | `water.json` with 1 existing entry; fake search returns 4 new URLs | `arp authority-library propose --theme water` | The file has 5 entries; the 4 new ones are `proposed`; the existing one is unchanged | unit |
| AC-17 | A proposed entry U | `arp authority-library approve --theme water --url U` | U has `status=approved`, `checked_on=2026-11-10` | unit |
| AC-17b | A proposed entry U | `arp authority-library reject --theme water --url U` | U is no longer in `water.json` | unit |
| AC-18 | A saved taxonomy JSON without the new fields | `arp taxonomy show` | Exit 0; output identical to `main` | unit |
| AC-19 | `arp taxonomy create --method authority_source` with the fake LLM | run | Same output and stored taxonomy as on `main` | unit |
| AC-19b | Two saved taxonomies | `arp taxonomy compare` with the fake LLM | Same output as on `main` | unit |
| AC-19c | Two saved taxonomies | `arp taxonomy merge` with the fake LLM | Same output and stored taxonomy as on `main` | unit |
| AC-19d | A taxonomy saved by accept (status `draft`) | `arp taxonomy ratify <id> --by owner` | Status becomes `ratified` with `ratified_by=owner`, as on `main` | unit |
| AC-20 | The CLI flow | `author start`, `select`, `review`, `accept` | Each exits 0 and prints, in order, `stage: awaiting_sources`, `stage: awaiting_review`, `stage: awaiting_review`, `stage: accepted` | unit |
| AC-21 | The backend suite on `main` | CI on this branch | Every test passing on `main` passes here | unit |
| AC-22 | The real model; golden case `hydrogen_eu_taxonomy` (EU Taxonomy Delegated Act Annex I, activity 3.2) with 3 expected activities; scope "manufacture of electrolysers" | `arp golden-set authority-taxonomy --case hydrogen_eu_taxonomy` | Exit 0: grounded rate = 1.0 and recall ≥ 0.67, recall computed with the activity matcher | golden |
| AC-22b | Fake LLM; a draft with "Manufacture of fuel cells and other hydrogen-to-power/heat equipment" and expected "Manufacture of fuel cells"; the fake judge says same | golden command | Output contains `FOUND Manufacture of fuel cells = Manufacture of fuel cells and other hydrogen-to-power/heat equipment (model:` | unit |
| AC-22c | Fake LLM; an expected activity with no produced match | golden command | Output contains `MISSED <expected name>` | unit |

Must not change: the existing derivation methods, `compare`/`merge`, ratification and taxonomies already saved
(AC-18, AC-19, AC-19b, AC-19c, AC-19d, AC-21).
