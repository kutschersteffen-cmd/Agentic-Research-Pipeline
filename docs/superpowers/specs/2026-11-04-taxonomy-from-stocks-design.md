# Reverse-engineering a stock set: index rules and taxonomy (layers 1 and 2)

Spec slug: `taxonomy-from-stocks`. Status: draft for owner approval. Date: 2026-11-04.
Flow chart: https://claude.ai/artifact/Tkfn4D19rhRXHfApew9NwV. Findings that led here:
`docs/golden_drafts/taxonomy_methods_etf_empirical_review.md`.

## Intent

The owner has a set of stocks: a thematic ETF's holdings, an index, or any universe, sometimes with the fund's
methodology documents. The goal is to reverse-engineer the key idea behind the set and turn it into reusable
artifacts:

- **Layer 1, index rules:** what the documents state about eligibility, selection, weighting, caps and
  rebalancing, as a draft `ConstructionSpec` (`arp/schemas/index.py:517`) with a quote per rule.
- **Layer 2, taxonomy:** the theme the stocks have in common, broken into activities with tiers and a
  three-bucket keyword dictionary, with an extraction schema that follows from it.

Layer 3 (baseline filters, purity score, weighting, replication against the real fund) is a later spec. These two
layers produce its inputs.

This replaces the `etf_index_holdings` and `empirical` taxonomy methods with **one method for both cases**. The
review showed the first reads names only and guesses from model memory; the second needs the theme as input,
crashes on one bad model reply and checks itself with the same model.

## Where it sits

```
stocks (+ methodology docs, segment revenue, stored data)
  └─ arp taxonomy infer start ──► profiles, topic clusters, ranked common themes, index rules   [stops]
       owner picks a theme
  └─ arp taxonomy infer pick ───► draft taxonomy (activities, tiers, keywords, KPIs), mapping, coverage
       owner reviews and ratifies (existing `arp taxonomy ratify`)
  └─ existing: build_taxonomy_schema ──► extraction schema ──► arp theme run
```

## Goals

1. One command pair goes from a set of stocks to a saved **draft** taxonomy, stopping once for the owner to pick
   the theme.
2. Every activity, keyword (all three buckets) and stock-to-activity mapping traces to a quote from a filing or a
   methodology document.
3. Shares, weights, coverage and selection are computed in code, never by the model.
4. One failing stock (bad model reply, no description, no document) never ends the run.
5. Stated index rules come back as a valid draft `ConstructionSpec`, each rule with its quote; rules that do not
   fit it are kept as quoted text.

## Non-goals

- Layer 3: baseline filters, purity score, weighting, replication check.
- Observed rules: holdings history, rebalance churn, weight regression (owner: stated rules only).
- Market data, patents, return co-movement, trained contrastive models, company-level supplier graphs.
- Automatic fetching of fund documents; the user passes files or URLs.
- UI and API endpoints for the new command. (The retired methods are removed from the existing UI, see below.)
- Changing the stage-evidence fields planned in `2026-11-03-stage-evidence-schema-design.md` (on `main`).

## Anti-goals

- A theme, activity, keyword or mapping that rests on model memory instead of a quote (the Cummins case).
- A result that changes when the input rows are reordered.
- The inference step creating or changing company rows. (Document discovery may register companies, as every
  discovery run does today; owner decision.)

## Owner decisions

One method for both cases · methodology and stocks merged as equals · output is ranked themes with supporting
stocks · read the top 30 by weight · schema gets share fields plus theme KPIs · layers 1 and 2 first · stocks
without a filing go through document discovery first, and discovery may register companies · the inference step's
database matching is read-only and keeps ISIN/SEDOL · layer 1 is stated rules only · golden checks are tuned on the
tune split only, scored on holdout by hand, not merge-blocking; prompts are never tuned on holdout runs.

## Design

### Commands and stages

```
arp taxonomy infer start --stocks <file> [--methodology <file|url> ...] [--segments <catalogue.csv>]
                         [--benchmark <universe csv|json>] [--name <set name>]
arp taxonomy infer pick <run_id> --theme <rank>
arp taxonomy infer show <run_id> [--json]
```

The run lives in `RunStore` with stages, like the authority agent's `run.py`:
`started → profiled → themes_ready` (start stops here) `→ drafted` (pick), or `failed`.
`start` prints `Run <run_id>` as its first stdout line, on success and on failure. `pick --theme <rank>` with a
rank not in `themes` exits 1 with `Run <run_id> has no theme <rank>.` A command at the wrong stage exits 1 with `Run <run_id> is at stage '<stage>'; '<command>' needs '<needed>'.`

`infer show --json` prints the run record with exactly the keys in this table, no others:

| Key | Content |
|---|---|
| `run_id`, `stage`, `name` | |
| `extractor_model`, `verifier_model` | model ids used for the description field |
| `selection` | `{method: weighted\|sample, cutoff_reason: cap_30\|weight_80\|sample\|all, total_weight}` |
| `profiles[]` | `{company_id, name, weight, isin, sedol, db_match, codes, exiobase, facts, segments, description, citation {doc_id, page, quote}, error}` |
| `clusters[]` | `{cluster_id, terms[10], members[], weight_share}` |
| `themes[]` | `{rank, name, description, supporting[], count_share, weight_share, cluster_ids[], stated_in_methodology, methodology_quote}` |
| `outliers[]` | `company_id`s |
| `index_rules` | `{currency, construction_spec, rules[{text, quote, source, mapped_to}]}` |
| `taxonomy_id`, `activities[]` | `activities[]`: `{activity_id, name, origin: stocks\|methodology\|both}` (origin lives here, not on the taxonomy) |
| `mapping[]` | `{company_id, activity_id, reason, quote, tier}` |
| `coverage` | `{profiled_weight_share, fund_weight_share, unmapped[]}` |

Numbers in the run JSON are JSON numbers rounded to 4 decimals. Every list is sorted: `profiles` in selection
order; `themes` by `rank`; `clusters` by `cluster_id`; `activities` by `activity_id`; `mapping` and every list of
company ids (`supporting`, `members`, `outliers`, `coverage.unmapped`) by `company_id`; `rules` in document order.

### Inputs

**Stocks.** `.json`, or a CSV with a `company_id` column → `load_company_universe` (unweighted; `CompanyRef` has no
weight field and none is added). Any other CSV → the holdings loader, the only weighted path. Fixes to the
holdings loader (`etf_holdings.py:53`, shared with `universe from-holdings` and `universe overlap`):
- Header row: the first row containing a name or ticker column from the existing variant lists; lines above it are
  skipped.
- Rows with fewer cells than the header are skipped.
- Non-security rows are dropped: empty ticker **and** a name containing `CASH`, `CURRENCY`, `POUND`, `EURO`,
  `DOLLAR`, `YEN`, `FRANC`, `PAYABLE`, `RECEIVABLE`, `FUTURE` or `SWAP` (case-insensitive). Rows with a ticker are kept.
