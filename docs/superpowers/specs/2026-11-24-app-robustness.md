# App robustness: no blank app, no silent failures, no stale screens

Status: Draft, for owner approval
Slug: `app-robustness`
Risk: `risk:normal` (frontend only; no auth, schema, money or workflow path; owes the UI review gate)
Size: `M`, two slices (bug-list bundle C = item 7, bundled as the owner asked)

## Decisions for the owner

1. **Publish for an authoritative framework (Decision Studio).** Asked in the spec thread. Specified here
   with the recommended answer: the button is hidden and one line says why (AC-31, AC-32). If the owner
   picks another answer, those two rows change before approval.

Every other choice is listed under "Defaults taken"; approving the spec approves them.

## Why

The review of 23 Nov 2026 (`/mnt/project-files/antigravity-patch-review/bug-list.md`, IDs A27 to A30, A33,
A35, B4, A37 to A42; consolidated rows M22 to M26, M28, L5 to L10) found faults that still reproduce on
`main` at `9359fb5`. Three of them blank the whole Agentic Research Platform: a crash in any screen, a bad `%`
in the address, and Enter in the command palette for a viewer. The rest make a screen fail without a word,
keep showing something that no longer applies, or undo what the person just did. The Antigravity patch has
reference fixes, but its Emerging Themes fix shows every error twice (B4), so this spec states the behaviour
instead of pointing at the patch.

## What the user can do afterwards that they cannot do today

- Keep working when one screen crashes: the top bar, the workspace row and the command palette still work,
  the screen shows what happened and a "Try again" button. Today the whole page goes blank.
- Open a pasted link with a broken `%` sequence (`#/history/%E0`). Today the page goes blank.
- Press Enter in the command palette as a viewer when nothing matches. Today the page goes blank.
- Pick a run that has no review screen from the palette and land on that run in Run History. Today every such
  run opens `#/history` at the top, and the rows share one React key, so the list can mix them up.
- Send a taxonomy from the Taxonomy Library to the Thematic Universe once. Today it reloads over the person's
  edits when the taxonomy list refreshes (for example after "Save as taxonomy draft") and on every later visit.
- See why Emerging Themes, the Taxonomy Library or Theme results did not load. Today the list stays empty.
- Run company exposure for a promoted Emerging Themes candidate and land on that run. Today it is refused (no
  universe sent) or lands on an empty Thematic Universe.
- Add a rule on the sandbox opened by IP over plain http. Today "+ Add a rule" throws.
- Publish from Decision Studio only what the server accepts, and not see the last framework's "Published"
  banner or sensitivity panel after switching frameworks.

## Three versions

- **Safe:** patch each site as the Antigravity patch does (try/catch here, a guard there, a boundary in
  `App.tsx`). Each site keeps its own ad-hoc race guard, so the next screen repeats the bug.
- **Strong (specified here):** one route-level error boundary; small pure helpers for the patterns that
  repeat (safe decode, latest-request-wins, a cache that forgets a failure, a random id); every load that can
  fail shows one line; state that belongs to one framework, run or visit is cleared when that changes.
- **Most ambitious:** the strong version plus a shared `useLoad` hook that every screen's first load goes
  through (loading, error and retry in one place), and replacing every `.catch(() => {})` in `frontend/src`
  (about 40 sites). Next step up would need: an audit of all those sites, many of which are intentional
  ("no dossiers just means no links"), so it is its own item.

## What exists today

All paths under `frontend/src/`.

- **Palette.** `components/CommandPalette.tsx:66` keys rows by `it.href`. `App.tsx:115` `runItem` gives every
  run that is neither `proxy_voting` nor in `REVIEWABLE_RUN_TYPES` the href `#/history`, so up to 50 rows share a
  key. With no `onAsk` (role `viewer`) and no match, `askRow` is `-1`, `count` is `0`, `current` is `-1`, so
  Enter takes the `current === askRow` branch and calls `onAsk!` (undefined): the throw blanks the app.
- **Address.** `App.tsx:125` `parseHash` maps each hash segment through `decodeURIComponent`, which throws on a
  malformed `%` sequence; nothing catches it. `components/SourcePanel.tsx:7` `isPdfUrl` does the same on a
  source address.
- **No error boundary.** No `ErrorBoundary` or `componentDidCatch` anywhere in `frontend/src`. The screens render
  inside `<Suspense>` in `<main>` (`App.tsx:301-354`).
