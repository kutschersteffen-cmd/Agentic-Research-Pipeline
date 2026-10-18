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
- Changing the transition plan assessment, Decision Studio or StewardIQ. They read the matrix through
  the existing dataset functions, which from now on return each cell's current (ratified) rating.

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
- **Roles.** `api/auth.py` has viewer, analyst and approver (`require_role`; approver outranks
  analyst).
- **Review decisions.** `review/decide.py` requires a second, different reviewer for corrections,
  high-risk items and decisions that change a published value (`published_change`). It samples 10% of
  approvals (`second_review_sample_rate`) and 20% of bulk accepts (`bulk_accept_sample_rate`) for a
  second review. A second review by the same person is refused with HTTP 409 `second review must be a
  different person`. Bulk accept is `POST /api/extraction/items/bulk-accept` (`run_id` plus items).
- **UI.** `frontend/src/pages/TransitionBarrierAssessment.tsx` shows the matrix, a criterion's rubric
  and its cells (rating, confidence, evidence, last verified), staleness, and starts a refresh.
- **Consumers.** `decision/sources.py::from_transition_barrier` feeds the matrix into Decision Studio.
  `scripts/build_transition_barrier_report.js` builds the Word report from the JSON.

## Design

### The flow

```
rule book ──► sources & search ──► fact extraction ──► derivation ──► review ──► current rating
 (stage 1)                          (stage 2, RAG)     (stage 3,       (named      (history kept)
                                    + analyst facts     rules engine)   people)
```

One unit of work is a **cell**: one criterion × one region. A derivation run covers one or more
cells.

**Data directory.** A new setting, `ARP_TRANSITION_BARRIER_DATA_DIR`, names the directory that holds
`criteria_schema.json`, `assessment_scores.json`, `source_registry.json` and the new `rule_book.json`.
It defaults to the bundled `backend/arp/transition_barrier/data/`. Tests and the evaluator point it at
a fixture directory.

### 1. The rule book

`rule_book.json` is the only authority for how a cell is rated. Sketch (field names beyond these are
the builder's call):

```json
{
  "version": 1,
  "fingerprint": "<sha256>",
  "history": [{"version": 1, "fingerprint": "<sha256>", "approved_by": "<owner>", "approved_at": "2026-.."}],
  "actions": {"Steel": [{"id": "steel.h2_dri", "label": "Hydrogen-based direct reduced iron"}]},
  "conversions": [{"from": "CNY", "to": "USD", "rate": 0.14, "year": 2025, "source": {"title": "...", "url": "..."}}],
  "domain_tiers": {"eur-lex.europa.eu": "primary", "iea.org": "primary", "reuters.com": "news"},
  "criteria": {
    "STL-R1": {
      "rationale": "Without a carbon price that closes the cost gap ..., no low-carbon steel route pays ...",
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

**Computed facts.** Many criteria compare two measured quantities, for example renewable against
fossil LCOE (`PWR-T1`), or SAF capacity as a share of jet fuel demand (`AVI-T1`). Sources rarely state
those ratios. So a fact may be computed from other facts of the same criterion: `{"id", "label",
"formula": "ratio" | "ratio_pct" | "difference", "inputs": [a, b]}`.

- `ratio` = a ÷ b and `ratio_pct` = a ÷ b × 100. Both need a and b in the same unit. A `ratio` has no
  unit (`unit` absent) and shows as a bare number (`0.75`); a `ratio_pct` has unit `%` and shows with `%`
  (`75%`).
- `difference` = a − b, in the inputs' shared unit, and shows with that unit (`-15 USD/MWh`).
- A computed fact has no quote of its own. It counts when every input counts, and its confidence is
  the lowest of its inputs'. When it doesn't count, the missing facts named are its uncounted inputs.

**Parameters.** Thresholds live in `params`, never inline in a condition, so each one carries a
`source` and a `rationale`. `by_region` overrides the value for one region (for example a hydrogen
breakeven cost that differs by region). Each override carries its own source.

**Open parameters.** Where no defensible number exists yet, a parameter is `{"id", "label", "status":
"open", "question"}`, with no value. The validator accepts it and counts it. A condition that reads an
open parameter is `unknown`. Like a missing fact, it only blocks a rating when it could change it
(section 4). If it does, the cell stays on its current rating, flagged
`Not re-derived: open threshold <parameter label>`. An open parameter renders as
`[open: <parameter label>]`, for example `Effective carbon price >= [open: High price level]`.
Version 1 can therefore merge with open questions, and each one closes in a later version.

**Conditions.** A condition is one of:

- `{fact, op, value}`, where the value is a boolean, an enum value or a date, never a number;
- `{fact, op, param}`, the only way to compare with a number;
- `{fact, op, other_fact}`, comparing two facts of the same type and unit, for example renewable LCOE
  `<=` fossil LCOE.

`op` is one of `>=`, `<=`, `>`, `<`, `=` or `in`. Conditions group with `all` / `any`, nested at most
two levels: a level's own group is level 1, a group inside it is level 2, and a group inside that is
refused.

**Regional overrides** apply in their region only. A sentence renders the default value, followed by
the overrides in brackets: `Effective carbon price >= 50 USD/tCO2 (China: 40 USD/tCO2)`. A cell's
detail sentences use its own region's value.

**Levels.** `H` is tested first, then `M`. `L` applies when both are false. There is no explicit L
condition, so the three levels cover every case by construction.

**Conversions.** Facts are compared in the rule book's unit. A value extracted in another unit (CNY,
EUR, short tons) is converted by code using the `conversions` table.

- **Rate choice:** the as-of year is the value's own as-of date if the extraction returned one, else
  its document's. The rate whose `year` equals that year applies; if there is none, the latest
  earlier year. If there is no earlier year either, the fact doesn't count, with reason
  `No CNY to USD rate for 2023 or earlier` (currencies and year filled in).
- **Unknown units:** a unit with no row in the table makes the fact not count, with reason
  `Unit not convertible: KRW/tCO2`.
- **Display:** comparisons use the unrounded value. Screens and detail sentences show at most two
  decimals, rounded half up on the decimal value, with trailing zeros dropped (`72`, `9.37`, `10`). A converted value is followed by the
  extracted value in brackets: `9.37 USD/tCO2 (66.9 CNY/tCO2)`.

Every rate cites its source and year.

**Actions.** Per sector, a list of decarbonisation actions with stable ids. Each criterion names the
actions it limits. The next project matches plan actions against these ids.

**Domain tiers.** `domain_tiers` maps a web domain (subdomains included) to a source tier (section
2). Search uses it to classify what it finds.

**Rendering.** Sentences are rendered from the conditions, never stored:

- `{fact, op, value | param}` renders as `<fact label> <op> <value> <unit>`, for example
  `Effective carbon price >= 50 USD/tCO2`; a computed fact without a unit renders as
  `LCOE ratio <= 1`;
- a boolean renders as `<fact label> is Yes` or `<fact label> is No`;
- `in` renders its values joined with `, `: `Carbon pricing scheme in ETS, tax`; a date renders as
  `YYYY-MM-DD`;
- `{fact, op, other_fact}` renders as `<label> <op> <other label>`, for example
  `Renewable LCOE <= New-build fossil LCOE`;
- `all` joins with ` and `, `any` with ` or `, and nested groups are bracketed;
- `L` renders as `Otherwise (neither H nor M holds)`.

The `/criteria` API's `rating_rubric` (`{H, M, L}`) is filled from these renderings. The free-text
`rating_rubric` in `criteria_schema.json` is removed, so no second wording exists.

**Methodology document.** `arp transition-barrier rules render [--out <file>]` writes
`docs/transition_barrier/RULE_BOOK.md` (or the given file). Per sector and criterion it shows the rationale, the actions,
the facts with their definitions, the H/M/L sentences, and every threshold with its value, source and
rationale. Open thresholds are listed with their questions. A test checks that the committed file
equals the render output.

**Versioning.** `fingerprint` is the SHA-256 (hex) of the rule book without its `fingerprint` and
`history` fields, serialised as JSON with sorted keys and separators `,` and `:`, non-ASCII characters
written as UTF-8 rather than escaped (in Python:
`json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`).
`arp transition-barrier rules sign --approved-by <name>` increments `version`, writes the new
fingerprint and appends a `history` entry. A content change without signing leaves a stale
fingerprint, which the validator reports as a changed rule book under an unchanged version.

**Validation.** `arp transition-barrier rules validate [--data-dir <dir>]` and the app's loader check
the rule book against the criteria schema in the same directory. The validator prints every error,
one per line, in the order of the list below, and exits 1 if there is any. The app refuses to start with an invalid rule book, naming
the first error. CI runs the validator. It rejects a rule book where:

1. a criterion in `criteria_schema.json` has no entry: `Missing rule book entry: <code>`; or an entry
   has no criterion: `Rule book entry without criterion: <code>`;
2. a condition names an unknown fact or parameter:
   `<code>: condition names unknown fact '<id>'` (or `unknown parameter`);
3. a comparison's types or units don't match: `<code>: '<id>' (<unit>) compared with '<id>' (<unit>)`
   (conditions reading an open parameter are skipped); a condition compares with an inline number:
   `<code>: condition on '<id>' uses an inline number; use a parameter`; an unknown operator:
   `<code>: unknown operator '<op>'`; groups nested deeper than two levels:
   `<code>: conditions nested deeper than two levels`;
4. a parameter that isn't open has no source or no rationale: `<code>: parameter '<id>' has no source`
   (or `no rationale`); a `by_region` override has no source:
   `<code>: parameter '<id>' override for <region> has no source`; an open parameter has no question:
   `<code>: open parameter '<id>' has no question`;
5. a criterion has no rationale, no facts, or no H or M level: `<code>: no rationale`, `<code>: no
   facts`, `<code>: no H level`, `<code>: no M level`;
6. a fact has no definition: `<code>: fact '<id>' has no definition`; a computed fact names an unknown
   input: `<code>: computed fact '<id>' names unknown input '<id>'`; an input is not numeric:
   `<code>: computed fact '<id>' input '<id>' is not numeric`; the inputs' units differ:
   `<code>: computed fact '<id>' input '<id>' is in <unit>, expected <unit of the first input>`;
7. a criterion's actions name an id not in its sector's list: `<code>: unknown action '<id>'`;
8. a registered source has no tier: `Source '<source key>' has no tier`;
9. the fingerprint doesn't match the content: `Rule book content changed but version is still <n>`.

On success it prints `Rule book v<version>: OK, <n> criteria, <m> open thresholds`.

**Content of version 1.** The builder drafts all 35 entries from today's rubrics, evidence and
sources. Each vague word ("material", "meaningful", "significant") becomes a number, and each number
cites a source. Where no defensible number can be found, the parameter is open, with the question
stated, so nothing is invented.

The version 1 pull request also cleans up the registry:

- every bundled source either points at a fetchable document (not a landing page such as
  `https://www.mee.gov.cn/`), or is marked `manual` with a reason (subscription, dashboard, company
  disclosure);
