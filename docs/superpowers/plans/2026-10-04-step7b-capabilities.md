# Step 7b: Coverage and capabilities — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** This step adds three ready-made extraction schemas:
- green and low-carbon revenue, CapEx and OpEx for any company, inside or outside the EU Taxonomy;
- the EU Taxonomy KPIs that companies report;
- ESG factors in executive pay.

It also adds:
- European ESEF filings, with their tagged facts going straight into "structured data first";
- publishing of tagged values;
- extraction runs triggered by new filings;
- portfolio groups and GICS grouping;
- calendar triggers for the schedulers;
- an audit row for every Q&A answer.

**Architecture:**
- **Preset schemas.**
  - The three schemas are built in code, the same way as `portfolio/climate/schemas.py build_climate_schema()`, in a new package `arp/presets/`.
  - They are flat field sets: one `FieldDefinition` per value, because `ExtractedField.value` is a scalar.
  - So they reuse the whole existing engine: tagged-first, grounding, verifier/adjudicator, checks, review, publish.
  - They are installed into the `SchemaRegistry` as drafts. The usual trial, first-audit and release flow then applies.
- **Derived numbers are computed, never extracted:**
  - green beyond the Taxonomy;
  - the effective weight of an ESG pay multiplier;
  - the 10% class.

  They come from pure summary functions served by read endpoints.
- **ESEF.** `ingestion/esef.py` parses inline XBRL with `lxml` (installed) and `zipfile`. An ESEF fact lives inside the stored filing, so its citation grounds against the stored text and publishes through the existing lineage gate.
- **SEC tagged values publish too.** The SEC companyfacts JSON is frozen as a stored original, with rendered text that the citations point into.
- **The rest** extends existing seams: `ChangeDetector` (E20), `PortfolioStore` and aggregation (E23), `IntervalScheduler` (E24), and the Q&A endpoints (E25).

**Tech Stack:** Python 3.11, FastAPI, Typer, Pydantic v2, `lxml` and `beautifulsoup4` (both already dependencies), stdlib `zipfile`/`csv`/`hashlib`/`json`/`datetime`, `httpx` (installed); pytest. Frontend is not touched in this step.

**Spec:** ARP Technical Enhancement Specification, Claude Doc `https://claude.ai/code/artifact/88d67850-3c01-4d47-89a2-72b8738943c4`. This plan covers rows E16, E20, E22, E23, E24 and E25, as amended by the user on 4 October 2026:
- **E19 (market-data feed) is parked.**
- **E22 is split.**
  - (A) green and low-carbon revenue, CapEx and OpEx that are *not* limited to the EU Taxonomy, for European, US and global firms;
  - (B) a separate extraction of reported EU Taxonomy values.
- **New:** (C) ESG factors in executive remuneration. This covers:
  - whether ESG is used at all;
  - whether it is climate, low-carbon or transition related;
  - its weight in the short-term (STI) and long-term (LTI) incentive;
  - whether that weight is below 10% or 10% and above;
  - an alternative measure for multipliers.

The user's defaults:
- the multiplier alternative is the *effective weight equivalent*, meaning the largest swing in payout as a percentage of the target;
- exactly 10% counts as "10% or above";
- the green categories are the ones listed in Task 2, with transition kept separate from green;
- for pay, the CEO is always covered, and the executive committee where disclosed.

Paths are relative to `backend/` unless they start with `docs/`. This plan builds on steps 1 to 7a.

**Decisions taken here:**
- **Preset installation.** `arp/presets/registry.py PRESETS: dict[str, Callable[[], DataPointSchema]]` holds the three builders. The fixed schema ids are:
  - `sch_green_lowcarbon`
  - `sch_eu_taxonomy`
  - `sch_esg_remuneration`

  `arp extract presets list | install <id>` and `GET /api/extraction/presets` / `POST /api/extraction/presets/{id}/install` (analyst) save the preset with `SchemaRegistry.save`. Installing the same content again is a no-op.
- **Two new generic checks, on layer 3:**
  - `CheckConfig.le_of: list[str] = []`: this value must be ≤ each listed sibling for the same period. Severity warn.
  - `CheckConfig.sum_target: float | None = None`: together with `sum_of`, the listed parts plus this field must add up to the target (for example 100). Severity warn, using `sum_tolerance`.
