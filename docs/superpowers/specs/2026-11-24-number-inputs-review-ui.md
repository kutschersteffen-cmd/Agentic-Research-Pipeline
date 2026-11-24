# Comma and number inputs that keep what you type; review excerpt, Argus and RFP fixes

Status: Draft, for owner approval
Slug: `number-inputs-review-ui`
Risk: `risk:normal` (frontend only; no auth, schema, money or workflow path; owes the UI review gate)
Size: `M`, one PR (bug-list bundle A = items 4 + 5, bundled as the owner asked)

## Decisions for the owner

None. Nothing open here would change an acceptance row. The choices taken are listed under "Defaults
taken"; approving the spec approves them.

## Why

The review of 23 Nov 2026 (`/mnt/project-files/antigravity-patch-review/bug-list.md`, IDs A18 to A23, A31,
A32, A34, B5, B8; consolidated rows H4, M15, M16, M27, H5, M17, M18, L11) found eight faults that still
reproduce on `main` at `7ce4350`. Four make an input fight the person typing in it. Four show or send the
wrong thing. The Antigravity patch has reference fixes, but it adds two faults of its own (B5: a cleared
number jumps to a default mid-typing; B8: a failed earlier run is hidden without a word), so this spec
states the behaviour instead of pointing at the patch.

## What the user can do afterwards that they cannot do today

- Type a comma list (seed keywords, matched labels, screen allow and deny lists, factor fields) the way
  one types anywhere else: `Energy,` stays `Energy,` until the next word is typed. Today the comma
  vanishes at once, so a second item can only be pasted in.
- Type a tier boundary of `-0.5` or `2.5` in the Decision Studio level grid. Today `-` disappears and
  `2.` becomes `2`.
- Type `Energy = 1.5` line by line in a category multiplier table. Today the line is deleted at the first
  keystroke, because `Energy` alone is not yet a valid line.
- Clear an Index Builder number and type a new one: select all, `7` gives `7`. Today, in the eight fields
  that default (for example Default multiplier), clearing shows the default at once and the next key
  gives `17`.
- Run or save an Index Builder methodology whose weighting field and tilt group are the ones the selects
  show. Today "Weight by metric" shows a field but sends none, and the backend refuses the run; a
  group-max tilt shows a group but sends `none`.
- Read the right source excerpt for a value cited on page 2 or later, under a caption that names the
  page once. Today the excerpt card is empty or shows the wrong sentence.
- See conflicts counted under Argus "Waiting for you"; today the Conflicts line never appears.
- Open a kept company's earlier TNFD or Financials results from Argus step 5, and still see the
  table when one earlier run cannot be read, with a line that says which. Today the link opens the
  extraction review, and one unreadable earlier run blanks the whole table.
- Open `#/rfp/abc` or a Refine link to `rfp/abc` without the app sending `NaN` requests, and press Cancel
  on "Discard the unsaved changes?" without a palette question firing on the next Agent visit.

## Three versions

- **Safe:** patch each call site in place (eleven `split(",")` handlers, one textarea, eight `?? default`
  handlers), as the Antigravity patch does. Every site keeps its own parsing, so the next comma list
  repeats the bug.
- **Strong:** one shared draft-while-focused input and one module of pure parsers used at every site;
  number fields that keep `null` while typing and fill their default on blur; selects that send what they
  show; the five review and Argus fixes with pure helpers.
- **Most ambitious (specified here):** the strong version, plus one check, `specProblem`, that blocks
  both Run and Save in Index Builder with a message naming the card to fix, and an explicit default
  for every required number field in Index Builder (today five of them can be sent empty and are
  refused by the backend).

Next step up would need: an audit of every other `type="number"` and free-text list input in the app
(Decision Studio weights, Signals, Strategy Replication, ThemePosition cites) and an inline per-field
error style, which needs a design the owner has not seen.

## What exists today

All paths under `frontend/src/`.

