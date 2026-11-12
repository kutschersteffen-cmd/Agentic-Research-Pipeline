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
- `showcase-portfolio-data` (draft spec, branch `claude/showcase-portfolio-data-spec`) PR 1 commits
  `data/simulated/esg_simulated.csv`: one row per ISIN, `company_id` = `isin_<ISIN>`, numeric ESG and
  revenue-share columns named as Index Construction's fields, flags as `true`/`false`, categories
  `lct_category`, `transition_grade` (`A` to `F`), `transition_grade_label`, and `sector` as the peer group.
  Its row AC-65 ("the field catalogue lists `transition_grade` as a category") is owned by this spec
  (here AC-14). Its PR 2 extends the importer's label tables (`Preferred Stock` → equity, English labels).
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
and `weight_pct`. Holdings of one company are summed into one candidate.

**Candidate fields:** `company_id` = `isin_<ISIN>` for files, the linked company id for portfolios; `name`;
`sector` and `country` translated to English (portfolios: from the stored company); `currency` `EUR`;
`price` 1.0; `fx_rate` 1.0; `free_float_factor` 1.0; `shares_outstanding` = weight (fraction) × 100,000,000.
Weights are not renormalised.

**Simulated ESG join**, when `simulated_esg_path` exists, by `company_id`:

- `true`/`false` columns → `flags`.
- `lct_category`, `transition_grade`, `transition_grade_label` → `categories`; the dataset's `sector` →
  category `peer_group`.
- Every other numeric column → `metrics` under its column name.
- `isin`, `company_id`, `name`, `country`, `files`, `data_status` are not joined.
- A company with no row gets nothing (no defaults).

**Notes** (exact text, in this order; `<n>` = candidates, numbers without separators except the notional):