- **Green criteria.**
  - The criteria table is `normalise/tables/green_categories_v1.csv`, with columns `category_id,label,kind,description,include,exclude,eu_objective`. `kind` is `green` or `transition`. It is guarded by the step 7a manifest.
  - The green schema's fields are generated from this table, so a new category means a new table version and a new schema version.
  - The categories are: renewable energy, energy efficiency, clean transport, green buildings, grids and storage, hydrogen, carbon capture/use/storage, low-carbon materials and products, circular economy, water and pollution control. Transition is kept separate.
- **Taxonomy status for green amounts.** For each metric, the green total is split into `eu_aligned`, `eu_eligible_not_aligned` and `eu_not_covered`, and the three must add up to the green total (`sum_of`). Green beyond the Taxonomy is computed as green total minus aligned.
- **Pay mechanisms.** `mechanism` is one of `weighted`, `multiplier`, `underpin`, `discretion` or `none`. Two numbers are derived:
  - **Effective weight:**
    - for a weighted metric, the ESG weight;
    - for a multiplier, `max(max_factor - 1, 1 - min_factor) × 100`;
    - for underpin, discretion or none, `None`.
  - **10% class:** `"10_or_above"` when the effective weight is ≥ 10, `"below_10"` when it is below, and `None` when the weight is unknown.
- **No new ESEF tags for Taxonomy KPIs.** There is no stable XBRL concept for them yet, so they are extracted from text and tables.
- **ESEF fetching.**
  - Filings come from the filings.xbrl.org public index, looked up by LEI. It is opt-in (`esef_enabled = False`), and tests never touch the network; the HTTP client is injected.
  - ESEF facts are offered to the tagged path through a small protocol, `FactSource.fact_for_tags(tags, *, fiscal_year) -> XbrlFact | None`. The SEC companyfacts JSON is wrapped in the same protocol.
- **E20.** New-filing runs are off by default, with an empty `schema_ids` list. Each `(company_id, schema_id, document sha256)` fires at most once, and there is a daily cap (`max_runs_per_day = 20`).
- **E23.** A group is resolved at save time, so its member list is stored and a reload returns exactly that set. GICS levels come from code prefixes (2/4/6/8 digits), using a user-supplied mapping from company to GICS code plus the existing `gics_reference_path` for labels. Without those files the dimension shows `None`.
- **E24.** A calendar sits on top of the existing daily tick:
  - `calendar_dates: list[str]` (ISO dates) and/or `calendar_rule: "month_end" | "quarter_end" | None`, as fields on a scheduler's config;
  - fires once per due date, tracked by `last_calendar_fire`;
  - the interval behaviour is unchanged when neither is set.
- **E25.**
  - Audit rows go to `settings.qa_audit_path`, an append-only JSONL file. Each row holds the time, the user id (internal only), the endpoint, the question, a sha256 of the answer and the data vintage.
  - Approvers can read them back with names, never user ids.
  - Every call writes a row, including unresolvable questions and errors.

## Global Constraints

- VOTING IS FROZEN. Do not change any of these:
  - `arp/api/routers/voting.py`, `arp/voting/`, `arp/cli/voting.py`, `arp/stewardship/voting_feed.py`
  - the voting tests
  - frontend `BallotReview.tsx`, `ReviewerField.tsx`, `ConfirmDecision.tsx`, `useReviewer`, and the voting pages

  The voting router stays unauthenticated.
- No new dependencies.
- Never invent FX rates.
- The grounding gate must never be weakened.
- Dev auth mode stays the default.
- Clients never see `user_id`.
- No model identifiers in code, commits or docs.
- Old rows and old schemas stay readable. Every new model field has a default.
- New schedulers, triggers and network sources are off by default.
- Tests never use the network.
- Backend checks: `cd backend && ARP_TEST_POSTGRES_DSN=postgresql+psycopg://arp:arp@localhost:5432/arp_test python -m pytest -q && ruff check arp tests`. The failures must equal the 42-failure Postgres baseline.

## Review Focus

