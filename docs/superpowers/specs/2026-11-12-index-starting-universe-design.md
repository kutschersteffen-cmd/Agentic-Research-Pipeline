# Index Construction: load a starting universe from a holdings file or a portfolio

Slug: `index-starting-universe`. Risk: normal (PR 1 and PR 2), see "Risk label".

## Intent

Index Construction (R&D Lab, Index Builder) only ever runs on the 60-company synthetic `demo_universe()`:
the page never sends `candidates`, so `POST /api/index/run` always falls back to it
(`backend/arp/api/routers/index.py:29-32`). The owner wants to build an index from a real starting point,
one of the public holdings files in `data/holdings/` (DAX, EURO STOXX 50, MSCI World, ...) or a portfolio
already imported into the app, and to screen and tilt it on the simulated ESG data the
`showcase-portfolio-data` spec produces. The demo universe stays, as the default.

The files carry weights only. Every size number is therefore an assumption and must say so, and the
features that need real prices or returns refuse rather than invent them.

## Current state (read on `main` f0b7ae0)

- `RunRequest` (`routers/index.py`) takes `candidates: list[IndexCandidate] | None`; omitted means demo.
  No API test sends `candidates`.
- `GET /api/index/catalogue` lists fields from `available_fields(demo_universe())`; the page's field
  pickers use that list plus the joined Decision Studio fields (`IndexBuilder.tsx:219-228`).
- Tracking-error methods (`min_tracking_error`, `max_score`, or a `tracking_error_budget`) without a
  `returns_panel` call `demo_risk_model(universe)`, which invents a hash-seeded returns panel for whatever
  company ids it is given, real names included.
- `GET /{index_id}/levels/{review_date}` prices only demo companies and answers 409
  `Level series is only available for reviews run on the built-in demo universe` for anything else.
  The page does not show levels; it is API only.
- `data/holdings/*.xlsx`: six files, sheet title = ISO date (2026-11-02), header in row 4 with columns
  `Name`, `ISIN`, `Country`, `Currency`, `Type of Security`, `Industry Classification`, `Weighting`
  (fraction), German labels. `backend/arp/portfolio/constituent_import.py` knows this layout and holds the
  `ASSET_CLASS`, `COUNTRY` and `SECTOR` tables, but only imports files named `Constituent_<ISIN>.xlsx` into
  the portfolio store. `DAX.xlsx`: 40 equity lines (largest SAP, ISIN DE0007164600, 0.1176506915), 2 cash
  lines, 1 mutual fund line.
- `showcase-portfolio-data` (approved spec on `main`, `2026-11-12-showcase-portfolio-data-design.md`) PR 1
  commits `data/simulated/esg_simulated.csv`: one row per ISIN, `company_id` = `isin_<ISIN>`, flags as
  `true`/`false`, `sector` = the GICS peer group, `country` in English. Its section "Fields for Index
  Construction" fixes which columns this spec reads and as what (see "Simulated ESG join"); it shows
  `transition_grade` as a category here (AC-30). Its PR 2 extends the importer's label tables
  (`Preferred Stock` → equity, English labels).
- The themes spec (`2026-11-12-showcase-themes-fixes.md`, PR 2) adds a fixed banner on every Index
  Construction tab: `Demo data: reviews on this page run on a built-in synthetic universe of 60 companies.
  The results describe nothing real.` (its AC-65).

## Goals

1. A user can pick a starting universe on Index Construction: the demo universe (default), any
   `data/holdings/*.xlsx` file, or any stored portfolio with holdings.
2. A review runs on that universe, and a saved review says in its notes which universe it ran on.
3. Sizes are a labelled weight proxy: price 1, shares = weight × an assumed EUR 100,000,000.
4. Lines that are not equity with a positive weight are dropped, and the counts are shown.
5. Simulated ESG data, when its file exists, joins by company id and its fields become pickable;
   without it, loaded companies carry no ESG fields and a rule on one stops the review (existing
   `Data quality block`).
6. Features that need prices or returns refuse clearly on a loaded universe.

## Non-goals