- Weights are scaled per column, not per cell: if the header contains `%`, any cell contains `%`, or any value is
  above 1, the whole column is divided by 100. (Today a 0.65 % holding is read as 65 %; HYDR's weights sum to 2.70.)
  A column of plain fractions with no `%` parses as today.
- `ISIN`, `SEDOL`, `LEI` and `CIK` columns are kept on the row when present.
- The weight column is found with the existing variants (`% of Net Assets` is already one, `etf_holdings.py:19`).
- A holdings row's `company_id` is its ticker as written, trimmed; the name when the ticker is empty.

**Methodology documents** (optional, repeatable): file paths or URLs, fetched with the authority agent's fetch.

**Segment revenue** (optional): the existing revenue-catalogue CSV (`revenue_exposure/catalogue.py:11`).

**Benchmark** (optional): a universe used only as contrast for the topic clusters.

`--name` defaults to the stocks file's stem.

### Step 1: select

- Weighted (holdings CSV): sort by weight descending, ties by `company_id` ascending. Take stocks until 30 are
  taken (`cap_30`) or the running total first reaches at least 80 % of `total_weight` (`weight_80`), including the
  stock that crosses 80 %. `total_weight` is the sum of security weights after non-security rows are dropped.
- Unweighted: sort by `company_id`, then `random.Random(0).sample(..., 30)` if more than 30 (`sample`), else all
  (`all`).

### Step 2: profile each selected stock

Per stock, `profile_stock(...)` (the seam tests fake: it receives the extract function as a parameter defaulting
to `_extract_company`):

- **Database match, read-only:** `lookup(session, scheme, value)` (`db/companies.py:50`) for the row's ISIN, then
  LEI, then CIK, where present; if none matches, a case-insensitive exact match on `companies.name` that returns exactly one company.
  Nothing is written. SEDOL is kept on the profile but not matched on (no SEDOL id scheme). Unmatched →
  `db_match: "none"`.
- **Stored data, no model call:** `codes`: ISIC/NACE/GICS from the input row, plus `isic_code` and `sector` of the
  matched company (the `companies` table has no NACE/GICS columns). `exiobase` via `nace_sectors()`. `facts`: the
  latest value per `field_id` from `company_view.facts()` (newest `period_end` wins).
- **Segments:** rows for this company from `--segments`, with shares computed as in `catalogue.total_value`.
- **Documents:** stocks with no document from local files, EDGAR or ESEF go through `run_discovery`
  (`discovery/pipeline.py:231`) first, all such stocks in one discovery run; then the registry is read again.
  Discovery may register these companies (owner decision); the read-only rule covers the lookups above.
- **Description:** one theme-neutral extraction field ("the company's main business segments, products and
  services, as the company states them", generic seed keywords), with
  `verifier_llm=build_verifier_llm_client(settings)`. All stocks run concurrently, sharing one `field_limit`
  semaphore of `settings.max_concurrent_llm_calls`. After the extract function returns, `profile_stock` itself
  checks the returned quote against the stock's documents with `arp/grounding.py`; only a grounded quote is kept
  as `citation`.
- **Outcomes**, recorded in `error` (absent on success):
  - extract function raises → `"<ExceptionType>: <message>"`;
  - extraction returns no value → `"not_found"`;
  - value returned but its quote is not grounded → `"ungrounded_quote"`; neither `description` nor `citation` is kept;
  - no document after discovery → `"no_document"`.
  Only stocks with a `description` count as **described**; every share below divides by described stocks.
- If no stock is described, the run goes to `failed` and exits 1 with
  `No stock could be profiled: <n> failed, <m> had no document.` (`<m>` counts `no_document`, `<n>` all other errors.)

### Step 3: topic clusters (BERTopic-style)

- Points: per described stock, the 8 chunks of its documents that best match the description query (existing
  retrieval), embedded with `embed_texts` (`retrieval/embeddings.py:24`).
- With `--benchmark`: up to 200 benchmark stocks (seeded sample), chunks from documents already available (no
  discovery, no model call), embedded the same way.
- UMAP (`random_state=0`, `n_neighbors = max(2, min(15, points - 1))`) + HDBSCAN (`min_cluster_size = 3`), as in
  `emerging_themes/clustering.py` (needs the `emerging_themes` extra).
  Each cluster gets its top 10 c-TF-IDF terms, computed in code; with a benchmark, the term weights are computed
  against the benchmark's chunks as the background class. Benchmark points never form or join a cluster's
  `members`.
- `members` are the described stocks with at least one chunk in the cluster; `weight_share` = their weight /
  described weight.
- Clustering sits behind one function, `cluster_points(embeddings) -> labels` (the seam tests fake).
- If HDBSCAN labels every point as noise, `clusters` is `[]` and the theme step runs on the profiles alone.

### Step 4: common themes

One structured model call gets the clusters (terms, three sample chunks each), the profiles and, when given, the
methodology's stated theme from layer 1. It returns 2-5 themes: name, description, supporting `company_id`s with
one reason each, cluster ids, and `stated_in_methodology` with a quote. Code then:
- drops supporting ids that are not described stocks, and methodology quotes that fail grounding
  (`arp/grounding.py`); a dropped quote sets `stated_in_methodology` to `false`;
- drops a theme left with no supporting stock;
- computes `count_share` (supporting / described) and `weight_share` (supporting weight / described weight; `null`
  when unweighted), ignoring any share the model returns;
- ranks by `weight_share` (by `count_share` when unweighted), ties by name ascending; `rank` starts at 1;
- if no theme is left, the run goes to `failed` and `start` exits 1 with `No common theme is supported by the
  profiled stocks.`;
- lists `outliers`: described stocks in no theme.

`start` prints the ranked table and stops at `themes_ready`.

### Layer 1: stated index rules (inside `start`, when methodology documents are given)

- `extract_source` (`authority_taxonomy/extract.py:138`) gets a `checklist` parameter (default: today's
  `AUTHORITY_CHECKLIST` and its draft models, so the authority agent's behaviour and tests stay unchanged).
  `theme_name` is `--name`.
- It runs once with the default checklist (stated theme, boundaries, thresholds, definitions) and once with
  `INDEX_RULES_CHECKLIST` (`eligibility`, `selection`, `weighting`, `caps`, `rebalance`): one call per item, every
  element quoted, ungrounded quotes dropped.
- Each extracted rule is mapped in code where its text has a recognised form; numbers are parsed from the
  grounded quote, not taken from the model:
  - minimum (free-float) market capitalisation → `MetricThresholdScreen` on `float_mcap`;
  - minimum average daily traded value → `MetricThresholdScreen` on `adv_3m`;
  - a numeric minimum revenue or exposure share → `MetricThresholdScreen` on `relevance` (only with a stated
    number);
  - sector exclusions → `CategoryScreen` on `sector`;
  - a fixed constituent count → `TopN`;
  - market-cap / equal weighting → `BaseWeighting.scheme`;
  - single-stock cap → `ConstraintSet.single_name_cap`; a 5/10/40 rule → `ucits_5_10_40`;
  - review frequency → `CalendarSpec.review_frequency`;
  - the currency of the first monetary threshold → `index_currency` and `index_rules.currency`.
- `rules[]` lists every rule with `text`, `quote`, `source` (document path or URL) and `mapped_to` (a JSON path such
  as `screens[0].min_value`, or `null`). `construction_spec` validates as `ConstructionSpec`; every field no
  stated rule sets keeps the model's default.

### Step 5: activities, tiers, keywords (`pick`)

- **Bottom-up:** activities synthesized from the picked theme's supporting stocks' chunks and profiles; each
  activity's `citations` hold the chunk quotes it rests on. An activity with no grounded quote is dropped.
- **Top-down:** when methodology documents were given, `consolidate` on their extractions, with `value_chain=True`
  and the configured input-output model when one is loaded (upstream enablers by sector).
- **Merge as equals:** `match_activities` (`authority_taxonomy/matching.py:46`); a matched pair becomes one
  activity holding both sides' citations, with run-JSON `origin` `both`.
- **Activity tiers:** the existing `tier` and `value_chain_role` fields.
- **Keyword dictionary:** `ActivityDefinition` keeps `seed_keywords` as the primary bucket (the funnel reads it)
  and gets `contextual_keywords`, `exclusion_keywords` (default empty) and `contextual_window_words` (default 50:
  a contextual keyword counts only within that many words of a primary one). "Occurs" means a case-insensitive
  whole-word phrase match (`PEM stack` does not match `PEM stacks`). Grounding, in code: a primary or
  contextual keyword must occur in at least one supporting stock's chunk; an exclusion keyword must occur in a
  non-supporting stock's chunk or in a methodology boundary quote. Others are dropped.
- **Mapping:** one call assigns every described stock to one activity or `none`, with a reason and a quote; kept
  only if the quote is grounded in that stock's own documents, else the stock goes to `coverage.unmapped`. A
  grounded `none` gets a `mapping[]` entry with `activity_id: null` and `tier` `unknown`; it is neither mapped
  weight nor in `unmapped`.
- **Company tier**, provisional, only with `--segments`: segment labels are linked to activities with the existing
  `suggest_catalogue_mapping` (`revenue_exposure/mapping.py:29`, a reviewable draft). The share of the company's
  revenue in labels linked to its mapped activity, in code: `core` when ≥ 50 %, `enabler` when ≥ 20 % and < 50 %,
  `adopter` when < 20 %. Without `--segments`, or without a segment row for the company: `unknown`. Stored in
  `mapping[].tier`.
- **Coverage, in code:** `profiled_weight_share` = mapped weight / described weight, `fund_weight_share` =
  mapped weight / `total_weight`. `source_notes` gets `Coverage: <a> of profiled weight, <b> of fund weight.`
  (two decimals), or `Coverage: n/a of profiled weight, n/a of fund weight.` when unweighted.
- **Share fields:** unchanged. `build_taxonomy_schema` still emits the four share fields per activity
  (revenue, CapEx, OpEx, R&D) from the ratified taxonomy; this spec adds nothing to them (AC-40).
- **Theme KPIs:** `ThemeDefinition.kpis: list[FieldDefinition]` (default empty). `pick` drafts 2-5 with
  `draft_schema()` (`schema_builder.py:55`) from the theme, its activities and the methodology excerpts.
  `build_taxonomy_schema` appends `theme.kpis` after all per-activity fields, whatever those are once the
  stage-evidence spec lands.
- Saved as a draft with `DerivationMethod.STOCK_INFERENCE = "stock_inference"`. The new schema fields change the
  OpenAPI output; regenerate both generated frontend files.

### Golden scoring script

`backend/scripts/score_stock_inference.py --run <run_id> --cases <cases.json> --split tune|holdout --check
theme|mapping [--theme-pattern <regex>] [--min-recall <x>] [--min-precision <x>]` reads the run JSON and the golden
file `backend/tests/golden/exposure/electrolyser_makers/cases.json` (labels `core` / `peripheral` / `not`, split in
each case's `split` field). It prints one score line per check and exits 0 only when every given threshold holds.
It ships with PR 2. Matching cases to run stocks is by `case_id` = `company_id`; the golden universe file is
generated from the cases with that id.

### Retiring the two old methods

- `arp taxonomy create --method etf_index_holdings|empirical` exits 1 and `POST /api/taxonomies` with
  `derivation_method` set to either answers 422; the message, and the API's `detail`, is
  `--method <m> is replaced by 'arp taxonomy infer start --stocks <file>'.`
- The refusal comes before any other option or body validation.
- The enum values stay, so saved taxonomies load.
- `frontend/src/pages/TaxonomyLibrary.tsx` drops `etf_index_holdings` and `empirical` from `CREATABLE_METHODS`
  (lines 34-41) and their option panels; `METHOD_LABELS` keeps both so saved taxonomies still show a label;
  screenshot and audit per the frontend rules.
- `build_theme_from_holdings`, `build_theme_empirical`, `load_holdings_corpus` and their tests are removed.
  `tests/test_walkthrough_pipeline.py:231` (`test_research_callers_write_no_trace`) uses
  `gather_corpus_from_extraction`; it is pointed at `profile_stock`, keeping its assertion, and listed in the PR.

## Constraints

- Postgres with pgvector, and the `emerging_themes` extra for UMAP/HDBSCAN.
- Cost: about 20k input tokens per profiled stock (measured), so about 600k per 30-stock run, plus discovery time.
- Three PRs in order (at most three agent PRs open): (1) loader fixes, selection, profiles, clusters, themes,
  retiring the old methods; (2) `pick`: activities, tiers, keywords, mapping, coverage, KPIs; (3) layer 1 index
  rules.
- Fund files from providers may not be redistributed; test fixtures are written by hand in the providers' layout.

## Approaches considered

| Approach | Trade-off | Decision |
|---|---|---|
| New `taxonomy infer` run (start / pick / show) | Matches the stop-for-a-pick flow; reuses extraction, authority agent, clustering, `arp/index` types | chosen |
| Another `--method` on `taxonomy create` | `create` needs a theme name and saves at once | rejected |
| LLM-only theme step, no clustering | Simpler, but finds no sub-themes and leans more on the model | kept only as the fallback when HDBSCAN finds nothing |

## Calls made (not decided by the owner)

1. Three PRs in the order above; CLI only.
2. 80 % weight cutoff alongside the cap of 30; seed 0 for samples.
3. Theme-neutral description; 8 chunks per stock; benchmark ≤ 200 stocks, no discovery for it.
4. `not_found` and `ungrounded_quote` count as failed, not as described.
5. Read-only lookup via `lookup`; name match only when exactly one company has that exact name.
6. Weighted input only through holdings CSVs; `CompanyRef` gets no weight field.
7. `origin` lives in the run JSON, not on `ActivityDefinition`.
8. Segment labels linked to activities with the existing draft mapper; the tier itself computed in code.
9. `extract_source` gains a `checklist` parameter; `theme_name` for layer 1 is `--name`.
10. Old methods refuse rather than alias, and leave the UI.
11. Test fixtures in the provider layout, written by hand.

## Left to the builder

Module layout (suggested `arp/research/stock_inference/`), prompts, the human-readable `show` output.

## Acceptance

Conventions for every row unless it says otherwise:
- `infer` rows replace the model client with a fake that gives the stated replies, and fake
  `profile_stock`'s extract function where a row says "the fake extractor".
- Documents are fixture text in the test Postgres; every stock has a document unless the row says otherwise.
- "Run JSON" is `arp taxonomy infer show <run_id> --json`. "Unchanged DB" means the rows of `companies` and
  `company_identifiers`, all columns ordered by id, are identical before and after.
- **Fixture `hydr_layout.csv`** (`tests/fixtures/holdings/`), exactly these lines:

```
Global X Hydrogen ETF
Fund Holdings Data as of 11/02/2026
% of Net Assets,Ticker,Name,SEDOL,Market Price ($),Shares Held,Market Value ($)
0.04,"",CASH,"",1.0,"31,526.89","31,526.89"
0.00,"",BRITISH STERLING POUND,"",1.0,0.01,0.01
-0.00,"",EURO,"",1.12,-491.13,-549.92
16.20,BE,BLOOM ENERGY CORP- A,BDD1BB8,196.25,"59,172.00","11,612,505.00"
7.90,PLUG,PLUG POWER INC,2508386,1.31,"4,319,682.00","5,658,783.42"
5.12,NEL NO,NEL ASA,B02NR83,0.21,"17,663,060.00","3,672,331.86"
0.65,NANO SP,NANOFILM TECHNOLOGIES INTERN,BNG70K5,0.63,"742,900.00","464,675.00"
0.39,288620 KS,S-PRISM CO LTD,BFD20N0,2.44,"115,550.00","282,510.98"
0.17,"",OTHER PAYABLE & RECEIVABLES,"",1.0,"122,228.55","122,228.55"
"The information contained herein may not be reproduced, redistributed or used to create any financial products."
```

| ID | Given | When | Then (observable, exact) | Checked by |
|---|---|---|---|---|
| AC-1 | `hydr_layout.csv` | `load_holdings_with_weights(path)` | 5 rows, tickers in order `BE`, `PLUG`, `NEL NO`, `NANO SP`, `288620 KS` | unit |
| AC-2 | `hydr_layout.csv` | `load_holdings_with_weights(path)` | Weights equal `0.162`, `0.079`, `0.0512`, `0.0065`, `0.0039` within 1e-9 | unit |
| AC-3 | `hydr_layout.csv` | `arp universe from-holdings <fixture> --out u.json` | Exit 0; `u.json` holds 5 companies | unit |
| AC-4 | CSV `Ticker,Name,Weight\n,CASH,1.0\nABC,Cash Holdings Corp,2.0\n` | `load_holdings_with_weights` | 1 row: ticker `ABC`, weight `0.02` | unit |
| AC-5 | CSV `Ticker,Name,Weight\nA,Alpha,0.6\nB,Beta,0.4\n` | `load_holdings_with_weights` | Weights `0.6` and `0.4` (as on `main`) | unit |
| AC-6 | Holdings CSV, 40 securities; the 30 largest sum to 75 % of total weight | `infer start` | Run JSON `profiles` holds exactly the 30 largest `company_id`s; `selection.cutoff_reason` `cap_30` | unit |
| AC-7 | Holdings CSV, weights 20,10,10,8,7,6,5,4,4,3,2,1 then 28 × 0.5 (total 94; 9 largest = 74, 10 largest = 77 ≥ 75.2) | `infer start` | `profiles` holds exactly the 10 largest; `cutoff_reason` `weight_80` | unit |
| AC-8 | 50 stocks in a JSON universe (unweighted), written in two row orders | `infer start` on each | Both runs' `profiles` hold the same 30 `company_id`s; `cutoff_reason` `sample` | unit |
| AC-9 | Holdings CSV, 40 securities; the 30 largest sum to 70 %; positions 30 and 31 have equal weight, tickers `t30a` and `t30b`; two row orders | `infer start` on each | Both `profiles` hold `t30a` and not `t30b`; `cutoff_reason` `cap_30` | unit |
| AC-10 | 5 stocks; the fake extractor raises `ValidationError` for `s3` | `infer start` | Exit 0; run JSON `stage` `themes_ready`; `s1`,`s2`,`s4`,`s5` have a `description` | unit |
| AC-11 | Same as AC-10 | `infer show --json` | Profile `s3`'s `error` starts with `ValidationError: ` and it has no `description` | unit |
| AC-12 | 5 stocks; `s3` has no document; fake discovery finds none | `infer start` | Exit 0; profile `s3` `error` `no_document` | unit |
| AC-13 | 5 stocks; `s5` has no document; fake discovery returns document `D5` for `s5` | `infer start` | Profile `s5` has a `description` and `citation.doc_id` `D5` | unit |
| AC-14 | 3 stocks; the fake extractor raises for `s1` and `s2`; `s3` has no document and discovery finds none | `infer start` | Exit 1; stdout line 1 `Run <run_id>`; stderr `No stock could be profiled: 2 failed, 1 had no document.`; run JSON for that id `stage` `failed` | unit |
| AC-15 | `ARP_LLM_MODEL=model-a`, `ARP_LLM_VERIFIER_MODEL=model-b` | `infer start` on 2 stocks | Run JSON `extractor_model` `model-a`, `verifier_model` `model-b` | unit |
| AC-16 | The fake extractor returns quote `We make PEM stacks.`, present in `s1`'s document `D1` | `infer start` | Profile `s1` `citation.quote` `We make PEM stacks.`, `citation.doc_id` `D1` | unit |
| AC-17 | The fake extractor returns a value whose quote is absent from `s1`'s document | `infer start` | Profile `s1` `error` `ungrounded_quote`, no `description`, no `citation` | unit |
| AC-18 | The fake extractor returns no value for `s1` | `infer start` | Profile `s1` `error` `not_found` | unit |
| AC-19 | Test DB holds company `Nel ASA` with ISIN `NO0010081235`; a holdings CSV with `ISIN` and `LEI` columns, whose row has that ISIN and an LEI registered nowhere | `infer start` | Profile `db_match` is that company's id; unchanged DB | unit |
| AC-20 | A holdings row matching no company by ISIN, LEI, CIK or exact name; its document is a local file, so discovery does not run | `infer start` | Profile `db_match` `none`; unchanged DB | unit |
| AC-21 | Fake theme reply supports `x1` (not profiled), `p1` (weight 0.10), `p2` (0.05); 5 described stocks with total weight 0.50; the reply also claims `weight_share` 0.9 | `infer start` | `themes[0].supporting` `["p1","p2"]`; `weight_share` `0.3`; `count_share` `0.4` | unit |
| AC-22 | Two fake themes, `Beta` and `Alpha`, each supported by stocks weighing 0.15 of 0.50 described weight | `infer start` | `themes[0].name` `Alpha`, `themes[1].name` `Beta` | unit |
| AC-23 | Fake reply: theme `T1` supported by `p1`, theme `T2` supported only by `x1` (not profiled) | `infer start` | `themes` holds only `T1` | unit |
| AC-23a | Fake reply whose only theme is supported only by `x1` | `infer start` | Exit 1; stderr `No common theme is supported by the profiled stocks.`; `stage` `failed` | unit |
| AC-24 | `--methodology <fixture>`; the fake theme reply quotes a sentence absent from it | `infer start` | That theme's `stated_in_methodology` `false`, `methodology_quote` `null` | unit |
| AC-25 | 3 stocks × 8 chunks; fixture embeddings: `s1`,`s2` chunks = unit vector A + Gaussian noise σ 0.01, `s3` = unit vector B (orthogonal to A) + the same noise, `numpy` seed 0; each group's text holds ≥ 10 distinct non-stopword words of ≥ 3 letters | `infer start` | `clusters` has 2 entries with 10 terms each; their `members` are `["s1","s2"]` and `["s3"]` | unit |
| AC-26 | A fake `cluster_points` returns -1 for every point | `infer start` | Exit 0; `clusters` `[]`; `stage` `themes_ready` | unit |
| AC-27 | 10 weighted stocks, same fake replies, written in two row orders | `infer start` then `infer pick --theme 1` on each | The two run JSONs are identical except `run_id` and `taxonomy_id` | unit |
| AC-28 | A run at `drafted` (after AC-29) | `infer pick <run> --theme 1` | Exit 1; stderr `Run <run_id> is at stage 'drafted'; 'pick' needs 'themes_ready'.` | unit |
| AC-28a | A run at `themes_ready` with 2 themes | `infer pick <run> --theme 9` | Exit 1; stderr `Run <run_id> has no theme 9.` | unit |
| AC-29 | A run at `themes_ready` | `infer pick <run> --theme 1` | Exit 0; run JSON `stage` `drafted`, `taxonomy_id` not null | unit |
| AC-30 | Same | `arp taxonomy show <taxonomy_id>` | stdout contains `"derivation_method": "stock_inference"` and `"status": "draft"` | unit |
| AC-31 | Fake synthesis returns activity `A` with a quote present in a supporting chunk, and `B` with an absent quote | `infer pick` | The saved taxonomy has `A`, whose `citations` hold that quote, and has no `B` | unit |
| AC-32 | Fake mapping assigns `p3` with a quote absent from `p3`'s documents | `infer pick` | No `mapping` entry for `p3`; `p3` in `coverage.unmapped` | unit |
| AC-32a | Fake mapping assigns `p4` to `none` with a quote grounded in `p4`'s documents | `infer pick` | `mapping` entry for `p4` with `activity_id` `null` and `tier` `unknown`; `p4` not in `coverage.unmapped` | unit |
| AC-33 | Described weight 0.50 of `total_weight` 1.00; mapped stocks weigh 0.30 | `infer pick` | Taxonomy `source_notes` contains `Coverage: 0.60 of profiled weight, 0.30 of fund weight.` | unit |
| AC-34 | An unweighted run | `infer pick` | `source_notes` contains `Coverage: n/a of profiled weight, n/a of fund weight.` | unit |
| AC-35 | Methodology activity with quote `Q2`; stock activity with quote `Q1`; the fake matcher confirms them as the same | `infer pick` | One activity for the pair; run JSON `origin` `both`; its `citations` hold `Q1` and `Q2` | unit |
| AC-36 | `--segments` linked (fake mapper) so that mapped-activity revenue shares are `p1` 60 %, `p6` 50 %, `p2` 25 %, `p4` 5 %; `p5` has no segment row | `infer pick` | `mapping[].tier`: `p1` `core`, `p6` `core`, `p2` `enabler`, `p4` `adopter`, `p5` `unknown` | unit |
| AC-37 | Supporting stock's chunk text `Our PEM stack plant in Herøya`; fake keyword reply: primary `PEM stack`, `fusion reactor`, `Herøya plants` | `infer pick` | The activity's `seed_keywords` include `PEM stack` and neither `fusion reactor` nor `Herøya plants` | unit |
| AC-38 | Supporting chunk text `Stack efficiency rose to 70 %.`; non-supporting stock's chunk text `We sell fuel cell systems.`; fake keyword reply: contextual `stack efficiency`, `warp drive`; exclusion `fuel cell` | `infer pick` | `contextual_keywords` `["stack efficiency"]`; `exclusion_keywords` `["fuel cell"]`; `contextual_window_words` `50` | unit |
| AC-39a | An unweighted run with no `--segments` | `infer pick` | Every `mapping[].tier` is `unknown` | unit |
| AC-39 | Fake `draft_schema` returns 3 KPI fields | `infer pick` | The saved taxonomy's `theme.kpis` holds those 3, in order | unit |
| AC-40 | A ratified taxonomy with 3 activities and no KPIs | `build_taxonomy_schema` | Fields identical to `main`'s output for the same taxonomy | unit |
| AC-41 | Same taxonomy with 2 KPIs | `build_taxonomy_schema` | AC-40's fields followed by the 2 KPIs | unit |
| AC-42 | Methodology fixture with "a minimum free-float market capitalisation of USD 500 million"; the fake eligibility reply returns that sentence as rule and quote | `infer start --methodology <fixture>` | `construction_spec` validates; `screens[0]` is `MetricThresholdScreen`, field `float_mcap`, `min_value` `500000000`; `index_currency` `USD`; the rule's `mapped_to` `screens[0].min_value`; every other field equals `ConstructionSpec()`'s default | unit |
| AC-43 | Fixture with "no constituent may exceed 8 % of the index"; matching fake caps reply | `infer start --methodology <fixture>` | `constraints.single_name_cap` `0.08`; the rule's `mapped_to` `constraints.single_name_cap` | unit |
| AC-44 | Fixture with "the index is reviewed semi-annually"; matching fake rebalance reply | `infer start --methodology <fixture>` | `calendar.review_frequency` `semi_annual`; the rule's `mapped_to` `calendar.review_frequency` | unit |
| AC-45 | Fixture with "the index committee may exclude any company at its discretion"; matching fake eligibility reply | `infer start --methodology <fixture>` | That rule is in `index_rules.rules` with its quote and `mapped_to` `null` | unit |
| AC-46 | A fake rule reply whose quote is absent from the document | `infer start --methodology <fixture>` | No such rule in `index_rules.rules` | unit |
| AC-47 | No other options | `arp taxonomy create X --method empirical`, then `--method etf_index_holdings` | Each exits 1; stderr `--method <m> is replaced by 'arp taxonomy infer start --stocks <file>'.` with `<m>` filled in | unit |
| AC-48 | API | `POST /api/taxonomies` with body `{"name":"X","derivation_method":"empirical"}`, then with `etf_index_holdings` | Each HTTP 422; `detail` equals the AC-47 string for that method | unit |
| AC-49 | The running app's taxonomy library, tab "New taxonomy" | open the method choice | No option `ETF / index holdings (bottom-up)` and no option `Empirical (Extraction Engine readings)` | evaluator |
| AC-49a | Same | open the method choice | Options, in order: `LLM draft (freeform)`, `Industry-anchored (ISIC / input-output)`, `Authority source (IEA, EU taxonomy, standards bodies, ...)`, `News & earnings-call transcript mining` | evaluator |
| AC-49b | Saved taxonomies with `derivation_method` `empirical` and `etf_index_holdings` | open the taxonomy library | Their rows show `Empirical (Extraction Engine readings)` and `ETF / index holdings (bottom-up)` | evaluator |
| AC-50 | Saved taxonomies from `main`, one `empirical`, one `etf_index_holdings` | `arp taxonomy show <id>` | stdout JSON equals `main`'s output for the same id, after removing keys `kpis`, `contextual_keywords`, `exclusion_keywords`, `contextual_window_words` | unit |
| AC-51 | The authority agent's tests on `main` (`test_authority_taxonomy_*.py`, `test_golden_authority_taxonomy.py`) | `pytest` on those files | Exit 0; the files are unchanged from `main` | unit |
| AC-52 | `tests/test_etf_holdings_universe.py`, `tests/test_overlap.py`, `tests/test_activity_generator.py`, `tests/test_authority_derivation.py`, `tests/test_news_mining_derivation.py`, `tests/test_taxonomy_store.py`, `tests/test_taxonomy_compare_merge.py`, `tests/test_cli_taxonomy_author.py` | `pytest` on those files | Exit 0 | unit |
| AC-53 | `tests/test_walkthrough_pipeline.py::test_research_callers_write_no_trace` | `pytest` on it | Exit 0; its assertion lines are identical to `main`'s | unit |
| AC-54 | Golden: tune split of `electrolyser_makers` (33 stocks, unweighted → seeded 30), golden documents, real model | `infer start`, then `scripts/score_stock_inference.py --run <id> --cases <cases.json> --split tune --check theme --theme-pattern electroly --min-recall 0.8` | Exits 0, which it does only when the top theme's name matches the pattern (case-insensitive) and its supporting stocks include ≥ 80 % of the described core and peripheral stocks | golden (by hand) |
| AC-55 | Golden: same run after `infer pick --theme <the matching rank>` | `scripts/score_stock_inference.py ... --split tune --check mapping --min-precision 0.8` | Exits 0, which it does only when ≥ 80 % of described `not` stocks are mapped to `none` or to an activity no described `core` stock is mapped to | golden (by hand) |
| AC-56 | Golden: the holdout split, same commands as AC-54/55 with `--split holdout` | run once per PR | The script's score lines appear in a PR comment (not merge-blocking) | golden (by hand) |

Must not change: AC-5, AC-40, AC-49b, AC-50, AC-51, AC-52.

PR checklist (not an AC row): any change to the files in AC-52 is listed in the PR description with the reason.