1. A pay plan that combines a weighted ESG metric with a multiplier: the effective weight uses the weighted part, and the summary notes that a multiplier is also present. *(Task 4 test.)*
2. A company that reports green revenue under its own definition and also reports EU Taxonomy alignment: aligned must be ≤ green, and the computed "beyond Taxonomy" figure is never negative. If it would be, it is flagged, not clipped. *(Tasks 2 and 3 tests.)*
3. An ESEF fact whose scale or sign attributes change the printed number (`scale="6"`, `sign="-"`): the parsed value is right, and the citation still points at the printed text. *(Task 5 test.)*
4. The same new filing seen twice (the poll repeats, or the webhook is retried): exactly one run. *(Task 7 test.)*
5. A Q&A call that fails or cannot resolve the question: it still gets an audit row. *(Task 10 test.)*

---

### Task 1: Preset schemas infrastructure and two generic checks

**Files:**
- Create: `arp/presets/__init__.py`, `arp/presets/registry.py`
- Modify:
  - `arp/schemas/datapoints.py`: `CheckConfig.le_of`, `CheckConfig.sum_target`
  - `arp/checks/plausibility.py`: `check_less_or_equal`, `check_sum_to_target`
  - `arp/checks/__init__.py`: register both on layer 3
  - `arp/api/routers/extraction.py`: the presets endpoints
  - `arp/cli/extraction.py`: `extract presets list | install`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_presets_infra.py`

**Interfaces:**
- Produces:
  - `PRESETS: dict[str, Callable[[], DataPointSchema]]`. It is empty in this task; Tasks 2–4 add to it.
  - `install_preset(preset_id: str, registry: SchemaRegistry) -> DataPointSchema`, which raises `KeyError` for an unknown id and returns the saved version.
  - `check_less_or_equal(spec, field, ctx)` with `check_id="le_of"`. It is not applicable unless there is a sibling with the same `period_end` and the same canonical unit; percentage siblings compare as percentages.
  - `check_sum_to_target(spec, field, ctx)` with `check_id="sum_target"`. It is only applicable when `spec.check_config.sum_target is not None` and every part is present.
  - `GET /api/extraction/presets` returns `[{preset_id, name, field_count}]`. `POST /api/extraction/presets/{preset_id}/install` requires analyst, gives 404 for an unknown id, and returns the saved schema's id and version.

- [ ] **Step 1: Write the failing tests.**
  - `test_le_of_warns_when_exceeding`: aligned 40 against eligible 30 fails with severity warn. 30 against 40 passes.
  - `test_le_of_not_applicable_on_other_period`
  - `test_sum_to_target_100`: 60 + 30 + 10 passes, 60 + 30 + 20 fails, and with tolerance 0.01 the value 100.5 passes.
  - `test_install_preset_idempotent`: register a dummy preset in a test. Installing twice gives the same version.
  - `test_presets_endpoint_and_install_requires_analyst`
- [ ] **Step 2:** Run `pytest tests/test_presets_infra.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_presets_infra.py tests/test_checks_*.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(presets): preset schema registry, le_of and sum_target checks`

### Task 2: Green and low-carbon revenue, CapEx and OpEx (E22 A)

**Files:**
- Create:
  - `arp/normalise/tables/green_categories_v1.csv`, plus its manifest entry
  - `arp/presets/green.py`
- Modify:
  - `arp/presets/registry.py`: add `sch_green_lowcarbon`
  - `arp/api/routers/extraction.py`: `GET /api/extraction/runs/{run_id}/green-summary`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_presets_green.py`

**Interfaces:**
- Consumes: Task 1's `PRESETS`, `le_of`, `sum_of` and `part_of`.
- Produces:
  - `load_green_categories() -> list[GreenCategory]`, where `GreenCategory` has `category_id`, `label`, `kind` and the other columns. It is cached, and the table name is `GREEN_TABLE = "green_categories_v1"`.
  - `build_green_schema() -> DataPointSchema`, with schema id `sch_green_lowcarbon`. For each metric `m` in `revenue`, `capex` and `opex`, these fields are generated, all with `required=False`:
    - `{m}_total`: currency, non-negative.
    - `green_{m}_total`: currency, `part_of={m}_total`, and `sum_of` = every green-kind category field.
    - `green_{m}_share_pct`: percentage.
    - `transition_{m}_total`: currency, `part_of={m}_total`.
    - One `green_{m}_{category_id}` field per green-kind category: currency, `part_of=green_{m}_total`.
    - `green_{m}_eu_aligned`, `green_{m}_eu_eligible_not_aligned` and `green_{m}_eu_not_covered`: currency, `part_of=green_{m}_total`. The green total carries a second identity over these three, done through a separate helper field `green_{m}_eu_split_total` with `sum_of` the three and `le_of` the green total.
    - `green_{m}_framework`: an enum of `own_definition`, `eu_taxonomy`, `icma_gbp`, `climate_bonds`, `china_catalogue` or `other`.
    - `green_{m}_definition`: a string holding the company's own definition, quoted.

    Every field's `extraction_instructions` names the category's include and exclude rules from the table, and the table version.
  - `green_summary(fields: list[dict]) -> list[GreenSummaryRow]`, computed per metric and period:
    - `green_total`, `aligned` and `share`;
    - `beyond_taxonomy = green_total - aligned`, which is `None` if either is missing;
    - `flag="aligned_exceeds_green"` when it would be negative. The value is never clipped.
  - The endpoint reads the run's results and returns the summary rows.