- sources that today's evidence cites but the registry lacks are added (for `STL-R1` China: ICAP,
  IEEFA, Transition Asia);
- the two copy-pasted URLs noted in `docs/TRANSITION_BARRIER_ASSESSMENT.md` are re-sourced.

The pull request includes an **impact table**. For each of the 105 cells it shows the current rating
and the rating the draft rules would give using the figures in today's evidence text, read by hand.
Every difference is listed with its reason. `STL-R1` China is expected to be one of them. The owner
approves version 1 in that pull request.

**Changing the rules later.** Every result stores a snapshot of the criterion's rule entry it was
evaluated under, together with the version. Its detail sentences render from that snapshot, so an old
rating always reads with its own rules. When the current entry for a criterion differs from a cell's
snapshot, the cell shows `Rules changed since this rating (v<n>)` until a result derived under the
current rules is ratified. Hand-rated
cells are not touched: they show as hand-rated on 2026-08-14, before the rule book existed.
`assessment_scores.json` keeps its hand ratings.

### 2. Sources and search for new material

**Registry.** The bundled registry (`criteria_schema.json` `primary_sources`) lists the sources a
criterion may use in all three regions. Each source gains a `tier`:

| Tier | Examples | May ground a fact | Fact confidence at most |
|---|---|---|---|
| `primary` | law text, regulators, ministries, official statistics, IEA, IRENA, IPCC, World Bank | yes | high |
| `secondary` | research institutes, industry trackers, think tanks, industry associations | yes | medium |
| `news` | news and commentary | no | n/a |

Every source has a stable `key` (the registry's existing keys) and may have a `cadence` (`annual`,
`quarterly`). `tier` and `cadence` live in `criteria_schema.json` `primary_sources`;
`source_registry.json` stays a derived view and the validator doesn't read it. The builder assigns the tier for every bundled source in the version 1 pull request, for
the owner to check. A source approved later applies to the criterion and region it was proposed for. It is stored
with the ratified results, never written into the bundled files. `GET /sources` lists bundled and
approved sources together, each with its tier and, for approved ones, its region.

**Documents.** Fetching a source stores the document (PDF or HTML) and its as-of date: the
publication date, or the data year where the document states one. Re-fetching an unchanged document
is a no-op. Documents are parsed with page breaks (`parse_file_to_text_with_pages`), so every quote
gets a page. A barrier source document must not create a company record. How it avoids the
`documents` table's company path is the builder's call.

**The refresh flag.** `ARP_TRANSITION_BARRIER_REFRESH_ENABLED` now gates every request to a source or
search provider: fetching, edition checks, search, and the existing EUR-Lex refresh. With the flag
off:

- `POST /search` answers 409;
- `POST /derive` still runs, using stored documents and analyst facts only, and its results note
  `Sources not fetched: refresh is disabled`.

So the engine and analyst facts work without network access. All requests go through the SSRF guard;
a URL the guard refuses is skipped and creates no review item.