- Uploading files of other formats, or uploading at all: the picker lists files already in `data/holdings/`.
- Real prices, shares outstanding, free float or returns.
- Any change to index, weighting, capping, optimiser or trajectory maths, or to `demo_universe()`.
- A new data feed; generating the simulated dataset (that is `showcase-portfolio-data`).
- Disabling the tracking-error options in the page (the refusal message is shown instead).

## Anti-goals

- A size, price or return on a real company name that could be read as market data.
- A loaded universe silently falling back to the demo universe, or the demo silently using loaded data.
- A review on a real universe that does not say where its companies came from.

## Approaches

1. **Universe id on the run request (chosen by the owner).** `RunRequest.universe` names the source;
   the server builds the candidates, joins the dataset and writes notes into `ReviewResult.input_notes`.
   Small requests even for MSCI World (1,250 companies); a saved review records its source.
2. Endpoint returns candidate rows, page sends them back as `candidates` (the intake's wording). No change
   to `RunRequest`, but about 1 MB per preview for MSCI World and a saved review does not record its source.
3. Import the files as portfolios first and only support portfolios. Rejected: needs the importer
   changes of `showcase-portfolio-data` PR 2 before anything works here.

Owner decision on missing market data (12 Nov): **refuse clearly**. Levels and tracking-error methods
answer with a plain message on a loaded universe; nothing is simulated.

## Design

### Universe ids

- `demo`: the built-in demo universe. Omitting `universe` means `demo`.
- `file:<stem>`: `<settings.holdings_dir>/<stem>.xlsx`, e.g. `file:DAX`. Only files directly in that
  directory, named `*.xlsx`; any other stem is unknown (no path traversal).
- `portfolio:<portfolio_id>`: a portfolio in the portfolio store that has at least one holdings snapshot;
  its latest snapshot is used.

### Settings (`backend/arp/config.py`)

- `holdings_dir: Path = REPO_ROOT / "data" / "holdings"` (env `ARP_HOLDINGS_DIR`).
- `simulated_esg_path: Path = REPO_ROOT / "data" / "simulated" / "esg_simulated.csv"` (env `ARP_SIMULATED_ESG_PATH`).

### Loader (new module `backend/arp/portfolio/index_universe.py`, outside `backend/arp/index/`)

Builds `IndexCandidate` rows and the notes below. It reuses `ASSET_CLASS`, `COUNTRY`, `SECTOR` and the
translate helper from `constituent_import.py` (imported, not copied), so the label fixes of
`showcase-portfolio-data` PR 2 apply here once they land.

**File lines**, read like the importer (sheet title = as-of date, header row 4, rows with a `Name` and
`ISIN`), each counted in exactly one bucket, checked in this order:

1. `Weighting` not a number → *without a weight*.
2. `ASSET_CLASS[Type of Security]` is `cash` → *cash*.
3. Not `equity` (including unknown types) → *other asset class*.
4. `Weighting` ≤ 0 → *zero or negative weight*.
5. Otherwise a candidate.

**Portfolio holdings** (latest snapshot): a holding whose security has no `company_id` → *not linked to a
company*; `weight_pct` missing → *without a weight*; then buckets 2 to 4 by the security's `asset_class`
and `weight_pct`. Holdings of one company are summed into one candidate: weight = summed `weight_pct` / 100.
`name`, `sector` and `country` come from the stored company (`CompanyRef`); with no stored company, the
first security's name and no sector or country.

**Layout errors** reuse the importer's wording: `<file name>: sheet title '<title>' is not an ISO date
(YYYY-MM-DD)` and `<file name>: header row 4 lacks column(s) [...]`. The universe list still lists such a
file, with `as_of_date` null; loading it answers 422 with that message.

**Look-ahead:** a run whose `review_date` is before the universe's as-of date is refused (400)
`<label> holds holdings as of <date>, after the review date <review_date>: a review cannot use holdings that did not exist yet.`
(My call, same rule as the Decision Studio join.)

**Reading:** the loader reads the file, the store and the dataset on every request (no cache), so a changed
file shows on the next request.

**Candidate fields:** `company_id` = `isin_<ISIN>` for files, the linked company id for portfolios; `name`;
`sector` and `country` translated to English (portfolios: from the stored company); `currency` `EUR`;
`price` 1.0; `fx_rate` 1.0; `free_float_factor` 1.0; `shares_outstanding` = weight (fraction) × 100,000,000.
Weights are not renormalised.

**Simulated ESG join**, when `simulated_esg_path` exists, by `company_id`:

exactly the columns of `showcase-portfolio-data`'s "Fields for Index Construction" table:

- `metrics` (float), under the column name: `esg_score`, `esg_trend`, `ghg_intensity`, `lct_score`,
  `coal_revenue_pct`, `oil_revenue_pct`, `gas_revenue_pct`, `high_intensity_power_revenue_pct`,
  `tobacco_revenue_pct`, `green_revenue_pct`, `weapons_revenue_pct`, `alcohol_revenue_pct`,
  `gambling_revenue_pct`, `esg_e_score`, `esg_s_score`, `esg_g_score`, `controversy_level`, `transition_score`.
- `flags` (`true`/`false`): `norms_violation`, `controversial_weapons`, `severe_controversy`.
- `categories`: `lct_category`, `transition_grade`.
- The dataset's `sector` and `country` replace the candidate's own `sector` and `country` (so every file
  uses the same GICS peer groups; DAX's older scheme files BMW under Consumer Staples).
- No other column is joined (the `climate_*` columns, `transition_grade_label`, identity columns).
- An empty cell is not joined (the key is absent, or the file's value is kept for `sector`/`country`).
- A company with no row gets nothing (no defaults).

**Notes** (exact text, in this order; `<n>` = candidates, numbers without separators except the notional):

1. `Starting universe: <label>, holdings as of <date>, <n> companies.` (`<label>`: the file name, e.g.
   `DAX.xlsx`, or the portfolio's name.)
2. `Dropped <k> lines: <a> cash, <b> other asset class, <c> zero or negative weight, <d> without a weight, <e> not linked to a company.`
3. `Size is a weight proxy: each company's free-float market cap is its weight × an assumed EUR 100,000,000, at price 1. It is not market data.`
4. Dataset present: `Simulated ESG data: matched <m> of <n> companies.` Absent:
   `Simulated ESG data: not available; loaded companies carry no ESG fields.`

A universe with no candidates is refused: 422 `<label>: no equity lines with a positive weight.`

### API (`backend/arp/api/routers/index.py`)

- `GET /api/index/universes` → list of `{universe_id, label, kind, as_of_date}`: first
  `{"universe_id": "demo", "label": "Built-in demo universe (60 synthetic companies)", "kind": "demo", "as_of_date": null}`,
  then files sorted by stem (`kind` `file`, `as_of_date` the sheet date), then portfolios with a snapshot
  sorted by name (`kind` `portfolio`, `as_of_date` the latest snapshot date). Builder's call: whether the
  list reads sheet dates eagerly or lazily, as long as the field is filled.
- `GET /api/index/universes/{universe_id:path}` (a `path` parameter, so an id holding `/` reaches the
  handler and gets the 404 below) → `{universe_id, label, kind, as_of_date, company_count, notes,
  fields}`; `fields` is `available_fields(candidates)` from `arp/index/fields.py` (called, not changed).
  For `demo`: `company_count` 60, `notes` `[]`, fields as the catalogue's. Unknown id → 404
  `Unknown starting universe: <id>`.
- `RunRequest.universe: str | None = None`. `universe` set to any value, `demo` included, together with a
  non-empty `candidates` → 400 `Send either universe or candidates, not both.` `candidates: []` counts as
  omitted (as today). Unknown → 404 as above. The loader's notes are put in
  front of the decision notes in `ReviewResult.input_notes`. Decision Studio joins work on a loaded
  universe as they do on the demo.
- Risk model: when the universe is not the demo (a non-demo `universe` or non-empty `candidates`), no
  `returns_panel` is sent, and the spec needs a risk model (the existing condition), answer 422
  `Risk model: a loaded starting universe has no returns history, so tracking-error methods cannot run on it. Use the built-in demo universe, or send a returns_panel.`
  With a `returns_panel` the existing `build_risk_model` path runs unchanged.
- Levels: the 409 for a non-demo review keeps its status and gets the message
  `No level series: this review ran on a loaded starting universe, which has no price history (its prices are a weight proxy).`
- `GET /api/index/catalogue` is unchanged (demo fields).

After the model changes: `scripts/export_openapi.py`, `npm run gen:api`, both generated files committed in
PR 1, plus `frontend/src/api/contract.ts` lines for the two new endpoints.

### Page (`frontend/src/pages/IndexBuilder.tsx`, PR 2)

- Compose, first card, above Preset: **Starting universe**, a select filled from `GET /api/index/universes`,
  each option's text `<label>` for demo, `<label> (holdings file, <as_of_date>)` for files,
  `<label> (portfolio, <as_of_date>)` for portfolios. Default: the demo universe.
- Choosing a non-demo universe calls `GET /api/index/universes/{id}` and shows its notes under the select,
  one line each. The field pickers then use that response's `fields` (plus the Decision Studio fields as
  today) instead of the catalogue's. Switching back to demo restores the catalogue's fields.