- [ ] **Step 1: Write the failing tests.**
  - `test_table_in_manifest`: the manifest check passes and the table has exactly the 10 categories plus transition.
  - `test_schema_generated_from_table`: the field ids are as specified for all three metrics, the green total's `sum_of` equals the green-kind category ids, and every new field is a draft.
  - `test_green_summary_beyond_taxonomy`: green 100 and aligned 40 give 60.
  - `test_aligned_exceeding_green_flagged_not_clipped` (Review Focus 2): green 30 and aligned 40 give `beyond_taxonomy == -10` with the flag set.
  - `test_install_and_trial_run_smoke`: install the preset, create a trial run (`trial=True`) with the fake LLM, and check it completes and produces rows. Reuse the pipeline test fakes.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_presets_green.py tests/test_normalise_tables_manifest.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(presets): green and low-carbon revenue, CapEx and OpEx schema with versioned criteria (E22)`

### Task 3: EU Taxonomy reported KPIs (E22 B)

**Files:**
- Create: `arp/presets/eu_taxonomy.py`
- Modify:
  - `arp/presets/registry.py`: add `sch_eu_taxonomy`
  - `arp/presets/green.py`: `green_summary` also reads aligned values from an EU Taxonomy run when one is supplied
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_presets_eu_taxonomy.py`

**Interfaces:**
- Produces: `build_eu_taxonomy_schema()` with schema id `sch_eu_taxonomy`. For each KPI `k` in `turnover`, `capex` and `opex`, all percentage fields with `required=False`:
  - `eut_{k}_aligned_pct`, `eut_{k}_eligible_not_aligned_pct` and `eut_{k}_not_eligible_pct`. The not-eligible field carries `sum_of` the other two and `sum_target=100`.
  - `eut_{k}_aligned_{obj}_pct` for each objective `obj` in `ccm`, `cca`, `wtr`, `ce`, `ppc` and `bio`, each with `part_of=eut_{k}_aligned_pct`. A helper `eut_{k}_aligned_by_objective_total` has `sum_of` the six and `le_of` the aligned share. It is `le_of` and not equality, because objectives can be double-counted under the double-counting rule.
  - `eut_{k}_enabling_pct` and `eut_{k}_transitional_pct`, each `le_of` the aligned share.
  - `eut_{k}_total_amount`: currency, the KPI denominator.

  Also:
  - `eut_nuclear_gas_reported`: an enum of `yes`, `no` or `not_disclosed`, for the Complementary Delegated Act Template 1.
  - `eut_reporting_year`: a date or string.

  Instructions point at the mandatory Taxonomy KPI tables.
- `green_summary(fields, eu_taxonomy_fields=None)`: when an EU Taxonomy run is given, its aligned amount (aligned % × total amount) is used as `aligned` if the green schema's own `eu_aligned` field is missing. Turnover maps to revenue.

- [ ] **Step 1: Write the failing tests.**
  - `test_shares_sum_to_100_check`: 40 + 35 + 25 passes, and 40 + 35 + 30 fails `sum_target`.
  - `test_aligned_le_eligible_relation`: the enabling share above the aligned share fails `le_of`.
  - `test_schema_ids_and_drafts`
  - `test_green_summary_uses_eu_taxonomy_when_missing` (Review Focus 2): the green run has turnover green 100 and no aligned value, and the EU Taxonomy run has 30% aligned of a 200 total, so aligned is 60 and beyond is 40.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_presets_eu_taxonomy.py tests/test_presets_green.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(presets): EU Taxonomy reported KPI schema (E22)`

### Task 4: ESG factors in executive remuneration (new)

**Files:**
- Create: `arp/presets/remuneration.py`
- Modify:
  - `arp/presets/registry.py`: add `sch_esg_remuneration`
  - `arp/api/routers/extraction.py`: `GET /api/extraction/runs/{run_id}/remuneration-summary`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_presets_remuneration.py`