**Newer editions.** For each registered source with a `cadence`, a check looks for a newer edition
(next year's report, an amended act). Legal sources reuse the existing EUR-Lex/ELI version check.
Other sources search through `WebSearchClient` for the source's title with a later year. A result on
the source's domain whose title equals the source's title with a later year is a newer edition. It
becomes a `new_source` review item that proposes replacing the old entry, and it inherits the old
entry's tier. Approving it replaces that source for its criterion in every region the old one applied
to: the old document is no longer read, and `GET /sources` no longer lists it. A result that is a
newer edition becomes only the edition item, never also a plain `new_source`. Edition checks run
inside every `transition_barrier_search` run, for the sources of the cells it covers.

**Policy-change search.** A search runs per cell, monthly and on demand. The monthly search is one
run of type `transition_barrier_search` covering every cell. A scheduled job, following the interval
pattern of `portfolio/monitoring/scheduler.py`, calls one scheduler tick (also
`arp transition-barrier search-tick [--now <ISO datetime>]`). A run started by a tick at time T is
recorded as started and finished at T, and the interval compares UTC calendar dates. A tick starts the
monthly run when the refresh flag is on and either no scheduled run exists, or the latest scheduled
run finished at least `ARP_TRANSITION_BARRIER_SEARCH_INTERVAL_DAYS` (default 30) days ago (30 days
counts). On-demand searches for single cells don't count towards the interval.

Queries are built from the criterion, the region and the fact definitions. Each result's tier comes
from `domain_tiers`; a domain not in the list is `unclassified`.

- A `primary`, `secondary` or `unclassified` result that isn't registered becomes a `new_source`
  review item for that criterion and region. Approving an `unclassified` one without choosing a tier
  is refused with HTTP 422 `choose a tier`.
- A `news` result goes to a change check: a model reads its title and snippet with the criterion and
  region, and answers whether it suggests a change. On yes, the cell gets the flag
  `Possible change: <article title>` (exactly that string), a `possible_change` review item carrying
  the article's title, URL and date, and a derivation run from its registered sources. The model's answer can only raise a flag and queue a
  re-derivation; it never touches a fact or a rating.

Results are matched by normalised URL. A URL a person rejected is never proposed again for the same
criterion and region. The search provider sits behind the existing `WebSearchClient` interface
(`arp/discovery/site_finder.py`). Which provider is the builder's call; a paid one needs the owner's
approval.

### 3. Fact extraction (RAG)

**Unit.** One fact for one cell. The inputs are the fact's definition, the region, and the fetched
documents of the cell's sources: the criterion's bundled sources plus sources approved for that
criterion and region. A pending `new_source` is not read. A cell with no fetched documents runs no
extraction, so a derivation from analyst facts alone makes no model call.

**Steps.** A rule book fact maps onto a `FieldDefinition`: its type, unit and allowed values carry
over, and its definition becomes the extraction instructions. It then runs through the existing
`extract_one_field` path, with the cell (for example "Steel, China, STL-R1") in place of the company
name.

1. Retrieve passages relevant to the fact from those documents.
2. The model returns either `not_found`, or a value in the source's own unit with the exact quote, the
   page or locator, and the as-of date.
3. Code checks the result in this order, and a value counts only if all of these pass:
   - the quote has an exact, normalised or fuzzy (score ≥ 0.92) match in a passage the model was shown
     (`ground_citations` with `passages`); otherwise `Quote not found in source`;
   - for numbers, the number appears in the quote; otherwise `Number not in quote`;
   - the unit is the fact's unit, or convertible (section 1);
   - the source's tier may ground a fact; otherwise `News cannot ground a fact`.

   A value that fails keeps its failure reason, and both the reviewer and the cell detail show it.
   The page shown for a value is the page where its quote was found. An HTML document has no pages:
   its values have `page` null and keep the locator the model returned.

**Several values for one fact.** When more than one counted value exists for a fact (two sources, two
editions), the engine evaluates every combination of values:

- if every combination gives the same rating, that rating stands and every value is shown;
- otherwise, if any combination is `not_rated`, the result is `not_rated`, naming what is missing,
  because the missing fact has to be found first;
- otherwise the result is a **conflict**: no rating is proposed, and the review item lists each value
  as `<value shown>, <document title>`. This is operating rule 4 of the existing module.

Values are listed with registered-source values first, in registry order and then by page, followed
by values from uploaded documents in the order they were entered, then by page.

**Dates.** The run date, and every age and interval computed from it, come from one clock,
`transition_barrier.clock.today()`, which tests freeze. The CLI commands take `--now` to set it.

**Fact confidence**, per counted value:

- `high`: from a `primary` source, as-of date at most `max_age_days` before the run date;
- `medium`: from a `secondary` source, or older than `max_age_days`;
- `low`: entered by an analyst without a document (below).

**Analyst-entered facts.** For sources code cannot read, an analyst (role `analyst` or higher) enters
the value, unit, quote, page and source.

- **The source** is either a registered source of the cell, or an uploaded document. An uploaded
  document needs a title, a publisher, an as-of date and a tier stated by the analyst. It is used only
  to check this fact's quote; extraction never reads it. Tier `news` is refused with
  HTTP 422 `News cannot ground a fact.`
- **With an uploaded document,** the quote is checked against it as above. A failed check is refused
  with HTTP 422 `Quote not found in the uploaded document.`
- **Without a document,** the fact is marked `not machine-checked` and its confidence is `low`.
- **Always:** a number must appear in its quote, or the fact is refused with HTTP 422
  `Number not in quote.`

An upload missing any of its four fields is refused with HTTP 422
`An uploaded document needs a title, publisher, as-of date and tier.` The checks run in this order:
required fields, tier, number in quote, quote in the uploaded document. A newer analyst fact for the
same fact and the same source replaces the earlier one in later derivations; both stay in the
history. Two uploads are the same source when their title and publisher match; a registered source is
the same source as itself. The analyst's
name is recorded on the fact.

**Choosing between conflicting values.** For a conflict, an analyst can choose which value counts with
a written reason (`POST /cells/{code}/{region}/choices`). An empty reason is refused with HTTP 422
`A reason is required.` A choice re-derives the cell using only the chosen value, and the choice, its
reason and its author appear in the cell's history. The choice holds for later derivations until a
value for that fact appears that wasn't there when the choice was made.

### 4. Derivation (the rules engine)

The engine is code only. Its inputs are a rule entry and the counted values for a cell, and its output
is a result. No model is involved.

**Three-valued logic.** A condition is `pass`, `fail` or `unknown`. It is `unknown` when a fact it
reads has no counted value, or when it reads an open parameter.

- `all` fails if any part fails, passes if every part passes, and is otherwise `unknown`.
- `any` passes if any part passes, fails if every part fails, and is otherwise `unknown`.

The two levels then give the rating:

| H | M | Rating |
|---|---|---|
| pass | any | `H` |
| unknown | any | `not_rated` |
| fail | pass | `M` |
| fail | unknown | `not_rated` |
| fail | fail | `L` |

A `not_rated` result names the facts (or open parameters) that made it unknown. So a missing fact only
blocks a rating when it could change it. With a carbon price of 30 and a high level of 50, a missing
border-levy fact cannot make the cell `H`, and the result is `M`.

**Result.** Each result records:

- the rating, or `not_rated` or `conflict`;
- each level's outcome;
- each condition's outcome, with the values used (as shown and as extracted) and their citations;
- the missing facts and open parameters;
- the confidence;
- the rule entry snapshot, the rule book version and the run id.

**Confidence of a result** is the lowest confidence among all counted values of all the criterion's
facts. That includes facts read only by a level that didn't decide the rating, and every value when a
fact has several. This is my call, and it is the stricter of the two readings.

**Detail sentences.** Each level evaluated renders as `<level>: <level sentence>.`, followed by one
clause per condition:

- one value: `<label> = <value shown> (<document title>, p. <page>): <outcome>.` A citation with a
  locator and no page reads `(<document title>, <locator>)`.
- several values: `<label> = <v1> (<doc 1>, p. <p1>), <v2> (<doc 2>, p. <p2>): <outcome>.` The outcome
  is `pass` or `fail` when every value gives it, else `mixed`.
- no counted value: `<label> not found: unknown.`
- a fact compared with a fact: `<label> = <v> (<cite>) vs <other label> = <v> (<cite>): <outcome>.`
- a computed fact: `<label> = <v> from <input label> = <v> (<cite>) and <input label> = <v> (<cite>): <outcome>.`
- an analyst fact without a document: `(<source title>, entered by <user>)` in place of
  `(<document title>, p. <page>)`.

Booleans show as `Yes` / `No`; numbers as in section 1.

**What a ratified derived cell shows** in `GET /scores`:

- `confidence`: the result's confidence;
- `evidence`: the detail of `H`, followed by a space and the detail of `M` when `H` failed;
- `source`: the titles of the documents (or registered sources) that the counted values cite, without
  duplicates, in the rule book's fact order, joined with `; `.

**Engine.** A plain Python evaluator over the rule book's structured conditions, in
`transition_barrier/`. That is my call, and it changes what I said in chat ("reuses the GoRules
engine"). GoRules expressions fail on a missing value, so the three-valued logic and the
per-condition evidence would have to be rebuilt around it. In-app rule editing, the one thing GoRules
would add, is a non-goal. The schema rules design approved today made the same choice for the same
kind of typed condition.

### 5. Review and ratification

Every derived result becomes a review item, queued with `queue_for_review` under a new run type,
`transition_barrier_derivation`. That run type is added to `REVIEWABLE_RUN_TYPES` and to the
frontend's reviewable kinds, so items show in the existing review screens. Decisions go through the
existing `POST /api/review/runs/{run_id}/items/{item_key}/decision` and `review/decide.py`, so its
second-review rules apply.

| Kind | What it is | Who decides |
|---|---|---|
| `changed` | proposed rating differs from the current one | an analyst approves; a second, different person with the approver role confirms (the owner's decision) |
| `unchanged` | same rating, new evidence | one analyst, with the existing second-review sampling; bulk accept allowed |
| `not_rated`, `conflict` | no rating proposed | resolved by an analyst fact or a choice (section 3), or dismissed by an analyst, which closes the item and keeps the current rating and its flag |
| `new_source` | a source found by search or a newer edition | an approver; anyone else gets HTTP 403 `a new source is approved by an approver` |
| `possible_change` | a news flag | an analyst; approving or rejecting clears the flag, and the queued re-derivation runs either way |

**Two people for a rating change** is the owner's decision. It matches `review/decide.py`, which
already sends a decision that changes a published value to a second reviewer (`published_change`).
For barrier items, `published_change` is set for `changed` items only. An `unchanged` item also
updates evidence, confidence and source, but it doesn't count as a published change.

`new_source` and `possible_change` items, from both search and edition checks, are queued under run
type `transition_barrier_search`. That run type is added to `REVIEWABLE_RUN_TYPES` and the frontend's
kinds too.

Rules on top of the existing ones:

- rejecting a `changed` item is final at once; only an approval needs the second review;
- the existing different-person check runs first. After it, any decision at the second review of a
  `changed` item needs the approver role, or HTTP 403 `a rating change is confirmed by an approver`;
- bulk accept refuses a `changed` item with reason `a rating change is not bulk-accepted`, and an item
  whose result uses a fact the accepting person entered with reason
  `you entered a fact this result uses`. The other items in the batch go ahead;
- nobody may decide an item whose result uses a fact they entered, or HTTP 409
  `you entered a fact this result uses`.

When an item's decision is final, an approved result becomes the cell's current rating.
`ratified_by` is the person whose decision made it final, and `last_verified` is that decision's date,
so staleness counts from there. A rejected result changes nothing. Every decision's author and time is
recorded in the cell's history.

**Storage.** Ratified results, approved sources, analyst facts and choices are stored append-only next
to runs and results. A cell's current rating is its latest ratified result. A cell never re-derived
keeps its bundled rating (`basis` `hand_rated`). The bundled JSON is never written at run time, and the
existing byte-identity test stays.

**Flags.** A cell keeps its current rating and shows a flag in these cases:

- its latest derivation was `not_rated`: `Not re-derived: missing <fact labels>` and/or
  `Not re-derived: open threshold <parameter labels>` (labels joined with `, `). The flag clears as soon as a
  later derivation of the cell gives a rating, before that result is reviewed;
- it has an open `possible_change` item: `Possible change: <article title>`;
- its rules changed since its rating: `Rules changed since this rating (v<n>)`, until a result derived
  under the current rules is ratified.

**Consumers.** The dataset functions in `transition_barrier/dataset.py` return current ratings, so
Decision Studio (`from_transition_barrier`) and every other reader see ratified ratings. They must pick
up a new approval without a restart. `arp transition-barrier export --out <file>` writes the criteria
(with rendered rubrics) and the current scores. `scripts/build_transition_barrier_report.js` reads
that export, so the Word report shows the same matrix as the app.

### 6. Screens

The layout is the builder's call, following `DESIGN.md`. What each screen must show:

- **Criterion page** (existing, Transition Barriers): the rationale, the actions it limits, the facts
  with their definitions, the H/M/L sentences, each threshold with its value, source and rationale (or
  its open question), and the rule book version.
- **Cell detail**:
  - rating, confidence, and who ratified it and when (or "hand-rated 2026-08-14");
  - each level and condition as pass, fail or unknown;
  - for every figure, its quote, document title, page, and a link that opens the source;
  - flags and the rating history;
  - the analyst fact form, with optional document upload, and the conflict choice.
- **Review**: barrier items in the existing review screens, with approve, reject, second review and
  bulk accept.

### 7. Interfaces

New CLI commands under `arp transition-barrier`:

- `rules validate [--data-dir <dir>]`: see Validation.
- `rules sign --approved-by <name> [--data-dir <dir>]`: bump the version and re-fingerprint.
- `rules render [--out <file>]`: write `docs/transition_barrier/RULE_BOOK.md`, or the given file.
- `export --out <file>`: current criteria and scores, for the Word report.
- `derive --code <code> --region <region> [--now <ISO date>]`: start a derivation run for one cell
  and print its run id.
- `search --code <code> --region <region> [--now <ISO datetime>]`: run the policy-change search and
  edition checks for one cell (an on-demand `transition_barrier_search` run).
- `search-tick [--now <ISO datetime>]`: one scheduler tick (section 2).
- `golden --cases <file> --documents-dir <dir> --min-precision <x> --min-coverage <y>`: prints
  `precision <p>, coverage <c>` (numbers as in section 1) and exits 0 only when both meet their minimum.

New and changed API routes under `/api/transition-barrier`:

- `GET /scores` and `GET /matrix` keep every existing field. Each cell gains `basis` (`hand_rated` or
  `derived`), `ratified_by` (null when hand-rated) and `flags` (a list of strings, empty by default).
- `GET /criteria/{code}`: `rating_rubric` comes from the rule book. The response gains `rationale`,
  `actions`, `facts`, `params` and `rule_book_version`.
- `GET /sources`: bundled and approved sources, each with `tier`, and `region` for approved ones.
- `GET /cells/{code}/{region}`: the current rating, the latest result with every field in section 4's
  Result list (each value with its citation, `confidence`, `machine_checked` and failure reason),
  flags and the history.
- `POST /derive` with `{"cells": [{"code", "region"}]}`: starts a run and returns `{"run_id"}`.
- `POST /search` with the same body: starts a search run, or answers 409 when the refresh flag is off.
- `POST /cells/{code}/{region}/facts`: an analyst fact (multipart, optional document).
- `POST /cells/{code}/{region}/choices`: choose a conflicting value, with a reason.

Review decisions use the existing `POST /api/review/runs/{run_id}/items/{item_key}/decision` and
`POST /api/extraction/items/bulk-accept`. Dismissing a `not_rated` or `conflict` item is the decision
`reject`.

**Response fields** (the names the acceptance rows read):

- `GET /cells/{code}/{region}`: `rating`, `basis`, `ratified_by`, `last_verified`, `confidence`,
  `flags[]`, `latest_result`, `history[]`.
  - `latest_result`: `run_id`, `rating` (`H`, `M`, `L`, `not_rated` or `conflict`), `confidence`,
    `missing_facts[]` (labels), `open_params[]` (labels), `notes[]`, `rule_book_version`, `snapshot`,
    `levels`, `values[]`.
  - `levels.H` and `levels.M`: `outcome`, `detail`, and `conditions[]`, each with `text` (the rendered
    condition), `outcome` (`pass`, `fail`, `unknown` or `mixed`) and `clause`.
  - `values[]`: `fact`, `value`, `unit`, `shown`, `extracted`, `document`, `page`, `locator`,
    `confidence`, `machine_checked`, `counted`, `reason`. Each computed fact also has one entry, with
    `document` and `page` null.
  - `history[]`: `at`, `by`, `kind` (`rating`, `fact`, `choice` or `decision`), plus `rating` and
    `basis` for ratings, `value` (shown with its document) and `reason` for choices.
- A barrier review item's payload: `kind`; for `changed` and `unchanged`, `current` and `proposed`; for
  `conflict`, `values[]` as `<value shown>, <document title>`; for `new_source`, `url`, `code`,
  `region`, `tier` and `replaces` (a source key or null); for `possible_change`, `title`, `url` and
  `date`.
- `GET /sources`: each entry has `key`, `title`, `url`, `code`, `region` (null for all regions),
  `tier` and `cadence`.

### 8. Golden set

Fact extraction is measured on a golden set of at least 40 facts from at least 12 source documents.
Each case names the cell, the fact, the document, and the correct value, unit and page.

- **precision** = correct counted values ÷ counted values. A counted value is correct when it equals
  the label in the rule book's unit at two decimals (booleans and enums exactly, dates to the day) and
  its page equals the label's.
- **coverage** = cases with a counted value ÷ cases.

The cases file is JSON, a list of `{code, region, fact, document, value, unit, page}`, where
`document` is a file name in `--documents-dir`. The set lives with the holdout tests once the holdout
repo is attached to the build. Until then it
lives in `backend/tests/golden/transition_barrier/`, listed as owed in the pull request. It uses only
documents the repo may store (law texts, and agency reports whose terms allow it). The builder drafts
the labels, and the owner checks them (about 40 values with their pages, roughly two hours) before
phase 3 merges.

### 9. Build order

Each phase is one pull request.

1. **Rule book.** The data directory setting, format, validator, `sign`, rendering, the `/criteria`
   change, `export` and the Word report change, version 1 content, source tiers, domain tiers, the
   registry clean-up, the impact table and `RULE_BOOK.md`. The owner approves the rules here, before
   any extraction code merges.
2. **Engine and ratification.** Derivation, storage, review items, cell detail, analyst facts,
   choices, flags, and the consumers reading current ratings. Usable from this phase on with
   analyst-entered facts.
3. **Extraction.** Document fetching and storage, retrieval, fact extraction and checks, and the
   golden set.
4. **Search.** Newer editions, policy-change search, the change check, the monthly schedule.

The owner described the flow as rules, then extraction, then engine. Building the engine before
extraction is my call: the engine is small and deterministic, and analysts can use it with entered
facts while extraction, the riskiest part, is built.

## Constraints

- The model extracts facts and answers the news change check. It never outputs a rating, a condition
  outcome or a confidence.
- Precision first: "not rated" is acceptable; a wrong figure that counts is not.
- The existing operating rules in `docs/TRANSITION_BARRIER_ASSESSMENT.md` stay in force.
- Tests make no network calls and no model calls: fetch, search and the model are stubbed
  (`FakeSearchClient`, `FakeLLMClient`, injected transports).
- Request/response model changes follow the API contract steps in `.claude/CLAUDE.md`.
- At most three agent pull requests in flight (`.claude/skills/steward/SKILL.md`), so phases 3 and 4
  wait for earlier ones to merge or run one at a time.

## Left to the builder

- Storage layout and table names, and JSON field names beyond the sketch.
- How barrier documents stay out of the company path of the `documents` table.
- Retrieval settings (passages, re-ranking), prompts, search query wording.
- The search provider behind `WebSearchClient` (paid ones need the owner's approval).
- How the dataset functions pick up new approvals (cache invalidation).
- Screen layout and wording beyond the strings in the acceptance table.
- A cap on how many value combinations a conflict check evaluates.
- The fixture documents' wording, as long as the quotes and pages in the acceptance table hold.

## Acceptance

Each section names the phase (section 9) whose pull request must make its rows pass.

### Fixtures

**Data directory F** (`ARP_TRANSITION_BARRIER_DATA_DIR`, in `backend/tests/fixtures/transition_barrier/`):

- `criteria_schema.json` holds one criterion, `STL-R1` (Steel, Regulation). Its registered sources,
  in this order, are `eu_ets_report` (D1, tier `primary`, cadence `annual`), `cbam_regulation` (D2,
  `primary`) and `steel_policy_tracker` (D3, `secondary`).
- `assessment_scores.json` holds the three bundled STL-R1 cells: European Union `H`, United States
  `L`, China `L`, each with `last_verified` 2026-08-14.
- `rule_book.json` is **RB**, version 7, signed.
- `source_registry.json` is derived from the schema, as today.
- D1's URL is `https://climate.ec.europa.eu/eu-ets-market-report-2026.pdf`.

**RB, criterion `STL-R1`:**

| Fact id | Label | Type |
|---|---|---|
| `price` | "Effective carbon price" | number, unit `USD/tCO2`, `max_age_days` 365 |
| `applies` | "Carbon price applies to steel" | boolean, no age limit |
| `levy` | "Border levy in force" | boolean, no age limit |

- **Parameters:** `p_high` "High price level" = 50 USD/tCO2; `p_material` "Material price level" =
  10 USD/tCO2. Each has a source and a rationale.
- **Levels:** `H` = `all(price >= p_high, levy = true)`; `M` = `all(applies = true, price >= p_material)`.
- **Actions:** `steel.h2_dri`, `steel.scrap_eaf`.
- **Conversions:** CNY → USD at 0.139 (2024) and 0.14 (2025).
- **Domain tiers:** `eur-lex.europa.eu` primary, `reuters.com` news.

**Variants of RB**, each signed as version 8 unless a row says otherwise. Every new parameter has a
source and a rationale.

- **RB2:** adds facts `ren` "Renewable LCOE" and `fos` "New-build fossil LCOE" (both `USD/MWh`), a
  computed fact `ratio` "LCOE ratio" = `ratio(ren, fos)`, and parameter `p_parity` "Parity level" = 1
  (no unit). `H` = `ratio <= p_parity`.
- **RB3:** `M` = `any(applies = true, price >= p_material)`.
- **RB4:** `M` = `all(applies = true, any(price >= p_material, levy = true))`.
- **RB5:** `p_high` has a China override of 40 USD/tCO2.
- **RB6:** `p_high` is open, with a question.
- **RB7:** `p_material` is open, with a question.
- **RB8:** RB2 with `H` = `ren <= fos`.
- **RB9:** `applies` replaced by an enum fact `scheme` "Carbon pricing scheme" (allowed `ETS`, `tax`,
  `none`); `M` = `all(scheme in [ETS, tax], price >= p_material)`.
- **RB10:** adds a date fact `start` "Levy start date"; `H` = `all(price >= p_high, levy = true,
  start <= 2026-12-31)`.

**Documents and quotes:**

| Id | Title | Tier | As-of |
|---|---|---|---|
| D1 | "EU ETS Market Report 2026" | primary | 2026-03-31 |
| D2 | "CBAM Regulation 2023/956" | primary | 2023-05-16 |
| D3 | "Steel Policy Tracker" | secondary | 2026-06-30 |
| D4 | "Carbon Weekly" (registered for STL-R1 only in AC-29) | news | 2026-09-01 |
| N1 | "Reuters: carbon price falls" (`https://www.reuters.com/x`) | news | 2026-10-01 |

| Document | Page | Quote |
|---|---|---|
| D1 | 4 | `The carbon price applies to steel producers.` |
| D1 | 12 | `The effective carbon price was USD 72/tCO2.` |
| D1 | 8 | `Renewable LCOE was USD 45/MWh.` |
| D1 | 9 | `New-build fossil LCOE was USD 60/MWh.` |
| D1 | 13 | `The floor price was USD 30/tCO2.` |
| D1 | 14 | `The effective carbon price was USD 45/tCO2.` |
| D1 | 15 | `The effective carbon price was USD 72.005/tCO2.` |
| D1 | 16 | `The effective carbon price fell to USD 9/tCO2.` |
| D1 | 17 | `The effective carbon price was CNY 66.9/tCO2.` |
| D1 | 18 | `The effective carbon price was CNY 71.42/tCO2.` |
| D1 | 19 | `The effective carbon price was KRW 66.9/tCO2.` |
| D1 | 20 | `Steel is covered by the EU ETS.` |
| D3 | 14 | `No carbon pricing scheme covers steel.` |
| D4 | 1 | `The effective carbon price was USD 72/tCO2.` |
| D2 | 3 | `The border levy applies from 1 January 2026.` |
| D3 | 7 | `Estimates range from USD 30/tCO2 to USD 65/tCO2.` |
| D3 | 8 | `The carbon price applies to steel.` |
| D3 | 9 | `The effective carbon price was USD 9/tCO2.` |
| D3 | 10 | `No border levy is in force.` |
| D3 | 11 | `The effective carbon price was USD 40/tCO2.` |
| D3 | 12 | `New-build fossil LCOE was USD 60/MWh.` |
| D3 | 13 | `A border levy is in force.` |

**Users:** `a.analyst` and `b.analyst` (role analyst), `a.approver` and `b.approver` (role approver).

**Stubs:** the fetch stub serves D1–D4 with the quotes table's text on the stated pages. The
extraction stub returns `not_found` for every fact unless a row says a value is extracted. The search
stub returns nothing unless a row says otherwise.

**Defaults**, unless a row says otherwise:

- the region is European Union, and the cell's current rating is the bundled hand rating `H`;
- the run date is 2026-10-20 (the clock in section 3 frozen at that date);
- a D1 value is entered before any D3 value;
- the refresh flag is on, and both second-review sample rates are 0;
- the counted values are `price` = 72 (D1, p. 12), `applies` = Yes (D1, p. 4) and `levy` = Yes (D2, p. 3).

A row that gives only a value keeps the default citation, except `price` = 30, which cites D1 p. 13,
and `price` = 9, which cites D3 p. 9. "Derived" means a derivation run for the cell has finished.
Result fields named in a Then column are read from the latest result in `GET /cells/<code>/<region>`.

Unless a row says a value is extracted, or says otherwise, counted values are analyst facts entered
by `b.approver`, with their documents uploaded and each value's quote taken from the quotes table.
Every uploaded document is sent with its title, as-of date and tier from the documents table (or the
row) and publisher `Fixture`, unless the row says otherwise.

### Engine (phase 2, except AC-9 in phase 3)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | the defaults | the cell is derived | result rating `H`; both `H` conditions `pass`; result confidence `high` | unit |
| AC-2 | `price` = 30 | the cell is derived | result rating `M`; `H` level `fail` | unit |
| AC-3 | `price` = 9, `levy` = No | the cell is derived | result rating `L` | unit |
| AC-4 | `price` has no counted value | the cell is derived | result rating `not_rated`; missing facts `["Effective carbon price"]` | unit |
| AC-5 | `price` = 30, `levy` has no counted value | the cell is derived | result rating `M` | unit |
| AC-6 | `levy` has no counted value | the cell is derived | result rating `not_rated`; missing facts `["Border levy in force"]` | unit |
| AC-7 | the defaults | the cell is derived | the `H` detail is exactly `H: Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes. Effective carbon price = 72 USD/tCO2 (EU ETS Market Report 2026, p. 12): pass. Border levy in force = Yes (CBAM Regulation 2023/956, p. 3): pass.` | unit |
| AC-8 | AC-6's Given | the cell is derived | the `H` detail ends with `Border levy in force not found: unknown.` | unit |
| AC-9 | the fetch stub serves D2 as HTML containing the p. 3 quote; `levy` extracted from it with locator `Art. 36` | the cell is derived | the `levy` value has `page` null and `locator` `Art. 36`; its clause is `Border levy in force = Yes (CBAM Regulation 2023/956, Art. 36): pass.` | unit |
| AC-10 | the defaults | the cell is derived | the result records rule book version 7, its run id, and a snapshot equal to RB's `STL-R1` entry | unit |
| AC-11 | refresh flag off; no source document fetched; the default values entered as analyst facts with D1 and D2 uploaded; the model client raises on any call | the cell is derived | result rating `H` | unit |
| AC-12 | RB3; `price` = 30; `applies` has no counted value | the cell is derived | result rating `M` | unit |
| AC-13 | RB3; `price` = 9; `applies` has no counted value | the cell is derived | result rating `not_rated`; missing facts `["Carbon price applies to steel"]` | unit |
| AC-14 | RB4 | `GET /criteria/STL-R1` | `rating_rubric.M` = `Carbon price applies to steel is Yes and (Effective carbon price >= 10 USD/tCO2 or Border levy in force is Yes)` | unit |
| AC-15 | RB5; region China; `price` = 45 (D1, p. 14) | the cell is derived | result rating `H` | unit |
| AC-143 | AC-15's Given | the cell is derived | the `H` detail starts `H: Effective carbon price >= 40 USD/tCO2 and Border levy in force is Yes. Effective carbon price = 45 USD/tCO2 (EU ETS Market Report 2026, p. 14): pass.` | unit |
| AC-16 | RB5; region European Union; `price` = 45 (D1, p. 14) | the cell is derived | result rating `M` | unit |
| AC-17 | RB5 | `GET /criteria/STL-R1` | `rating_rubric.H` = `Effective carbon price >= 50 USD/tCO2 (China: 40 USD/tCO2) and Border levy in force is Yes` | unit |
| AC-18 | RB6 | the cell is derived; then `GET /cells/STL-R1/European Union` | result rating `not_rated`; `flags` contains `Not re-derived: open threshold High price level` | unit |
| AC-19 | RB7; the defaults | the cell is derived; then `GET /cells/STL-R1/European Union` | result rating `H`; `flags` `[]` | unit |
| AC-20 | RB6 | `GET /criteria/STL-R1` | `rating_rubric.H` = `Effective carbon price >= [open: High price level] and Border levy in force is Yes` | unit |
| AC-21 | RB2; `ren` = 45 (D1, p. 8), `fos` = 60 (D1, p. 9) | the cell is derived | the `ratio` clause is `LCOE ratio = 0.75 from Renewable LCOE = 45 USD/MWh (EU ETS Market Report 2026, p. 8) and New-build fossil LCOE = 60 USD/MWh (EU ETS Market Report 2026, p. 9): pass.` | unit |
| AC-22 | RB2; `ren` = 45; `fos` has no counted value | the cell is derived | result rating `not_rated`; missing facts `["New-build fossil LCOE"]` | unit |
| AC-23 | RB2; `ren` = 45 (D1, p. 8); `fos` = 60 (D3, p. 12) | the cell is derived | the `values[]` entry for `ratio` has `value` 0.75 and `confidence` `medium` | unit |
| AC-24 | RB8; AC-21's values | the cell is derived | the `H` clause is `Renewable LCOE = 45 USD/MWh (EU ETS Market Report 2026, p. 8) vs New-build fossil LCOE = 60 USD/MWh (EU ETS Market Report 2026, p. 9): pass.` | unit |
| AC-25 | RB8 | `GET /criteria/STL-R1` | `rating_rubric.H` = `Renewable LCOE <= New-build fossil LCOE` | unit |
| AC-146 | RB2 with `ratio` = `ratio_pct(ren, fos)` and `p_parity` = 100 (unit `%`); AC-21's values | the cell is derived | the `ratio` clause starts `LCOE ratio = 75% from` | unit |
| AC-149 | RB9 | `GET /criteria/STL-R1` | `rating_rubric.M` = `Carbon pricing scheme in ETS, tax and Effective carbon price >= 10 USD/tCO2` | unit |
| AC-150 | RB9; `scheme` = `ETS` (D1, p. 20); `price` = 30 | the cell is derived | result rating `M` | unit |
| AC-151 | RB9; `scheme` = `none` (D3, p. 14); `price` = 30 | the cell is derived | result rating `L` | unit |
| AC-152 | RB9; `scheme` has no counted value; `price` = 30 | the cell is derived | result rating `not_rated`; missing facts `["Carbon pricing scheme"]` | unit |
| AC-153 | RB10 | `GET /criteria/STL-R1` | `rating_rubric.H` = `Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes and Levy start date <= 2026-12-31` | unit |
| AC-154 | RB10; `start` = 2026-01-01 (D2, p. 3) | the cell is derived | result rating `H` | unit |
| AC-147 | RB2 with `ratio` = `difference(ren, fos)`, `p_parity` = 0 USD/MWh; AC-21's values | the cell is derived | the `ratio` clause starts `LCOE ratio = -15 USD/MWh from` | unit |

### Fact checks and conversions (phase 3, except AC-35 in phase 2)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-26 | the extracted `price` quote has no exact, normalised or fuzzy (≥ 0.92) match in any passage the model was shown | the cell is derived | `price` is not counted, with reason `Quote not found in source` | unit |
| AC-27 | AC-26's Given | the cell is derived | result rating `not_rated` | unit |
| AC-28 | `price` extracted as 72 with quote `The carbon price applies to steel producers.` (D1, p. 4), which matches a passage | the cell is derived | `price` is not counted, with reason `Number not in quote` | unit |
| AC-29 | D4 registered for STL-R1; the extraction stub returns `price` 72 from D4, p. 1, with its quote | the cell is derived | that value is not counted, with reason `News cannot ground a fact` | unit |
| AC-30 | `price` extracted as 66.9 CNY/tCO2 from D1, p. 17, with no as-of date of its own (D1 is 2026-03-31; there is no 2026 rate, so 2025's applies) | the cell is derived | the `price` clause shows `9.37 USD/tCO2 (66.9 CNY/tCO2)`; result rating `L` | unit |
| AC-31 | `price` extracted as 71.42 CNY/tCO2 from D1, p. 18, with no as-of date of its own | the cell is derived | the `price` clause in `M` shows `10 USD/tCO2 (71.42 CNY/tCO2)` with outcome `fail`; result rating `L` | unit |
| AC-32 | `price` extracted as 66.9 CNY/tCO2 from D1, p. 17, with its own as-of date 2024-06-30 | the cell is derived | the `price` clause shows `9.3 USD/tCO2 (66.9 CNY/tCO2)` | unit |
| AC-33 | `price` extracted as 66.9 CNY/tCO2 from D1, p. 17, with its own as-of date 2023-06-30 | the cell is derived | `price` is not counted, with reason `No CNY to USD rate for 2023 or earlier` | unit |
| AC-34 | `price` extracted as 66.9 KRW/tCO2 from D1, p. 19 | the cell is derived | `price` is not counted, with reason `Unit not convertible: KRW/tCO2` | unit |
| AC-148 | `price` extracted as 72 from D1 with the p. 12 quote, but reported as page 5 | the cell is derived | the `price` value has `page` 12 | unit |
| AC-35 | `price` = 72.005 (D1, p. 15) | the cell is derived | the `price` clause shows `72.01 USD/tCO2` | unit |

### Several values and confidence (phase 2)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-36 | `price` counted as 72 (D1, p. 12) and 30 (D3, p. 7) | the cell is derived | result rating `conflict`; no proposed rating | unit |
| AC-37 | AC-36's Given | the cell is derived | one review item of kind `conflict` listing, in this order, `72 USD/tCO2, EU ETS Market Report 2026` and `30 USD/tCO2, Steel Policy Tracker` | unit |
| AC-38 | `price` counted as 72 (D1, p. 12) and 65 (D3, p. 7) | the cell is derived | result rating `H`; the `price` clause is `Effective carbon price = 72 USD/tCO2 (EU ETS Market Report 2026, p. 12), 65 USD/tCO2 (Steel Policy Tracker, p. 7): pass.` | unit |
| AC-39 | AC-38's Given | the cell is derived | result confidence `medium` | unit |
| AC-40 | `levy` = No; `price` counted as 72 (D1, p. 12) and 30 (D3, p. 7) | the cell is derived | result rating `M`; the `price` clause in `H` is `Effective carbon price = 72 USD/tCO2 (EU ETS Market Report 2026, p. 12), 30 USD/tCO2 (Steel Policy Tracker, p. 7): mixed.` | unit |
| AC-41 | `levy` has no counted value; `price` counted as 72 (D1) and 30 (D3) | the cell is derived | result rating `not_rated`; missing facts `["Border levy in force"]` | unit |
| AC-42 | `levy` = Yes from D3, p. 13, instead of D2 | the cell is derived | result confidence `medium` | unit |
| AC-43 | D1's as-of date is 2025-09-01 (414 days before the run) | the cell is derived | `price` confidence `medium` | unit |
| AC-44 | D1's as-of date is 2025-10-20 (365 days before the run) | the cell is derived | `price` confidence `high` | unit |
| AC-45 | `applies` entered by `a.analyst` citing D1, without a document | the cell is derived | result rating `H`; result confidence `low`; `applies` marked `not machine-checked` | unit |

### Analyst facts and choices (phase 2)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-46 | as `a.analyst` | `POST /cells/STL-R1/European Union/facts`: `price` 72 USD/tCO2, citing D1, page 12, no document, quote `about USD 70` | HTTP 422 `Number not in quote.` | unit |
| AC-47 | as `a.analyst` | `POST .../facts`: `price` 72, quote `USD 72/tCO2`, page 12, an uploaded PDF "Extra report" (tier primary, as-of 2026-05-01) that doesn't contain the quote | HTTP 422 `Quote not found in the uploaded document.` | unit |
| AC-48 | as `a.analyst` | `POST .../facts`: `price` 72, quote `USD 72/tCO2`, page 12, an uploaded document "Carbon Weekly", publisher `Fixture`, as-of 2026-09-01, tier `news` | HTTP 422 `News cannot ground a fact.` | unit |
| AC-49 | as `a.analyst` | `POST .../facts`: `price` 72, quote `The effective carbon price was USD 72/tCO2.`, page 12, D1 uploaded (tier primary, as-of 2026-03-31); then the cell is derived | `price` counted with confidence `high` | unit |
| AC-145 | as `a.analyst` | `POST .../facts`: `price` 72, quote `about USD 70`, page 12, D1 uploaded with no publisher and tier `news` | HTTP 422 `An uploaded document needs a title, publisher, as-of date and tier.` | unit |
| AC-50 | AC-36's conflict, as `a.analyst` | `POST /cells/STL-R1/European Union/choices` choosing D1's value with an empty reason | HTTP 422 `A reason is required.` | unit |
| AC-51 | AC-36's conflict | `a.analyst` chooses D1's value with reason `newer data` | the cell is re-derived with rating `H`; its `price` clause cites only EU ETS Market Report 2026 | unit |
| AC-52 | AC-51 | `GET /cells/STL-R1/European Union` | the history has an entry with `a.analyst`, `72 USD/tCO2, EU ETS Market Report 2026` and `newer data` | unit |
| AC-53 | AC-51 | the cell is derived again with the same values | result rating `H` | unit |
| AC-139 | AC-51, then a new `price` value 40 (D3, p. 11) is counted | the cell is derived | result rating `conflict` | unit |

### Review and ratification (phase 2)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-54 | `price` = 30 | `POST /derive` for the cell; the run finishes; `GET /scores?sector=Steel&region=European Union` | STL-R1 shows rating `H`, `basis` `hand_rated` | unit |
| AC-55 | AC-54 | the run's review items are listed | exactly one item, kind `changed`, current `H`, proposed `M` | unit |
| AC-56 | AC-55's item | `a.analyst` approves it | `GET /scores` still shows STL-R1 European Union `H` | unit |
| AC-57 | AC-56 | `a.approver` approves it as second reviewer | `GET /scores` shows rating `M`, `basis` `derived`, `ratified_by` `a.approver`, `last_verified` = the date of `a.approver`'s decision | unit |
| AC-58 | AC-57 | `GET /scores` | STL-R1 European Union `confidence` `high`; `source` `EU ETS Market Report 2026; CBAM Regulation 2023/956` | unit |
| AC-59 | AC-57 | `GET /scores` | STL-R1 European Union `evidence` is exactly `H: Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes. Effective carbon price = 30 USD/tCO2 (EU ETS Market Report 2026, p. 13): fail. Border levy in force = Yes (CBAM Regulation 2023/956, p. 3): pass. M: Carbon price applies to steel is Yes and Effective carbon price >= 10 USD/tCO2. Carbon price applies to steel = Yes (EU ETS Market Report 2026, p. 4): pass. Effective carbon price = 30 USD/tCO2 (EU ETS Market Report 2026, p. 13): pass.` | unit |
| AC-60 | AC-56 | `a.analyst` approves it as second reviewer | HTTP 409 `second review must be a different person` | unit |
| AC-61 | AC-56 | `b.analyst` approves it as second reviewer | HTTP 403 `a rating change is confirmed by an approver` | unit |
| AC-62 | AC-56 | `b.analyst` rejects it as second reviewer | HTTP 403 `a rating change is confirmed by an approver` | unit |
| AC-63 | AC-55's item | `a.approver` rejects it | `GET /scores` shows STL-R1 European Union `H`, `basis` `hand_rated` | unit |
| AC-64 | a `changed` item whose result uses a fact `a.approver` entered | `a.approver` decides it | HTTP 409 `you entered a fact this result uses` | unit |
| AC-65 | refresh flag off; `b.analyst` entered the default values for European Union, and for United States and China `price` 9 (D3, p. 9), `applies` Yes (D3, p. 8), `levy` No (D3, p. 10); one `POST /derive` with the three cells; all three items are `unchanged` | `a.analyst` bulk-accepts the three items | each cell shows `basis` `derived` and `ratified_by` `a.analyst` | unit |
| AC-66 | one `POST /derive` for European Union with `price` 30 (`changed`) and United States with `price` 9, `applies` Yes, `levy` No (`unchanged`) | `a.analyst` bulk-accepts both items | the `changed` item is refused with reason `a rating change is not bulk-accepted`; STL-R1 European Union still shows `H`; STL-R1 United States shows `basis` `derived`, `ratified_by` `a.analyst` | unit |
| AC-67 | AC-65's Given | `b.analyst` bulk-accepts the three items | each item is refused with reason `you entered a fact this result uses` | unit |
| AC-68 | AC-57, then `b.approver` enters `price` 9 citing D1, p. 16, uploading D1 again, which replaces the earlier D1 value; the cell is derived and ratified (`a.analyst` approves, `a.approver` confirms) | `GET /cells/STL-R1/European Union` | the history's ratings are, in order: `H` hand-rated 2026-08-14, `M` ratified by `a.approver`, `L` ratified by `a.approver` | unit |
| AC-69 | AC-4's result | `GET /cells/STL-R1/European Union` | the cell's current rating (not the latest result's) is `H`; `flags` contains `Not re-derived: missing Effective carbon price` | unit |
| AC-70 | AC-69 | `a.analyst` dismisses the item (decision `reject`); then `GET /cells/STL-R1/European Union` | the cell's current rating is `H`; `flags` still contains `Not re-derived: missing Effective carbon price` | unit |
| AC-140 | AC-69, then the cell is derived with the defaults and its item not yet decided | `GET /cells/STL-R1/European Union` | `flags` `[]` | unit |
| AC-71 | each of AC-49, AC-51, AC-57, AC-63 and AC-65, run separately from a fresh copy of F | the action finishes | every file in that copy is byte-identical to before | unit |
| AC-72 | AC-57, then RB with `p_high` = 60 signed as version 8 and the app restarted | `GET /cells/STL-R1/European Union` | `flags` contains `Rules changed since this rating (v7)` | unit |
| AC-73 | AC-72 | `GET /cells/STL-R1/European Union` | the current result's `H` detail starts `H: Effective carbon price >= 50 USD/tCO2` | unit |
| AC-141 | AC-72, then the cell is derived and its item not yet decided | `GET /cells/STL-R1/European Union` | `flags` still contains `Rules changed since this rating (v7)` | unit |

### Rule book validation, rendering and consumers (phase 1, except AC-96 and AC-97 in phase 2)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-74 | the bundled data directory | `arp transition-barrier rules validate` | exit 0; prints `Rule book v<version in rule_book.json>: OK, 35 criteria, <number of open parameters> open thresholds` | unit |
| AC-75 | F | `rules validate --data-dir F` | exit 0; prints `Rule book v7: OK, 1 criteria, 0 open thresholds` | unit |
| AC-76 | F with RB6 | `rules validate --data-dir F` | exit 0; prints `Rule book v8: OK, 1 criteria, 1 open thresholds` | unit |
| AC-77 | F with `H` naming fact `prices` | `rules validate --data-dir F` | exit 1; output contains `STL-R1: condition names unknown fact 'prices'` | unit |
| AC-78 | F with `p_high` lacking `source` | `rules validate --data-dir F` | exit 1; output contains `STL-R1: parameter 'p_high' has no source` | unit |
| AC-79 | F with a China override of `p_high` lacking `source` | `rules validate --data-dir F` | exit 1; output contains `STL-R1: parameter 'p_high' override for China has no source` | unit |
| AC-80 | F with an empty `rationale` | `rules validate --data-dir F` | exit 1; output contains `STL-R1: no rationale` | unit |
| AC-81 | F with `price` lacking `definition` | `rules validate --data-dir F` | exit 1; output contains `STL-R1: fact 'price' has no definition` | unit |
| AC-82 | F with no `M` level | `rules validate --data-dir F` | exit 1; output contains `STL-R1: no M level` | unit |
| AC-83 | F with `p_high` in `EUR/tCO2` | `rules validate --data-dir F` | exit 1; output contains `STL-R1: 'price' (USD/tCO2) compared with 'p_high' (EUR/tCO2)` | unit |
| AC-84 | F with the `H` condition `price >= 50` written inline | `rules validate --data-dir F` | exit 1; output contains `STL-R1: condition on 'price' uses an inline number; use a parameter` | unit |
| AC-85 | F with `STL-R1` actions including `steel.foo` | `rules validate --data-dir F` | exit 1; output contains `STL-R1: unknown action 'steel.foo'` | unit |
| AC-86 | F with RB2 where `fos` is in `USD/kWh` | `rules validate --data-dir F` | exit 1; output contains `STL-R1: computed fact 'ratio' input 'fos' is in USD/kWh, expected USD/MWh` | unit |
| AC-142 | F with `M` = `all(applies = true, any(price >= p_material, all(levy = true)))` | `rules validate --data-dir F` | exit 1; output contains `STL-R1: conditions nested deeper than two levels` | unit |
| AC-87 | F with `STL-T1` added to the criteria schema only | `rules validate --data-dir F` | exit 1; output contains `Missing rule book entry: STL-T1` | unit |
| AC-88 | F with a rule book entry `XXX-T9` that has no criterion | `rules validate --data-dir F` | exit 1; output contains `Rule book entry without criterion: XXX-T9` | unit |
| AC-89 | F with `tier` removed from `steel_policy_tracker` in `criteria_schema.json` | `rules validate --data-dir F` | exit 1; output contains `Source 'steel_policy_tracker' has no tier` | unit |
| AC-90 | F with `p_high` changed to 60 and not signed | `rules validate --data-dir F` | exit 1; output contains `Rule book content changed but version is still 7` | unit |
| AC-91 | F | `rules sign --approved-by owner --data-dir F` | `version` 8; the last `history` entry has `version` 8, `approved_by` `owner`, and a `fingerprint` equal to the SHA-256 defined in section 1 | unit |
| AC-92 | AC-77's directory | the API starts | startup fails with an error containing `STL-R1: condition names unknown fact 'prices'` | unit |
| AC-93 | F | `GET /criteria/STL-R1` | `rating_rubric` = `{"H": "Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes", "M": "Carbon price applies to steel is Yes and Effective carbon price >= 10 USD/tCO2", "L": "Otherwise (neither H nor M holds)"}` | unit |
| AC-94 | F | `GET /criteria/STL-R1` | `rule_book_version` 7; `actions` `["steel.h2_dri", "steel.scrap_eaf"]`; `params` includes `p_high` with value 50, its source and its rationale | unit |
| AC-95 | the bundled data directory | `rules render --out X` | X equals the committed `docs/transition_barrier/RULE_BOOK.md` | unit |
| AC-96 | AC-57 | `arp transition-barrier export --out X`, then the Word report script with X | the script exits 0; the report's STL-R1 European Union rating is `M` | unit |
| AC-97 | Decision Studio loaded its transition-barrier source before AC-57's approval, in the same process | after AC-57 it loads the source again | the STL-R1 European Union row has rating `M` | unit |

### Sources and search (phase 4, except AC-115 in phase 2 and AC-116 in phase 3)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-98 | the search stub returns `https://eur-lex.europa.eu/eli/reg/2026/123/oj` (U) for STL-R1 China; U is not registered | `arp transition-barrier search --code STL-R1 --region China` | the search run's review items include exactly one `new_source` item, with U, `STL-R1`, `China` and tier `primary` | unit |
| AC-99 | the search stub returns `https://example-institute.org/report.pdf` | the search runs for STL-R1 China | one `new_source` item with tier `unclassified` | unit |
| AC-100 | AC-98's item | `a.analyst` approves it | HTTP 403 `a new source is approved by an approver` | unit |
| AC-101 | AC-99's item | `a.approver` approves it without choosing a tier | HTTP 422 `choose a tier` | unit |
| AC-102 | AC-98's item | `a.approver` approves it | `GET /sources` lists U for `STL-R1`, region `China`, tier `primary` | unit |
| AC-103 | AC-98's item still pending | STL-R1 China is derived | no request is made to U | unit |
| AC-104 | AC-102 | STL-R1 China is derived | a request is made to U | unit |
| AC-105 | AC-98's item rejected | the search runs again and returns U | no new review item | unit |
| AC-106 | the search stub returns N1 for STL-R1 European Union; the change-check stub answers yes | the search runs | the cell's `flags` contains `Possible change: Reuters: carbon price falls` | unit |
| AC-107 | AC-106 | the search run's review items are listed | exactly one `possible_change` item, with N1's title, URL and date 2026-10-01 | unit |
| AC-108 | AC-106 | the runs are listed | exactly one derivation run for STL-R1 European Union created after the search run started | unit |
| AC-109 | AC-107's item | `a.analyst` rejects it | the cell's `flags` is `[]` | unit |
| AC-110 | AC-106's Given with the change-check stub answering no | the search runs | the cell's `flags` is `[]` | unit |
| AC-111 | the search stub returns `https://climate.ec.europa.eu/eu-ets-market-report-2027.pdf` titled "EU ETS Market Report 2027" | `arp transition-barrier search --code STL-R1 --region European Union` | exactly one `new_source` item with that URL, `replaces` `eu_ets_report` and tier `primary` | unit |
| AC-112 | AC-111's item | `a.approver` approves it | `GET /sources` lists the 2027 edition for `STL-R1` with no region, and no longer lists D1 | unit |
| AC-113 | the search stub returns `http://169.254.169.254/latest` | the search runs | no request is made to that URL; no review item is created | unit |
| AC-114 | the refresh flag is off | `POST /search` for the cell | HTTP 409; no request to any source or search provider | unit |
| AC-115 | the refresh flag is off; no source document fetched; the default values entered as analyst facts | `POST /derive` for the cell; the run finishes | result rating `H`; the result notes `Sources not fetched: refresh is disabled`; no request to any source or search provider | unit |
| AC-116 | the companies table has N rows | D1 is fetched and stored for STL-R1 | the companies table still has N rows | unit |
| AC-117 | the bundled data directory; refresh flag on; `search-tick --now T` started a run that finished at T | `search-tick --now` T + 31 days | one new `transition_barrier_search` run, covering 105 cells | unit |
| AC-118 | the same | `search-tick --now` T + 30 days | one new search run | unit |
| AC-119 | the same | `search-tick --now` T + 29 days | no new search run | unit |
| AC-120 | the bundled data directory; refresh flag on; no scheduled `transition_barrier_search` run has ever run | `search-tick` | one new search run | unit |
| AC-144 | AC-117's Given, plus `search --code STL-R1 --region China --now` T + 30 days | `search-tick --now` T + 31 days | one new `transition_barrier_search` run, covering 105 cells | unit |
| AC-121 | AC-117's Given with the refresh flag off | `search-tick --now` T + 31 days | no new search run; no request to any source or search provider | unit |

### Extraction quality (phase 3)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-122 | a cases file with 4 cases (section 8 format); the extraction stub returns a counted value for each, 3 of them correct | `arp transition-barrier golden --cases <them> --documents-dir <dir> --min-precision 0.95 --min-coverage 0.5` | prints `precision 0.75, coverage 1`; exits 1 | unit |
| AC-123 | golden set G (section 8): at least 40 facts from at least 12 documents, labels checked by the owner | `arp transition-barrier golden --cases G --documents-dir <dir> --min-precision 0.95 --min-coverage 0.5` | exits 0 | golden |

### In the running app (phase 2)

The app runs with `ARP_TRANSITION_BARRIER_DATA_DIR` = F, the refresh flag off and both second-review
sample rates at 0. D1–D3 are PDF files in F containing the quotes above, which the evaluator uploads
through the analyst form.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-124 | none | open Transition Barriers, then the STL-R1 criterion | shows the rationale, the two actions, each fact with its definition, the H, M and L sentences of AC-93, and `p_high` and `p_material` each with value, source and rationale, plus "rule book v7" | evaluator |
| AC-125 | `a.analyst` has entered `price` 30 (D1, p. 13), `applies` Yes (D1, p. 4) and `levy` Yes (D2, p. 3) through the form and started a derivation | open the review screen | the STL-R1 European Union item is listed with current `H` and proposed `M` | evaluator |
| AC-126 | AC-125 | `b.analyst` approves the item in the review screen, then `a.approver` confirms it there | the cell detail shows rating `M` and "ratified by a.approver" with the date | evaluator |
| AC-127 | AC-126 | open the cell detail | H shows `Effective carbon price >= 50 USD/tCO2` fail and `Border levy in force is Yes` pass; M shows `Carbon price applies to steel is Yes` pass and `Effective carbon price >= 10 USD/tCO2` pass; each figure shows its quote, document title and page, and its link opens that PDF | evaluator |
| AC-128 | AC-125 | `b.analyst` rejects the item in the review screen | the cell detail shows rating `H`, hand-rated 2026-08-14 | evaluator |
| AC-129 | `a.analyst` entered the default values for European Union and, for United States and China, `price` 9 (D3, p. 9), `applies` Yes (D3, p. 8), `levy` No (D3, p. 10), then derived the three cells in one run | `b.analyst` bulk-accepts the three items in the review screen | each cell's detail shows "ratified by b.analyst" | evaluator |

### Must not change (every phase from 1; the `basis`, `ratified_by` and `flags` checks in AC-130 and AC-131 from phase 2; AC-137 from phase 3; AC-138 from phase 4)

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-130 | the bundled data directory; a cell never re-derived | `GET /scores` | rating, confidence, evidence, source and `last_verified` equal the bundled values; `basis` `hand_rated`, `ratified_by` null, `flags` `[]` | unit |
| AC-131 | AC-130's Given | `GET /matrix` | every field present before this change has the same value; the cell has `basis` `hand_rated`, `ratified_by` null, `flags` `[]` | unit |
| AC-132 | a fixture directory with the pre-change `criteria_schema.json` (with only a `tier` added to each source) and `source_registry.json`, plus a signed rule book for its 35 criteria | `GET /refresh/coverage` | equals the response `main` gives for the pre-change files | unit |
| AC-133 | the refresh flag is off | `POST /refresh/runs` | HTTP 409, as before this change | unit |
| AC-134 | an extraction run item whose approval needs a second review (`published_change`), approved by `a.analyst` | `b.analyst` submits the second review | accepted, as before this change | unit |
| AC-135 | the bundled data directory; no derivation has run | `arp transition-barrier export --out X`, then the Word report script with X | the script exits 0; the report's 105 ratings equal `assessment_scores.json` | unit |
| AC-136 | AC-135's Given | Decision Studio loads its transition-barrier source | its 105 ratings equal `assessment_scores.json` | unit |
| AC-137 | AC-116, run from a fresh copy of F | the fetch finishes | every file in that copy is byte-identical to before | unit |
| AC-138 | each of AC-102 and AC-106, run separately from a fresh copy of F | the action finishes | every file in that copy is byte-identical to before | unit |
| AC-155 | the bundled data directory | `GET /criteria/STL-R1` | every field `main` returns, except `rating_rubric`, has the same value as on `main` | unit |

Must not change: the criteria API's existing fields (AC-155), cells never re-derived (AC-130, AC-131,
AC-135, AC-136), the bundled data files at
run time (AC-71, AC-137, AC-138), the refresh coverage report (AC-132), the existing refresh's 409 (AC-133), and second
review for other run types (AC-134).