- While loading: the select is disabled and `Loading <label>…` shows. A failed load shows the error text
  under the select and keeps the previous universe.
- Runs send `universe: <id>` (omitted for demo).
- If the index id is still `demo_index` when a non-demo universe is chosen, it changes to `<slug>_index`:
  `<slug>` is the stem lower-cased (`dax_index`) or the portfolio id, so a saved review does not chain onto
  demo reviews. An index id the user typed is never changed. (My call.)
- Banner: the themes spec's demo banner stays for the demo universe. With a loaded universe the same banner
  slot shows instead
  `Starting universe: <label> (holdings as of <date>, <n> companies). Sizes are a weight proxy and ESG values, where present, are simulated. The results describe no real index.`
- Run errors (Data quality block, the risk-model refusal) show in the existing error area as they are.

## Risk label

Steward: index maths and portfolio weights are `risk:high`. Neither PR touches a file under
`backend/arp/index/` or any weighting, capping, optimiser or trajectory code; the loader produces inputs
only, and the router change is request validation and a message. So PR 1 and PR 2 are `risk:normal`.
If a builder finds they must change a file under `backend/arp/index/`, the PR becomes `risk:high` and the
builder stops and says why. PR 1 touches `arp/config.py`, which may start the golden-set CI job; that job
is unaffected and passes.

