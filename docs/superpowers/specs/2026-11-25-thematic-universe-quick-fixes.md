# Thematic Universe quick fixes: plain words, no prefilled theme, sensible order

Status: Draft, for owner approval
Slug: `thematic-universe-quick-fixes`
Risk: `risk:low` (frontend copy and layout; the one logic change is the default sort order). One PR, one slice. R&D Lab plan item 11, fixes part of finding U2.

## Decisions for the owner

None needed a question. Every choice is listed under "Defaults taken"; approving the spec approves them.

## Why

The Thematic Universe page (`#/theme`, `frontend/src/pages/ThemeBuilder.tsx`) is the R&D Lab's way into a theme, and it greets a new visitor with someone else's theme, internal words and numbers nobody reads:

- the theme name opens as "Electrification" and the description as a sentence about electricity, so a new theme is typed over an old one;
- the Exposure column shows `pure_play`, `significant`, `minor`, `none` as stored;
- results open sorted by the model's confidence, so a weak match the model is sure about outranks a pure play it is less sure about;
- the Layers table shows scores such as `0.7234`;
- the input-output checkbox and the catalogue upload use the words "EXIOBASE input-output propagation", "catalogue", "taxonomy_id" and "CapEx".

The Theme Workbench (plan item 13) replaces this screen later; these fixes stay small and touch nothing else.

## Goals

1. The page opens with an empty theme name and an empty description.
2. Exposure shows a plain label, never the stored value.
3. Results open sorted strongest exposure first, ties by higher confidence, then by company name A to Z.
4. The Layers table shows Layer 1, Layer 2 and Score as percentages.
5. The input-output and catalogue options use the plain wording in "Wording" below.

## Non-goals

