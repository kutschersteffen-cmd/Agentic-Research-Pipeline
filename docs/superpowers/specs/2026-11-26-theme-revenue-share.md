# Theme revenue share: reported segments and a modelled range

Spec slug: `theme-revenue-share`. R&D Lab upgrade plan items 6 (reported segment revenue) and 7 (modelled share
with a range), approved by the owner 2026-11-25. First child spec of the B1 revenue sizing outline
(`2026-11-01-phase-b-exposure-outline.md`).

Status: draft for owner approval, 2026-11-26.

## Why

Plan finding P5: without an uploaded revenue catalogue CSV, a theme run's exposure is a label (pure play,
significant, minor, none) that `research/arbitration.py` turns into 1.0, 0.6, 0.3 or 0. The XBRL store already
holds each filer's revenue by segment and product line (`segments.jsonl`, specs `2026-11-01-xbrl-segment-revenue-design.md`,
`2026-11-01-xbrl-product-geography-design.md`, `2026-11-02-xbrl-segment-sum-check-design.md`) and the segment note
text (`segment_note.txt`), but no theme run reads them. Nothing estimates a share where the segments do not name
the activity.

This spec makes the revenue resolver (`research/revenue_exposure/resolver.py`) read those files: a segment whose
name matches the activity counts in full and is labelled `reported`; a segment that only its description in the
segment note ties to the activity counts at 30% to 50% (Morningstar's 50-70% discount for description-only
matches), always as a range, labelled `modelled`. A grounded quote stays `extracted`, as today.

## Goals

- A theme company × activity gets a revenue share labelled `reported` from its XBRL segment or product rows when a
  row's name matches the activity.
- Where no row name matches, a share labelled `modelled` with `low_pct` and `high_pct` from segments the segment
  note describes in the activity's words.
- One fixed precedence: `catalogue` → `reported` → `extracted` → `modelled` → the qualitative debate.
- `reported` short-circuits the debate like `catalogue` and `extracted` do; `modelled` does not, it enters
  arbitration as one more signal.
- One setting turns it on for every theme run (API, CLI, resume), with or without a catalogue.
- No LLM call anywhere in the new steps.

## Non-goals

- CapEx and OpEx by segment (the XBRL store has CapEx rows; this spec reads revenue only).
- Segments from the LLM financials extraction (`arp/extraction/segment_extractor_agent.py`); a later spec can add
  them as a second `reported` source.
- Embedding-expanded keywords or an LLM picking segments (Morningstar and MSCI do; here plain keyword match only).
- Company-level rollup across activities, tiers and momentum: item 8 (`theme-company-exposure`) builds on the
  fields defined here.
- Recomputing stored runs. Currency conversion (every share is a ratio within one filing).
- The Theme Workbench and other new screens (items 12-13); only the existing Theme Builder results list changes.
- Changing the matcher's evidence record keys (`matcher-shared-retrieval`, PR #739).

## Anti-goals

- A `modelled` value without both `low_pct` and `high_pct`, or a range on any other source.
- A share computed against a total that failed the XBRL sum check.
- A `modelled` share counted as a hard number: it never skips the debate and never enters the L1 theme layer.
- Any change to runs while the setting is off.

## Decided (defaults chosen by the spec writer)