- **Board diagram.** `boardDiagram.ts:7-14` caches the Mermaid import promise even when it rejects, so one
  failed load fails every later draw. `draw()` awaits the import and fonts, so two quick `draw` messages can
  finish in the other order and leave the older diagram on screen.
- **Rules list.** `components/RulesList.tsx:110` calls `crypto.randomUUID`, which only exists in a secure
  context (https or localhost).
- **Orb.** `components/Orb.tsx:124-157` `loop` calls `scene.frame(...)` and only then requests the next frame,
  so one throw (a lost WebGL call) ends the animation for good. `orb/orbScene.ts:290-300` builds the
  `EffectComposer`, `UnrealBloomPass` and final pass up front, though `low` quality never renders them.
- **Rule engine download.** `lib/zenEngine.ts:55` reads `fetch(wasmUrl)` as an `ArrayBuffer` without checking
  the status, so a 404 page reaches WebAssembly and the editor shows
  `WebAssembly.instantiate(): expected magic word…`.
- **Theme Builder.** `App.tsx:165,253-256,316` keeps `pendingTaxonomyId` for the whole session.
  `pages/ThemeBuilder.tsx:72-76` loads it whenever `taxonomies` changes, and `saveAsDraft` appends to
  `taxonomies`. "Refresh results" (`:476`) awaits `getThemeResults` with no catch. The "Filter by activity"
  select (`:490`) lists `theme?.activities`, and a run opened from `#/theme/<run id>` has no theme loaded.
- **Decision Studio** (`pages/DecisionStudio.tsx`). "Publish to stewardship and index…" (`:1346`) shows for any
  ratified, saved version; `backend/arp/api/routers/decision.py:826` answers 422 for `purpose ===
  "authoritative"`. `published` and `sensitivity` survive `onApplyTemplate` and `onSave`. The score effect
  (`:358-371`) debounces but does not drop a response that arrives after the config changed again. `onRatify`
  (`:455`) does not call `refreshTemplates`, unlike `onSave`.
- **Emerging Themes** (`pages/EmergingThemesDetector.tsx`). `:40-44` calls `refreshRecentRuns()` and
  `getEmergingThemesSchedule()` with no catch; `selectRun` and the two Refresh buttons don't catch either.
  `runCompanyExposure` (`:147`) sends `universe_path: null` when no universe is picked (backend 422) and on
  success calls `onNavigate("theme")`, an empty Thematic Universe. The page's one error line is `:197`.
- **Taxonomy Library** (`pages/TaxonomyLibrary.tsx`). `refreshLibrary` (`:58`) has no catch; `TaxonomyVersions`
  (`:95`) swallows its error. `mapStandards` (`:164`) saves a new version but the open editor keeps the old
  `activities`, so the mapped codes never show. `OverlapView.addFund` (`:687`) accepts a name already in the
  list, and `compute` builds `{name: path}`, so the second fund silently replaces the first.
- **Smaller ones.** `components/RuleGraphEditor.tsx:68,103` keeps `traceRow` when the rows shrink, so nothing
  is traced and no row is marked. `components/RefineThread.tsx:330-364` `DeckView` with no `section[data-slide]`
  shows an empty slide area with no message; `SlideFrame.mark` (`:383`) reports overflow after `fonts.ready` even when the frame was
  unmounted meanwhile, so a slide's "Text doesn't fit" line can land on the next slide.
  `pages/ArgusFlow.tsx:69-71` reads the flow on every step change without the `changes` guard `refresh` uses,
  and `:173` passes `flow.companies.find(...)!` to the edit row, which crashes when the company is gone.

## Goals

1. A crash inside one screen shows a message and "Try again" in place of that screen; the rest of the app
   keeps working.
2. No address, however malformed, blanks the app.
3. The command palette never throws on Enter, and every row has its own key and its own target.
4. A taxonomy sent to the Thematic Universe loads once, on that visit only.
5. Every load named above that can fail says so in one line, and Emerging Themes shows each error once.
6. Company exposure from Emerging Themes is sent only with a universe, and opens the run it started.
7. Decision Studio offers Publish only where the server can accept it, and drops state that belonged to
   another framework version or to an older score request.
8. Taxonomy Library shows the result of "Map to NACE / NAICS / SIC / GICS" and refuses a duplicate fund name.
9. Thematic Universe: "Refresh results" errors are shown; a run opened by link can be filtered by activity.
10. Rule ids, the board diagram, the Orb, the rule engine download, the rule trace, the Refine deck view and
    the Argus flow survive the failure each one has today.