- **Comma lists.** Each `onChange` does `e.target.value.split(",").map(trim).filter(Boolean)` and the
  input's `value` is the parsed list joined with `", "`, so a trailing comma or a space after it is
  removed on the keystroke that typed it. Sites: `components/ActivityEditorTable.tsx:79` (Taxonomy Library,
  "Seed keywords (comma-separated)"), `components/SchemaFieldsEditor.tsx:53` (Argus schema editor, same
  label), `pages/ThemeBuilder.tsx:388` (activity "Seed keywords (comma-separated)"),
  `pages/ThemeBuilder.tsx:221` `updateMappingLabels` (input `aria-label="Matched labels for <activity>
  <metric>"`), `pages/IndexBuilder.tsx:656` "Allow only (comma separated)", `:664` "Deny (comma
  separated)", `:1175` "Factor fields (comma separated) — …".
- **Tier boundaries.** `components/LevelGridEditor.tsx:83-95`, "Tier boundaries (best first)": the same
  pattern with `Number(v.trim())` and `!Number.isNaN`, so `-` is dropped and `2.` re-renders as `2`.
- **Bucket multipliers.** `pages/IndexBuilder.tsx:891-902`, textarea "Multipliers, one "value = factor" per
  line": the value is rebuilt from the parsed map on every keystroke, so a line that does not yet parse is
  deleted.
- **Index Builder numbers.** `NumberField` (`pages/IndexBuilder.tsx:93`) is `type="number"` and emits `null`
  for an empty field. Eight call sites turn `null` into a default on the keystroke (`v ?? 0`, `?? 1`,
  `?? 0.4`, `?? 260`, `?? 252`, `?? 0.07`): Threshold, N per group, Default multiplier, group cap Max
  weight, Optimality gap, Lookback periods, Periods per year, Annual reduction. Five required fields
  pass `null` through and the backend refuses the spec: Coverage target, Buffer, Fallback coverage,
  Floor multiplier, Ceiling multiplier (`backend/arp/schemas/index.py`, all non-optional floats).
- **Weighting field.** `WeightingCard` (`:779`) shows `spec.base_weighting.field ?? fields.metrics[0]` in
  its Field select but writes nothing until the person changes it; `BaseWeighting` rejects `metric` and
  `inverse_metric` without `field`.
- **Tilt group.** A new metric tilt has `group_by: "none"`; choosing Normalisation `group_max` shows a
  Within select whose value `none` is not an option, so the browser shows the first category while `none`
  is sent.
- **Run check.** `runReview` (`:295`) refuses a `max_score` objective without a score field with the
  message `Choose the field to maximise under 5 · Constraints before running a max_score methodology.`
  Save (`CalibrationsTab.save`) has no check.
- **Calibration approve.** `CalibrationsTab.approve` (`:1301`) re-reads the versions but not the
  saved-calibrations list (`refresh`), unlike `save`.
- **Source excerpt.** `lib/sourceText.ts` `excerptView` passes `char_start`/`char_end` (document offsets)
  to `excerptParts` on `page_text`; `components/SourcePanel.tsx:96` already subtracts `page_start`.
  Its caption appends ` · p. N` even when `ReviewControls.openSpan` built a title ending `— p. N`.
- **Argus waiting.** `lib/argusStart.ts:104` hard-codes the Conflicts count to 0; conflict items are
  counted under "Values to review".