## PRs

| PR | Contents | Risk | Waits for |
|---|---|---|---|
| 1 | Settings, loader, the two endpoints, `RunRequest.universe`, risk-model refusal, levels message, generated API types | normal | nothing (the dataset join is tested with a fixture CSV) |
| 2 | Starting-universe card, notes, field pickers, run wiring, index id, banner line | normal | PR 1, and themes PR 2 merged (or built on its rebased head; same `IndexBuilder.tsx`) |

The intake's third PR (dataset join and end-to-end check) is folded into PR 1 (join) and PR 2 (evaluator
rows): the join is a column mapping, and the dataset's own field names are fixed by its spec.

## Left to the builder

- Function names, the response model names.
- How the select and notes are laid out, within the existing card and help-text styles.


## Acceptance

"DAX" means `data/holdings/DAX.xlsx` as committed. `holdout` rows run on the default e2e stack and do not
depend on whether `data/simulated/esg_simulated.csv` exists. Rows that need other settings or fixture
files are `unit`, with settings overridden in the test client: "no dataset" means `simulated_esg_path`
points at a file that does not exist; "the fixture dataset" means it points at a CSV with the full header of
`showcase-portfolio-data`'s dataset and one row for `company_id` `isin_DE0007164600` with `esg_score` 7.25,
`coal_revenue_pct` 0, `norms_violation` `false`, `lct_category` `neutral`, `transition_grade` `B`,
`transition_grade_label` `Credible`, `sector` `Information Technology`, every other column non-empty.
"The default spec" is `ConstructionSpec()` (no screens, select all, free-float market cap weighting,
waterfall, no constraints, trajectory off). Every run row sends its own `index_id` `ac<n>_index` (n = the
row number), `use_prior_state` false and `review_date` 2026-11-02 unless it says otherwise.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The default stack | `GET /api/index/universes` | 200; the first entry is `{"universe_id": "demo", "label": "Built-in demo universe (60 synthetic companies)", "kind": "demo", "as_of_date": null}` | holdout |
| AC-2 | Same | `GET /api/index/universes` | it holds `{"universe_id": "file:DAX", "label": "DAX.xlsx", "kind": "file", "as_of_date": "2026-11-02"}`, and the `file:` entries come right after `demo`, sorted by stem | holdout |
| AC-3 | Same | `GET /api/index/universes/file:DAX` | 200; `company_count` 40; `notes[0]` `Starting universe: DAX.xlsx, holdings as of 2026-11-02, 40 companies.` | holdout |
| AC-4 | Same | same | `notes[1]` `Dropped 3 lines: 2 cash, 1 other asset class, 0 zero or negative weight, 0 without a weight, 0 not linked to a company.` | holdout |
| AC-5 | Same | same | `notes[2]` `Size is a weight proxy: each company's free-float market cap is its weight × an assumed EUR 100,000,000, at price 1. It is not market data.` | holdout |
| AC-6 | No dataset | `GET /api/index/universes/file:DAX` | `notes[3]` `Simulated ESG data: not available; loaded companies carry no ESG fields.` | unit |
| AC-7 | No dataset | same | `fields` is exactly `{"metrics": ["float_mcap", "free_float_factor", "price", "shares_outstanding"], "flags": [], "categories": ["country", "sector"]}` | unit |
| AC-8 | The default stack | `GET /api/index/universes/file:NOPE` | 404, detail `Unknown starting universe: file:NOPE` | holdout |
| AC-9 | Same | `GET /api/index/universes/file:..%2Fconfig%2Fusers` | 404, detail `Unknown starting universe: file:../config/users` | holdout |
| AC-10 | Same | `POST /api/index/run`, default spec, `universe` `file:../../config/users` | 404, detail `Unknown starting universe: file:../../config/users` | holdout |
| AC-11 | `holdings_dir` = a directory with one file `X.xlsx` (DAX layout) whose only lines are 1 cash line, 1 equity line with weight −0.01, 1 equity line with weight `N/A` | `GET /api/index/universes/file:X` | 422, detail `X.xlsx: no equity lines with a positive weight.` | unit |
| AC-12 | `holdings_dir` = a directory with `X.xlsx` in DAX layout but sheet title `Sheet1` | `GET /api/index/universes` | it lists `file:X` with `as_of_date` null | unit |
| AC-13 | Same | `GET /api/index/universes/file:X` | 422, detail `X.xlsx: sheet title 'Sheet1' is not an ISO date (YYYY-MM-DD)` | unit |
| AC-14 | The default stack, default spec | `POST /api/index/run`, `universe` `file:DAX`, `persist` false | 200; 40 constituents; `isin_DE0007164600` named `SAP` with weight 0.1176544801 (within 1e-9) | holdout |
| AC-15 | Same | same | that constituent's price is 1.0 | holdout |
| AC-16 | Same | same | `input_notes[0:3]` equal `notes[0:3]` of `GET /api/index/universes/file:DAX` | holdout |
| AC-17 | Same | run `file:DAX` with `persist` true, then `GET /api/index/ac17_index/reviews/2026-11-02` | `input_notes[0]` is `Starting universe: DAX.xlsx, holdings as of 2026-11-02, 40 companies.` | holdout |
| AC-18 | Same | run `file:DAX` with `review_date` 2026-10-01 | 400, detail `DAX.xlsx holds holdings as of 2026-11-02, after the review date 2026-10-01: a review cannot use holdings that did not exist yet.` | holdout |
| AC-19 | Same | run with `universe` `file:DAX` and a one-element `candidates` list | 400, detail `Send either universe or candidates, not both.` | holdout |
| AC-20 | Same | run with `universe` `demo` and a one-element `candidates` list | 400, detail `Send either universe or candidates, not both.` | holdout |
| AC-21 | Same | run with `universe` `file:NOPE` | 404, detail `Unknown starting universe: file:NOPE` | holdout |
| AC-22 | Same, default spec with solver method `min_tracking_error`, no `returns_panel` | run `file:DAX` | 422, detail `Risk model: a loaded starting universe has no returns history, so tracking-error methods cannot run on it. Use the built-in demo universe, or send a returns_panel.` | holdout |
| AC-23 | Same, default spec with `tracking_error_budget` 0.02, no `returns_panel` | run with 3 `candidates` sent directly, no `universe` | 422 with the detail of AC-22 | holdout |
| AC-24 | Same, a review on `file:DAX` saved under `ac24_index` @ 2026-11-02 | `GET /api/index/ac24_index/levels/2026-11-02` | 409, detail `No level series: this review ran on a loaded starting universe, which has no price history (its prices are a weight proxy).` | holdout |
| AC-25 | A stored portfolio `p1` whose latest snapshot holds company `c_a` (stored name `Alpha AG`) through two equity securities (weight_pct 30 and 20), company `c_b` (weight_pct 45), a cash security linked to company `c_cash` (weight_pct 5), an equity security with no company (weight_pct 1) | `GET /api/index/universes/portfolio:p1` | `company_count` 2; `notes[1]` `Dropped 2 lines: 1 cash, 0 other asset class, 0 zero or negative weight, 0 without a weight, 1 not linked to a company.` | unit |
| AC-26 | Same | run `portfolio:p1`, default spec, `review_date` = the snapshot date | constituent weights `c_a` 0.5263157895, `c_b` 0.4736842105 (within 1e-9) | unit |
| AC-27 | Same | same | the `c_a` constituent is named `Alpha AG` | unit |
| AC-28 | Same, and a portfolio `p0` with no snapshot | `GET /api/index/universes` | exactly one `portfolio:` entry, `portfolio:p1`, with `label` the portfolio's name, `kind` `portfolio`, `as_of_date` the snapshot date, after every `file:` entry | unit |
| AC-29 | The fixture dataset | `GET /api/index/universes/file:DAX` | `notes[3]` `Simulated ESG data: matched 1 of 40 companies.` | unit |
| AC-30 | The fixture dataset | same | `fields.categories` is exactly `["country", "lct_category", "sector", "transition_grade"]` | unit |
| AC-31 | The fixture dataset, a spec with one metric threshold screen on `esg_score` min 5, `missing` `fail` | run `file:DAX` | exactly 1 constituent, `isin_DE0007164600` | unit |
| AC-32 | The fixture dataset, a spec with one category screen on `transition_grade` allowing only `B`, `missing` `fail` | run `file:DAX` | exactly 1 constituent, `isin_DE0007164600` | unit |
| AC-33 | No dataset, the AC-31 screen with `missing` `block` | run `file:DAX` | 422, detail starts `Data quality block:` and contains `esg_score` | unit |
| AC-34 | A published decision whose results cover `isin_DE0007164600` only, published before 2026-11-02 | run `file:DAX` with its `decision_snapshot_ids` | `input_notes[4]` ends `matched 1 of 40 candidates.` | unit |
| AC-35 | Must not change: the default stack | run the default spec and each preset from `GET /api/index/presets/<name>` (names from the catalogue's `presets`) with no `universe`, no `candidates` | each body equals `main` before this spec, excluding `created_at` | holdout |
| AC-36 | Must not change: same | the same runs with `universe` `demo` | each body equals the AC-35 body, excluding `created_at`, `index_id` and `state.index_id` | holdout |
| AC-37 | Must not change: a demo review saved under `ac37_index` @ 2026-03-31 | `GET /api/index/ac37_index/levels/2026-03-31?days=5` | identical to `main` before this spec | holdout |
| AC-38 | Must not change: a demo run, solver method `min_tracking_error`, no `returns_panel` | `POST /api/index/run` | the same status and body as `main` before this spec, excluding `created_at` | holdout |
| AC-39 | Must not change | `GET /api/index/catalogue` | `fields` equals `main` before this spec | holdout |
| AC-40 | Must not change: `candidates: []`, solver method `min_tracking_error`, no `returns_panel` | `POST /api/index/run` | the same status and body as AC-38, excluding `created_at`, `index_id` and `state.index_id` | holdout |
| AC-41 | The fixture dataset, default spec | run `file:DAX` | constituent `isin_DE0007164600` has `sector` `Information Technology` (the file says `Technologie`) | unit |
| AC-42 | No dataset, default spec | run `file:DAX` | constituent `isin_DE0007164600` has `sector` `Technology` and `country` `Germany` | unit |
| AC-50 | The e2e stack, Index Construction → Compose | the page opens | a `Starting universe` card is directly above the Preset card | evaluator |
| AC-51 | Same | the card's select is read | it shows `Built-in demo universe (60 synthetic companies)` | evaluator |
| AC-52 | Same | the select's options are read | one reads `DAX.xlsx (holdings file, 2026-11-02)` | evaluator |
| AC-53 | Same | DAX is chosen | four note lines show under the select, the first `Starting universe: DAX.xlsx, holdings as of 2026-11-02, 40 companies.` | evaluator |
| AC-54 | Same, DAX chosen | the Base weighting scheme is set to `metric` and its Field picker opened | it lists `float_mcap` and not `adv_3m` | evaluator |
| AC-55 | Same, DAX chosen, the index id still `demo_index` | the index id field is read | `dax_index` | evaluator |
| AC-56 | Same, DAX chosen, no preset, no rules added | Preview is run and the Result tab opened | 40 constituents, among them `SAP` at `11.77%` | evaluator |
| AC-57 | Same, DAX chosen | the Compose tab and the Result tab are read | both show `Starting universe: DAX.xlsx (holdings as of 2026-11-02, 40 companies). Sizes are a weight proxy and ESG values, where present, are simulated. The results describe no real index.` | evaluator |
| AC-58 | Same, DAX chosen | the Compose tab and the Result tab are read | neither shows text starting `Demo data:` | evaluator |
| AC-59 | Same, DAX chosen, then the demo universe chosen again | Compose is read | the themes spec's `Demo data:` banner shows | evaluator |
| AC-60 | Same as AC-59 | the area under the select is read | no note line starting `Starting universe:` shows | evaluator |
| AC-61 | Same as AC-59 | the Base weighting Field picker (scheme `metric`) is opened | it lists `adv_3m` | evaluator |
| AC-62 | Same, DAX chosen, solver method set to Minimum tracking error | Preview is run | the page shows the detail of AC-22 | evaluator |
| AC-63 | Index Builder, API mocked: universes as in AC-1/AC-2, the DAX load answering 500 `boom` | DAX is chosen | an error containing `boom` shows under the select | unit |
| AC-64 | Same | same | the select shows the demo universe again | unit |
| AC-65 | Same | same, then the Base weighting Field picker (scheme `metric`) is read | it lists the mocked catalogue's metrics | unit |
| AC-66 | Index Builder, API mocked, the user typed index id `my_index`, then chose DAX | the index id field is read | `my_index` | unit |
| AC-67 | Index Builder, API mocked, DAX chosen | Preview is run | the request body has `"universe": "file:DAX"` and no `candidates` key | unit |
| AC-68 | Index Builder, API mocked, the universes list holds `{"universe_id": "portfolio:p1", "label": "My fund", "kind": "portfolio", "as_of_date": "2026-10-31"}` | the select's options are read | one reads `My fund (portfolio, 2026-10-31)` | unit |
| AC-69 | Must not change: Index Builder, API mocked, the demo universe | Preview is run | the request body has no `universe` and no `candidates` key | unit |

Rows owned by PR 1: AC-1 to AC-42. PR 2: AC-50 to AC-69.

Must not change: demo runs and presets, demo levels, demo tracking-error runs, the catalogue's fields,
empty `candidates`, run requests from the page on the demo universe (AC-35 to AC-40, AC-69).