| Topic | Decision |
|---|---|
| Setting | `theme_revenue_share_enabled: bool = False` (env `ARP_THEME_REVENUE_SHARE_ENABLED`). Off by default, per the B outline rule "setting off by default". |
| Discount | `revenue_share_modelled_low_factor = 0.3`, `revenue_share_modelled_high_factor = 0.5`: a description-only segment counts at 30% to 50% of its revenue. One global pair, not per theme (B1 open question). |
| Arbitration weights | `arbitration_weight_revenue_reported = 1.0` (same as catalogue), `arbitration_weight_revenue_modelled = 0.4`. |
| Point value for `modelled` | `value_pct = (low_pct + high_pct) / 2`, so existing readers of `value_pct` (banding, company role, arbitration signal) keep working. |
| Keywords | The activity's `seed_keywords`; `exclusion_keywords` veto. `contextual_keywords` are not used. Whole words only, so a plural (`electrolysers`) matches only if it is a keyword itself. |
| Axis | Product lines (`axis_kind` `product`, `level` `company`) before reportable segments; geography is used only as a total. |
| Extraction without a catalogue | With the setting on and no catalogue, the resolver does not call the extractor (no new LLM cost). With a catalogue, extraction runs as today. |
| L1 theme layer | `reported` counts like `catalogue` and `extracted`; `modelled` does not. |
| Risk | Implementation slice 1 is `risk:high` (index maths: it changes the L1 layer and arbitration). Slice 2 is `risk:normal`. |

## Design

### Data model (`arp/schemas/revenue_exposure.py`)

- `ExposureDataSource` gains `"reported"` and `"modelled"`.
- `MetricExposure` gains `low_pct: float | None = None` and `high_pct: float | None = None` (0-1). Both are set
  only when `source == "modelled"`.
- `RevenueResolverContext` gains `xbrl_store: XbrlStore | None = None` and `extract_enabled: bool = True`.
  `xbrl_store is None` means the new steps are off.

After the change: `cd backend && python scripts/export_openapi.py`, `cd frontend && npm run gen:api`, commit both.

### Finding the company's rows

1. Store key: `company.cik.zfill(10)` when `company.cik` is set and that key is in `store.ciks()`; otherwise the
   first key in `store.ciks()` whose `store.company_ids(key)` contains `company.company_id`. No key: no rows.
2. Rows: `store.read_segments(key)` with `metric == "revenue"` and `fiscal_year` equal to the highest
   `fiscal_year` among those revenue rows. `<year>` below is that year.
3. A **group** is the rows with one (`axis_kind`, `level`) pair.

### Total `T`

The first group in the order (`segment`, null), (`product`, `standard`), (`product`, `company`), (`geography`, null)
that has at least one row and whose rows all have `sum_matches_total` true. `T` = the sum of that group's `value`s
plus its first row's `reconciling` (null counts as 0). No such group, or `T <= 0`: neither `reported` nor `modelled`
is produced.

### Keyword match

Keyword `k` **matches** text `t` when
`re.search(r"(?<!\w)" + r"\s+".join(map(re.escape, k.split())) + r"(?!\w)", t, re.IGNORECASE)` finds something.
Blank keywords are skipped. A text **matches the activity** when at least one `seed_keywords` entry matches it
and no `exclusion_keywords` entry matches it.

### `reported`

Candidate groups in order: (`product`, `company`), then (`segment`, null). The first candidate group with at least
one row whose `segment` matches the activity is used; its matching rows are the **reported rows**. A candidate
group is used even when its own rows have `sum_matches_total` false: only the group that gives `T` must pass.

- `value_pct = min(sum of reported rows' value / T, 1.0)`, `source = "reported"`, `confidence = 1.0`,
  `low_pct = high_pct = None`.
- `notes = "Reported segments (FY<year>): <names>"`, names = the reported rows' `segment` in file order, joined
  with `", "`.

### `modelled`

Only when no `reported` row was found. Note = `store.read_segment_note(key)`; none: no `modelled`.
Sentences = the note split on `re.split(r"(?<=[.!?])\s+|\n+", note)`, each stripped, blanks dropped.

A row of the (`segment`, null) group is **description-matched** when some sentence both matches the row's
`segment` (as a keyword) and matches the activity.

- `S = min(sum of description-matched rows' value / T, 1.0)`. No such row: no `modelled`.
- `low_pct = S × revenue_share_modelled_low_factor`, `high_pct = S × revenue_share_modelled_high_factor`,
  `value_pct = (low_pct + high_pct) / 2`, `source = "modelled"`, `confidence = 1.0`.