- **Argus results.** `pages/ArgusResults.tsx:129` links a kept company to `#/review/extraction/<run>`
  whatever the flow extracts; `:71` loads the current and every earlier run in one `Promise.all`, so one
  failure shows only the error and no table. The earlier run is of the flow's own run type
  (`backend/arp/argus/repeat.py` keys repeats on the schema version or the profile's run type).
- **RFP ids.** `App.tsx:341` passes `Number(route.params[0])` to `RfpAnswers`, so `#/rfp/abc` asks for
  `/api/rfp/projects/NaN`. `lib/agent.ts:253` `refineDoc` accepts `rfp/abc`, then
  `components/RefineThread.tsx:64` calls `api.getRfpProject(Number("abc"))`.
- **Queued Agent ask.** `App.tsx:227` `askAgent` stores the question, then navigates to `#/agent`. When the
  open screen refuses the navigation (`canLeave()` false, `App.tsx:173`), the stored question stays and is
  sent the next time the Agent screen opens.

## Goals

1. A comma-list input shows exactly the typed text while it has focus, at all seven sites.
2. Tier boundaries take decimals and negatives while typing.
3. The bucket multipliers textarea shows exactly the typed text while it has focus.
4. An Index Builder number field never shows a value the person did not type while it has focus; a
   required field left empty gets its default when focus leaves it.
5. Index Builder sends the weighting field and the tilt group its selects show, and refuses to run or
   save a methodology that still lacks one, with a message naming the card.
6. Approving a calibration re-reads the saved-calibrations list.
7. The source excerpt is right on every page, and its caption names the page once.
8. Argus "Waiting for you" counts conflicts under Conflicts.
9. Argus step 5 links a kept company to the review of its run's type, and shows the table with a line per
   earlier run that could not be read.
10. A non-numeric RFP id never reaches a request.
11. A queued Agent ask is dropped when the navigation to the Agent screen is refused.

## Non-goals

- Every other bug-list item: Agent screen (bundle B), App robustness (bundle C), and the rest.
- Any backend or API change. No generated API file changes.
- Number and list inputs outside the sites named above (Decision Studio weights, Report Builder focus
  areas, ThemePosition cites, Signals, Strategy Replication).
- The layout of the review queue, the source panel and Argus step 5.

## Anti-goals

- A cleared number field that fills in a default while it still has focus (B5).
- An earlier run that fails to load and disappears without a line (B8).
- A select that shows one value and sends another.
- Any UI text with the word "product".

## Design

### Shared parsers: `frontend/src/lib/draftInput.ts` (new)

Pure functions, exported by these names, with no runtime import other than `.ts`-suffixed relative paths
(so `node --test --experimental-strip-types` can load the module, as `npm test` does):

| Function | Behaviour |
|----------|-----------|
| `parseList(text: string): string[]` | Split on `,`, trim each part, drop empty parts. Order kept, duplicates kept. |
| `listText(items: string[]): string` | `items.join(", ")`. |
| `parseNumberList(text: string): number[]` | Split on `,`, trim, drop empty parts, `Number(part)`, keep only finite numbers. |
| `parseMultipliers(text: string): Record<string, number>` | For each line split on `\n`: split at the first `=`; the key is the trimmed left side, the factor is `Number` of the trimmed right side. A line is kept only when it has an `=`, the key is not empty and the factor is finite and `> 0`. A repeated key: the last line wins. Keys in first-seen order. |
| `multipliersText(m: Record<string, number>): string` | One `<key> = <factor>` line per entry, joined with `\n`. |

### One draft-while-focused input

A shared component (name and file left to the builder) that the seven comma-list sites, the tier
boundaries and the multipliers textarea all use:

- While the element has focus it shows the text the person typed, character for character.
- On every change it hands the parsed value to its owner (`parseList`, `parseNumberList` or
  `parseMultipliers`), so the spec, theme or schema is current without a blur.
- On blur it drops its draft and shows the owner's value formatted (`listText`, `listText` of the
  numbers, `multipliersText`). So `Energy,` becomes `Energy`, `2.` becomes `2`, and an unfinished
  multiplier line disappears.
- Without focus it shows the owner's value as it is now (a loaded preset or theme shows at once).

Tier boundaries keep today's side effect: any change sets `cut_mode` to `absolute`.

### Index Builder number fields

`NumberField` keeps `type="number"` and still emits `null` for an empty field while it has focus. It
gains an optional default: when focus leaves the field and it is empty, it emits the default and shows
it. A field without a default stays empty and its value stays `null`.

| Field (label) | Default on blur when empty |
|---------------|----------------------------|
| Coverage target (0-1) | 0.5 |
| Buffer (0-1) | 0 |
| Threshold | 0 |
| Fallback coverage | 0.25 |
| N per group | 1 |
| Floor multiplier | 0.5 |
| Ceiling multiplier | 2 |
| Default multiplier | 1 |
| Max weight (group cap) | 0.4 |
| Optimality gap | 0 |
| Lookback periods | 260 |
| Periods per year | 252 |
| Annual reduction (0-1) | 0.07 |