## Non-goals

- Raw `setInterval` polling, `window.confirm`, stale `eslint-disable` comments (bug-list C3.5).
- Every other bug-list item, and every `.catch(() => {})` not named above.
- An authoritative publish flow in Decision Studio (the backend has `POST /api/authoritative/publish`; no screen
  uses it).
- Any backend or API change. No generated API file changes.
- Hardening the render code of a screen so it cannot crash (the boundary catches it instead).

## Anti-goals

- An error shown twice on one screen (B4).
- A silent `catch {}` in the Orb loop: the first failure is logged.
- A boundary that hides the top bar, the workspace row or the palette.
- Any UI text with the word "product".

## Design

### Shared helpers (pure, node-loadable)

Each module below has no runtime import other than `.ts`-suffixed relative paths, so
`node --test --experimental-strip-types` can load it, as `npm test` does.

| Export (file) | Behaviour |
|---|---|
| `safeDecode(s: string): string` (`lib/nav.ts`) | `decodeURIComponent(s)`; when that throws, `s` unchanged. |
| `runItem(r: RunManifest): PaletteItem` (`lib/commandPalette.ts`, new; moved out of `App.tsx`. Not `lib/palette.ts`, which holds the chart colours and must stay unchanged) | `label` `` `${runTypeLabel(r.run_type)} ${r.run_id}` `` and `hint` `"Run"`, as today. `href`: `proxy_voting` → `#/voting/<run_id>` and a type in `REVIEWABLE_RUN_TYPES` → `#/review/<run_type>/<run_id>`, both as today (not encoded); any other type → `#/history/<encodeURIComponent(run_id)>`. `PaletteItem` moves with it and `CommandPalette` re-exports or imports it. |
| `latestGate(): { next(): () => boolean }` (`lib/latest.ts`, new) | Each `next()` returns a check that is `true` until `next()` is called again on the same gate, then `false` for good. Gates are independent. |
| `memoUntilRejected<T>(load: () => Promise<T>): () => Promise<T>` (`lib/latest.ts`) | The first call calls `load` and returns its promise; later calls return that same promise while it is pending or after it resolved. After it rejects, the next call calls `load` again. |
| `randomId(): string` (`lib/randomId.ts`, new) | 32 lowercase hex characters from `crypto.getRandomValues` (16 bytes). Never reads `crypto.randomUUID`. |
| `wasmBytes(res: Response): Promise<ArrayBuffer>` (`lib/wasmFetch.ts`, new) | `res.arrayBuffer()` when `res.ok`; else rejects with `Error("the rule engine could not be downloaded (HTTP <status>)")`. |
| `activityOptions(theme, results)` (`lib/themeBuilder.ts`) | `theme: ThemeDefinition \| null`, `results: CompanyMatch[]`. Returns `{ id, name }[]`: with a theme, its activities (`activity_id`, `name`) in theme order; without one, each distinct `activity_id` of `results` with its `activity_name`, in first-seen order. |

### App shell

- **Error boundary.** A class component (file left to the builder) wraps the content of `<main>` after the hub
  nav: the `<Suspense>` and every screen. `ProcessBar`, the hub nav, `AppTopbar`, `WorkspaceRow` and the palette
  stay outside it. It is not keyed by the hash: a screen that is not in error is never remounted by it (Argus steps, Agent,
  Voting and XBRL selections keep their state as today). When it is showing an error and
  `window.location.hash` changes, it clears the error and renders the new route. When a screen throws
  while rendering (including a lazy screen whose code fails to load), it renders, in place of the screen:

  ```html
  <div class="card" role="alert">
    <h2>This screen stopped working</h2>
    <p>Something went wrong while showing it. The rest of the app still works: try again, or open another screen.</p>
    <button>Try again</button>
    <details><summary>Error details</summary><pre>{error.message}</pre></details>
  </div>
  ```

  It calls `console.error` once per caught error. "Try again" clears the error and renders the screen again
  (a fresh mount, so its first loads run again). Class names are the builder's; the texts are exact.
- **Address.** `parseHash` uses `safeDecode`. `SourcePanel.isPdfUrl` uses `safeDecode`.
- **Palette.** Keep the line `const askRow = onAsk && question ? …` as it is: `frontend/tests/searchOrAsk.test.ts`
  reads it. `App.tsx` uses `runItem` from `lib/commandPalette.ts`. Rows are keyed so that no two rows share a key.
  Enter does nothing when `count === 0`; it calls `ask()` only when `askRow >= 0 && current === askRow`.
  Arrow keys stay within `0 … count-1` (nothing happens when `count === 0`).