- `notes = "Modelled from segment descriptions (FY<year>): <names>; counted at <lo>-<hi>% of segment revenue."`,
  names as for `reported`, `<lo>` = `f"{low_factor * 100:g}"`, `<hi>` = `f"{high_factor * 100:g}"`
  (defaults give `30-50%`).

### Precedence (`resolve_company_activity_exposure`)

1. `catalogue` for revenue and CapEx, as today.
2. Revenue still `unresolved` and `ctx.xbrl_store` set: `reported`.
3. Extraction for every metric still `unresolved`, as today, only when `ctx.extract_enabled` (and sector-relevant,
   as today).
4. Revenue still `unresolved` and `ctx.xbrl_store` set: `modelled`.

CapEx and OpEx are untouched by steps 2 and 4.

### Matching graph (`research/match_graph.py`)

- `_route_after_revenue` short-circuits to `finalize_from_revenue` when `value_pct` is set and `source` is not
  `"modelled"`. A `modelled` share goes to `gather_evidence` and the debate, as an unresolved one does today.
- `_finalize_from_revenue` describes `reported` as `reported segment revenue`, so its rationale reads
  `Resolved via reported segment revenue: <value_pct:.1%> of revenue attributed to this activity. <notes>`.
  Confidence and `flagged_for_review` rules stay as they are (only `extracted` can be flagged by confidence).

### Arbitration (`research/arbitration.py`)

`_collect_contributions` adds a revenue contribution for `reported` (method `revenue_reported`, weight
`arbitration_weight_revenue_reported`, detail `<value_pct:.1%>`) and `modelled` (method `revenue_modelled`, signal
`value_pct`, weight `arbitration_weight_revenue_modelled`, detail `<low_pct:.1%>-<high_pct:.1%>`). Catalogue and
extracted contributions are unchanged.

### L1 layer (`research/exposure_layers.py`)

`_l1` accepts sources `catalogue`, `extracted` and `reported`.

### Run wiring

`api/routers/themes.py` (POST `/api/themes/runs`), `research/pipeline.py` (resume) and `cli/theme.py` (`arp theme run`)
build the resolver context as follows:

| Setting | Catalogue given | Context |
|---|---|---|
| off | no | none (as today) |
| off | yes | as today (`xbrl_store` None) |
| on | yes | as today plus `xbrl_store = XbrlStore(settings.xbrl_dir)` |
| on | no | `catalogue_by_company={}`, `mappings=[]`, `xbrl_store = XbrlStore(settings.xbrl_dir)`, `extract_enabled=False` |

The POST response's `revenue_exposure_enabled` is true whenever a context is built. `create_theme_run` stores the
setting's value at creation as manifest param `theme_revenue_share` (bool); resume builds its context from that
stored value, not the current setting (a run stored without the param counts as `false`), so a resumed run never
changes method halfway.

### Theme Builder results (`frontend/src/pages/ThemeBuilder.tsx`)

- Badge: `reported (30.0%)` with class `badge badge-high`; `modelled (12.0–20.0%)` (en dash, `low_pct` and
  `high_pct` × 100 to one decimal) with class `badge badge-mid`. Catalogue and extracted badges are unchanged.
- Detail line: `Revenue: 12.0–20.0% (modelled)` for `modelled`; every other source as today.

## Acceptance

Fixtures and conventions (the test-writer builds these from `tests/test_research_pipeline.py` and `tests/conftest.py`):

- `settings = _settings(tmp_path).model_copy(update={"xbrl_dir": tmp_path / "xbrl", "max_concurrent_llm_calls": 1})`
  (the helper in `tests/test_research_pipeline.py`), built after any env var a row sets, so `Settings` picks it up.
  No indirect model and no R&D resolver anywhere.