The first two, Fallback coverage, Floor and Ceiling use the backend's own defaults. The others keep the
default their `?? x` handler uses today; the `?? x` handlers themselves go. Every other `NumberField`
(Minimum, Maximum, Single-name cap, Minimum weight, Max and Min constituents, Time limit, TE budget,
Reduction vs. universe, and the rest) has no default.

### Selects send what they show

- Choosing scheme `metric` or `inverse_metric` writes `base_weighting.field` = `fields.metrics[0]` when the
  spec has no field, so the Field select's shown value is the value sent.
- Choosing normalisation `group_max` writes `group_by` = `fields.categories[0]` when the tilt's `group_by`
  is not one of `fields.categories`.
- Neither writes anything when the list is empty; `specProblem` then stops the run.

### `specProblem`: one check for Run and Save

A pure function `specProblem(spec)` in `frontend/src/lib/indexSpecCheck.ts` (new), loadable by
`node --test` like `draftInput.ts`. It reads only `spec.base_weighting`, `spec.tilts` and
`spec.constraints.solver`, and returns the first of these messages that applies, else `null`:

1. `base_weighting.scheme` is `metric` or `inverse_metric` and `base_weighting.field` is missing or `""`:
   `Choose the field to weight by under 3 · Base weighting.`
2. For tilts in order, the first with `type` `metric_tilt`, `normalisation` `group_max` and `group_by`
   missing, `""` or `none`: `Choose the group of tilt <n> under 4 · Tilts.` (`<n>` is its 1-based position
   in `spec.tilts`, enabled or not).
3. `constraints.solver.method` is `max_score` and `score_field` is missing or empty: today's message,
   unchanged: `Choose the field to maximise under 5 · Constraints before running a max_score methodology.`

Preview, "Run review and save", "Save as new calibration" and "Save as v<n> of <name>" call it first. A
message is shown in the page's error line (as today's max_score message is) and no request is sent;
Preview and Run also switch to the Compose tab, as today.

### Calibration approve

After a successful approve, `CalibrationsTab` also calls `refresh()` (the saved-calibrations list), as
`save` does.

### Source excerpt

`excerptView(source)`:

- passes `char_start - page_start` and `char_end - page_start` to `excerptParts`; when the result is null
  it falls back to the quote, as today;
- appends ` · p. <page>` only when `text.page` is a number ≥ 1 and the title does not already end with
  `p. <page>` preceded by a space (`/(^|\s)p\. <page>$/`).

### Argus

- `waiting` in `lib/argusStart.ts`: Conflicts = own items with `kind === "conflict"`; Values to review =
  own items that are neither `conflict` nor `quarantined_document`. Group order and the empty-group rule
  unchanged.
- `lib/argusFlow.ts` gains three exports, used by `ArgusResults`:
  - `flowReviewHref(choice, runId)`: `#/review/<type>/<encodeURIComponent(runId)>`, where `<type>` is
    `financials` or `tnfd` for a profile choice of that profile, else `extraction` (a schema choice, or no
    choice).
  - `readEach(ids, read)`: calls `read(id)` for each id and waits for all; returns
    `{ loaded: { runId, value }[], failed: string[] }`, both in the order of `ids`. Never rejects.
  - `earlierFailedLine(runId)`: `Earlier results of <runId> could not be loaded.`
