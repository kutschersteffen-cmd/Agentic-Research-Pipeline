# Transition barriers: rule book, cited facts, derived ratings

Date: 2026-10-17
Status: draft for approval

## Intent

The transition barrier matrix answers one question per sector and region: how feasible is
decarbonisation here at all? It rates 35 criteria (9 sectors × Technology / Regulation / Demand &
Economics) for the EU, the US and China, giving 105 cells. `H` means more feasible (the enabling
condition is in place), `L` less. See `docs/TRANSITION_BARRIER_ASSESSMENT.md`.

Today every rating was set by hand in August 2026. A cell carries one evidence sentence and a free-text
source. The H/M/L rubrics use words nobody has defined. Example: `STL-R1` (effective carbon price on
steel) for China is rated `L`, "No material carbon price on steel production". Its own evidence says
the national ETS has covered steel since 2025 at about USD 9–14/t. Under the rubric as written, that
reads as `M` ("Carbon price applies but free allocation still material"). The analyst meant "too low
to matter", but the rubric never says what "material" means. A committee member cannot tell which
reading is right, or check the figure.

The owner's requirements:

- **Exact sources and rationale for every rating statement.** Anyone in a committee can see why a
  criterion matters, where every figure comes from (document, page, quote), and how the rating
  follows from those figures.
- **Rules first.** The rules and criteria that must be met for H, M and L are defined and approved
  before anything is extracted.
- **Then extraction (RAG).** The facts the rules need are extracted from sources and compared against
  the criteria.
- **Then a rules engine** derives the final rating.
- **Search for new material** as well: new laws, policy reversals, newer editions, new data. Re-reading
  the registered sources is not enough. Two US cells changed in August 2026 because of 2025 policy
  reversals (Section 30D sourcing rules, the EPA methane fee) that re-fetching the same pages would have
  missed.

This is the first project of a wider Transition Intelligence programme. The next project uses these
ratings to assess companies' transition plans one at a time: does each action in a company's plan
have the regulation, technology and demand it needs in that company's regions? That project needs
ratings that can be explained fact by fact, and criteria tagged with the decarbonisation actions they
limit. Both are built here.

## Goals

1. **A rule book** covers all 35 criteria. Each criterion has:
   - a rationale: which decarbonisation actions it limits, and why;
   - the facts it needs, each with a type and an exact definition;
   - H and M conditions written as tests on those facts. L applies when neither holds.

   Every threshold carries its own source and rationale. The rule book is versioned, and the owner
   approves each version.
2. **One source of truth for reading the rules.** The criterion page, the `/criteria` API and a
   methodology document are all generated from the rule book, so they cannot drift from it.
3. **Facts are extracted from sources** with an exact quote, page or locator, URL and as-of date. Code
   checks every quote against the document text. A fact whose quote is not found does not count.
4. **A deterministic engine** derives each cell's rating from the facts and shows every condition as
   passed, failed or unknown, with the figures it used. No model decides a rating.
5. **A missing fact never becomes a guess.** If a missing fact could change the outcome, the cell is
   "not rated", naming what is missing.
6. **Confidence follows a written rule**, computed from the facts.
7. **A named person ratifies every derived result** before it becomes the cell's rating. Every rating
   is kept in an append-only history.
8. **New material is found** monthly and on demand. A new source is used only after a person approves
   it. News can trigger a re-check but never grounds a fact.
9. **Sources code cannot read** (subscription trackers, dashboards, company disclosures) are covered by
   analyst-entered facts, which go through the same engine.

## Non-goals

- Assessing companies' transition plans (the next project).
- Combining a sector-region's criteria into one score, or a feasibility verdict per decarbonisation
  action (next project).
- New sectors, regions or criteria. The 35 criterion codes and what they measure stay; the rule book
  sharpens their wording into numbers. Adding coverage later is data work.
- Editing the rule book in the app. It is a file in the repo, changed by pull request with a version
  bump that the owner approves.
- Automated extraction from company disclosures. They stay manual, as today.
- Scraping dashboards or logging into subscription trackers.
- Changing the transition plan assessment, Decision Studio or StewardIQ. They keep reading the current
  rating through the existing dataset functions.

## Anti-goals (a failure even if it works)