- **Rules list.** `rule_${randomId()}` replaces `rule_${crypto.randomUUID()}`.
- **Board diagram.** `loadMermaid` is `memoUntilRejected(...)`. `draw` takes a check from one module-level
  `latestGate` when it starts, and after each `await` returns without touching `root` or replying when the
  check is `false`.
- **Orb.** `loop` calls `scene.frame` in `try`. On a throw it calls `console.error("Orb frame failed", error)`
  the first time only (per Orb mount), and still requests the next frame. Three throws in a row switch the Orb
  to its still image (`toStill()`), as a lost context does today. `orbScene` builds the composer, bloom and final
  pass on the first `layout()` whose quality is not `low`, and never for an Orb that stays `low`; once built
  they are kept. The step-down rule (spec `expressive-ui-orb`, AC-26) is unchanged.
- **Rule engine.** `instantiate` reads the wasm with `wasmBytes(await fetch(wasmUrl))`. `zenErrorText` of that
  error is its message, unchanged.

### Screens

- **Theme Builder, sent taxonomy.** `App.tsx` passes the pending id once: `ThemeBuilder` gets an
  `onPendingTaxonomyTaken` callback (name left to the builder) and calls it right after it loads the pending
  taxonomy; `App` then sets `pendingTaxonomyId` to `null`. If the pending id is not in the first loaded list, nothing
  loads and the pending id is still cleared. A later change of the taxonomy list, and a later visit
  to `#/theme`, load nothing.
- **Theme Builder, results.** "Refresh results" catches its error and shows `errorDetail(e)` in the page's
  existing error line (as `onFinish` does). "Filter by activity" lists `activityOptions(theme, results)`.
- **Decision Studio.**
  - The Publish button shows only when `config.ratified && !unsaved && dataset && config.purpose !==
    "authoritative"`. For a ratified, saved authoritative version, in its place, a
    `<span className="muted">` (shown when `config.ratified && !unsaved && dataset && config.purpose ===
    "authoritative"`) reads `This framework is authoritative: it publishes values, not tiers, so it
    has no Publish button here.`
  - `loadConfig(next)` sets `published` and `sensitivity` to `null` when `next` is `null` or its `framework_id`
    or `version` differs from the current config's. (Ratify returns the same id and version, so it keeps them.)
  - The score effect takes a check from a `latestGate` per request and sets `result` or the error only when the
    check is still `true` after the response.
  - `onRatify` calls `refreshTemplates()` after a successful ratify.
- **Emerging Themes.** One error line, the existing `role="alert"` at `:197`, for every page error. No second
  error element is added.
  - Recent scans load (first load and the "Refresh" button) fails: `Recent scans could not be loaded: <detail>`.
  - Candidates load (`selectRun`, "View candidates", "Refresh candidates") fails:
    `Candidates could not be loaded: <detail>`.
  - The schedule load fails: the "Automatic schedule" card renders with only its `h2` and
    `<p className="error-text" role="alert">The schedule could not be loaded: <detail></p>`.
  - "Run company exposure" with no universe picked sends nothing and shows
    `Choose the company universe under "Run a scan now" first.` in the error line.
  - A successful exposure start sets `window.location.hash` to `#/theme/<encodeURIComponent(run_id)>` of the
    response. The 409 "gated" path is unchanged.
  - Each of these lines is cleared by the next successful load of the same list, and replaced by any later
    error the page shows.
  - `<detail>` everywhere in this spec is `errorDetail(e)` from `lib/themeLayers.ts` (the server's `detail`
    without the `NNN: ` prefix).
- **Taxonomy Library.**
  - `refreshLibrary` failure: `The taxonomy list could not be loaded: <detail>` in a `role="alert"` paragraph
    under the sub-nav; it is cleared by the next successful load.
  - `TaxonomyVersions` failure: `The versions could not be loaded: <detail>` in place of the list.
  - `mapStandards` success: the open editor shows the returned version's activities, and a `role="status"`
    line reads `Standards mapped and saved as v<version>.` (`version` of the response).
  - `addFund` with a name already in the list (exact match after trimming): no upload is sent, the file input
    is cleared, and the error line reads `<name> is already in the list. Give this fund another name.`