- XBRL rows are `SegmentRow`s written with `XbrlStore(settings.xbrl_dir).write_segments("0000000001", rows)` plus a
  `meta.json` under that key whose `company_ids` is `["c1"]`. Every row: `company_id` `c1`, `market` `sec`,
  `fiscal_year` 2025, `metric` `revenue`, `concept` `us-gaap:Revenues`, `axis` `us-gaap:StatementBusinessSegmentsAxis`
  (product rows `srt:ProductOrServiceAxis`, geography rows `srt:StatementGeographicalAxis`), `member` = `x:` + the
  segment name without spaces + `Member`, `unit` `USD`, `period_start` `2025-01-01`, `period_end` `2025-12-31`,
  `accession` `0000000001-25-000001`, other fields at their defaults unless the fixture says otherwise. A segment
  note is written with `write_segment_note("0000000001", text)`; note texts are Python string literals.
- Company `c1` = `CompanyRef(company_id="c1", name="Acme Gas")` (no `cik`). Activity `A` = `ActivityDefinition(name="Electrolysers",
  in_scope_description="Makes water electrolysers.", out_of_scope_description="Industrial gas distribution.",
  seed_keywords=["electrolyser", "hydrogen"], exclusion_keywords=["hydrogen peroxide"])`.
- **Fixture R**: (`segment`, null) rows `Hydrogen Systems` 300, `Industrial Gases` 500, `Services` 200, each
  `sum_matches_total` true, `reconciling` 0. No segment note.
- **Fixture M**: (`segment`, null) rows `Gas Systems` 400, `Engineering` 600, each `sum_matches_total` true,
  `reconciling` 0; note `"Gas Systems makes electrolyser stacks and compressors. Engineering builds plants."`
- **Context X**: `RevenueResolverContext(catalogue_by_company={}, mappings=[], registry=DocumentSourceRegistry([]),
  settings=settings, schema=released_schema(A), xbrl_store=XbrlStore(settings.xbrl_dir), extract_enabled=False)`.
- **Context C**: Context X but with `extract_enabled=True` and a catalogue row `EV Sales` (`as_pct_of_total` 0.4) for
  `c1` whose mapping names a different activity, so the catalogue never resolves `A`.
- **Stub N** (extraction finds nothing): `FakeLLMClient` scripted with `ExtractionDraft` `[no_value_draft]*3` and
  `VerifierOutput` `[no_value_verifier]*3`, as in `test_match_company_revenue_unresolved_falls_through_to_qualitative_debate`
  (with fewer metrics to extract, the unused replies stay unused).
- **Stub E** (grounded 18.5): as in `test_match_company_extraction_hit_skips_qualitative_debate`, but the revenue
  draft's value is 18.5 and its quote `About 18.5% of revenue came from electrolysers.`; capex and opex miss.
  **Doc E** is that test's document with `full_text` `About 18.5% of revenue came from electrolysers.`
- "`resolve` runs" = `result, _ = await resolve_company_activity_exposure(c1, A, None, documents=docs, ctx=ctx, llm=stub)`
  with `docs=[]`, Context X and `FakeLLMClient({})` unless the row says otherwise; "revenue" is `result.revenue`.
  "Within 1e-9" means `abs(a - b) < 1e-9`. No row calls a real model.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Fixture R | `resolve` runs | revenue `source == "reported"`, `value_pct` within 1e-9 of 0.3 | holdout |