- A rating changes without a named person approving it.
- A fact counts although its quote is not in the source document, or its number is not in its quote.
- A model output, rather than the rule book, decides a rating.
- A missing fact is silently treated as "no", and a cell drops to `L`.
- Two sources disagree on the outcome and one silently wins.
- The sentence shown for a rule doesn't match what the engine evaluated.
- A news article ends up as the evidence for a fact.
- The bundled data files under `backend/arp/transition_barrier/data/` change at run time.

## Current state (what this builds on)

Paths are under `backend/arp/` unless they start with `frontend/` or `docs/`.

- **Data.** `transition_barrier/data/criteria_schema.json` (35 criteria, each with a one-line H/M/L
  `rating_rubric` and its `primary_sources`), `assessment_scores.json` (105 cells: rating,
  confidence, evidence sentence, free-text source, `last_verified` 2026-08-14) and
  `source_registry.json` (86 sources, a view derived from the schema). `transition_barrier/dataset.py`
  loads them under `lru_cache`. Nothing writes to them, and
  `tests/test_transition_barrier_refresh_pipeline.py` asserts the scores file is byte-identical after
  a run.
- **Refresh slice.** `transition_barrier/refresh/` (router, `eurlex.py`, `eli.py`, `reconciler.py`,
  `pipeline.py`) checks the 15 EUR-Lex sources for changed acts, behind
  `ARP_TRANSITION_BARRIER_REFRESH_ENABLED`. Findings needing review are queued with
  `orchestration/review_queue.py::queue_for_review` under run type `transition_barrier_refresh`. They
  are invisible in the unified review screen: `review/items.py::REVIEWABLE_RUN_TYPES` and
  `frontend/src/components/RunReviewList.tsx` don't include that run type. Nothing applies an approved
  finding to the matrix.
- **Fetching and parsing.** Outbound requests use `net_safety.ssrf_guard_request_hook`.
  `research/taxonomy_sources/fetch.py::fetch_source_original` fetches any URL and caches the bytes.
  `ingestion/local_files.py::parse_file_to_text_with_pages` (Docling) returns text with page breaks,
  cached by `DocumentContentStore.get_or_parse`. Non-company documents are already wrapped as
  `SourceDocument`s in `replication/spec_graph.py` and
  `research/taxonomy_sources/authority_extraction.py`. The Postgres `documents` table, however, has a
  foreign key to `companies`, and `DocumentRegistry.register_document` creates a stub company for any
  `company_id` string it is given.
- **Retrieval and extraction.** Passages are `DocumentChunk`s (`ingestion/parsing.py::chunk_document`),
  ranked by `retrieval/select_evidence.py::select_relevant_chunks`. A `FieldDefinition`
  (`schemas/datapoints.py`) types a value (number, currency_amount, percentage, string, boolean, enum,
  date, with `unit`, `allowed_values` and `extraction_instructions`).
  `extraction/field_graph.py::extract_one_field` runs extract → verify → ground for one field. Its
  `company_name` is only a string in the prompt.
- **Quote checks.** `grounding.py::ground_citations` matches a quote exactly, then normalised, then
  fuzzily (score ≥ `grounding_fuzzy_threshold`, 0.92, and never with a digit outside the matched
  block). It sets `grounded` and `page`. The precision-extraction design
  (`docs/superpowers/specs/2026-10-12-precision-extraction-design.md`) adds the check that a number
  appears in its quote.
- **Web search.** `discovery/site_finder.py::WebSearchClient` with one web provider,
  `DuckDuckGoSearchClient`: an HTML scrape that returns nothing when challenged. Tests use
  `tests/conftest.py::FakeSearchClient`.
- **Model.** `llm/base.py::LLMClient` (`complete_structured`), built by `llm/factory.py`. Tests use
  `FakeLLMClient`.
- **Rules engines.** `zen-engine` 2.0.2 (GoRules) drives voting policy, tiers, monitoring and
  escalation (`stewardship/policy_graph.py` and others) and Decision Studio's levels mode
  (`decision/levels.py`). The schema rules design approved today
  (`docs/superpowers/specs/2026-10-17-schema-rules-design.md`) evaluates its typed rules in plain
  Python (`checks/rules.py`).
- **Roles.** `api/auth.py` has viewer, analyst and approver (`require_role`).
- **UI.** `frontend/src/pages/TransitionBarrierAssessment.tsx` shows the matrix, a criterion's rubric
  and its cells (rating, confidence, evidence, last verified), staleness, and starts a refresh.