- **Rule trace.** The traced row is `min(traceRow, inputs.length - 1)`; with no rows nothing is traced.
- **Refine deck.** `DeckView` with `count === 0` shows `<p className="muted">This deck has no slides.</p>` and
  no slide frame. `SlideFrame` does not call `onOverflow` or touch the frame's document after it unmounted.
- **Argus flow.** The step-change read uses the same `changes` guard as `refresh`, so a read that began before
  a change is dropped. When the row being edited has no company in `flow.companies`, the edit form closes and the
  row renders as a normal row.

## Defaults taken

- The boundary is per route, not per component: one crash replaces the whole screen, not one card.
- The boundary shows the error message under a closed "Error details"; no stack trace.
- A crash in the top bar, the workspace row or the palette is not caught (they are small and shared).
- Palette run rows without a review screen open `#/history/<run id>`, which scrolls to and marks the run (the
  existing Run History behaviour), rather than keeping `#/history`.
- Run ids in `#/history/…` are encoded; the existing `#/voting/…` and `#/review/…` palette targets are not
  touched.
- Decision Studio clears `published` and `sensitivity` on a framework or version change; the comparison is
  kept (it compares tables, not versions).
- The Orb goes still after three failed frames in a row; one or two failures only log.
- A duplicate fund name is refused rather than renamed.
- An Emerging Themes schedule load failure shows in the schedule card, not the page error line, so a load
  failure of both shows two different lines, each once.
- No `evaluator` rows: every row below runs as a hidden test (pure function or browser with stubbed API).
  Rows that need a real WebGL failure, a timing race or a real deck are `unit`; the UI review covers looks.
- The "no word `product`" anti-goal is covered by the exact-text rows: they are the only new UI strings.

## Notes for the builder

- Proof per defect: a test that fails on `main` and passes after, with the failing output in the PR
  description. Pure functions: `node --test` tests in `frontend/tests/`. Screens: browser tests in
  `backend/tests/e2e` with `page.route` stubs, as `test_refine_agent.py` does.