- `ArgusResults`: the "open" link of a kept company uses `flowReviewHref(flow.schema_choice, run_id)`. The
  current run is read as today (its failure shows today's error and no table). Earlier runs are read with
  `readEach`; the table shows the current run's rows plus the kept rows of every loaded earlier run, and
  for each failed one a line `earlierFailedLine(run_id)` in an element with `role="alert"` above the
  table. The note's wording ("kept from the extraction of <date>, open") is unchanged; only its link
  target changes.

### RFP ids and the queued ask

- `rfpId(param)` in `lib/agent.ts`: the number when `param` matches `/^[0-9]+$/`, else `null`. `App.tsx`
  passes `rfpId(route.params[0])` to `RfpAnswers` (`null` shows the project list, as `#/rfp` does).
- `refineDoc`: a `rfp/<id>` whose id fails `rfpId` returns `null` (the Refine picker). Deck ids are
  unchanged.
- `App.tsx`: when the hash-change handler refuses a navigation, it also clears the queued Agent ask.

## Defaults taken

- After blur, a list shows normalised (`a, b`), not the typed spacing. An unfinished multiplier line is
  dropped on blur, not kept as a draft.
- While an input has focus, a change to its value from elsewhere is not shown until blur.
- Index Builder blur defaults are the backend's defaults where today's UI has none; Ceiling multiplier is
  2 (backend), though a new metric tilt still starts at 1.5.
- The weighting field and tilt group are filled with what the select already shows, not left for the
  person to pick (unlike the max_score field, which stays a deliberate choice).
- `specProblem` counts every tilt, enabled or not: the backend validates disabled tilts too.
- The earlier-run line uses the run id, not the run's date.
- RFP ids are plain digits; `007` is 7.
- The Argus "kept from the extraction of <date>" note keeps its wording for profile flows too.
- The "no word `product`" anti-goal is covered by the exact-text rows (AC-34 to AC-40, AC-55): they are
  the only new UI strings.

## Notes for the builder

- Proof per defect: a test that fails on `main` and passes after, with the failing output in the PR
  description. Pure functions: `node --test` tests in `frontend/tests/`. Keystroke behaviour: a browser
  test in `backend/tests/e2e`.
- Run `/impeccable:impeccable audit` on Index Builder and Argus step 5 after the change (UI rule).
- Keep `cut_mode: "absolute"` on tier boundary edits. Keep `encodeURIComponent` out of the existing
  `#/review/...` links you do not touch.
- Left to the builder: the shared input's name and file, test names, and how `NumberField` takes its
  default.
- Say in the PR whether `openwiki/` needs an update (it likely does not: no route or API change).

## Acceptance

**Node rows** ("Checked by" `holdout` with a function call in "When") import the named export from the
named file under `frontend/src/lib/` and run under `node --test --experimental-strip-types`, as
`npm test` does. **Browser rows** run in headless Chromium at 1440 × 900 against the app from
`backend/scripts/e2e_stack.sh up` (dev auth, role `approver`). "Type X" means keyboard input into the
focused element with no blur; `\n` is the Enter key; "Tab" moves focus out. "Input value" is the
element's DOM `value`. **IB** is `#/index`, Compose tab, after the preset button "Empty" is
clicked. "Preview body" is the JSON body of the `POST /api/index/run` that clicking Preview sends.
**T** is `Intro here. In 2025 revenue grew to €39bn, up 16%. Backlog hit €136bn. Outro.` and `s`, `e`
are the start and end of `revenue grew to €39bn` in T. **TX(o)** is the source text object
`{run_id: "r", item_key: "k", doc_id: "d", doc_type: "pdf", page: 2, page_start: 1000, page_text: T}`
with the fields of `o` merged in.

### Comma lists and multipliers

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | — | `parseList(" a , b ,, c ,")` | `["a", "b", "c"]` | holdout |
| AC-2 | — | `listText(["a", "b"])` and `listText([])` | `"a, b"` and `""` | holdout |
| AC-3 | — | `parseNumberList("0.5, -1, 2")` | `[0.5, -1, 2]` | holdout |
| AC-4 | — | `parseNumberList("2., -, 1e, x, , -0.25")` | `[2, -0.25]` | holdout |
| AC-5 | — | `parseMultipliers("Energy = 1.5\nUtilities=0.5")` | `{"Energy": 1.5, "Utilities": 0.5}` | holdout |
| AC-6 | — | `parseMultipliers("Energy\nUtilities = \nTech = 0\nBank = -1\n = 2\nOil = x\nGas = 1.2")` | `{"Gas": 1.2}` | holdout |
| AC-7 | — | `parseMultipliers("Oil = 1\nGas = 2\nOil = 3")` | `{"Oil": 3, "Gas": 2}`, keys in that order | holdout |
| AC-8 | — | `multipliersText({"Energy": 1.5, "Oil": 2})` | `"Energy = 1.5\nOil = 2"` | holdout |
| AC-9 | IB; "+ Category allow / deny" clicked | Type `Energy,` into "Allow only (comma separated)" | Input value `Energy,` | holdout |
| AC-10 | IB; "+ Category allow / deny" clicked | Type `Energy,, Utilities ,` into "Allow only (comma separated)", then Tab | Input value `Energy, Utilities` | holdout |
| AC-11 | The end state of AC-10 | Click Preview | Preview body `spec.screens[0].allow` == `["Energy", "Utilities"]` | holdout |
| AC-12 | IB; "+ Category allow / deny" clicked | Type `Coal, ` into "Deny (comma separated)" | Input value `Coal, ` | holdout |
| AC-13 | IB; Objective set to `min_tracking_error`, then Risk model set to `factor` | Type `sector,` into "Factor fields (comma separated) — …" | Input value `sector,` | holdout |
| AC-14 | IB; "+ Category multiplier table" clicked | Type `Energy` into the "Multipliers, one "value = factor" per line" textarea | Textarea value `Energy` | holdout |
| AC-15 | IB; "+ Category multiplier table" clicked | Type `Energy = 1.5\nOil = 0.` into the multipliers textarea | Textarea value `Energy = 1.5\nOil = 0.` | holdout |
| AC-16 | IB; "+ Category multiplier table" clicked | Type `Energy = 1.5\nOil`, then Tab | Textarea value `Energy = 1.5` | holdout |
| AC-17 | The end state of AC-16 | Click Preview | Preview body `spec.tilts[0].multipliers` == `{"Energy": 1.5}` | holdout |
| AC-18 | Taxonomy Library with a taxonomy whose activity editor is open | Type `solar,` into an activity's "Seed keywords (comma-separated)", then Tab | Value `solar,` before the Tab, `solar` after it | evaluator |
| AC-19 | Argus schema editor with at least one field | Type `revenue,` into a field's "Seed keywords (comma-separated)", then Tab | Value `revenue,` before the Tab, `revenue` after it | evaluator |
| AC-20 | Theme Builder with a theme that has an activity | Type `grid,` into an activity's "Seed keywords (comma-separated)", then Tab | Value `grid,` before the Tab, `grid` after it | evaluator |
| AC-21 | Theme Builder with catalogue mappings shown | Type `Revenue,` into a "Matched labels for …" input, then Tab | Value `Revenue,` before the Tab, `Revenue` after it | evaluator |
| AC-22 | Decision Studio with a framework open on its Level grid | Type `-0.5, 2.` into "Tier boundaries (best first)" (replacing its text) | Input value `-0.5, 2.` | evaluator |
| AC-23 | The end state of AC-22 | Tab | Input value `-0.5, 2` | evaluator |
| AC-67 | Decision Studio framework whose Decision tree "Cut-point method" is `Quantiles` | Type `0.5` into "Tier boundaries (best first)" (replacing its text), Tab, open the Decision tree tab | "Cut-point method" shows `Fixed` (must not change) | evaluator |

### Index Builder numbers, selects and checks

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-24 | IB; "+ Category multiplier table" clicked | Select all in "Default multiplier", press Backspace | Input value `""` (today `1`) | holdout |
| AC-25 | The end state of AC-24 | Type `7` | Input value `7` (today `17`) | holdout |
| AC-26 | The end state of AC-25 | Click Preview | Preview body `spec.tilts[0].default_multiplier` == 7 | holdout |
| AC-27 | IB; "+ Category multiplier table" clicked | Select all in "Default multiplier", Backspace, Tab | Input value `1` | holdout |
| AC-28 | IB; "+ Metric tilt" clicked | Select all in "Floor multiplier", Backspace, Tab | Input value `0.5` | holdout |
| AC-29 | The end state of AC-28 | Click Preview | Preview body `spec.tilts[0].floor` == 0.5 | holdout |
| AC-30 | IB; "Single-name cap (0-1)" set to `0.1` and Tab | Select all in it, Backspace, Tab, click Preview | Preview body `spec.constraints.single_name_cap` == null (must not change) | holdout |
| AC-66 | IB; "Single-name cap (0-1)" set to `0.1` and Tab | Select all in it, Backspace, Tab | Input value `""` (no default fills in; must not change) | holdout |
| AC-31 | IB; "+ Category multiplier table" clicked; "Default multiplier" cleared with select all + Backspace | Click the Calibrations tab, type `ac31` in Name, click "Save as new calibration" | The `POST /api/index/calibrations` body has `spec.tilts[0].default_multiplier` == 1 | holdout |
| AC-32 | IB | Set Scheme (3 · Base weighting) to `metric`, click Preview | Preview body `spec.base_weighting.field` == the value of the Field select shown next to it | holdout |
| AC-33 | IB; "+ Metric tilt" clicked | Set its Normalisation to `group_max`, click Preview | Preview body `spec.tilts[0].group_by` == the value of the "Within" select, and is not `none` | holdout |
| AC-34 | — | `specProblem({base_weighting: {scheme: "metric"}, tilts: [], constraints: {solver: {method: "waterfall"}}})` | `"Choose the field to weight by under 3 · Base weighting."` | holdout |
| AC-35 | — | `specProblem` with `base_weighting: {scheme: "inverse_metric", field: ""}`, otherwise as AC-34 | `"Choose the field to weight by under 3 · Base weighting."` | holdout |
| AC-36 | — | `specProblem` with `base_weighting: {scheme: "equal"}`, `tilts: [{type: "bucket_tilt", field: "sector", multipliers: {}}, {type: "metric_tilt", field: "esg_score", normalisation: "group_max", group_by: "none"}]`, solver `waterfall` | `"Choose the group of tilt 2 under 4 · Tilts."` | holdout |
| AC-37 | — | `specProblem` with `base_weighting: {scheme: "equal"}`, `tilts: [{type: "metric_tilt", field: "esg_score", normalisation: "group_max", group_by: "", enabled: false}]`, solver `waterfall` | `"Choose the group of tilt 1 under 4 · Tilts."` | holdout |
| AC-38 | — | `specProblem({base_weighting: {scheme: "metric", field: "esg_score"}, tilts: [{type: "metric_tilt", field: "esg_score", normalisation: "group_max", group_by: "sector"}], constraints: {solver: {method: "waterfall"}}})` | `null` | holdout |
| AC-39 | — | `specProblem({base_weighting: {scheme: "metric"}, tilts: [], constraints: {solver: {method: "max_score"}}})` | `"Choose the field to weight by under 3 · Base weighting."` (base weighting is checked first) | holdout |
| AC-40 | — | `specProblem` with `base_weighting: {scheme: "equal"}`, `tilts: []`, solver `{method: "max_score"}` | `"Choose the field to maximise under 5 · Constraints before running a max_score methodology."` (must not change) | holdout |
| AC-41 | IB with a spec for which `specProblem` returns a message (for example a metric tilt with `group_max` while the catalogue has no categories) | Click Preview, or Save on the Calibrations tab | The error line shows that message and no `POST /api/index/run` or `POST /api/index/calibrations…` is sent | unit |
| AC-42 | Calibrations tab, an approver approving another user's version | Click Approve | After the `POST …/approve` answers, a `GET /api/index/calibrations` is sent | unit |

### Source excerpt

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-43 | — | `excerptView({title: "AR 2025", src: "", text: TX({char_start: 1000 + s, char_end: 1000 + e})})` | `.parts` deep-equals `{lead: "Intro here.", before: "In 2025 ", mark: "revenue grew to €39bn", after: ", up 16%.", trail: "Backlog hit €136bn."}` | holdout |
| AC-44 | — | The same call as AC-43 | `.caption` == `"AR 2025 · p. 2"` | holdout |
| AC-45 | — | `excerptView({title: "AR 2025", src: "", quote: "Q", text: TX({char_start: 1000, char_end: 1000 + T.length + 1})})` | `{caption: "AR 2025 · p. 2", quote: "Q"}` | holdout |
| AC-46 | — | `excerptView({title: "AR 2025 — p. 2", src: "", text: TX({char_start: 1000 + s, char_end: 1000 + e})})` | `.caption` == `"AR 2025 — p. 2"` | holdout |
| AC-47 | — | `excerptView({title: "AR 2025 — p. 12", src: "", quote: "Q", text: TX({})})` | `.caption` == `"AR 2025 — p. 12 · p. 2"` | holdout |
| AC-48 | — | `excerptView({title: "AR 2025", src: "", text: TX({page: 34, page_start: 0, char_start: s, char_end: e})})` | `.caption` == `"AR 2025 · p. 34"` and `.parts.mark` == `"revenue grew to €39bn"` (must not change) | holdout |

### Argus

**R** is one `ArgusRow` with `runId: "r2"` and `status: "Running"` (other fields any). **I(k)** is a review
item with `run_id: "r2"` and `kind: k`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-49 | — | `waiting([R], [I("value"), I("conflict"), I("conflict"), I("quarantined_document")])` | `{total: 4, groups: [{label: "Conflicts", count: 2}, {label: "Values to review", count: 1}, {label: "Documents to check", count: 1}]}` | holdout |
| AC-50 | — | `waiting([R], [I("value"), I("value")])` | `{total: 2, groups: [{label: "Values to review", count: 2}]}` (must not change) | holdout |
| AC-51 | — | `flowReviewHref({kind: "profile", profile: "tnfd"}, "run_1")` | `"#/review/tnfd/run_1"` | holdout |
| AC-52 | — | `flowReviewHref({kind: "profile", profile: "financials"}, "run_1")` | `"#/review/financials/run_1"` | holdout |
| AC-53 | — | `flowReviewHref({kind: "schema", schema_id: "s", version: 1}, "run_1")` and `flowReviewHref(null, "run_1")` | `"#/review/extraction/run_1"` both | holdout |
| AC-54 | — | `await readEach(["a", "b", "c"], id => id === "b" ? Promise.reject(new Error("x")) : Promise.resolve(id + "!"))` | `{loaded: [{runId: "a", value: "a!"}, {runId: "c", value: "c!"}], failed: ["b"]}` | holdout |
| AC-55 | — | `earlierFailedLine("run_7")` | `"Earlier results of run_7 could not be loaded."` | holdout |
| AC-56 | Argus step 5 of a flow with kept companies from two earlier runs, one of which cannot be read | The page loads | The table shows the current run's rows and the other earlier run's kept rows; one `role="alert"` element reads `earlierFailedLine(<that run>)` | unit |

### RFP ids and the queued ask

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-57 | — | `rfpId("12")` and `rfpId("007")` | `12` and `7` | holdout |
| AC-58 | — | `rfpId(x)` for each x of `"abc"`, `""`, `"1.5"`, `"-1"`, `"12abc"`, `" 12"`, `"NaN"`, `undefined` | `null` for each | holdout |
| AC-59 | — | `refineDoc("rfp/abc")` | `null` | holdout |
| AC-60 | — | `refineDoc("rfp/12")` and `refineDoc("deck/abc")` | `{kind: "rfp", docId: "12"}` and `{kind: "deck", docId: "abc"}` (must not change) | holdout |
| AC-61 | Stack, signed in | Open `#/rfp/abc` and wait for network idle | No request URL sent contains `NaN` | holdout |
| AC-62 | Stack, signed in | Open `#/rfp/abc` and wait for network idle; then, in a fresh page, open `#/rfp` and wait for network idle | The text of the page's `main` element is the same for both | holdout |
| AC-63 | Stack, signed in | Open `#/agent/refine/rfp/abc` and wait for network idle | No request URL sent contains `NaN` | holdout |
| AC-64 | Decision Studio holds an unsaved change (its "Discard the unsaved changes…" confirm is armed) | Open the command palette (Ctrl+K), type `what changed?`, choose the ask row; answer Cancel on the confirm; then click the Agent nav item and answer OK on the second confirm | The Agent screen opens with no new ask thread `what changed?` and no ask request for it is sent | evaluator |
| AC-65 | As AC-64 | Open the command palette (Ctrl+K), type `what changed?`, choose the ask row, and answer OK on the confirm | The Agent screen opens and a new ask thread `what changed?` starts (must not change) | evaluator |

Must not change: AC-30, AC-40, AC-48, AC-50, AC-60, AC-65, AC-66, AC-67. Also unchanged and already covered by tests on
`main`: `frontend/tests/sourceText.test.ts`, `frontend/tests/argusStart.test.ts`, `frontend/tests/refine.test.ts`
and `backend/tests/e2e/test_argus_start.py` pass without edits.
