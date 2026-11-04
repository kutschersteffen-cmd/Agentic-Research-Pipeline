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

This replaces the `etf_index_holdings` and `empirical` taxonomy methods with **one method for both cases**: the
review showed one reads names only and guesses from model memory, the other needs the theme as input, crashes on
one bad model reply and checks itself with the same model.

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
2. Every activity, keyword and stock-to-activity mapping traces to a quote from a filing or a methodology
   document.
3. Shares, weights, coverage and selection are computed in code, never by the model.
4. One failing stock (bad model reply, no document) never ends the run.
5. Stated index rules come back as a valid draft `ConstructionSpec`, with each rule's quote; rules that do not fit
   it are kept as quoted text, not dropped.

## Non-goals

- Layer 3: baseline filters, purity score, weighting, replication check.
- Observed rules: holdings history, rebalance churn, weight regression (owner: stated rules only).
- Market data, patents, return co-movement, trained contrastive models, company-level supplier graphs.
- Automatic fetching of fund documents; the user passes files or URLs (`taxonomy discover-sources` already points
  to fund pages).
- UI and API endpoints for the new command.
- Writing to the company registry (owner: read-only matching).
- Changing the stage-evidence fields planned in `2026-11-03-stage-evidence-schema-design.md` (on `main`).

## Anti-goals

- A theme, activity or mapping that rests on model memory instead of a quote (the Cummins case).
- A result that changes when the input rows are reordered.
- An inference run that creates or changes company rows.

## Owner decisions

One method for both cases · methodology and stocks merged as equals · output is ranked themes with supporting
stocks · read the top 30 by weight · schema gets share fields plus theme KPIs · layers 1 and 2 first · stocks
without a filing go through document discovery first · matching is read-only and keeps ISIN/SEDOL · layer 1 is
stated rules only · golden checks are tuned on the tune split only and scored on holdout by hand, not merge-blocking.

## Design

### Commands and stages

```
arp taxonomy infer start --stocks <csv|json> [--methodology <file|url> ...] [--segments <catalogue.csv>]
                         [--benchmark <universe csv|json>] [--name <set name>]
arp taxonomy infer pick <run_id> --theme <rank>
arp taxonomy infer show <run_id> [--json]
```

The run lives in `RunStore` with stages, like the authority agent's `run.py`:
`started → profiled → themes_ready` (start stops here) `→ drafted` (pick), or `failed`.
A command at the wrong stage exits 1 with `Run <run_id> is at stage '<stage>'; '<command>' needs '<needed>'.`

`infer show --json` prints the run record. Its keys are the observable surface for the Acceptance rows:
`run_id, stage, extractor_model, verifier_model, selection {method, cutoff_reason}, profiles[], clusters[],
themes[], outliers[], index_rules {construction_spec, rules[]}, taxonomy_id, mapping[], coverage {}`.

### Inputs

**Stocks.** `.json` or a CSV with a `company_id` column → `load_company_universe`; any other CSV → the holdings
loader. Fixes to the holdings loader (`etf_holdings.py:53`, shared with `universe from-holdings` and
`universe overlap`):
- Header row: the first row containing a name or ticker column from the existing variant lists; lines above it are
  skipped.
- Rows with fewer cells than the header are skipped.
- Non-security rows are dropped: empty ticker **and** a name containing a cash, currency, payable, receivable,
  future or swap word. Rows with a ticker are kept.