**Interfaces:**
- Produces: `build_remuneration_schema()` with schema id `sch_esg_remuneration`. The source routing prefers the proxy statement (DEF 14A) and the remuneration report.
  - `rem_scope`: an enum of `ceo` or `executive_committee`, saying which group the disclosure covers.
  - `rem_esg_in_pay`: an enum of `yes`, `no` or `not_disclosed`.
  - For each plan `p` in `sti` and `lti`:
    - `rem_{p}_esg_present`: an enum of `yes`, `no` or `not_disclosed`.
    - `rem_{p}_esg_metrics`: a string, the metric names separated by semicolons.
    - `rem_{p}_climate_related`: an enum of `yes`, `no` or `not_disclosed`.
    - `rem_{p}_climate_metric_types`: a string, separated by semicolons, from the list `emissions_reduction`, `renewable_share`, `green_revenue_or_capex`, `sbti_target`, `transition_plan_milestone`, `energy_efficiency`, `other_climate`.
    - `rem_{p}_mechanism`: an enum of `weighted`, `multiplier`, `underpin`, `discretion` or `none`.
    - `rem_{p}_esg_weight_pct`: a percentage, `min_value=0`, `max_value=100`.
    - `rem_{p}_climate_weight_pct`: a percentage, `le_of=rem_{p}_esg_weight_pct`.
    - `rem_{p}_multiplier_min` and `rem_{p}_multiplier_max`: numbers between 0 and 3. The minimum has `le_of` the maximum.
    - `rem_{p}_multiplier_direction`: an enum of `up`, `down` or `both`.
    - `rem_{p}_has_multiplier_also`: an enum of `yes` or `no`, for a weighted metric that also has a modifier.
- `RemunerationSummary(plan, scope, esg_present, climate_related, mechanism, weight_pct, multiplier_range, effective_weight_pct, threshold_class, also_multiplier, notes: list[str])`, built by `remuneration_summary(fields: list[dict]) -> list[RemunerationSummary]`:
  - `effective_weight_pct` follows the rules in the decisions above.
  - When the mechanism is weighted and `has_multiplier_also == "yes"`, the effective weight is the weight and `notes` includes `"also has an ESG multiplier"`.
  - `threshold_class` is `"10_or_above"` when ≥ 10.0, so 10.0 counts as "10% or above".
- The endpoint returns the summary rows for one run.

- [ ] **Step 1: Write the failing tests.**
  - `test_weighted_15_is_10_or_above`
  - `test_weighted_exactly_10_is_10_or_above`
  - `test_weighted_8_is_below_10`
  - `test_multiplier_09_to_115_effective_15`: max(0.15, 0.1) × 100 = 15, which is 10 or above.
  - `test_multiplier_095_105_effective_5_below_10`
  - `test_underpin_or_discretion_has_no_weight`: weight `None`, class `None`.
  - `test_weighted_plus_multiplier_note` (Review Focus 1)
  - `test_climate_weight_le_esg_weight_check`
  - `test_schema_ids_and_routing`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_presets_remuneration.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(presets): ESG in executive remuneration schema with effective weight and 10% class`

### Task 5: European ESEF filings (E16)

**Files:**
- Create: `arp/ingestion/esef.py`
- Modify:
  - `arp/ingestion/xbrl.py`: a `FactSource` protocol, plus a `CompanyFactsSource` wrapper over the SEC JSON implementing `fact_for_tags(tags, *, fiscal_year)`
  - `arp/extraction/field_graph.py` (`_try_tagged`) and `arp/extraction/pipeline.py`: consume a `FactSource` instead of a raw dict, merging the SEC and ESEF sources (ESEF first for non-US filers)
  - `arp/ingestion/local_files.py`: `.xhtml` and ESEF `.zip` packages parse through `esef.parse_package` text
  - `arp/discovery/crawler.py` and `arp/discovery/downloader.py`: accept `.xhtml` and `.zip`
  - `arp/config.py`: `esef_enabled: bool = False`, `esef_index_url`
  - the registry builders that assemble `DocumentSourceRegistry([...])`: add `EsefDocumentSource` when enabled
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_esef.py` and `tests/fixtures/esef/` (a small hand-written iXBRL XHTML and its zipped report package)