1. `Starting universe: <label>, holdings as of <date>, <n> companies.` (`<label>`: the file name, e.g.
   `DAX.xlsx`, or the portfolio's name.)
2. `Dropped <k> lines: <a> cash, <b> other asset class, <c> zero or negative weight, <d> without a weight, <e> not linked to a company.`
3. `Size is a weight proxy: each company's free-float market cap is its weight × an assumed EUR 100,000,000, at price 1. It is not market data.`
4. Dataset present: `Simulated ESG data: matched <m> of <n> companies.` Absent:
   `Simulated ESG data: not available; loaded companies carry no ESG fields.`

A universe with no candidates is refused: 422 `<label>: no equity lines with a positive weight.`
A file that does not have the layout is refused: 422 `<file name>: ` followed by the reason.

### API (`backend/arp/api/routers/index.py`)

- `GET /api/index/universes` → list of `{universe_id, label, kind, as_of_date}`: first
  `{"universe_id": "demo", "label": "Built-in demo universe (60 synthetic companies)", "kind": "demo", "as_of_date": null}`,
  then files sorted by stem (`kind` `file`, `as_of_date` the sheet date), then portfolios with a snapshot
  sorted by name (`kind` `portfolio`, `as_of_date` the latest snapshot date). Builder's call: whether the
  list reads sheet dates eagerly or lazily, as long as the field is filled.
- `GET /api/index/universes/{universe_id}` → `{universe_id, label, kind, as_of_date, company_count, notes,
  fields}`; `fields` is `available_fields(candidates)` from `arp/index/fields.py` (called, not changed).
  For `demo`: `company_count` 60, `notes` `[]`, fields as the catalogue's. Unknown id → 404
  `Unknown starting universe: <id>`.
- `RunRequest.universe: str | None = None`. A non-demo `universe` together with `candidates` → 400
  `Send either universe or candidates, not both.` Unknown → 404 as above. The loader's notes are put in
  front of the decision notes in `ReviewResult.input_notes`. Decision Studio joins work on a loaded
  universe as they do on the demo.
- Risk model: when the universe is not the demo (a non-demo `universe` or any `candidates`), no
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

- Function names, the response model names, caching of a loaded file.
- How the select and notes are laid out, within the existing card and help-text styles.

## Acceptance

"DAX" means `data/holdings/DAX.xlsx` as committed. "No dataset" means `ARP_SIMULATED_ESG_PATH` points at a
file that does not exist. "The fixture dataset" means `ARP_SIMULATED_ESG_PATH` points at a CSV with the
header of `showcase-portfolio-data`'s dataset and one row for `company_id` `isin_DE0007164600` with
`esg_score` 7.25, `coal_revenue_pct` 0, `norms_violation` `false`, `transition_grade` `B`,
`transition_grade_label` `Credible`, `sector` `Information Technology`, other columns any valid value.
"The default spec" is `ConstructionSpec()` (no screens, select all, free-float market cap weighting,
waterfall, no constraints, trajectory off).

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | `ARP_HOLDINGS_DIR` = a directory holding copies of `SP500.xlsx` and `DAX.xlsx` and a file `notes.txt`; a portfolio store with no portfolios | `GET /api/index/universes` | 200; exactly three entries: `{"universe_id": "demo", "label": "Built-in demo universe (60 synthetic companies)", "kind": "demo", "as_of_date": null}`, then `{"universe_id": "file:DAX", "label": "DAX.xlsx", "kind": "file", "as_of_date": "2026-11-02"}`, then the same for `SP500` | holdout |
| AC-2 | Same, plus a stored portfolio with one snapshot dated 2026-10-31 | `GET /api/index/universes` | the list ends with an entry `universe_id` `portfolio:<its id>`, `kind` `portfolio`, `label` its name, `as_of_date` `2026-10-31` | holdout |
| AC-3 | No dataset | `GET /api/index/universes/file:DAX` | 200; `company_count` 40; `notes` exactly: `Starting universe: DAX.xlsx, holdings as of 2026-11-02, 40 companies.`, `Dropped 3 lines: 2 cash, 1 other asset class, 0 zero or negative weight, 0 without a weight, 0 not linked to a company.`, `Size is a weight proxy: each company's free-float market cap is its weight × an assumed EUR 100,000,000, at price 1. It is not market data.`, `Simulated ESG data: not available; loaded companies carry no ESG fields.` | holdout |
| AC-4 | No dataset | `GET /api/index/universes/file:DAX` | `fields` is exactly `{"metrics": ["float_mcap", "free_float_factor", "price", "shares_outstanding"], "flags": [], "categories": ["country", "sector"]}` | holdout |
| AC-5 | — | `GET /api/index/universes/file:NOPE`, then `GET /api/index/universes/file:..%2Fconfig%2Fusers` | both 404 with detail starting `Unknown starting universe:` | holdout |
| AC-6 | `ARP_HOLDINGS_DIR` = a directory with one file `X.xlsx` whose only lines are 1 cash line, 1 equity line with weight −0.01, 1 equity line with weight `N/A` | `GET /api/index/universes/file:X` | 422, detail `X.xlsx: no equity lines with a positive weight.` | holdout |
| AC-7 | No dataset, the default spec | `POST /api/index/run` with `universe` `file:DAX`, `review_date` 2026-11-02, `persist` false | 200; 40 constituents; constituent `isin_DE0007164600` named `SAP` with weight 0.1176544801 (within 1e-9) and price 1.0 | holdout |
| AC-8 | Same | the same run's `input_notes` are read | its first four entries equal the four notes of AC-3 | holdout |
| AC-9 | A stored portfolio `p1` whose latest snapshot holds: company `c_a` through two securities (weight_pct 30 and 20), company `c_b` (weight_pct 45), a cash security (weight_pct 5), a security with no company (weight_pct 1) | `GET /api/index/universes/portfolio:p1` | `company_count` 2; notes line 2 is `Dropped 2 lines: 1 cash, 0 other asset class, 0 zero or negative weight, 0 without a weight, 1 not linked to a company.` | holdout |
| AC-10 | Same | `POST /api/index/run` with `universe` `portfolio:p1`, the default spec | constituent weights: `c_a` 0.5263157895, `c_b` 0.4736842105 (within 1e-9) | holdout |
| AC-11 | The fixture dataset | `GET /api/index/universes/file:DAX` | notes line 4 is `Simulated ESG data: matched 1 of 40 companies.` | holdout |
| AC-12 | The fixture dataset, a spec with one metric threshold screen on `esg_score` min 5, `missing` `fail` | run on `file:DAX` | exactly 1 constituent, `isin_DE0007164600` | holdout |
| AC-13 | No dataset, the same screen with `missing` `block` | run on `file:DAX` | 422, detail starts `Data quality block:` and names `esg_score` | holdout |
| AC-14 | The fixture dataset | `GET /api/index/universes/file:DAX` | `fields.categories` is exactly `["country", "lct_category", "peer_group", "sector", "transition_grade", "transition_grade_label"]` | holdout |
| AC-15 | The fixture dataset, a spec with a category screen on `transition_grade` allowing only `B`, `missing` `fail` | run on `file:DAX` | exactly 1 constituent, `isin_DE0007164600` | holdout |
| AC-16 | The default spec | `POST /api/index/run` with `universe` `file:DAX` and a one-element `candidates` list | 400, detail `Send either universe or candidates, not both.` | holdout |
| AC-17 | — | `POST /api/index/run` with `universe` `file:NOPE` | 404, detail `Unknown starting universe: file:NOPE` | holdout |
| AC-18 | The default spec with solver method `min_tracking_error`, no `returns_panel` | run on `file:DAX` | 422, detail `Risk model: a loaded starting universe has no returns history, so tracking-error methods cannot run on it. Use the built-in demo universe, or send a returns_panel.` | holdout |
| AC-19 | The default spec with `tracking_error_budget` 0.02, no `returns_panel` | run with 3 `candidates` sent directly | 422 with the detail of AC-18 | holdout |
| AC-20 | A review on `file:DAX` saved under `dax_index` @ 2026-11-02 | `GET /api/index/dax_index/levels/2026-11-02` | 409, detail `No level series: this review ran on a loaded starting universe, which has no price history (its prices are a weight proxy).` | holdout |
| AC-21 | Must not change: the default spec, and each preset `GET /api/index/presets/<name>` returns for the names in the catalogue's `presets` | run with no `universe` and no `candidates`, and again with `universe` `demo` | both responses equal `main` before this spec (excluding `created_at`), and equal each other | holdout |
| AC-22 | Must not change: a demo review saved under `demo_index` @ 2026-03-31 | `GET /api/index/demo_index/levels/2026-03-31?days=5` | identical to `main` before this spec | holdout |
| AC-23 | Must not change: a demo run with solver method `min_tracking_error` and no `returns_panel` | `POST /api/index/run` | the same status and body as on `main` before this spec (excluding `created_at`) | holdout |
| AC-24 | Must not change | `GET /api/index/catalogue` | `fields` equals `main` before this spec | holdout |
| AC-25 | Must not change: no `universe` sent | a run with `decision_snapshot_ids` | `input_notes` equal `main` before this spec (no starting-universe notes) | holdout |
| AC-30 | The e2e stack, Index Construction → Compose | the page opens | a `Starting universe` card is above the Preset card, its select shows `Built-in demo universe (60 synthetic companies)`, and its options include `DAX.xlsx (holdings file, 2026-11-02)` | evaluator |
| AC-31 | Same | `DAX.xlsx (holdings file, 2026-11-02)` is chosen | the four notes of the loaded universe show under the select, the first being `Starting universe: DAX.xlsx, holdings as of 2026-11-02, 40 companies.` | evaluator |
| AC-32 | Same, DAX chosen | the Base weighting scheme is set to `metric` and its Field picker opened | it lists `float_mcap` and does not list `adv_3m` | evaluator |
| AC-33 | Same, DAX chosen, the index id still `demo_index` | the index id field is read | `dax_index` | evaluator |
| AC-34 | Same, DAX chosen, no preset, no rules added | Preview is run, the Result tab opened | the result lists 40 constituents, among them `SAP` at `11.77%` | evaluator |
| AC-35 | Same, DAX chosen | the Compose and the Result tab are read | both show `Starting universe: DAX.xlsx (holdings as of 2026-11-02, 40 companies). Sizes are a weight proxy and ESG values, where present, are simulated. The results describe no real index.` and neither shows the `Demo data:` banner | evaluator |
| AC-36 | Same, DAX chosen, then the demo universe chosen again | Compose is read | the `Demo data:` banner of the themes spec shows, the notes are gone, and the Base weighting Field picker (scheme `metric`) lists `adv_3m` again | evaluator |
| AC-37 | Same, DAX chosen, the solver method set to Minimum tracking error | Preview is run | the page shows the 422 detail of AC-18 | evaluator |
| AC-38 | Index Builder with the API mocked: universes list as AC-1, the DAX load answering 500 `boom` | DAX is chosen | an error containing `boom` shows under the select, the select shows the demo universe again, and the pickers keep the catalogue's fields | unit |
| AC-39 | Index Builder with the API mocked, the user typed index id `my_index`, then chose DAX | the index id field is read | `my_index` | unit |
| AC-40 | Index Builder with the API mocked, DAX chosen | Preview is run | the run request body has `"universe": "file:DAX"` and no `candidates` | unit |
| AC-41 | Must not change: Index Builder with the API mocked, the demo universe | Preview is run | the run request body has no `universe` and no `candidates` key, as on `main` | unit |

Rows owned by PR 1: AC-1 to AC-25. PR 2: AC-30 to AC-41.

Must not change: demo runs, demo levels, demo tracking-error runs, the catalogue's fields, and run requests
without a universe (AC-21 to AC-25, AC-41).