| AC-2 | AC-1 | same | revenue `notes == "Reported segments (FY2025): Hydrogen Systems"`, `low_pct is None`, `high_pct is None`, `confidence == 1.0` | holdout |
| AC-3 | Fixture R with `Services` renamed `Hydrogen Services` | `resolve` runs | revenue `value_pct` within 1e-9 of 0.5; `notes == "Reported segments (FY2025): Hydrogen Systems, Hydrogen Services"` | holdout |
| AC-4 | Fixture R with `Hydrogen Systems` renamed `Hydrogen Peroxide` | `resolve` runs | revenue `source == "unresolved"` | holdout |
| AC-5 | Fixture R with `Hydrogen Systems` renamed `Hydrogenics` | `resolve` runs | revenue `source == "unresolved"` (whole words only) | holdout |
| AC-6 | Fixture R with `Hydrogen Systems` renamed `HYDROGEN systems` | `resolve` runs | revenue `source == "reported"`, `value_pct` within 1e-9 of 0.3 | holdout |
| AC-7 | Fixture R plus (`product`, `company`) rows `Electrolyser Stacks` 120 and `Compressors` 380, both `sum_matches_total` false | `resolve` runs | revenue `source == "reported"`, `value_pct` within 1e-9 of 0.12, `notes == "Reported segments (FY2025): Electrolyser Stacks"` | holdout |
| AC-8 | Fixture R with values 300 / 500 / 300 and every row `reconciling` −100 | `resolve` runs | revenue `value_pct` within 1e-9 of 0.3 (T = 1100 − 100) | holdout |
| AC-9 | Fixture R with every row `sum_matches_total` false and no other group | `resolve` runs | revenue `source == "unresolved"`, `value_pct is None` | holdout |
| AC-10 | Fixture R with every segment row `sum_matches_total` false, plus (`geography`, null) rows `US` 400 and `EU` 600 with `sum_matches_total` true | `resolve` runs | revenue `source == "reported"`, `value_pct` within 1e-9 of 0.3 | holdout |
| AC-11 | One (`segment`, null) row `Hydrogen` 1100, `sum_matches_total` true, `reconciling` −100 | `resolve` runs | revenue `value_pct == 1.0` | holdout |
| AC-12 | Fixture R plus FY2024 rows `Hydrogen Systems` 900, `Other` 100 (all true) | `resolve` runs | revenue `value_pct` within 1e-9 of 0.3; `notes` contains `(FY2025)` | holdout |
| AC-13 | Fixture R stored under key `0000000002` whose `company_ids` is `["other"]`; `c1` has `cik="2"` | `resolve` runs | revenue `source == "reported"`, `value_pct` within 1e-9 of 0.3 | holdout |
| AC-14 | Fixture M | `resolve` runs | revenue `source == "modelled"`; `low_pct` within 1e-9 of 0.12; `high_pct` within 1e-9 of 0.2; `value_pct` within 1e-9 of 0.16 | holdout |
| AC-15 | AC-14 | same | revenue `notes == "Modelled from segment descriptions (FY2025): Gas Systems; counted at 30-50% of segment revenue."` | holdout |
| AC-16 | Fixture M with env `ARP_REVENUE_SHARE_MODELLED_LOW_FACTOR=0.5` and `ARP_REVENUE_SHARE_MODELLED_HIGH_FACTOR=0.7` | `resolve` runs | `low_pct` within 1e-9 of 0.2, `high_pct` within 1e-9 of 0.28, `notes` ends with `counted at 50-70% of segment revenue.` | holdout |
| AC-17 | Fixture M without the segment note | `resolve` runs | revenue `source == "unresolved"` | holdout |
| AC-18 | Fixture M with the note `"Gas Systems makes hydrogen peroxide. Engineering builds plants."` | `resolve` runs | revenue `source == "unresolved"` | holdout |
| AC-19 | Fixture M with the note `"Gas Systems makes compressors.\nEngineering designs electrolyser plants."` (`\n` is a real newline character) | `resolve` runs | revenue `source == "modelled"`, `high_pct` within 1e-9 of 0.3, `notes` starts with `Modelled from segment descriptions (FY2025): Engineering;` | holdout |
| AC-20 | Fixture R plus the note `"Industrial Gases makes electrolyser stacks."` | `resolve` runs | revenue `source == "reported"`, `value_pct` within 1e-9 of 0.3 (a name match wins over a description match) | holdout |
| AC-21 | Fixture R; Context C but its catalogue mapping names `A` (so it resolves `A` to 0.4); Stub N | `resolve` runs | revenue `source == "catalogue"`, `value_pct == 0.4`, `low_pct is None`, `high_pct is None` | holdout |
| AC-22 | Fixture R; Context C; Stub E; `docs=[Doc E]` | `resolve` runs | revenue `source == "reported"`, `value_pct` within 1e-9 of 0.3 (reported is tried before extraction) | holdout |
| AC-23 | Fixture M; Context C; Stub E; `docs=[Doc E]` | `resolve` runs | revenue `source == "extracted"`, `value_pct` within 1e-9 of 0.185, `low_pct is None` | holdout |
| AC-24 | Context X over an empty XBRL store | `resolve` runs | revenue `source == "unresolved"` and the stub recorded no call | holdout |
| AC-25 | Fixture R; Context C without `xbrl_store` (default None); Stub N; `docs=[Doc E]` | `resolve` runs | revenue `source == "unresolved"`, `low_pct is None` | holdout |
| AC-26 | Fixture R, Context X, Doc E | `match_company_activity(c1, A, documents=[Doc E], documents_by_id={Doc E's doc_id: Doc E}, llm=FakeLLMClient({}), settings=settings, revenue_resolver=Context X)` runs | `match.revenue_exposure.revenue.source == "reported"`, `match.advocate is None`, `match.verdict == "include"`, `match.exposure_estimate == "significant"`, stub recorded no call | holdout |
| AC-27 | AC-26 | same | `match.adjudicator_rationale == "Resolved via reported segment revenue: 30.0% of revenue attributed to this activity. Reported segments (FY2025): Hydrogen Systems"` | holdout |
| AC-28 | AC-26 | same | `len(match.arbitration.contributions) == 1`; that entry has `method == "revenue_reported"`, `weight == 1.0`, `detail == "30.0%"` | holdout |
| AC-29 | Fixture M, Context X; a document with `full_text` `Gas Systems makes electrolyser stacks.`; a stub with the advocate, opposing and adjudicator replies of `test_match_company_include_with_grounded_citation`, every citation's quote replaced by `makes electrolyser stacks` | `match_company_activity` runs as in AC-26 with that document and stub | `match.advocate is not None`; `match.revenue_exposure.revenue.source == "modelled"` | holdout |
| AC-30 | AC-29 | same | exactly one entry of `match.arbitration.contributions` has `method == "revenue_modelled"`; it has `signal` within 1e-9 of 0.16, `weight == 0.4`, `detail == "12.0%-20.0%"` | holdout |
| AC-31 | row = `{"company_matches": [AC-26's match.model_dump(mode="json")]}` | `run_company_l1([c1], [row])` runs | `[0][2]` of the result is within 1e-9 of 0.3 | holdout |
| AC-32 | Same with AC-29's match, its `verdict` set to `include` | `run_company_l1` runs | `[0][2]` of the result `is None` | holdout |
| AC-33 | TestClient with `settings_dep` overridden to `settings` with `theme_revenue_share_enabled=True`, the LLM factory stubbed, a released taxonomy as in the existing themes API tests, `companies=[c1]`, no catalogue | `POST /api/themes/runs` | 200 and `revenue_exposure_enabled` is `true` | holdout |
| AC-34 | Same with `theme_revenue_share_enabled=False` | `POST /api/themes/runs` | 200 and `revenue_exposure_enabled` is `false` | holdout |
| AC-35 | No env vars set | read `Settings()` | `theme_revenue_share_enabled is False`, `revenue_share_modelled_low_factor == 0.3`, `revenue_share_modelled_high_factor == 0.5`, `arbitration_weight_revenue_reported == 1.0`, `arbitration_weight_revenue_modelled == 0.4` | holdout |
| AC-36 | A run created by `create_theme_run` with the setting on and no catalogue | read its manifest | `params["theme_revenue_share"] is True` | holdout |
| AC-37 | A run created with the setting on and no catalogue, interrupted before `c1`; Fixture R in `xbrl_dir`; resumed by `resume_theme_run` with the setting now off | the resumed run finishes | its stored match for `c1` has revenue `source == "reported"` | unit |
| AC-38 | Setting on, no catalogue, Fixture R, stubbed LLM | `arp theme run` for a theme containing `A` and a universe of `c1` | the stored match for `c1` has revenue `source == "reported"` | unit |
| AC-39 | The existing tests in `tests/test_revenue_resolver.py`, `tests/test_revenue_percent_scale.py`, `tests/test_arbitration.py`, `tests/test_research_pipeline.py` and `tests/test_exposure_layers.py` | CI runs them | they pass with no edits | unit |
| AC-40 | Theme Builder results with a match whose revenue is `reported`, `value_pct` 0.3 | the list renders | badge text `reported (30.0%)` with class `badge-high` | unit |
| AC-41 | A match whose revenue is `modelled`, `low_pct` 0.12, `high_pct` 0.2, `value_pct` 0.16 | the list renders | badge text `modelled (12.0–20.0%)` with class `badge-mid` | unit |
| AC-42 | AC-41, details opened | the detail renders | a line `Revenue: 12.0–20.0% (modelled)` | unit |
| AC-43 | A match whose revenue is `catalogue`, `value_pct` 0.4 | the list renders | badge text `catalogue (40.0%)` with class `badge-high` (unchanged) | unit |
| AC-44 | Setting on, a catalogue whose mapping does not resolve `A`, Fixture R, stubbed LLM | `arp theme run` with that catalogue runs to the end | the stored match for `c1` has revenue `source == "reported"` | unit |
| AC-45 | A run created with the setting off and no catalogue (and a second one whose manifest has no `theme_revenue_share` param), interrupted before `c1`; Fixture R in `xbrl_dir`; resumed by `resume_theme_run` with the setting now on | the resumed run finishes | its stored match for `c1` has `revenue_exposure is None` | unit |