**Interfaces:**
- Produces:
  - `EsefFact(concept: str, value: float, unit: str | None, period_start: str | None, period_end: str, decimals: str | None, char_start: int, char_end: int, printed: str)`.
  - `parse_ixbrl(xhtml: bytes) -> tuple[str, list[EsefFact]]`. It returns the visible text, which matches the text extraction exactly so the offsets hold, and the facts from `ix:nonFraction`. It applies `scale`, `sign="-"` and `format` (ixt `num-dot-decimal` and `num-comma-decimal`), resolves `contextRef` periods and units from `xbrli:context` and `xbrli:unit`, and uses `lxml` only.
  - `parse_package(data: bytes) -> tuple[str, list[EsefFact]]`. It takes a zip, finds `reports/*.xhtml` (the largest one, if there are several), and rejects zip bombs using the same decompressed-size cap pattern as the holdings intake.
  - `EsefFactSource(facts: list[EsefFact], doc: SourceDocument)` implements `fact_for_tags(tags, *, fiscal_year)`. It matches `ifrs-full:Revenue`-style concepts, takes duration facts of about a year ending in that fiscal year, and prefers the most precise duplicate. Its `XbrlFact`'s `as_citation` returns a citation with the document's `doc_id`, `content_key` and `parser_version`, `char_start`/`char_end`, `quote` = the printed text, and `grounded=True`. It is a real span in a stored original, so it is publishable.
  - `EsefDocumentSource(DocumentSource)` looks a filing up by the company's LEI through an injected `httpx.AsyncClient`. It store-or-fails the original (`upload_or_fail`), registers the document (as `EdgarDocumentSource` does), and sets the language and decimal through `normalise.locale`.

- [ ] **Step 1: Write the failing tests.**
  - `test_esef_filing_yields_tagged_facts_through_e29` (the spec's test): a field with `xbrl_tags=["ifrs-full:Revenue"]` and the fixture filing loaded as a document and fact source gives `method == "tagged"`, a citation inside the stored text, and 0 model calls.
  - `test_scale_and_sign` (Review Focus 3): `scale="6"` and `sign="-"` give the right value, and the citation span equals the printed text.
  - `test_comma_decimal_format`
  - `test_package_zip_and_bomb_rejected`
  - `test_esef_citation_publishable`: the candidate passes `lineage_error` with the fixture blob stored.
  - `test_crawler_accepts_xhtml_and_zip`
  - `test_source_off_by_default`: no network call is made when `esef_enabled` is false.
  - `test_sec_companyfacts_wrapper_unchanged`: the step 7a tagged tests pass through `CompanyFactsSource`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_esef.py tests/test_tagged_first.py tests/test_xbrl.py tests/test_checks_cross_source.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ingestion): ESEF iXBRL filings with tagged facts into structured-data-first (E16)`

### Task 6: Publishing SEC tagged values (carried from 7a)

**Files:**
- Modify:
  - `arp/ingestion/xbrl.py`: `fetch_company_facts` keeps the raw bytes and freezes them, and `as_citation` gains `content_key`, `parser_version` and the span
  - `arp/orchestration/reground.py`: skip `xbrl_companyfacts` parser versions, as for EDGAR
  - the plan and the TECHNICAL_REFERENCE E29 paragraph: remove the "not published" limitation
- Test: `tests/test_xbrl_publish.py`

**Interfaces:**
- Produces:
  - `freeze_company_facts(raw: bytes, cik: str, *, blob_store, content_store) -> FrozenFacts(doc_id, content_key, parser_version, text)`.
    - It store-or-fails the raw JSON under `sha256(raw)` and registers the document as `xbrl:{cik}:{sha[:16]}`, setting `storage_uri`.
    - It renders one line per annual fact, `"{taxonomy}:{name} = {value} {unit} (period ending {end}, form {form}, filed {filed})"`, and stores that text under `(content_key, parser_version="xbrl_companyfacts_v1")`.
    - It is idempotent.
  - `XbrlFact.as_citation(cik, *, frozen: FrozenFacts | None = None)`. With `frozen`, it sets `doc_id`, `content_key`, `parser_version`, and the `char_start`/`char_end` of its rendered line, using a quote equal to that line. Without it, the behaviour is the old one.

- [ ] **Step 1: Write the failing tests.**
  - `test_tagged_value_publishes`: a tagged run with frozen facts publishes the fact.
  - `test_missing_frozen_original_blocks_release`: delete the blob, and lineage gives `original_missing`.
  - `test_reground_skips_xbrl_versions`
  - `test_old_tagged_rows_still_load`
  - Update step 7a's `test_tagged_value_is_refused_by_publish_not_dropped` to the new behaviour, with a note.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_xbrl_publish.py tests/test_tagged_first.py tests/test_publish*.py tests/test_reground_parser.py -q` (with the DSN). Expected: PASS.