- **Consumers.** `decision/sources.py::from_transition_barrier` feeds the matrix into Decision Studio.
  `scripts/build_transition_barrier_report.js` builds the Word report from the JSON.

## Design

### The flow

```
rule book ──► sources & search ──► fact extraction ──► derivation ──► review ──► current rating
 (stage 1)                          (stage 2, RAG)     (stage 3,       (named      (history kept)
                                    + analyst facts     rules engine)   person)
```

One unit of work is a **cell**: one criterion × one region. A derivation run covers one or more
cells.

### 1. The rule book

A new file, `backend/arp/transition_barrier/data/rule_book.json`, is the only authority for how a
cell is rated. Sketch (field names beyond these are the builder's call):

```json
{
  "version": 1,
  "approved_by": "<owner>",
  "approved_at": "2026-..",
  "actions": { "Steel": [{"id": "steel.h2_dri", "label": "Hydrogen-based direct reduced iron"}, "..."] },
  "conversions": [{"from": "CNY", "to": "USD", "rate": 0.14, "year": 2025, "source": {"...": "..."}}],
  "criteria": {
    "STL-R1": {
      "rationale": "Without a carbon price that reaches the gap between ... every low-carbon route ...",
      "actions": ["steel.h2_dri", "steel.scrap_eaf", "steel.ccus"],
      "facts": [
        {"id": "price", "label": "Effective carbon price", "type": "number", "unit": "USD/tCO2",
         "definition": "Price per tonne CO2 paid by steel producers in the latest full year, net of free allocation ...",
         "max_age_days": 365}
      ],
      "params": [
        {"id": "p_high", "label": "High price level", "value": 50, "unit": "USD/tCO2",
         "by_region": {}, "rationale": "...", "source": {"title": "...", "url": "...", "locator": "..."}}
      ],
      "levels": {
        "H": {"all": [{"fact": "price", "op": ">=", "param": "p_high"}, {"fact": "levy", "op": "=", "value": true}]},
        "M": {"all": [{"fact": "applies", "op": "=", "value": true}, {"fact": "price", "op": ">=", "param": "p_material"}]}
      }
    }
  }
}
```

**Facts.** Each fact is `number` (with a `unit`), `boolean`, `enum` (with `allowed_values`) or `date`.
The `definition` is what the extractor is told and what a reviewer checks against: period, scope,
"net of what". `max_age_days` feeds confidence. Facts are always per region.

**Parameters.** Thresholds live in `params`, never inline in a condition, so each one carries a
`source` and a `rationale`. `by_region` overrides the value for one region (example: a hydrogen
breakeven cost that differs by region), with its own source.

**Conditions.** A condition is `{fact, op, value | param}`, with `op` one of `>=`, `<=`, `>`, `<`, `=`,
`in`. Conditions group with `all` / `any`, nested at most two levels. A comparison is valid only between
a fact and a value of the same type and unit.

**Levels.** `H` is tested first, then `M`. `L` applies when both are false. There is no explicit L
condition, so the three levels cover every case by construction.

**Conversions.** Facts are compared in the rule book's unit. A value extracted in another unit (CNY,
EUR, short tons) is converted by code using the `conversions` table. Every rate cites its source and
year. Comparisons use the unrounded converted value; screens and detail sentences show it rounded to
two decimals, followed by the extracted value in brackets. A unit not in the table makes the fact not
count ("Unit not convertible: KRW/tCO2").

**Actions.** Per sector, a list of decarbonisation actions with stable ids. Each criterion names the
actions it limits. The next project matches plan actions against these ids.

**Rendering.** Sentences are rendered from the conditions, never stored, so they cannot disagree with
what the engine evaluates:

- a condition renders as `<fact label> <op> <value> <unit>`, for example
  `Effective carbon price >= 50 USD/tCO2`;
- a boolean renders as `<fact label> is Yes` or `is No`;
- `all` joins with ` and `, `any` with ` or `, and nested groups are bracketed;
- `L` renders as `Otherwise (neither H nor M holds)`.

The `/criteria` API's `rating_rubric` (`{H, M, L}`) is filled from these renderings. The free-text
`rating_rubric` in `criteria_schema.json` is removed, so no second wording exists. The Word report
script reads the rendered text.

**Methodology document.** `arp transition-barrier rules render` writes `docs/transition_barrier/RULE_BOOK.md`:
per sector and criterion, the rationale, actions, facts with definitions, the H/M/L sentences, and every
threshold with its value, source and rationale. The committed file must equal the render output (a
test checks this), the same way the Word report is generated from the JSON.

