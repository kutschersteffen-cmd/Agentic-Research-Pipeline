# Fund overlap: how much the house funds hold the same companies, and which companies are picked in more than one scope

Slug: `stewardship-workbench-overlap`. Risk: normal (read-only, no migration, no new table, nothing stored). Size M,
2 PRs. Spec 2a of the prioritisation workbench; uploads are spec 2b (`stewardship-workbench-uploads`).

Status: **approved by the owner on 15 Nov 2026** (buttons in the spec session; review page https://claude.ai/artifact/CkKDtoiuA26h6zSHDpguru).

Where it comes from: `2026-11-13-stewardship-priority-worklist-design.md`, Non-goals: "the consolidated view of
dependencies and overlaps across funds (fund × company matrix, overlap between fund pairs, where selections of
different scopes share companies)". Owner on 13 Nov 2026: "Plus the consolidates view to see dependencies and
overlaps." The owner asked on 15 Nov 2026 to start it; the intake split spec 2 into this spec and uploads.

Owner decisions (15 Nov 2026, buttons in the spec session):

1. A fund pair's cell shows **the shared company count and the shared weight side by side, equally**
   (`412 · 63.0 %`), not one headline number.
2. The fund × company grid shows **the top 100 companies by house weight**, with a switch to **the companies picked
   this quarter in a chosen scope** instead.
3. **Overlap first**: this spec is built for the showcase on about 27 Nov 2026; uploads (spec 2b) come after it.
4. **Risk normal**: the view only reads and shows fund weights; it stores nothing and changes no holdings.

## Why

The house runs several funds (the showcase: 7 ETF funds, 2,581 held companies). An engagement picked in one fund often
concerns a company that four other funds hold too. Today the Workbench shows this one company at a time (the Funds
column, the side panel's Holdings tab, "Also selected in"). The steward and senior management want the whole picture
at once: which funds are close to each other, which companies sit in most funds, and which companies have been picked
by more than one team this quarter, so one engagement can speak for all of them.

## Goals

1. `GET /api/stewardship/overlap`: every house fund, every fund pair's shared company count and shared weight, and
   the companies picked in two or more scopes this cycle, with who holds them.
2. `GET /api/stewardship/overlap/matrix`: a fund × company grid of weights, for the top N companies by house weight
   (default 100) or for the companies picked in one scope this cycle.
3. A Steward Workflow tab **Overlap** (`#/stewardship/overlap`) after **Workbench** that shows the three parts.
4. Fast enough to open in front of senior management: each read under 1 s warm on the showcase data.

## Non-goals

- Uploads of extra per-company information (spec 2b).
- Changing a selection, a programme or a note from the Overlap tab. It only reads; picking stays in the Workbench.
- Stored overlap history, snapshots or trends over time; an overlap at another date than the latest snapshot.
- A new model, data source or table. No change to `worklist.build()`, its response, or the Workbench tab.
- The uncapped 7 × 2,581 grid on screen, CSV or Excel export, charts.
- The ticker-based overlap of uploaded CSV files (`POST /api/overlap`, `compute_holdings_overlap`) stays as it is;
  only its formula is reused.
- Opening the Workbench side panel from the Overlap tab.

## Anti-goals

- A number nobody can trace: every shared weight is the sum of per-company lower weights the grid shows.
- Overlap read as a recommendation. The tab says what the funds hold; it ranks nothing for engagement and pre-selects
  nothing.
- Amber where nobody must act. The only amber is the existing `Proposed` tag on picks that wait for confirmation.
- A slow tab: the two new routes must not call `worklist.build()` or `house_universe()` (the tab may still use
  `GET /worklist/scopes` for its scope list) (the worklist takes about 4 s on the showcase,
  PR #491).

## Constraints

- Built on `fund_holdings(store)` (`arp/stewardship/worklist.py`): fund → company → market value EUR, at the global
  latest snapshot, counting only holdings that resolve to a company. A company's **weight in a fund** is its market
  value ÷ the sum of the fund's company market values × 100, exactly as the worklist's `held_in[].weight_pct`
  (unrounded in the maths, rounded only in the response). Companies are matched by company id, never by ticker.
- The universe source comes from `HouseUniverseSetting(settings.stewardship_streams_dir).get()["source"]`
  (`sample` or `portfolio`); `resolve_scope` gets `{"source": <that>}` as its `sample` argument. The routes do not
  reuse the worklist router's `_in_scope` or `_scope` helpers, which load the whole house universe.
- Selections come from `SelectionLog(root).all_rows(cycle)`; scope names from `scope_labels(store)` plus `house` →
  `All house holdings`; scope keys are validated with `resolve_scope` (404 and 422 as the worklist).
- Company names come from the portfolio store's company directory (`portfolio_directories(store)`, as
  `from_portfolio` names them), without reading observations. Selection rows already carry `company`.
- Computed on every request, no cache. Reads need `viewer` (router-level `authorize`).
- New response models go in a new `arp/schemas/overlap.py`: `scripts/export_openapi.py` and `npm run gen:api` in PR 1, both generated files committed; each
  new `request<T>()` gets a line in `frontend/src/api/contract.ts` (PR 2).
- `DESIGN.md` ("The Annotated Report"): ink on white, accent tint for intensity, amber only for `Proposed`, square
  markers, serif figures, mono for numbers in tables, hand-built HTML/CSS, no chart library. Wide tables scroll
  inside their frame. PR 2 is checked with impeccable and ui-ux-pro-max and carries a Playwright screenshot of
  `#/stewardship/overlap` with the showcase data.
- "LLM plans, code computes": no model call anywhere in this feature.

## Approaches considered

1. **Two read-only endpoints on `fund_holdings()` and the selection log, a new tab (picked).** One pass over the
   latest holdings gives every fund's weights; pairs, the grid and shared picks are plain loops. A separate tab keeps
   the frontend PR out of `workbench.tsx`, which #491's follow-ups are still changing.
2. Derive everything from `worklist.build()` (it already has `held_in` and `selected_elsewhere`). No new maths, but
   about 4 s per read and the whole worklist computed for three small tables. Rejected for speed.
3. A section inside the Workbench page. Closer to the table, but it collides with the open Workbench PRs and makes
   the page longer. Rejected; the tab is one click away.

## Definitions

- **Fund:** a house portfolio with at least one holding that resolves to a company at the latest snapshot, i.e. a key
  of `fund_holdings()`. Funds are listed by name (case-insensitive), then `portfolio_id`.
- **Shared companies** of funds A and B: the companies with a weight in both.
- **Shared weight** of A and B: Σ over the shared companies of min(weight in A, weight in B), in %. It runs from 0
  (nothing shared) to 100 (identical funds), and it is at most the smaller of the two funds' weights in the shared
  companies. It is the formula of `compute_holdings_overlap` (whose denominator, the smaller fund's total weight, is
  100 here) with weights per company id.
- **House weight** of a company: its market value across all funds ÷ the market value of all funds' company holdings
  × 100. It equals the Workbench's `holdings_weight_pct` in the house scope (AC-10).
- **Picked:** a company with a `proposed` or `confirmed` row in a scope's selection log for the cycle (the Workbench's
  **Add to … selection**).

## API

`GET /api/stewardship/overlap?cycle=2026-Q4` (viewer; `cycle` defaults to the current quarter; a value that is not
`YYYY-Qn` is a 422 `A cycle looks like <current cycle>`, as `GET /selection`):

```json
{"as_of": "2026-11-02", "cycle": "2026-Q4", "companies": 2581,
 "funds": [{"portfolio_id": "portfolio_dax", "name": "DAX (public ETF holdings, 2026-11-02)", "companies": 40}],
 "pairs": [{"a": "portfolio_dax", "b": "portfolio_msci_world", "shared_companies": 33, "shared_weight_pct": 71.42}],
 "shared_selections": [
   {"issuer_id": "isin_GB00BP6MXD84", "company": "Shell plc",
    "scopes": [{"scope": "house", "label": "All house holdings", "status": "confirmed"},
               {"scope": "portfolio:portfolio_dax", "label": "DAX (...)", "status": "proposed"}],
    "held_in": [{"portfolio_id": "portfolio_msci_world", "name": "MSCI World (...)", "weight_pct": 0.412}]}]}
```

- `as_of`: the latest snapshot date; `null` with no holdings and with the sample universe (on both routes). `companies`: the number of distinct companies held
  by any fund (0 with no funds). `funds[].companies`: the number of companies that fund holds.
- `pairs`: one entry per unordered pair of funds, `a` listed before `b` in `funds` order (21 pairs for 7 funds).
  `shared_weight_pct` rounded to 2 decimals.
- `shared_selections`: the companies picked in two or more scopes in `cycle`, sorted by the number of scopes
  (descending), then `company` (case-insensitive). `scopes`: `house` first, then by `label` (case-insensitive).
  A scope key with no label (a deleted group or portfolio) shows the key itself as `label` and still counts.
  `held_in`: the funds that hold it, in `funds` order, `weight_pct` rounded to 3 decimals; `[]` when no fund holds it.
- With the sample universe or no holdings: `funds` `[]`, `pairs` `[]`; `shared_selections` still lists picks (the
  sample has `house` and company groups).

`GET /api/stewardship/overlap/matrix?basis=top&n=100` or `?basis=selection&scope=<key>&cycle=2026-Q4` (viewer):

```json
{"as_of": "2026-11-02", "basis": "top", "scope": null, "cycle": "2026-Q4",
 "funds": [{"portfolio_id": "...", "name": "...", "companies": 40}],
 "companies": [{"issuer_id": "isin_US0378331005", "company": "Apple Inc.", "house_weight_pct": 4.213, "funds": 5,
                "weights": {"portfolio_dax": null, "portfolio_msci_world": 4.801}}]}
```

- `basis` `top` (default): the `n` companies with the largest house weight; `n` defaults to 100, 1 to 200, else 422
  `n must be 1 to 200`. Ties: by `company` (case-insensitive), then `issuer_id`. `scope` is ignored and returned as
  `null`.
- `basis` `selection`: every company picked in `scope` in `cycle` (proposed or confirmed), in the same order (house
  weight descending, a company no fund holds last with `house_weight_pct` `null`); `n` is ignored. Without `scope`:
  422 `basis selection needs a scope`. `scope` resolves like the worklist (404 unknown portfolio or group; 422 for a
  group of securities or a fund scope with the sample universe). `scope` is returned as given.
- `weights` has one key per fund in `funds`, the company's weight in that fund rounded to 3 decimals, `null` when the
  fund does not hold it. `funds` (per company) counts the non-null weights. `house_weight_pct` rounded to 3 decimals.
- Any other `basis`: 422. `cycle` is validated as on `/overlap` for every `basis` (it only matters for `selection`)
  and always returned.
- With the sample universe: `basis=top` → 200 with `funds` `[]` and `companies` `[]`; `basis=selection` → 200 with
  the picked companies, each with `house_weight_pct` `null`, `funds` 0 and `weights` `{}`.

Both routes read only. The router lives beside `stewardship_worklist.py` (a new `stewardship_overlap.py`, or new
routes in that router; the builder's call) and is registered with the router-level `authorize`.

## Screen

Steward Workflow gets a tab **Overlap** right after **Workbench**: `{ id: "overlap", n: null, label: "Overlap" }`
inserted in `STAGE_TABS` (`frontend/src/pages/steward/common.tsx`) directly after the entry whose `id` is
`workbench` (added by #491). Top to bottom:

```
Overlap              As of 2 Nov 2026 · 7 funds · 2,581 companies (`companies`) · Cycle 2026-Q4
How much the house funds hold the same companies. Shared weight adds up, for each company two funds both hold,
the lower of its two weights.

Funds side by side
                 DAX            Euro Stoxx 50   MSCI World      S&P 500   …
DAX              40 companies   28 · 54.1 %     33 · 71.4 %     0 · 0.0 %
Euro Stoxx 50    28 · 54.1 %    50 companies    46 · 88.0 %     1 · 0.4 %
MSCI World       33 · 71.4 %    46 · 88.0 %     1,412 companies 498 · 79.3 %
…
(cell = shared companies · shared weight; background: accent tint in 5 steps by shared weight, 0 % none)

Companies across funds          Show: (•) Top [100 ▾] by house weight   ( ) Picked in [ scope ▾ ] 2026-Q4
Company            House wt %   Funds   DAX     Euro Stoxx 50   MSCI World   S&P 500   …
Apple Inc.         4.21         5       —       —               4.80         6.90
Shell plc          0.62         4       —       2.10            0.41         —
…                                                          (cell: weight in that fund, 2 decimals; — not held)

Picked in more than one scope · 2026-Q4
Company      Picked in                                                   Held by
Shell plc    All house holdings · Confirmed;  DAX · ✎ Proposed            Euro Stoxx 50, MSCI World, …
```

- Numbers on the tab: counts with a comma thousands separator (`1,412`); shared weight in the fund table with 1
  decimal, a space, then `%` (`63.0 %`); House wt % and the fund columns of the grid with 2 decimals and no `%` sign
  (the header says %).
- The fund table is square: one row and one column per fund in `funds` order; the diagonal shows `<n> companies`
  (muted); every other cell `<shared companies> · <shared weight, 1 decimal> %`, the same number in both halves. The
  cell's tooltip: `<A> and <B> share <n> companies; <A> holds <x>, <B> holds <y>.`
- The grid scrolls inside its frame with the Company column and the header row pinned. Switching to **Picked in**
  loads `basis=selection` for the chosen scope (the scope list is `GET /api/stewardship/worklist/scopes`); an empty
  result says `No company is picked in <scope> in <cycle>.` The **Top** box offers 25, 50, 100, 200.
- **Picked in more than one scope**: statuses as on the Workbench (`Confirmed`, and `Proposed` with the existing ✎
  tag); empty says `No company is picked in more than one scope in <cycle>.`
- With the sample universe the first two parts are replaced by `Fund overlap needs the portfolio universe. Switch the
  house universe to portfolio holdings in Selection.`; the third part still shows.
- Nothing on the tab is a button that changes data.

## PR split

1. **Backend (can start once this spec is approved):** the two routes, their response models, the maths in a small
   module (e.g. `arp/stewardship/overlap.py`), unit tests, openapi export and `gen:api`. Touches no file of #491 or
   its follow-ups. Measures both reads on the showcase data (warm, second call) and writes the numbers in the PR.
2. **Overlap tab (waits for #491 to merge, because #491 adds the Workbench tab it sits next to):** the tab, the three
   parts, the switch, tooltips, the contract lines. It does not edit `workbench.tsx`, so it does not wait for #491's
   follow-ups (filter builder, side panel, commitments tag); if one of them is open, rebase on `main` and keep the
   tab list change to one line. Screenshot, impeccable audit.

## Left to the builder

- Where the maths sits (new module or `worklist.py`) and how `fund_holdings()` is read once per request.
- The five tint steps' exact thresholds (suggested 0, < 20, < 40, < 60, < 80, ≥ 80 %), column widths, how names
  are shortened in the fund table header (full name in the tooltip).
- If PR 1 measures a read over 1 s on the showcase data: say so in the PR and propose the fix there; adding a cache
  needs the owner (spec 1 allowed one cache only, by owner decision).

## Acceptance

Holdout and evaluator rows run on the e2e stack with `ARP_ENGAGEMENT_STORE=postgres`. Words used below:

- **Showcase data:** `arp showcase load`, `arp stewardship seed-demo`, then `PUT /api/stewardship/universe`
  `{"source": "portfolio"}` (the 7 showcase funds, plus any other house portfolio the stack holds), with the `selection/` directory under `stewardship_streams_dir`
  removed. **P**, **R**: the first and the second fund of `GET /api/stewardship/overlap`'s `funds`. **n**: the number of `portfolio:` keys of `GET /api/stewardship/worklist/scopes` (owner, 16 Nov 2026: count what is there).
- **Fixture W:** as in `stewardship-priority-worklist`: house universe `sample` (`SYN01`..`SYN12`), the `selection/`
  directory removed. **Group G:** `POST /api/portfolio/groups` `{"group_id": "g", "name": "g", "kind": "companies",
  "members": ["SYN01", "SYN02"]}`.
- **Q:** the current calendar quarter, e.g. `2026-Q4`.
- **Unit fixture U:** an in-memory portfolio store with one snapshot date, fund `A` holding company `x` for 600 and `y`
  for 400 EUR, fund `B` holding `x` for 200, `y` for 300 and `z` for 500 EUR, and fund `C` holding `z` for 100 EUR plus
  one holding of 900 EUR whose security resolves to no company.
- PR tags: a row whose Given starts `PR 2;` applies from PR 2; a row whose Given names another row applies from that
  row's PR on (e.g. a Given `AC-27` applies from PR 2); the others from PR 1.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | Unit fixture U | the overlap of the store is computed | Pair (A, B) has `shared_companies` 2 and `shared_weight_pct` 50.0 (min(60, 20) + min(40, 30)) | unit |
| AC-2 | Unit fixture U | the overlap of the store is computed | Pair (B, C) has `shared_companies` 1 and `shared_weight_pct` 50.0 (C's unresolved holding is not counted, so `z` is 100 % of C) | unit |
| AC-35 | Unit fixture U | the overlap of the store is computed | Pair (A, C) has `shared_companies` 0 and `shared_weight_pct` 0.0 | unit |
| AC-3 | Unit fixture U | the top-2 matrix is computed | `companies` lists `x` then `y` (house weights 800/2,100 = 38.095 % and 700/2,100 = 33.333 %; C's unresolved holding is not counted), and `x`'s `weights` = `{"A": 60.0, "B": 20.0, "C": null}` with `funds` 2 | unit |
| AC-4 | Showcase data | `GET /api/stewardship/overlap` | Status 200; `funds` holds n entries whose `portfolio:<portfolio_id>` keys are exactly the `portfolio:` keys of `GET /api/stewardship/worklist/scopes` | holdout |
| AC-5 | AC-4 | — | Each fund's `companies` equals the `companies` of its `portfolio:` entry in `GET /worklist/scopes` | holdout |
| AC-6 | AC-4 | — | `pairs` holds n × (n − 1) / 2 entries, each unordered pair of funds once, with `a` before `b` in `funds` order | holdout |
| AC-7 | AC-4 | `GET /api/stewardship/worklist?scope=portfolio:P` | For every other fund F, the pair (P, F)'s `shared_companies` equals the number of rows whose `held_in` contains F | holdout |
| AC-8 | AC-7 | — | For every other fund F, the pair (P, F)'s `shared_weight_pct` equals the sum over those rows of min(`held_in` weight in P, `held_in` weight in F) within 0.1 | holdout |
| AC-9 | Showcase data | `GET /api/stewardship/overlap/matrix` | Status 200; `basis` `top`, `scope` `null`, 100 `companies`, `house_weight_pct` not increasing down the list | holdout |
| AC-10 | AC-9 and `GET /api/stewardship/worklist?scope=house` | — | Every listed company's `house_weight_pct` equals its worklist `holdings_weight_pct` within 0.001 | holdout |
| AC-11 | AC-10 | — | For every listed company and fund, `weights[<fund>]` equals that fund's `weight_pct` in the company's worklist `held_in` within 0.001, and is `null` when `held_in` has no entry for the fund | holdout |
| AC-12 | AC-9 | — | Every company's `funds` equals the number of non-null values in its `weights` | holdout |
| AC-13 | Showcase data | `GET /api/stewardship/overlap/matrix?n=201` | Status 422 with detail `n must be 1 to 200` | holdout |
| AC-14 | Showcase data | `GET /api/stewardship/overlap/matrix?n=25` | 25 `companies`, the same 25 as the first 25 of AC-9 in the same order | holdout |
| AC-15 | Showcase data; C = the `issuer_id` of the last row of `GET /api/stewardship/worklist?scope=portfolio:P`; `POST /api/stewardship/selection` `{"cycle": Q, "scope": "portfolio:P", "add": [C]}` | `GET /api/stewardship/overlap/matrix?basis=selection&scope=portfolio:P` | `companies` holds exactly C; `basis` `selection`; `scope` `portfolio:P` | holdout |
| AC-16 | Showcase data | `GET /api/stewardship/overlap/matrix?basis=selection` | Status 422 with detail `basis selection needs a scope` | holdout |
| AC-17 | Showcase data | `GET /api/stewardship/overlap/matrix?basis=selection&scope=portfolio:nope` | Status 404 | holdout |
| AC-18 | Fixture W, Group G; `POST /selection` `{"cycle": Q, "scope": "house", "add": ["SYN01", "SYN02"]}`; `POST /selection` `{"cycle": Q, "scope": "group:g", "add": ["SYN01"]}` | `GET /api/stewardship/overlap` | Status 200 with `funds` `[]`, `pairs` `[]` and `companies` 0 | holdout |
| AC-39 | AC-18 | `GET /api/stewardship/overlap` | `shared_selections` holds exactly one entry: `issuer_id` `SYN01`, `held_in` `[]` | holdout |
| AC-43 | AC-18 | `GET /api/stewardship/overlap/matrix` | Status 200, `funds` `[]`, `companies` `[]`, `as_of` `null` | holdout |
| AC-44 | AC-18 | `GET /api/stewardship/overlap/matrix?basis=selection&scope=house` | Status 200; `companies` = `SYN01` and `SYN02` (any order), each with `house_weight_pct` `null`, `funds` 0, `weights` `{}` | holdout |
| AC-45 | Unit: a selection log for cycle Q with company `x` picked in `house` and in `group:gone`, a group that no longer exists | the shared selections are computed | `x` is listed with the scope `{"scope": "group:gone", "label": "group:gone", "status": "proposed"}` | unit |
| AC-19 | AC-18 | — | That entry's `scopes` = `[{"scope": "house", "label": "All house holdings", "status": "proposed"}, {"scope": "group:g", "label": "g", "status": "proposed"}]` | holdout |
| AC-20 | AC-18, then `POST /api/stewardship/selection/confirm` `{"cycle": Q, "scope": "house"}` | `GET /api/stewardship/overlap` | `SYN01`'s `house` scope has `status` `confirmed`; the `group:g` one stays `proposed` | holdout |
| AC-21 | AC-18 | `GET /api/stewardship/overlap?cycle=2020-Q1` | Status 200, `cycle` `2020-Q1`, `shared_selections` `[]` | holdout |
| AC-22 | Fixture W | `GET /api/stewardship/overlap?cycle=2026-13` | Status 422 with detail `A cycle looks like <Q>` | holdout |
| AC-23 | Showcase data; C1 = the `issuer_id` of the first row of `GET /api/stewardship/worklist?scope=portfolio:P`; `POST /selection` adds C1 in scope `house` and in scope `portfolio:P` (cycle Q) | `GET /api/stewardship/overlap` | C1's `shared_selections` entry's `held_in[].portfolio_id`s equal the `portfolio_id`s of C1's `held_in` in `GET /api/stewardship/worklist?scope=house`, in `funds` order | holdout |
| AC-24 | AC-23 (selection files written) | `GET /api/stewardship/overlap` and `GET /overlap/matrix` | The files under `<stewardship_streams_dir>/selection/` have the same names and bytes before and after the two calls | holdout |
| AC-25 | A unit store with 2,600 companies and 7 funds, fund i (i = 0..6) holding the first 300 + i × 383 companies at 1 EUR m each | the overlap and the top-100 matrix are computed | Each takes under 1.0 s on the CI runner | unit |
| AC-26 | Showcase data on the e2e stack | `GET /api/stewardship/overlap` and `GET /overlap/matrix` are each called twice | The second call of each answers in under 1.0 s (time recorded in the evidence) | evaluator |
| AC-27 | PR 2; Showcase data | A user opens `#/stewardship/overlap` | The tab **Overlap** sits right after **Workbench**; the page shows the heading `Funds side by side` with an n × n table | evaluator |
| AC-28 | AC-27 | The user reads the cell for P (row) and R (column) | It shows `<shared_companies> · <shared_weight_pct, 1 decimal> %` from `GET /overlap`'s (P, R) pair | evaluator |
| AC-36 | AC-27 | The user reads the cell for R (row) and P (column) | It shows the same text as the P/R cell | evaluator |
| AC-37 | AC-27 | The user reads the diagonal cell P/P | It shows `<P's companies> companies` | evaluator |
| AC-41 | AC-27 | The user hovers the P/R cell | The tooltip reads `<P name> and <R name> share <n> companies; <P name> holds <x>, <R name> holds <y>.` with the numbers of `GET /overlap` | evaluator |
| AC-29 | AC-27 | The user reads `Companies across funds` | It lists 100 companies, house weight descending, one column per fund, a not-held cell shows `—` | evaluator |
| AC-30 | AC-27 and AC-15's pick | The user chooses **Picked in** and the scope P | The grid shows exactly C | evaluator |
| AC-31 | PR 2; Showcase data, no picks | A user opens `#/stewardship/overlap` | Under `Picked in more than one scope · <Q>` it says `No company is picked in more than one scope in <Q>.` | evaluator |
| AC-38 | AC-31 | The evaluator reads the computed styles of every element inside the Overlap tab's panel (below the tab bar) | No `color`, `background-color` or `border-color` equals DESIGN.md's `signal-amber` (#85601a) or `signal-amber-wash` (#f6ecd6), or their Night values when the dark theme is on | evaluator |
| AC-40 | AC-31 | The evaluator lists the controls inside the Overlap tab's panel and the page's network requests while using every one of them | The only controls are the Top / Picked in switch, the Top select (25, 50, 100, 200) and the scope select; every request the page sends is a GET | evaluator |
| AC-42 | AC-31 | The user chooses **Picked in** and the scope P | The grid area says `No company is picked in <P name> in <Q>.` | evaluator |
| AC-32 | PR 2; Fixture W | A user opens `#/stewardship/overlap` | It says `Fund overlap needs the portfolio universe. Switch the house universe to portfolio holdings in Selection.` and still shows `Picked in more than one scope` | evaluator |
| AC-33 | PR 1 and PR 2 | The evaluator runs `git diff origin/main --stat` on each PR's head | Neither lists `backend/arp/schemas/worklist.py` or `frontend/src/pages/steward/workbench.tsx` (this feature adds no worklist field) | evaluator |
| AC-46 | PR 1 and PR 2 | `pytest tests/test_overlap.py tests/test_showcase_pack.py`, and `git diff origin/main --stat` on each PR's head | The tests pass with neither test file changed, and the diff does not list `backend/arp/research/taxonomy_sources/overlap.py` or `backend/arp/api/routers/overlap.py` | unit |
| AC-34 | PR 2; Showcase data | A user opens `#/stewardship/workbench` | The Workbench tab shows as before this feature: its three steps and the table with the showcase companies | evaluator |

Must not change: the worklist response (AC-33); the Workbench tab (AC-34); the selection logs are only read (AC-24);
`POST /api/overlap` and `compute_holdings_overlap` are not edited (AC-46).