- Weights are scaled per column, not per cell: if the header contains `%`, any cell contains `%`, or any value
  is above 1, the whole column is divided by 100. (Today a 0.65 % holding is read as 65 %; HYDR's weights sum to 2.70.)
- ISIN and SEDOL columns are kept on the row when present.

**Methodology documents** (optional, repeatable): file paths or URLs, fetched with the authority agent's fetch.

**Segment revenue** (optional): the existing revenue-catalogue CSV (`revenue_exposure/catalogue.py:11`).

**Benchmark** (optional): a universe used only as contrast for the topic clusters.

### Step 1: select

- With weights: sort by weight descending (ties by `company_id`), take stocks until 30 are taken or the running
  total first reaches at least 80 % of total security weight, including the stock that crosses 80 %.
  `selection.cutoff_reason` is `cap_30` or `weight_80`.
- Without weights: sort by `company_id`, then `random.Random(0).sample(..., min(30, n))`; `cutoff_reason` is
  `sample`.

### Step 2: profile each selected stock

- **Database match, read-only:** `resolve(session, ids, allow_create=False)` (`db/companies.py:76`) on ISIN, LEI and
  CIK; if none matches, a case-insensitive exact name match that returns exactly one company. Nothing is written.
  SEDOL is kept on the profile but not matched on (no SEDOL id scheme exists). Unmatched → `db_match: "none"`.
- **Stored data, no model call:** ISIC/NACE/GICS codes from the row or the matched company; EXIOBASE sectors via
  `nace_sectors()`; the latest value per field from `company_view.facts()` (dedupe per `field_id`, newest
  `period_end`).
- **Segments:** rows for this company from `--segments`, with shares.
- **Documents:** stocks with no document from local files, EDGAR or ESEF go through `run_discovery`
  (`discovery/pipeline.py:231`) first, then the registry is read again.
- **Description:** one theme-neutral extraction field ("the company's main business segments, products and
  services, as the company states them", generic seed keywords), run through `_extract_company` with
  `verifier_llm=build_verifier_llm_client(settings)`. All stocks run concurrently, sharing one `field_limit`
  semaphore of `settings.max_concurrent_llm_calls`. The verified quote is kept as `citation {doc_id, page, quote}`.
- **Failure per stock:** any exception is recorded as `error: "<ExceptionType>: <message>"`; a stock with no
  document after discovery gets `error: "no_document"`. The run continues. If no stock has a description, the
  run goes to `failed` and exits 1 with `No stock could be profiled: <n> failed, <m> had no document.`

### Step 3: topic clusters (BERTopic-style)

- Points: per profiled stock, the 8 chunks of its documents that best match the theme-neutral description query
  (existing retrieval), embedded with `embed_texts` (`retrieval/embeddings.py:24`).
- With `--benchmark`: the benchmark's chunks are embedded the same way, from documents already available (no
  discovery, no model call, at most 200 benchmark stocks, seeded sample).
- UMAP + HDBSCAN as in `emerging_themes/clustering.py` (needs the `emerging_themes` extra). Each cluster gets its
  top 10 c-TF-IDF terms, computed in code; with a benchmark, the terms are weighted against the benchmark's chunks.
- Each cluster records its member stocks and their weight share.
- If HDBSCAN finds no cluster, `clusters` is empty and the theme step runs on the profiles alone.

### Step 4: common themes

One structured model call gets the clusters (terms, three sample chunks each), the profiles and, when given, the
methodology's stated theme from layer 1. It returns 2-5 themes: name, description, supporting `company_id`s with
one reason each, cluster ids, and `stated_in_methodology` with a quote. Code then:
- drops `company_id`s not in the profiles and quotes that fail grounding (`arp/grounding.py`);
- computes `count_share` (supporting / profiled with a description) and `weight_share` (supporting weight /
  profiled weight), ignoring any share the model returns;
- ranks by `weight_share`, or `count_share` without weights, ties by name;
- lists `outliers`: profiled stocks that support no theme.

`start` prints the ranked table and stops at `themes_ready`.

### Layer 1: stated index rules (inside `start`, when methodology documents are given)

- The authority agent's `extract_source` runs on each document for the theme items (stated theme, boundaries,
  thresholds, definitions).
- A second checklist, `INDEX_RULES_CHECKLIST` (`eligibility`, `selection`, `weighting`, `caps`, `rebalance`), runs
  through the same machinery: one call per item, every element quoted, ungrounded quotes dropped.
- Each extracted rule is mapped, in code where possible, to the `ConstructionSpec` parts that exist:
  `MetricThresholdScreen` on `float_mcap`, `adv_3m`, `relevance`; `CategoryScreen` on `sector`; `TopN`;
  `BaseWeighting.scheme`; `ConstraintSet.single_name_cap` and `ucits_5_10_40`; `CalendarSpec.review_frequency`.
- `index_rules.rules[]` lists every rule with `text`, `quote`, `source`, and `mapped_to` (a JSON path into the
  spec, or `null`). `construction_spec` must validate as `ConstructionSpec`. Rules with `mapped_to: null` stay
  in the list.

### Step 5: activities, tiers, keywords (`pick`)

- **Bottom-up:** activities synthesized from the picked theme's supporting stocks' chunks and profiles; each
  activity carries the chunk quotes it rests on in `citations`. An activity without a grounded quote is dropped.
- **Top-down:** when methodology documents were given, `consolidate` on their extractions, with
  `value_chain=True` and the loaded input-output model when one is configured (upstream enablers by sector).
- **Merge as equals:** `match_activities` (`authority_taxonomy/matching.py:46`); each activity records
  `origin: stocks | methodology | both`.