- No layout redesign, no new components, no new screens (item 13, Theme Workbench).
- No navigation or tool renames (the Theme Radar dispatcher's `theme-radar-screen` spec owns them). The page title stays "Thematic Universe".
- No backend, API or schema change; no new endpoint field.
- The verdict filter options, the other column headers and the saved-run behaviour do not change.
- The Taxonomy Library's own "New taxonomy" form (it also opens with "Electrification") is not touched; no row covers it.

## Anti-goals (must stay true)

- A run opened by link (`#/theme/<run id>`) still shows its stored results.
- What is sent to the backend is unchanged except that it is now typed by the user instead of prefilled.
- The word "product" appears nowhere in new text.

## Design

All changes are in `frontend/src/pages/ThemeBuilder.tsx` and `frontend/src/components/ThemeLayersTable.tsx`.

**1. Empty theme.** `useState("Electrification")` becomes `useState("")`, and the description default becomes `""`. "Decompose into activities" is disabled while the name, trimmed, is empty (it would send an empty theme). Nothing else about the form changes.

**2. Exposure labels.** The Exposure cell in the results table shows `Pure play`, `Significant`, `Minor` or `None` for `pure_play`, `significant`, `minor`, `none`. A value outside these four is shown as stored and ranks with `None` when sorting.

**3. Sort.** `sortBy` starts as `"exposure_desc"`. Its comparator orders by exposure tier (Pure play, Significant, Minor, None), then `confidence` high to low, then `name` A to Z (`localeCompare` with default arguments). Its option text becomes `Sort: strongest exposure first` and it is the first option. The other three options keep their text and behaviour. Filters apply as before.

**4. Percentages.** In the Layers table, Layer 1, Layer 2 and Score are shown as `(value × 100).toFixed(1) + "%"`. A null value stays empty. "not available" (Layer 3) and "insufficient data" (Score) stay as they are.

**5. Wording.**

| Where | Today | New |
|---|---|---|
| Checkbox | Enable indirect (input-output) exposure tier using the bundled sample dataset | Also find companies linked to the theme through supply chains (uses sample data) |
| Help under it | Structural supply-chain exposure via EXIOBASE input-output propagation … | Finds companies that never mention the theme but buy from or sell to those that do. The sample data is for trying this out only; for a real run, set ARP_VALUE_CHAIN_DIR on the backend and leave this off. |
| Help over the file input | Optional: a structured revenue/CapEx catalogue … | Optional: upload a CSV of company revenue and capital spending by activity. Where a company is in the file, its figures are used first; the written debate above is used only when there are none. |
| File input accessible name | Revenue/CapEx catalogue (CSV) | Revenue and capital spending file (CSV) |
| Button | Suggest activity -> catalogue-label mapping | Match activities to file labels |
| Hint when no taxonomy is loaded | Load a saved taxonomy above first — mapping suggestion needs a taxonomy_id to reference. | Load a saved taxonomy above first. Matching activities to file labels needs one. |

## Defaults taken

- "Combined score" is defined as exposure tier first, then confidence, then name. The results carry no single score field, and a backend change is out of scope.
- Percentages show one decimal (`72.3%`), matching the one-decimal percentages already on the page.
- Plain labels are Title-case sentence style: `Pure play`, not `Pure-play`.
- The empty-name guard is a disabled button, with no new message.
- The sort change is logic, not only text, so a reviewer may relabel the PR `risk:normal`; the spec does not change either way.

## Supersedes

No earlier acceptance row asserted the old prefilled text, the stored exposure values, the old default order, four-decimal scores or the old option text (checked in `frontend/tests/` and `backend/tests/e2e/`). `test_authority_taxonomy_page.py` also types "Electrification" but on the Taxonomy Library page, which stays.

## Acceptance

E2E rows run the page with the API stubbed by Playwright routes (as in `backend/tests/e2e/test_showcase_themes_screens.py`): `**/api/runs/run_t` returns a completed theme-run manifest, `**/api/themes/runs/run_t/results*` returns the stated results, `**/api/themes/runs/run_t/layers*` returns the stated layers. No model call is made. Every stubbed match has `verdict: "include"`, one activity, a distinct `company_id` per company, and the stated name, `exposure_estimate` and `confidence`. "As on a fresh page" means `#/theme` with no stored state.

Result sets used below (company: exposure, confidence):
- **Set 1:** `A Co`: minor, 0.95; `B Co`: pure_play, 0.60; `C Co`: significant, 0.90; `D Co`: none, 0.99; `E Co`: significant, 0.70.
- **Set 2:** `Zed`: significant, 0.80; `Alpha`: significant, 0.80; `Mid`: significant, 0.80; `Top`: pure_play, 0.10; `Low`: none, 0.99.
- **Set 3:** `A`: pure_play, 0.5; `B`: significant, 0.5; `C`: minor, 0.5; `D`: none, 0.5; `E`: none, 0.5 (E ranks last on name).

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | A fresh page | It has rendered | The "Macro theme name" input value is `""` | holdout |
| AC-2  | A fresh page | It has rendered | The "Description" textarea value is `""` | holdout |
| AC-3  | A fresh page | It has rendered | "Decompose into activities" is disabled | holdout |
| AC-4  | A fresh page | The user types `Water` into "Macro theme name" | "Decompose into activities" is enabled | holdout |
| AC-5  | A fresh page | The user types three spaces into "Macro theme name" | "Decompose into activities" is disabled | holdout |
| AC-6  | Set 3, `#/theme/run_t` | It has loaded | The Exposure cells read, top to bottom, exactly `Pure play`, `Significant`, `Minor`, `None`, `None` | holdout |
| AC-7  | Set 3, `#/theme/run_t` | It has loaded | No table cell contains `pure_play`, `significant` or `minor` | holdout |
| AC-8  | Set 1, `#/theme/run_t` | It has loaded, sort untouched | The Company column reads top to bottom `B Co`, `C Co`, `E Co`, `A Co`, `D Co` | holdout |
| AC-9  | Set 2, `#/theme/run_t` | It has loaded, sort untouched | The Company column reads `Top`, `Alpha`, `Mid`, `Zed`, `Low` | holdout |
| AC-10 | Set 1, `#/theme/run_t` | It has loaded | The selected option of "Sort results" reads `Sort: strongest exposure first` | holdout |
| AC-11 | Set 1, `#/theme/run_t` | It has loaded | The first option of "Sort results" reads `Sort: strongest exposure first` | holdout |
| AC-12 | Set 1, `#/theme/run_t` | The user picks `Sort: confidence (high to low)` | The Company column reads `D Co`, `A Co`, `C Co`, `E Co`, `B Co` | holdout |
| AC-13 | Set 1, `#/theme/run_t` | The user picks `Sort: confidence (low to high)` | The Company column reads `B Co`, `E Co`, `C Co`, `A Co`, `D Co` | holdout |
| AC-14 | Set 1, `#/theme/run_t` | The user picks `Sort: company name (A-Z)` | The Company column reads `A Co`, `B Co`, `C Co`, `D Co`, `E Co` | holdout |
| AC-15 | `#/theme/run_t`; layers stub returns one row `{issuer_key: "k1", name: "A Co", rank: 1, in_run: true, l1: 0.7234, l2: 0.05, l3: null, score: 0.6, pure_play: false, status: "ok", l2_via: []}` | The Layers card has loaded | That row's Layer 1, Layer 2 and Score cells read exactly `72.3%`, `5.0%`, `60.0%` | holdout |
| AC-16 | As AC-15 but `l1: 1`, `l2: null`, `score: null`, `status: "insufficient data"` | The Layers card has loaded | Layer 1 reads `100.0%` and Layer 2 is empty | holdout |
| AC-17 | As AC-16 | The Layers card has loaded | Layer 3 reads `not available` and Score reads `insufficient data` | holdout |
| AC-18 | A fresh page | It has rendered | A checkbox labelled exactly `Also find companies linked to the theme through supply chains (uses sample data)` exists | holdout |
| AC-19 | A fresh page | The page text is searched | None of `input-output`, `EXIOBASE`, `bundled sample dataset` occurs | holdout |
| AC-20 | A fresh page | It has rendered | The text `Finds companies that never mention the theme but buy from or sell to those that do. The sample data is for trying this out only; for a real run, set ARP_VALUE_CHAIN_DIR on the backend and leave this off.` is present | holdout |
| AC-21 | A fresh page | It has rendered | A file input with accessible name `Revenue and capital spending file (CSV)` exists and none has the name `Revenue/CapEx catalogue (CSV)` | holdout |
| AC-22 | A fresh page | It has rendered | The text `Optional: upload a CSV of company revenue and capital spending by activity. Where a company is in the file, its figures are used first; the written debate above is used only when there are none.` is present | holdout |
| AC-23 | A fresh page; `**/api/universe/raw-upload` stubbed to return `{"path": "/tmp/c.csv"}`, `**/api/taxonomies` to return `{"taxonomies": []}`; the user chooses a CSV in the file input | The upload finishes | The text `Load a saved taxonomy above first. Matching activities to file labels needs one.` is present | holdout |
| AC-24 | The component's own unit test with a loaded taxonomy and an uploaded file | It renders | A button named `Match activities to file labels` exists and none is named `Suggest activity -> catalogue-label mapping` | unit |
| AC-25 | A fresh page | The visible text of the page, excluding the navigation bar, is searched | The word `product` (whole word, any case) does not occur | holdout |
| AC-26 | A fresh page; `**/api/themes/decompose` stubbed; the user types `Water` and `Wet` into the name and description | The user presses "Decompose into activities" | The request body is exactly `{"name": "Water", "description": "Wet"}` | holdout |
| AC-27 | A fresh page | It has rendered | The `h1` text is exactly `Thematic Universe` | holdout |
| AC-28 | Set 1, `#/theme/run_t`; the stub has citation quote `Revenue rose` and rationale `Builds batteries.` on `B Co` | The user clicks the `B Co` row | The text `Builds batteries.` is visible | evaluator |
| AC-29 | As AC-28 | The user clicks the `B Co` row | The text `Revenue rose` is visible | evaluator |
| AC-30 | Set 1, `#/theme/run_t` | It has loaded | The result table headers read, in order, `Company`, `Activity`, `Verdict`, `Exposure`, `Confidence`, `Source`, `Structural`, `Review` | holdout |
| AC-31 | Set 1, `#/theme/run_t` | The "Filter by verdict" options are read | They read `All verdicts`, `Include`, `Exclude`, `Uncertain` | holdout |

Must not change: AC-12 to AC-14 (kept sort options), AC-26 (request payload), AC-27 (page title), AC-28 and AC-29 (row detail), AC-30 and AC-31 (headers and verdict filter).