Must not change: without `xbrl_store` the resolver behaves as today (AC-25, AC-39); setting off gives no context
without a catalogue (AC-34); catalogue still wins (AC-21); a catalogue badge looks as before (AC-43); `extracted` still
beats a description-only guess (AC-23).

Checked by: every backend `holdout` row calls functions or the API directly with a stub model and fixture files, so the
test-writer needs no running app and no model credit. Resume and CLI wiring (AC-37, AC-38, AC-44, AC-45) and the existing suites
(AC-39) are the implementer's tests. The Theme Builder rows are component tests in the frontend suite (`unit`):
rendering a stored match needs no running app, and an `evaluator` run would need a full theme run. There are no
`evaluator` or `golden` rows; the B1 golden gate (±10 pp on the A3 sets) runs with the precision scorecard
(`theme-precision-scorecard`) once both are built, and is not a merge gate here.

## Slices

| Slice | Size | Rows | Contents | Risk |
|---|---|---|---|---|
| 1 | M | AC-1 to AC-39, AC-44, AC-45 | Schema fields, resolver steps, settings, routing, finalize text, arbitration, L1, run wiring (API, resume, CLI), OpenAPI and generated types | `risk:high` |
| 2 | S | AC-40 to AC-43 | Theme Builder badge and detail line | `risk:normal` |

Order: slice 1, then slice 2 (it needs slice 1's generated types). Slice 1 touches `research/match_graph.py`,
which the `matcher-shared-retrieval` and `theme-precision-scorecard` slice 2 builders also change: whichever merges
second merges `origin/main` first.

## Follow-ups

- A second `reported` source from the LLM financials segments.
- B1 open question: may `modelled` values enter Decision Studio (not touched here).
- Turning `theme_revenue_share_enabled` on by default once the precision scorecard shows it helps.