**Validation.** `arp transition-barrier rules validate` and the loader reject a rule book where:

1. a criterion in `criteria_schema.json` has no entry, or an entry has no criterion;
2. a condition names a fact or parameter that doesn't exist in its criterion;
3. a comparison's types or units don't match;
4. a parameter has no `source` or no `rationale`;
5. a criterion has no `rationale`, no facts or no `H` and `M` levels;
6. a criterion's `actions` name an id not in its sector's action list;
7. a registered source has no `tier`;
8. the content changed but `version` did not. How the content is fingerprinted (a hash next to the
   version is enough) is the builder's call.

The app refuses to start with an invalid rule book, naming the first error. CI runs the validator.

**Content of version 1.** The builder drafts all 35 entries from today's rubrics, evidence and
sources. Each vague word ("material", "meaningful", "significant") becomes a number, and each number
cites a source. Where no defensible number can be found, the draft says so in the entry, as an open
question for the owner, rather than inventing one. The draft's pull request includes an **impact
table**: for each of the 105 cells, the current rating, and the rating the draft rules would give
using the figures in today's evidence text, read by hand. Every difference is listed with its reason.
`STL-R1` China is expected to be one of them. The owner approves version 1 in that pull request.

### 2. Sources and search for new material

**Registry.** The existing source registry (`criteria_schema.json` `primary_sources`) stays the list of
sources a criterion may use. Each source gains a `tier`:

| Tier | Examples | May ground a fact | Fact confidence at most |
|---|---|---|---|
| `primary` | law text, regulators, ministries, official statistics, IEA, IRENA, IPCC, World Bank | yes | high |
| `secondary` | research institutes, industry trackers, think tanks, industry associations | yes | medium |
| `news` | news and commentary | no | n/a |

The builder assigns the tier for the 86 existing sources in the version 1 pull request, for the owner
to check. Sources approved later (see below) are stored with the ratified results, not written into
the bundled files, and `GET /sources` lists bundled and approved sources together.

**Documents.** Fetching a source stores the document (PDF or HTML) and its as-of date: the
publication date, or the data year where the document states one. Re-fetching an unchanged document
is a no-op. Documents are parsed with page breaks (`parse_file_to_text_with_pages`), so every quote
gets a page. A barrier source document must not create a company record. It stays out of the
`documents` table's company path, or uses another way the builder chooses. All fetches go through the
SSRF guard, and all fetching and searching stays behind `ARP_TRANSITION_BARRIER_REFRESH_ENABLED`.