- **Tiers:** each activity's existing `tier` (core / enabling / critical_input) and `value_chain_role`. Per
  company, a provisional tier where `--segments` gives a share for a mapped activity: `core` ≥ 50 %, `enabler`
  20-49 %, `adopter` < 20 %; otherwise `unknown` (the theme run fills it later).
- **Keyword dictionary:** `ActivityDefinition` keeps `seed_keywords` as the primary bucket (the funnel reads it)
  and gets `contextual_keywords` and `exclusion_keywords` (default empty). The rule recorded with them: a
  contextual keyword counts only within 50 words of a primary one. A primary keyword that occurs in none of the
  supporting stocks' chunks is dropped in code.
- **Mapping:** one call assigns every profiled stock to one activity or `none`, with a reason; kept only if it
  cites that stock's own profile or chunk quote, else the stock goes to `unmapped`.
- **Coverage, in code:** `mapped weight / profiled weight` and `mapped weight / total security weight`, written to
  `coverage` and into `source_notes` as `Coverage: <a> of profiled weight, <b> of fund weight.` (two decimals;
  `n/a` without weights).
- **Theme KPIs:** `ThemeDefinition.kpis: list[FieldDefinition]` (default empty). `pick` drafts 2-5 with
  `draft_schema()` (`schema_builder.py:55`) from the theme, its activities and the methodology excerpts.
  `build_taxonomy_schema` appends `theme.kpis` after all per-activity fields, whatever those are once the
  stage-evidence spec lands.
- The taxonomy is saved as a draft with `DerivationMethod.STOCK_INFERENCE = "stock_inference"`.

### Retiring the two old methods

`arp taxonomy create --method etf_index_holdings|empirical` exits 1, and the API answers 422 with `detail`:
`--method <m> is replaced by 'arp taxonomy infer start --stocks <file>'.` The enum values stay so saved taxonomies
load. `build_theme_from_holdings`, `build_theme_empirical`, `load_holdings_corpus` and their tests go.
`tests/test_walkthrough_pipeline.py:231` uses `gather_corpus_from_extraction`; it is pointed at the new profile
step and listed in the PR as a test change.

## Constraints

- Postgres with pgvector, and the `emerging_themes` extra for UMAP/HDBSCAN.
- Cost: about 20k input tokens per profiled stock (measured), so about 600k per 30-stock run, plus discovery time
  for stocks without filings.
- Build as three PRs in order (at most three agent PRs open): (1) loader fixes, selection, profiles, clusters,
  themes, retire old methods; (2) `pick`: activities, tiers, keywords, mapping, coverage, KPIs; (3) layer 1 index
  rules.

## Approaches considered

| Approach | Trade-off | Decision |
|---|---|---|
| New `taxonomy infer` run (start / pick / show) | Matches the stop-for-a-pick flow; reuses extraction, authority agent, clustering, arp/index types | chosen |
| Another `--method` on `taxonomy create` | `create` needs a theme name and saves at once | rejected |
| LLM-only theme step, no clustering | Simpler, but no sub-theme discovery and more reliance on the model's reading | rejected; kept as the fallback when HDBSCAN finds nothing |

## Calls made (not decided by the owner)

1. Three PRs in the order above.
2. CLI only.
3. 80 % weight cutoff alongside the cap of 30; seed 0 without weights.
4. Theme-neutral description field; 8 chunks per stock for clustering; benchmark capped at 200 stocks, no
   discovery for it.
5. Read-only name match only when exactly one company has that exact name.
6. Old methods refuse instead of acting as aliases.
7. Mappings and keywords kept only when grounded in the stock's own text.
8. Provisional company tier from segment shares with the framework's 50 / 20 % thresholds.

## Left to the builder

Module layout (suggested `arp/research/stock_inference/`), prompts, the exact non-security word list, the
human-readable `show` output.

## Acceptance

Unless a row says otherwise, `infer` rows use a fake model client with stated replies, and documents are fixture
text in the test Postgres. "Run JSON" means `arp taxonomy infer show <run_id> --json`.