- [ ] **Step 5:** Commit: `feat(publish): tagged XBRL values publish through a frozen companyfacts original`

### Task 7: Event-driven refresh (E20)

**Files:**
- Create: `arp/discovery/refresh.py`
- Modify:
  - `arp/discovery/change_detector.py`: an optional `on_events: Callable[[list[DocumentEvent]], Awaitable[None]] | None`, called after the events are recorded, with its errors logged and never raised
  - `arp/discovery/pipeline.py` and `arp/extraction/pre_steps.py`: pass `on_events` when refresh is enabled
  - `arp/config.py`: `event_refresh_enabled: bool = False`, `event_refresh_schema_ids: list[str] = []`, `event_refresh_max_runs_per_day: int = 20`, `event_refresh_state_dir`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_event_refresh.py`

**Interfaces:**
- Produces: `async refresh_on_events(events, *, settings, run_store, registry, launcher=None) -> list[str]`, which returns the run ids it started.
  - It does nothing unless refresh is enabled and the schema list is not empty.
  - For each `NEW_DOCUMENT` or `UPDATED_DOCUMENT` event, and each configured released schema (`SchemaRegistry.get`, skipping unreleased ones with a warning), it creates one extraction run for `[CompanyRef(company_id=..., name=...)]` with `create_extraction_run`, then launches it with `get_job_launcher().launch(run_id, lambda: execute_extraction_run(...), run_store=run_store)`.
  - It dedupes on `(company_id, schema_id, document.sha256)` in `event_refresh_state_dir/fired.jsonl`, and caps runs per UTC day.

- [ ] **Step 1: Write the failing tests.** Use an injected launcher fake.
  - `test_new_filing_triggers_one_run` (the spec's test)
  - `test_same_filing_twice_one_run` (Review Focus 4)
  - `test_disabled_or_empty_schema_list_no_runs`
  - `test_unreleased_schema_skipped`
  - `test_daily_cap`
  - `test_change_detector_calls_on_events_and_survives_errors`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_event_refresh.py tests/test_discovery*.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(discovery): new filings trigger one extraction run per issuer and schema (E20)`

### Task 8: Portfolio groups and GICS (E23)

**Files:**
- Modify:
  - `arp/schemas/portfolio.py`: `PortfolioGroup`
  - `arp/storage/portfolio_store.py` and `arp/storage/postgres_portfolio_store.py`: `save_group`, `get_group`, `list_groups`, mirroring how analytics are stored in each
  - `arp/portfolio/aggregation.py`: GICS dimensions
  - `arp/research/standards_mapping/gics.py`: `load_company_gics(path)` and a label lookup
  - `arp/config.py`: `company_gics_path: Path | None = None`
  - `arp/api/routers/portfolio.py`: `POST/GET /api/portfolio/groups`, `GET /api/portfolio/groups/{id}`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_portfolio_groups.py`, plus a `_pg` variant for the Postgres store

**Interfaces:**
- Produces:
  - `PortfolioGroup(group_id: str = new_id("grp"), name: str, kind: Literal["portfolios", "companies", "securities"], members: list[str], created_at: str, created_by: str)`. The members are stored resolved and sorted. A save with an existing id creates a new version, and the latest version wins on read.
  - The aggregation dimensions gain `gics_sector`, `gics_industry_group`, `gics_industry` and `gics_sub_industry`, taken from the code prefixes 2/4/6/8 with labels from the reference file, or `None`.
  - The endpoints: saving requires analyst, reading requires a signed-in user, and `created_by` is the name, never the user id.

- [ ] **Step 1: Write the failing tests.**
  - `test_group_reload_returns_same_set` (the spec's test)
  - `test_group_saved_resolved_and_sorted`
  - `test_aggregate_by_gics_sector_with_fixture`
  - `test_gics_missing_files_gives_none`
  - `test_pg_store_parity_pg`
  - `test_group_api_hides_user_id`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_portfolio_groups.py tests/test_portfolio*.py -q` (with the DSN). Expected: PASS.