**Newer editions.** For each registered source with a periodic cadence, a check looks for a newer
edition (next year's report, an amended act). Legal sources reuse the existing EUR-Lex/ELI version
check. A newer edition becomes a `new_source` review item that proposes replacing the old entry.

**Policy-change search.** Monthly, and on demand for a cell, a search runs per cell. The monthly
run is a scheduled job, following the interval-job pattern of
`portfolio/monitoring/scheduler.py`, and only runs while the refresh flag is on. Queries are built
from the criterion, the region and the fact definitions. Each result is classified by tier:

- a `primary` or `secondary` result not already registered becomes a `new_source` review item for that
  criterion and region;
- a `news` result that suggests a change puts a `possible_change` flag on the cell, with the article's
  title, URL and date, and queues a derivation run for the cell from its registered sources.

Results are matched by normalised URL. A URL a person rejected is never proposed again for the same
criterion. The search provider sits behind the existing `WebSearchClient` interface
(`arp/discovery/site_finder.py`); which provider to use is the builder's call, and the owner approves
any paid one.

### 3. Fact extraction (RAG)

**Unit.** One fact for one cell. Inputs: the fact's definition, the region, and the documents of the
criterion's registered sources (approved new sources included).

**Steps.** A rule book fact maps onto a `FieldDefinition`: its type, unit and allowed values carry
over, and its definition becomes the extraction instructions. It then runs through the existing
`extract_one_field` path, with the cell (for example "Steel, China, STL-R1") in place of the company
name.

1. Retrieve passages relevant to the fact from those documents.
2. The model returns either `not_found`, or a value in the source's own unit with the exact quote, the
   page or locator, and the as-of date.
3. Code checks the result. The quote check is `ground_citations`, run against the passages the model
   was shown. A fact counts only if all of these pass:
   - the quote is found in the document text;
   - for numbers, the number appears in the quote;
   - the unit is the fact's unit or convertible through the `conversions` table;
   - the source's tier may ground a fact.

   A fact that fails keeps its failure reason ("Quote not found in source", "Number not in quote",
   "Unit not convertible: …", "News cannot ground a fact"). Both reviewer and cell detail show it.

**Several values for one fact.** When more than one counted value exists for a fact (two sources, two
editions), the engine evaluates each value. If they all give the same rating, the rating stands and
every value is shown. If they give different ratings, the cell is a **conflict**: no rating is proposed,
and the review item shows each value with its source. This is operating rule 4 of the existing
module.

**Fact confidence.**

- `high`: counted, from a `primary` source, as-of date within `max_age_days`;
- `medium`: counted, but from a `secondary` source or older than `max_age_days`;
- `low`: entered by an analyst without a document (below).

**Analyst-entered facts.** For sources code cannot read, an analyst enters the value, unit, quote, page
and source. With an uploaded document, the quote is checked exactly as above. Without one, the fact is
marked "not machine-checked" and its confidence is `low`. The analyst's name is recorded on the fact.

### 4. Derivation (the rules engine)

The engine is code only. Input: the rule book version, and the counted facts for a cell. Output: a
result. No model is involved.

**Three-valued logic.** A condition is `pass`, `fail` or `unknown`. It is `unknown` when its fact has
no counted value. `all` fails if any part fails, passes if every part passes, and is otherwise
`unknown`. `any` passes if any part passes, fails if every part fails, and is otherwise `unknown`. Then:

| H | M | Rating |
|---|---|---|
| pass | any | `H` |
| unknown | any | `not_rated` |
| fail | pass | `M` |
| fail | unknown | `not_rated` |
| fail | fail | `L` |

A `not_rated` result names the facts whose absence made it unknown. So a missing fact only blocks a
rating when it could change it: with a carbon price of 30 and a high level of 50, a missing border-levy
fact cannot make the cell `H`, and the result is `M`.

**Result.** Each result records:

- the rating, or `not_rated` or `conflict`;
- each level's outcome, and each condition's outcome with the value used (in the rule book's unit and
  as extracted) and its citation;
- the missing facts and the confidence;
- the rule book version and the run id.

**Confidence of a result** is the lowest confidence among the facts the result read.

**Detail sentence.** Each level renders as its sentence followed by one clause per condition. AC-7 has
the exact form.

**Engine.** A plain Python evaluator over the rule book's structured conditions, in
`transition_barrier/`. That is my call, and it changes what I said in chat ("reuses the GoRules
engine"). GoRules expressions fail on a missing value, so the three-valued logic and the
per-condition evidence would have to be rebuilt around it. In-app rule editing, the one thing GoRules
would add, is a non-goal. The newly approved schema rules design made the same choice for the same
kind of typed condition.

### 5. Review and ratification

Every derived result becomes a review item. Kinds:

- **changed**: the proposed rating differs from the current one;
- **unchanged**: same rating, new evidence;
- **not rated** and **conflict**: resolved by adding an analyst fact, or by choosing which value counts
  with a written reason, which re-derives the cell; or dismissed, which keeps the current rating;
- **new source** and **possible change**, from search. Approving or rejecting a possible-change item
  clears its flag; the re-derivation it queued runs either way.

Items are queued with `queue_for_review` under a new run type, `transition_barrier_derivation`.
That run type is added to `REVIEWABLE_RUN_TYPES` and to the frontend's reviewable kinds, so items show
in the existing review screens.

A person with the `approver` role approves or rejects each item; entering an analyst fact needs
`analyst` *(my call)*. Their name and the time are recorded. Unchanged items can be approved in bulk,
and each item in the batch still records the approver. An approved result becomes
the cell's current rating, and `last_verified` becomes the approval date, so staleness counts from
there. A rejected result changes nothing.

**Storage.** Ratified results are stored append-only next to runs and results. The current rating of a
cell is its latest ratified result. A cell never re-derived keeps its bundled rating, labelled
"hand-rated 2026-08-14". The bundled JSON is never written at run time; the existing byte-identity test
stays.

A cell whose latest derivation was `not_rated`, or that has an open `possible_change`, keeps its
current rating and shows a flag: "Not re-derived: missing <fact labels>" or "Possible change: <article
title>".

### 6. Screens

The layout is the builder's call, following `DESIGN.md`. What each screen must show:

- **Criterion page** (existing, Transition Barriers): the rationale, the actions it limits, the facts
  with their definitions, the H/M/L sentences, and each threshold with its value, source and rationale,
  plus the rule book version.
- **Cell detail**: rating, confidence, ratified by and when; each level and condition as pass, fail or
  unknown; for every figure, its quote, document title, page and a link that opens the source; flags;
  the cell's rating history.
- **Review**: barrier items in the existing review screens, with approve, reject and bulk-approve.
- **Analyst fact entry**: a form on the cell detail, with optional document upload.

### 7. Interfaces

New CLI commands under `arp transition-barrier`:

- `rules validate`: exit 0 and print `Rule book v<version>: <n> criteria, OK`, or exit 1 and print one
  line per error.
- `rules render`: write `docs/transition_barrier/RULE_BOOK.md`.
- `derive --code <code> --region <region>`: start a derivation run for one cell and print its run id.
- `search --code <code> --region <region>`: run the policy-change search for one cell.
- `golden --cases <file> --documents-dir <dir> --min-precision <x>`: fact-extraction precision on a
  golden set; exit 0 when precision ≥ x.

New and changed API routes under `/api/transition-barrier`:

- `GET /scores` and `GET /matrix` keep every existing field. Each cell gains `basis` (`hand_rated` or
  `derived`), `ratified_by` (null when hand-rated) and `flags` (a list of strings, empty by default).
- `GET /criteria/{code}`: `rating_rubric` comes from the rule book. The response gains `rationale`,
  `actions`, `facts`, `params` and `rule_book_version`.
- `GET /cells/{code}/{region}`: the current rating, the latest result (levels, conditions, facts with
  citations and failure reasons), flags and the rating history.
- `POST /derive` with `{"cells": [{"code", "region"}]}`: starts a run and returns `{"run_id"}`. When
  `ARP_TRANSITION_BARRIER_REFRESH_ENABLED` is false it answers 409, as `POST /refresh/runs` does today.
- `POST /cells/{code}/{region}/facts`: an analyst fact (multipart, optional document).

Review decisions use the existing `POST /api/review/runs/{run_id}/items/{item_key}/decision`.

### 8. Build order

Each phase is one pull request.

1. **Rule book.** Format, validator, rendering, the `/criteria` change, version 1 content, source tiers,
   impact table, `RULE_BOOK.md`. The owner approves the rules here, before any extraction code merges.
2. **Engine and ratification.** Derivation, storage, review items, cell detail, analyst facts. Usable
   from this phase on with analyst-entered facts.
3. **Extraction.** Document fetching, retrieval, fact extraction and checks, golden-set evaluation.
4. **Search.** Newer editions, policy-change search, the monthly schedule.

The owner described the flow as rules, then extraction, then engine. Building the engine before
extraction is my call: the engine is small and deterministic, and analysts can use it with entered
facts while extraction, the riskiest part, is built.

## Constraints

- The model extracts facts. It never outputs a rating, a condition outcome or a confidence.
- Precision first: "not rated" is acceptable; a wrong figure that counts is not.
- The existing operating rules in `docs/TRANSITION_BARRIER_ASSESSMENT.md` stay in force.
- Tests make no network calls and no model calls; fetch, search and the model are stubbed.
- Request/response model changes follow the API contract steps in `.claude/CLAUDE.md`.
- At most three agent pull requests in flight (`.claude/skills/steward/SKILL.md`), so phases 3 and 4
  wait for earlier ones to merge or run one at a time.

## Left to the builder

- Storage layout and table names, and JSON field names beyond the sketch.
- Retrieval settings (passages, re-ranking), prompts, search query wording.
- The search provider behind `WebSearchClient` (paid ones need the owner's approval).
- How the rule book's content fingerprint is stored.
- Screen layout and wording beyond the strings in the acceptance table.
- A cap on how many value combinations a conflict check evaluates.

## Acceptance

**Fixture rule book RB** (version 7) with one criterion, `STL-R1`:

| Fact id | Label | Type |
|---|---|---|
| `price` | "Effective carbon price" | number, unit `USD/tCO2`, `max_age_days` 365 |
| `applies` | "Carbon price applies to steel" | boolean |
| `levy` | "Border levy in force" | boolean |

- Parameters: `p_high` = 50 USD/tCO2, `p_material` = 10 USD/tCO2, each with a source and a rationale.
- `H`: `all(price >= p_high, levy = true)`. `M`: `all(applies = true, price >= p_material)`.
- Conversions: CNY → USD at 0.14 (2025).

**Fixture documents:** D1 "EU ETS Market Report 2026" (primary), D2 "CBAM Regulation 2023/956"
(primary), D3 "Steel Policy Tracker" (secondary), N1 "Reuters: carbon price falls" (news).

Unless a row says otherwise, the region is "European Union" and the cell's current rating is the
bundled hand rating `H`. The facts are:

- `price` = 72 from D1, p. 12;
- `applies` = true from D1, p. 4;
- `levy` = true from D2, p. 3.

Every fact is counted, from a primary source, with an as-of date within `max_age_days`.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | RB and the default facts | the cell is derived | result rating `H`; both `H` conditions `pass` | unit |
| AC-2 | `price` = 30 | the cell is derived | result rating `M`; `H` level `fail` | unit |
| AC-3 | `price` = 9, `levy` = false | the cell is derived | result rating `L` | unit |
| AC-4 | `price` has no counted value | the cell is derived | result rating `not_rated`; missing facts = `["Effective carbon price"]` | unit |
| AC-5 | `price` = 30, `levy` has no counted value | the cell is derived | result rating `M` (`H` fails on price whatever the levy) | unit |
| AC-6 | `price` = 72, `levy` has no counted value | the cell is derived | result rating `not_rated`; missing facts = `["Border levy in force"]` | unit |
| AC-7 | the default facts | the cell is derived | the `H` level's detail is exactly `H: Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes. Effective carbon price = 72 USD/tCO2 (EU ETS Market Report 2026, p. 12): pass. Border levy in force = Yes (CBAM Regulation 2023/956, p. 3): pass.` | unit |
| AC-8 | `price`'s quote does not occur in D1's text | the cell is derived | `price` is not counted with reason `Quote not found in source`; result rating `not_rated` | unit |
| AC-9 | `price` = 72 but its quote contains no `72` | the cell is derived | `price` is not counted with reason `Number not in quote` | unit |
| AC-10 | the only `price` value comes from N1 | the cell is derived | `price` is not counted with reason `News cannot ground a fact` | unit |
| AC-11 | `price` extracted as 66.9 CNY/tCO2 from D1 | the cell is derived | `price` is counted and shown as `9.37 USD/tCO2 (66.9 CNY/tCO2)`; result rating `L` | unit |
| AC-12 | `price` extracted as 66.9 KRW/tCO2 | the cell is derived | `price` not counted with reason `Unit not convertible: KRW/tCO2` | unit |
| AC-13 | `price` has counted values 72 (D1) and 30 (D3) | the cell is derived | result rating `conflict`; no proposed rating; the review item lists both values with their documents | unit |
| AC-14 | `price` has counted values 72 (D1) and 65 (D3) | the cell is derived | result rating `H`; the `price` condition shows both values | unit |
| AC-15 | `levy` from D3 (secondary) | the cell is derived | `levy` confidence `medium`; result confidence `medium` | unit |
| AC-16 | `price` as-of date 400 days before the run | the cell is derived | `price` confidence `medium` | unit |
| AC-17 | `applies` entered by analyst "a.analyst" without a document | the cell is derived | `applies` confidence `low`, marked `not machine-checked`; result confidence `low` | unit |
| AC-18 | the default facts | the cell is derived | the result records `rule_book_version` 7 and its run id | unit |
| AC-19 | `price` = 30 | `POST /derive` for the cell, then `GET /scores?sector=Steel&region=European Union` | the STL-R1 cell still shows rating `H`, `basis` `hand_rated`; the review queue has one item for the cell with current `H` and proposed `M` | unit |
| AC-20 | AC-19's item | user "a.approver" (role approver) approves it | `GET /scores` shows STL-R1 EU rating `M`, `basis` `derived`, `ratified_by` `a.approver`, `last_verified` = the approval date | unit |
| AC-21 | AC-19's item | a user with role analyst submits an approve decision | HTTP 403; the cell still shows `H` | unit |
| AC-22 | AC-19's item | "a.approver" rejects it | the cell still shows `H`, `basis` `hand_rated` | unit |
| AC-23 | three cells derived with unchanged ratings | "a.approver" approves them in one bulk action | each cell shows `basis` `derived` and `ratified_by` `a.approver` | unit |
| AC-24 | AC-4's result | `GET /cells/STL-R1/European Union` | rating still `H`; `flags` contains `Not re-derived: missing Effective carbon price` | unit |
| AC-25 | any derivation, approval or rejection | the run finishes | the files in `backend/arp/transition_barrier/data/` are byte-identical to before | unit |
| AC-26 | the shipped rule book | `arp transition-barrier rules validate` | exit 0, prints `Rule book v1: 35 criteria, OK` | unit |
| AC-27 | RB with `H` naming fact `prices` | `rules validate` | exit 1, prints `STL-R1: condition names unknown fact 'prices'` | unit |
| AC-28 | RB with `p_high` lacking `source` | `rules validate` | exit 1, prints `STL-R1: parameter 'p_high' has no source` | unit |
| AC-29 | RB with `rationale` empty | `rules validate` | exit 1, prints `STL-R1: no rationale` | unit |
| AC-30 | `criteria_schema.json` has STL-T1 but RB has no entry for it | `rules validate` | exit 1, prints `Missing rule book entry: STL-T1` | unit |
| AC-31 | RB with `p_high` changed to 60, version still 7 | `rules validate` | exit 1, prints `Rule book content changed but version is still 7` | unit |
| AC-32 | RB | `GET /criteria/STL-R1` | `rating_rubric` = `{"H": "Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes", "M": "Carbon price applies to steel is Yes and Effective carbon price >= 10 USD/tCO2", "L": "Otherwise (neither H nor M holds)"}` | unit |
| AC-33 | the shipped rule book | `rules render` | the output equals the committed `docs/transition_barrier/RULE_BOOK.md` | unit |
| AC-34 | search stub returns URL U (classified primary, not registered) for STL-R1 China | `arp transition-barrier search --code STL-R1 --region China` | one `new_source` review item with U, STL-R1, China | unit |
| AC-35 | AC-34's item | "a.approver" approves it | `GET /sources` lists U for STL-R1 | unit |
| AC-36 | AC-34's item rejected | the search runs again and returns U | no new review item | unit |
| AC-37 | search stub returns N1 for STL-R1 European Union | the search runs | the cell's `flags` contains `Possible change: Reuters: carbon price falls`; a derivation run exists for the cell; no fact cites N1 | unit |
| AC-38 | `ARP_TRANSITION_BARRIER_REFRESH_ENABLED` false | `POST /derive` | HTTP 409; no outbound request made | unit |
| AC-39 | an uploaded PDF and a quote not in it | `POST /cells/STL-R1/European Union/facts` | HTTP 422 with message `Quote not found in the uploaded document.` | unit |
| AC-40 | golden set G: at least 40 facts from at least 12 source documents, values and pages labelled by a person | `arp transition-barrier golden --cases G --documents-dir <dir> --min-precision 0.95` | exits 0 | golden |
| AC-41 | the running app after AC-20 | open Transition Barriers, then the STL-R1 European Union cell | shows rating M, its confidence, "ratified by a.approver" with the date; each condition as pass, fail or unknown; each figure with its quote, document title, page, and a link that opens the source | evaluator |
| AC-42 | the running app | open the STL-R1 criterion | shows the rationale, the actions it limits, each fact with its definition, the H, M and L sentences, each threshold with value, source and rationale, and the rule book version | evaluator |
| AC-43 | the running app with AC-19's item | open the review screen | the item is listed with current and proposed rating; approve and reject work from there; unchanged items can be bulk-approved | evaluator |
| AC-44 | a cell never re-derived | `GET /scores` | rating, confidence, evidence, source and `last_verified` equal the bundled values; `basis` `hand_rated`, `flags` `[]` | unit |
| AC-45 | the existing refresh slice | `GET /refresh/coverage` | the same response as before this change | unit |
| AC-46 | refresh flag on; the last policy-change search finished 31 days ago | the scheduler ticks | one search has run for each of the 105 cells | unit |
| AC-47 | a registered source without `tier` | `rules validate` | exit 1, prints `Source '<source key>' has no tier` | unit |

Must not change: the bundled data files at run time (AC-25), cells never re-derived (AC-44), the
refresh coverage report (AC-45), and the 409 when the refresh flag is off (AC-38).