- Do not harden the render code the hidden boundary tests may use to make a screen throw (for example
  Emerging Themes' `signal_velocity.toFixed`): this spec catches crashes, it does not remove them.
- After the change, screenshot the boundary and Emerging Themes and run `/impeccable:impeccable audit` (UI rule).
- Left to the builder: the boundary's file and class names, the callback name for the pending taxonomy, test
  names.
- Say in the PR whether `openwiki/` needs an update (it likely does not: no route or API change).

## Acceptance

**Node rows** ("When" is a function call) import the named export from the named file under `frontend/src/`
and run under `node --test --experimental-strip-types`, as `npm test` does. **Browser rows** run in headless
Chromium at 1440 × 900 against the app from `backend/scripts/e2e_stack.sh up` (dev auth, role `approver`
unless "Given" says `viewer`, which means `GET /api/me` is stubbed to answer `{"user_id": "vic", "name": "vic",
"role": "viewer"}`). Any API response a row names is stubbed with `page.route`; "fails" means it answers 500 with
`{"detail": "boom"}`. "No page error" means Playwright's `pageerror` event did not fire. **CRASH** is: open
`#/emergingThemes` with `GET /api/runs?run_type=emerging_themes` answering one run `{"run_id": "et_1", "status":
"completed", …}`, then click its "View candidates", with
`GET /api/emerging-themes/runs/et_1/candidates` answering one candidate whose `signal_velocity` is the string
`"x"` (so rendering the row throws). **DS(purpose)** is Decision Studio at `#/decision` with these stubs: `GET /api/decision/datasets` answers one
dataset `d1` whose columns include every column the frameworks use; `POST /api/decision/templates/match` answers
framework A v1 (ratified, `purpose` as given, no `missing_columns`) and framework B v1 (ratified, not
authoritative, no `missing_columns`), both with `rule_graph: null`; `GET /api/decision/mechanisms/<A or B>…` answers that framework's envelope;
`POST /api/decision/score` answers a result with one entity; `POST /api/decision/sensitivity` answers one row for
it; `POST /api/decision/publish` answers a snapshot of 1 row; `GET /api/decision/published` answers `[]`;
`GET /api/authoritative/values…` answers `[]`. "Apply X" means: select `d1` on the Data tab, then click `Apply` on
X's row. **M(r, t)** is a `RunManifest` with `run_id: r`, `run_type: t`.

### Shared helpers

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | — | `safeDecode("%E0")` and `safeDecode("100%")` | `"%E0"` and `"100%"` | holdout |
| AC-2 | — | `safeDecode("a%20b")` and `safeDecode("Grid%2FStorage")` | `"a b"` and `"Grid/Storage"` (must not change) | holdout |
| AC-3 | — | `runItem(M("es 1", "emerging_themes")).href` | `"#/history/es%201"` | holdout |
| AC-4 | — | `runItem(M("x1", "extraction")).href` and `runItem(M("v1", "proxy_voting")).href` | `"#/review/extraction/x1"` and `"#/voting/v1"` (must not change) | holdout |
| AC-5 | — | `runItem(M("es1", "emerging_themes"))` `.label` and `.hint` | `runTypeLabel("emerging_themes") + " es1"` and `"Run"` (must not change) | holdout |
| AC-6 | — | `const g = latestGate(); const a = g.next(); const b = g.next();` then `a()`, `b()` | `false`, `true` | holdout |
| AC-7 | — | Two gates `g1`, `g2`; `const a = g1.next(); g2.next();` then `a()` | `true` | holdout |
| AC-8 | `load` counts its calls and resolves `"m"` | `const f = memoUntilRejected(load); await f(); await f();` | both results `"m"`, `load` called 1 time | holdout |
| AC-9 | `load` rejects with `Error("x")` on its first call, resolves `"m"` on its second | `const f = memoUntilRejected(load);` `await f()` (caught), then `await f()` | first rejects with message `"x"`, second resolves `"m"`, `load` called 2 times | holdout |
| AC-10 | `globalThis.crypto.randomUUID` replaced by `undefined` for the test | `randomId()` twice | each matches `/^[0-9a-f]{32}$/`, and the two differ | holdout |
| AC-11 | — | `await wasmBytes(new Response("<html>", {status: 404}))` | rejects with message `"the rule engine could not be downloaded (HTTP 404)"` | holdout |
| AC-12 | — | `await wasmBytes(new Response(new Uint8Array([0, 97, 115, 109])))` | an `ArrayBuffer` of byte length 4 | holdout |
| AC-13 | — | `activityOptions(null, [{activity_id: "a2", activity_name: "Storage", …}, {activity_id: "a1", activity_name: "Grid", …}, {activity_id: "a2", activity_name: "Storage", …}])` | `[{id: "a2", name: "Storage"}, {id: "a1", name: "Grid"}]` | holdout |
| AC-14 | — | `activityOptions({activities: [{activity_id: "a1", name: "Grid", …}]} , [{activity_id: "a9", activity_name: "Other", …}])` | `[{id: "a1", name: "Grid"}]` (must not change) | holdout |

### App shell

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-15 | — | CRASH | One `role="alert"` element contains heading `This screen stopped working`, the text `Something went wrong while showing it. The rest of the app still works: try again, or open another screen.` and a button `Try again`; no page error | holdout |
| AC-16 | The end state of AC-15 | Look at the page | The top bar's `Main` navigation and the link `ARP start` are visible | holdout |
| AC-17 | The end state of AC-15 | Click `ARP start` | The URL hash is `#/home` and no element shows `This screen stopped working` | holdout |
| AC-56 | The end state of AC-15 | Press Ctrl+K | The command palette dialog (`Search or ask`) is open | holdout |
| AC-57 | `GET /api/argus/flows/f1` answers a flow `f1` with `step: 2` (reached) and one company row; `#/argus/f1/1` open; the test has set `data-mark="1"` on the page's `.argus-flow` element | Click the step 2 link in `nav` `Steps` | The URL ends `/2` and the `.argus-flow` element still has `data-mark="1"` (not remounted; must not change) | holdout |
| AC-18 | The end state of AC-15, then the candidates stub changed to answer `signal_velocity: 1.5` | Click `Try again` | `h1` `Emerging Themes` is visible and no element shows `This screen stopped working` | holdout |
| AC-19 | — | Open `#/history` with `GET /api/runs` answering `{"runs": []}` | `h1` `Run History` visible; no element shows `This screen stopped working` (must not change) | holdout |
| AC-20 | — | Open `#/history/%E0` | `h1` `Run History` is visible; no page error | holdout |
| AC-58 | A source panel opened on a source whose address contains `%E0` | It renders | No page error | unit |
| AC-21 | Role `viewer` | Press Ctrl+K, type `zzqxq`, press Enter | No page error; the palette is still open and shows `No screen matches “zzqxq”.` | holdout |
| AC-22 | Role `viewer`; palette open with `zzqxq` typed | Press ArrowDown, then Enter | No page error | holdout |
| AC-23 | Role `approver` | Press Ctrl+K, type `zzqxq`, press Enter | The URL hash becomes `#/agent` (Enter still asks; must not change) | holdout |
| AC-24 | `GET /api/runs` (no query; the palette's run list) answers runs `M("es1", "emerging_themes")` and `M("es2", "emerging_themes")`, both updated now | Press Ctrl+K, type `es2`, press Enter | The URL hash is `#/history/es2` | holdout |
| AC-25 | A schema editor with rules, the app opened at `http://<the machine's non-loopback IP>:5173` | Click "+ Add a rule" | The new-rule editor opens; no page error | unit |
| AC-26 | The board's diagram frame, the first Mermaid import failing | Ask it to draw again | The second draw imports again and shows the diagram | unit |
| AC-27 | Orb at quality `high`, `scene.frame` throwing once | The next animation frames run | One `console.error` beginning `Orb frame failed`; the Orb keeps animating | unit |
| AC-28 | Orb, `scene.frame` throwing on every frame | Three frames run | The still image shows; `console.error` was called once | unit |
| AC-29 | Orb at quality `low` from the start | It runs | No `EffectComposer` or `UnrealBloomPass` is created; the step-down of `expressive-ui-orb` AC-26 still happens (must not change) | unit |

### Screens

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-30 | Taxonomy Library, `GET /api/taxonomies` answering T1 (theme name `Grid build-out`) and T2 (theme name `Heat pumps`) | Open T1's row, click `Use in Thematic Universe →` | The Thematic Universe's "Macro theme name" input value is `Grid build-out` (must not change) | holdout |
| AC-33 | The end state of AC-30 | Set the URL hash to `#/taxonomy`, wait for `h1` `Taxonomy Library`, then set it to `#/theme` | "Macro theme name" input value is `Electrification` (the default) | holdout |
| AC-34 | The end state of AC-30; `POST /api/themes/decompose` answers a theme named `Drafted`; `POST /api/taxonomies` answers T3 (theme name `Drafted`, `taxonomy_id: "t3"`) | Click `Decompose into activities`, then `Save as taxonomy draft` | "Macro theme name" input value is `Drafted` | holdout |
| AC-35 | `#/theme/tr_1`; `GET /api/runs/tr_1` answers `{"run_id": "tr_1", "run_type": "theme", "status": "completed", …}`; `GET /api/themes/runs/tr_1/results…` answers 2 results with activities `a1`/`Grid` and `a2`/`Storage` | Open the "Filter by activity" select | Its options read `All activities`, `Grid`, `Storage` | holdout |
| AC-36 | The end state of AC-35, then the results stub changed to fail | Click `Refresh results` | Exactly one `role="alert"` element on the page; it reads `boom`; no page error | holdout |
| AC-31 | DS(`authoritative`); Apply A | Open the Audit tab | No button `Publish to stewardship and index…`; the text `This framework is authoritative: it publishes values, not tiers, so it has no Publish button here.` is visible | holdout |
| AC-32 | DS(`score`); Apply A | Open the Audit tab | The button `Publish to stewardship and index…` is visible and the AC-31 text is not (must not change) | holdout |
| AC-37 | DS(`score`); Apply A; on Audit, Publish confirmed (a line starting `Published ` shows); on Results, the entity row expanded and `How much do the weights matter?` clicked (an `h2` starting `How much do the weights matter —` shows) | Apply B, then open Results and Audit | No `h2` starting `How much do the weights matter —` and no line starting `Published ` is shown | holdout |
| AC-38 | DS(`score`) with A unratified (`ratified: false`); Apply A; `POST /api/decision/mechanisms/A/ratify…` answers A v1 ratified | Open Audit, click `Ratify version 1…` and confirm | After the ratify answer, a `POST /api/decision/templates/match` is sent | holdout |
| AC-39 | Decision Studio, config edited twice in a row, the first `POST /api/decision/score` answering after the second | Both answers arrive | Results show the second answer | unit |
| AC-40 | `GET /api/runs?run_type=emerging_themes` fails | Open `#/emergingThemes` | Exactly one `role="alert"` element on the page; it reads `Recent scans could not be loaded: boom`; no page error | holdout |
| AC-41 | `GET /api/emerging-themes/schedule` fails, the run list answers `{"runs": []}` | Open `#/emergingThemes` | Under the heading `Automatic schedule`, a `role="alert"` element reads `The schedule could not be loaded: boom`; exactly one `role="alert"` on the page | holdout |
| AC-42 | One completed run `et_1` listed; its candidates request fails | Click `View candidates` | Exactly one `role="alert"` on the page; it reads `Candidates could not be loaded: boom` | holdout |
| AC-43 | Run `et_1` with one candidate, status `promoted`, `promoted_to_taxonomy_id: "tx1"`, expanded; no universe picked | Click `Run company exposure` | No `POST /api/themes/runs` is sent; exactly one `role="alert"` element on the page; it reads `Choose the company universe under "Run a scan now" first.` | holdout |
| AC-44 | As AC-43, but a CSV chosen in the `Run a scan now` universe picker with `POST /api/universe/upload` answering `{"path": "u/uni.csv", "company_count": 3, "sample": []}`; `POST /api/themes/runs` answers `{"run_id": "tr_9", "company_count": 3}` | Click `Run company exposure` | The `POST /api/themes/runs` body has `universe_path: "u/uni.csv"` | holdout |
| AC-54 | The end state of AC-44 | — | The URL hash is `#/theme/tr_9` | holdout |
| AC-45 | `GET /api/taxonomies` fails | Open `#/taxonomy` | A `role="alert"` element reads `The taxonomy list could not be loaded: boom`; no page error | holdout |
| AC-46 | Taxonomy Library, T1 open; `GET /api/taxonomies/<T1 id>/versions` fails | Look at T1's detail | The text `The versions could not be loaded: boom` is visible | holdout |
| AC-47 | Taxonomy Library, T1 (v1) open; `POST /api/taxonomies/<T1 id>/map-standards` answers T1 v2 whose first activity has `standards_mapping` with `nace_codes: [{"code": "D35.11", "label": ""}]` and every other array (`naics_codes`, `sic_codes`, `gics`, `unmapped_isic_codes`) empty; the following `GET /api/taxonomies` answers T1 v2 | Click `Map to NACE / NAICS / SIC / GICS` | The open detail shows `NACE: D35.11` | holdout |
| AC-55 | The end state of AC-47 | — | A `role="status"` element reads `Standards mapped and saved as v2.` | holdout |
| AC-48 | Taxonomy Library, `ETF holdings overlap` tab; `POST /api/universe/raw-upload` stubbed; fund `Fund A` added once | Type `Fund A` as the display name and choose a CSV file | No second upload request is sent; the funds table has 1 row; an element reads `Fund A is already in the list. Give this fund another name.` | holdout |
| AC-49 | Rule editor tracing row 5 of 6 preview rows | The rows shrink to 2 (another table) | Row 2 is traced and marked selected | unit |
| AC-50 | A Refine deck thread whose deck HTML has no `section[data-slide]` | Open it | The text `This deck has no slides.` is visible | holdout |
| AC-51 | A Refine deck with an overflowing slot on slide 1 only | Select slide 1, then slide 2 before slide 1's fonts are ready | No `Text doesn't fit` line under slide 2 | unit |
| AC-52 | Argus step 1, a step-change read started, then a change saved | The step-change read answers after the change | The flow shown is the one the change returned | unit |
| AC-53 | Argus step 1, editing a row whose company is then removed by an identity result | The flow re-renders | The edit form is gone and the row renders; no page error | unit |

Must not change: AC-2, AC-4, AC-5, AC-14, AC-19, AC-23, AC-29 (the Orb step-down), AC-30, AC-32, AC-57 (no remount on
step change). The existing hidden
test `test_ac_18_palette_keeps_screens` reads option text only and keeps passing.

## Slices

Two PRs, each `risk:normal`, each with `Spec: app-robustness` and its `Rows:` line in the description, and every
test it changes listed. Slice 2 starts after slice 1 has merged (it uses `latestGate` and `memoUntilRejected`).

| Slice | Size | PR contents | Rows |
|---|---|---|---|
| 1 | S | App shell and shared helpers: `safeDecode`, `lib/commandPalette.ts`, `lib/latest.ts`, `lib/randomId.ts`, `lib/wasmFetch.ts`, `activityOptions`; error boundary; palette; address; rules list; board diagram; Orb; rule engine download | AC-1 to AC-29, AC-56 to AC-58 |
| 2 | M | Screens: Theme Builder, Decision Studio, Emerging Themes, Taxonomy Library, rule trace, Refine deck, Argus flow | AC-30 to AC-55 |