- [ ] **Step 5:** Commit: `feat(portfolio): saved portfolio groups and GICS grouping (E23)`

### Task 9: Calendar triggers (E24)

**Files:**
- Modify:
  - `arp/orchestration/interval_scheduler.py`: an optional calendar mode
  - `arp/emerging_themes/scheduler.py` and `arp/portfolio/monitoring/scheduler.py`: their config models gain `calendar_dates`, `calendar_rule` and `last_calendar_fire`
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_calendar_triggers.py`

**Interfaces:**
- Produces:
  - `calendar_due(today: date, *, dates: list[str], rule: Literal["month_end", "quarter_end"] | None, last_fire: str | None) -> str | None`, pure. It returns the ISO due date to fire, or `None`.
    - A due date from the list fires on that date, or on the next tick if the tick missed it, but only when it is later than `last_fire`.
    - `month_end` is the last calendar day of the month, and `quarter_end` is the last day of March, June, September or December.
  - `IntervalScheduler`: when the config has calendar fields set, `_apply` ticks every 24 hours, and `_run_scheduled` runs `_run` only when `calendar_due` returns a date, then records `last_calendar_fire`. Without calendar fields the behaviour is unchanged.

- [ ] **Step 1: Write the failing tests.**
  - `test_trigger_fires_on_fixed_date` (the spec's test): the date list holds `2026-11-15`. 2026-11-14 does not fire, 2026-11-15 does, and a second tick the same day does not.
  - `test_missed_date_fires_next_tick_once`
  - `test_month_end_and_quarter_end_rules`
  - `test_interval_mode_unchanged_without_calendar`
  - `test_emerging_themes_and_monitoring_configs_accept_calendar`
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_calendar_triggers.py tests/test_*scheduler*.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(schedulers): calendar triggers on fixed dates, month end and quarter end (E24)`

### Task 10: Q&A audit (E25)

**Files:**
- Create: `arp/portfolio/qa_audit.py`
- Modify:
  - `arp/config.py`: `qa_audit_path` (default `portfolios_dir/qa_audit.jsonl`)
  - `arp/api/routers/portfolio.py`: `POST /api/portfolio/ask` writes an audit row, and `GET /api/portfolio/qa-audit` returns them (approver only)
  - `arp/api/routers/bi.py`: `POST /api/bi/ask` writes an audit row
  - `arp/portfolio/qa_agent.py`: `QAAnswer` gains `vintage: dict = {}`, filled with `holdings_as_of` and any `observation_dates` used
  - `docs/TECHNICAL_REFERENCE.md`
- Test: `tests/test_qa_audit.py`

**Interfaces:**
- Produces:
  - `record_answer(settings, *, endpoint: str, principal: Principal, question: str, answer_text: str | None, vintage: dict, error: str | None = None) -> None`, append-only. The row is `{at, endpoint, user_id, user_name, question, answer_sha256 (of answer_text or ""), vintage, error}`.
  - `list_audit(settings, *, limit=200) -> list[dict]`, newest first, with `user_id` removed.
  - Both ask endpoints call `record_answer` in a `try/finally`, so success, an unresolvable question and an exception all write a row. An exception is still raised to the caller.

- [ ] **Step 1: Write the failing tests.**
  - `test_every_answer_has_an_audit_row` (the spec's test): three asks give three rows with matching answer hashes.
  - `test_unresolvable_and_error_still_audited` (Review Focus 5)
  - `test_vintage_holds_holdings_as_of`
  - `test_audit_endpoint_approver_only_and_no_user_id`
  - `test_bi_ask_audited`: use a fake BI client.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `pytest tests/test_qa_audit.py tests/test_portfolio*.py tests/test_bi*.py -q`, then the full backend check. Expected: PASS, and the failures equal the baseline.
- [ ] **Step 5:** Commit: `feat(audit): every Q&A answer leaves an audit row with its data vintage (E25)`