| ID | Given | When | Then (observable, exact) | Checked by |
|---|---|---|---|---|
| AC-1 | `tests/fixtures/holdings/hydr_2026-11-02.csv`: the Global X HYDR file as downloaded (2 title lines, header, 30 rows, footer) | `load_holdings_with_weights(path)` | 26 rows; no row named `CASH`, `BRITISH STERLING POUND`, `EURO` or `OTHER PAYABLE & RECEIVABLES` | unit |
| AC-2 | Same fixture | `load_holdings_with_weights(path)` | First row ticker `BE`, weight `0.162`; the row `NANO SP` has weight `0.0065` | unit |
| AC-3 | Same fixture | `arp universe from-holdings <fixture> --out u.json` | Exit 0; `u.json` holds 26 companies | unit |
| AC-4 | CSV `Ticker,Name,Weight\n,CASH,1.0\nABC,Cash Holdings Corp,2.0\n` | `load_holdings_with_weights` | 1 row: ticker `ABC`, weight `0.02` | unit |
| AC-5 | CSV `Ticker,Name,Weight\nA,Alpha,0.6\nB,Beta,0.4\n` (fractions, no `%`) | `load_holdings_with_weights` | Weights `0.6` and `0.4`, as today | unit |
| AC-6 | 40 securities with weights; the 30 largest sum to 75 % | `infer start` | Run JSON `profiles` has the 30 largest `company_id`s; `selection.cutoff_reason` `cap_30` | unit |
| AC-7 | 40 securities, weights 20,10,10,8,7,6,5,4,4,3,2,1 then 28 × 0.5 (total 94); the 9 largest sum to 74 (78.7 %), the 10 largest to 77 (81.9 %) | `infer start` | `profiles` has exactly the 10 largest; `cutoff_reason` `weight_80` | unit |
| AC-8 | 50 stocks without weights, written in two different row orders | `infer start` on each | The two runs' `profiles` hold the same set of `company_id`s | unit |
| AC-9 | 40 weighted stocks where positions 30 and 31 have equal weight, in two row orders | `infer start` on each | Same `profiles` set; the tie goes to the smaller `company_id` | unit |
| AC-10 | 5 stocks; the fake extractor raises `ValidationError` for `s3` | `infer start` | Exit 0; run JSON `stage` `themes_ready`; 4 profiles have a `description` | unit |
| AC-11 | Same as AC-10 | `infer show --json` | Profile `s3` has `error` starting `ValidationError: ` | unit |
| AC-12 | 5 stocks; `s3` has no document and the fake discovery finds none | `infer start` | Exit 0; profile `s3` has `error` `no_document`; discovery was asked for `s3` only (its recorded call list is `["s3"]`) | unit |
| AC-13 | 3 stocks; the fake extractor raises for all | `infer start` | Exit 1; stderr `No stock could be profiled: 3 failed, 0 had no document.`; run JSON `stage` `failed` | unit |
| AC-14 | `ARP_LLM_MODEL=model-a`, `ARP_LLM_VERIFIER_MODEL=model-b` | `infer start` on 2 stocks | Run JSON `extractor_model` `model-a`, `verifier_model` `model-b` | unit |
| AC-15 | A stock whose fake extraction returns quote `We make PEM stacks.`, present in its document | `infer start` | Its profile `citation.quote` is `We make PEM stacks.` with that document's `doc_id` | unit |
| AC-16 | A stock whose fake extraction returns a quote absent from its document | `infer start` | Its profile has no `citation` and `error` `ungrounded_quote` | unit |
| AC-17 | Company `Nel ASA` in the test DB with ISIN `NO0010081235`; a stock row with that ISIN | `infer start` | Profile `db_match` is that company's id; row counts of `companies` and `company_identifiers` unchanged after the run | unit |
| AC-18 | A stock row matching no company by ISIN, LEI, CIK or exact name | `infer start` | Profile `db_match` `none`; `companies` row count unchanged | unit |
| AC-19 | Fake theme reply cites `x1` (not profiled), `p1` (weight 0.10), `p2` (0.05); 5 profiled stocks with total weight 0.50; the reply also claims `weight_share: 0.9` | `infer start` | Theme 1 lists only `p1`, `p2`; `weight_share` `0.30`; `count_share` `0.40` | unit |
| AC-20 | Two fake themes, `Beta` and `Alpha`, each with `weight_share` 0.30 | `infer start` | `themes[0].name` `Alpha`, `themes[1].name` `Beta` | unit |
| AC-21 | Fake theme reply with a methodology quote absent from the document | `infer start` | That theme has `stated_in_methodology` `false` and no quote | unit |
| AC-22 | Fixture embeddings forming 2 separable groups of 12 chunks | `infer start` | Run JSON `clusters` has 2 entries, each with 10 terms | unit |
| AC-23 | 3 stocks with 8 near-identical chunks each (HDBSCAN finds no cluster) | `infer start` | Exit 0; `clusters` `[]`; `stage` `themes_ready` | unit |
| AC-24 | A run at `profiled` | `infer pick <run> --theme 1` | Exit 1; stderr `Run <run_id> is at stage 'profiled'; 'pick' needs 'themes_ready'.` | unit |
| AC-25 | A run at `themes_ready` | `infer pick <run> --theme 1` | `arp taxonomy show <taxonomy_id>` prints `derivation_method` `stock_inference` and status `draft` | unit |
| AC-26 | Fake synthesis returns activity `A` with a grounded chunk quote and activity `B` with none | `infer pick` | The saved taxonomy has `A` (its `citations` hold that quote) and not `B` | unit |
| AC-27 | Fake mapping assigns `p3` to an activity without citing `p3`'s text | `infer pick` | Run JSON `mapping` has no entry for `p3`; `p3` is in `coverage.unmapped` | unit |
| AC-28 | Profiled weights 0.50 of a 1.00 fund; mapped stocks weigh 0.30 | `infer pick` | Taxonomy `source_notes` contains `Coverage: 0.60 of profiled weight, 0.30 of fund weight.` | unit |
| AC-29 | A methodology activity and a stock activity that the fake matcher marks the same | `infer pick` with methodology given at `start` | One merged activity with `origin` `both` and citations from both sides | unit |
| AC-30 | `--segments` gives `p1` 60 %, `p2` 25 %, `p4` 5 % of revenue in mapped activities; `p5` has no segment row | `infer pick` | Run JSON company tiers: `p1` `core`, `p2` `enabler`, `p4` `adopter`, `p5` `unknown` | unit |
| AC-31 | Fake keyword reply: primary `PEM stack` (in a supporting stock's chunk) and `fusion reactor` (in none) | `infer pick` | The activity's `seed_keywords` has `PEM stack` and not `fusion reactor` | unit |
| AC-32 | Fake `draft_schema` returns 3 KPI fields | `infer pick` | The saved taxonomy's `theme.kpis` holds those 3, in order | unit |
| AC-33 | A ratified taxonomy with 3 activities and no KPIs | `build_taxonomy_schema` | Output identical to `main`'s output for the same taxonomy | unit |
| AC-34 | Same taxonomy with 2 KPIs | `build_taxonomy_schema` | Output equals AC-33's fields followed by the 2 KPIs | unit |
| AC-35 | Methodology fixture stating "minimum free-float market capitalisation of USD 500 million", "constituents capped at 8 %", "reviewed semi-annually" | `infer start --methodology <fixture>` | `index_rules.construction_spec` validates as `ConstructionSpec` with a `MetricThresholdScreen` on `float_mcap` `min_value` `500000000`, `single_name_cap` `0.08`, `review_frequency` `semi_annual` | unit |
| AC-36 | Same fixture, plus "companies must derive revenue from hydrogen technologies" | `infer start --methodology <fixture>` | That rule is in `index_rules.rules` with its quote and `mapped_to` `null` | unit |
| AC-37 | Fake rule extraction returning a quote absent from the document | `infer start --methodology <fixture>` | That rule is not in `index_rules.rules` | unit |
| AC-38 | Any stocks | `arp taxonomy create X --method empirical`, then with `etf_index_holdings` | Each exits 1; stderr `--method <m> is replaced by 'arp taxonomy infer start --stocks <file>'.` with `<m>` filled in | unit |
| AC-39 | API | `POST /taxonomies` with `method` `empirical`, then `etf_index_holdings` | Each HTTP 422; `detail` equals the AC-38 string | unit |
| AC-40 | A saved taxonomy from `main` with `derivation_method` `empirical` | `arp taxonomy show <id>` | stdout identical to the same command on `main` | unit |
| AC-41 | Existing test files for `llm_draft`, `industry_anchored`, `authority_source`, `news_transcript_mining`, `universe overlap` | full backend test run | All pass unchanged (any test changed is listed in the PR) | unit |
| AC-42 | Golden: the tune split of `electrolyser_makers` (33 stocks, no weights → seeded 30), golden documents, real model | `infer start`, then `scripts/score_stock_inference.py --run <id> --cases <cases.json> --split tune` | The top theme's name contains `electroly` (case-insensitive), and its supporting stocks include ≥ 80 % of the profiled core and peripheral stocks that have a description; exits 0 | golden (by hand) |
| AC-43 | Golden: same run, `infer pick` on that theme | `scripts/score_stock_inference.py ... --split tune --check mapping` | ≥ 80 % of profiled `not` stocks with a description are mapped to `none` or to an activity that no profiled `core` stock is mapped to; exits 0 | golden (by hand) |
| AC-44 | Golden: the holdout split, same commands | as AC-42/43 with `--split holdout` | Scores posted on the PR; not merge-blocking; prompts are never tuned on holdout runs | golden (by hand) |

Must not change: AC-5, AC-33, AC-40 and AC-41.
