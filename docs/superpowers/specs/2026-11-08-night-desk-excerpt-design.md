# Night Desk, release 3: source excerpt

## Intent

In the review queue the source is the most important thing a reviewer reads (owner, during the
mockups). Today the source panel (`frontend/src/components/SourcePanel.tsx`) shows the citation as a
small grey italic quote. Release 3 turns it into an excerpt that looks like the source document: a
paper card in a serif face, with the document title and page, the sentence before and after in grey,
and the cited part highlighted in amber. Mockup: `docs/design-directions.html`, "Source excerpt".

## Goals

- The quote in the source panel renders as a paper-like excerpt card in Source Serif 4.
- When the panel has the stored page text and the cited span, the card shows the previous and next
  sentence as context and highlights the cited span.
- The card names the document and, when known, the page.

## Non-goals

- No grounding footer ("Grounded: exact match"): needs backend data.
- No change to the document view under the card (page/text toggle, file frame), the review list,
  or the decision buttons.
- No start page or landing page changes.
- No backend change.

## Anti-goals

- Text in the excerpt that is not in the source (no ellipses inside the mark, no rewording).
- Amber used for anything other than marking the cited span (release 1's rule allows the
  highlight: it marks what the reviewer must decide on).

## Approaches

| | Approach | Trade-off |
|---|---|---|
| A | Restyle the quote only | Smallest; a styled quote, not an excerpt |
| **B (picked)** | Excerpt with surrounding sentences when page text and span are known, else the quote | Close to the mockup, no backend change |
| C | B plus a grounding footer | Needs grounding status from the backend |

The owner picked B.

## Decided

**Pure function.** `excerptParts(text: string, start: number, end: number)` in
`frontend/src/lib/sourceText.ts` returns `null` for an invalid span (same rule as `highlightParts`),
otherwise `{ lead, before, mark, after, trail }`:

- `mark` = `text.slice(start, end)`.
- A sentence boundary is the position right after `". "`, `"? "`, `"! "` or `"\n"` (the boundary
  character and its space belong to the earlier sentence).
- `before` = text from the start of the sentence containing `start` up to `start`; `after` = text
  from `end` to the end of the sentence containing `end`.
- `lead` = the whole sentence before that one (empty if none); `trail` = the whole sentence after
  (empty if none).
- A span that ends exactly at a boundary ends its sentence there: `after` is `""` and `trail` is
  the next sentence.
- Order: first trim, then cut. All five strings are trimmed of leading and trailing whitespace,
  except `before`'s end and `after`'s start, which are kept so words stay separated. Then `lead` is
  cut to its last 240 characters and `trail` to its first 240. Nothing else is shortened.

**View helper.** `excerptView(source: ActiveSource)` in `frontend/src/lib/sourceText.ts` returns
`null` (no figure), `{ caption, quote }` or `{ caption, parts }`: `caption` is the title plus
`" · p. <page>"` when `source.text?.page` is a number; `parts` is `excerptParts` of the stored page text
when `char_start`/`char_end` are set and valid; otherwise `quote` when `source.quote` is set; otherwise
`null`. `SourcePanel` renders only what this returns.

**Card markup.** In `SourcePanel`, the `source-panel-quote` paragraph is replaced by
`<figure class="source-excerpt">` containing:
- `<figcaption class="source-excerpt-meta">` with the title, plus `" · p. <page>"` when
  `source.text?.page` is a number.
- When `source.text` has `char_start` and `char_end` and `excerptParts` returns parts:
  `<blockquote class="source-excerpt-page">` with `lead` and `trail` in
  `<span class="source-excerpt-ctx">`, and `before`, `<mark>{mark}</mark>`, `after` as the middle.
- Otherwise, when `source.quote` is set: the same blockquote with the quote only, no `<mark>`.
- When neither is available, no figure is rendered (as today, when there is no quote).

**Look.** Paper card: background `--panel` in light, `#f5f2ea` (paper) with ink `#1b1a17` in dark
(defined as tokens `--paper` and `--ink`, light `#ffffff` / `--text`), 16px Source Serif 4 at
line-height 1.6, context in `--muted`, `<mark>` background `--await` with a 2px `--await-edge`
underline. The Google Fonts link in `frontend/index.html` adds `Source+Serif+4:opsz,wght@8..60,400;8..60,500`.
`DESIGN.md` gets one line naming Source Serif 4 as the excerpt face.

## Left to the builder

- Spacing inside the card, within the mockup's look.

## Acceptance

Rows marked `unit` are owed as `holdout` once `HOLDOUT_TOKEN` is set; the PR lists them. `T` is
`"Intro here. In 2025 revenue grew to €39bn, up 16%. Backlog hit €136bn. Outro."`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `T`, span on `"revenue grew to €39bn"` | `excerptParts` | `{ lead: "Intro here.", before: "In 2025 ", mark: "revenue grew to €39bn", after: ", up 16%.", trail: "Backlog hit €136bn." }` | unit |
| AC-2 | `T`, span on `"Intro"` | `excerptParts` | `lead === ""` | unit |
| AC-3 | `T`, span on `"Outro"` | `excerptParts` | `trail === ""` | unit |
| AC-4 | `"a".repeat(500) + ". X here. Z."`, span on `"X"` | `excerptParts` | `lead === "a".repeat(239) + "."` (the last 240 characters of the trimmed sentence) | unit |
| AC-5 | `"A. X here. " + "b".repeat(500) + "."`, span on `"X"` | `excerptParts` | `trail === "b".repeat(240)` | unit |
| AC-6 | `"L1\nIn X here\nL3"`, span on `"X"` | `excerptParts` | `lead === "L1"` and `trail === "L3"` | unit |
| AC-6b | `T`, span on `"Intro here. "` (ends exactly at a boundary) | `excerptParts` | `after === ""` and `trail === "In 2025 revenue grew to €39bn, up 16%."` | unit |
| AC-7 | `start >= end`, `start < 0` or `end > text.length` | `excerptParts` | Returns `null` | unit |
| AC-8 | Every span in AC-1..6b | `excerptParts` | `before + mark + after`, trimmed at the outer ends, is a contiguous slice of the input text | unit |
| AC-9 | A source with title `"AR 2025"`, page text `T`, `page: 34`, span as AC-1 | `excerptView` | `caption === "AR 2025 · p. 34"` and `parts.mark === "revenue grew to €39bn"` | unit |
| AC-9b | A source with title `"AR 2025"`, no `text`, `quote: "Revenue was €39bn"` | `excerptView` | `{ caption: "AR 2025", quote: "Revenue was €39bn" }` | unit |
| AC-9c | A source with `text` whose `char_end > page_text.length` and `quote: "Q"` | `excerptView` | Returns `quote: "Q"` and no `parts` | unit |
| AC-9d | A source with no `text` and no `quote` | `excerptView` | Returns `null` | unit |
| AC-10 | `index.css` | `.source-excerpt-page mark` is read | It contains `var(--await)` and `var(--await-edge)` | unit |
| AC-10b | The branch vs `origin/main` | Lines in `frontend/src` outside the three token blocks containing `var(--hi`, `var(--hi-ink`, `var(--await` or `var(--await-edge` are listed | Compared with `origin/main`, the only added lines are in `.source-excerpt-page mark` | unit |
| AC-11 | `index.css` | `.source-excerpt-page` is read | Its `font-family` starts with `"Source Serif 4"` | unit |
| AC-11b | `index.css` | `--paper` and `--ink` are read | Light `#ffffff` and `var(--text)`; both dark blocks `#f5f2ea` and `#1b1a17`; `.source-excerpt-page` uses `var(--paper)` and `var(--ink)` | unit |
| AC-12 | `frontend/index.html` | The Google Fonts URL is read | It contains `Source+Serif+4` | unit |
| AC-13 | The running app, Review Queue, any item with a citation | "view source" is clicked | A `figure.source-excerpt` is shown whose `figcaption` starts with the document title shown in the panel header; if the seed has no such item, the evaluator reports the row as not reachable | evaluator |
| AC-14 | The running app, source panel open on a document with several pages | The page/text toggle, Prev and Next are used | The toggle switches between page and text view; Prev and Next change the shown page number by 1; the file frame is visible in page view | evaluator |
| AC-15 | The branch vs `origin/main` | `git diff origin/main -- frontend/tests` is read | No test or assert is removed; the only changed existing test is `ac13_amber_usage_unchanged`, extended to allow the excerpt `mark` rule | unit |
| AC-15b | The branch | `npm test` runs | Exits 0 | unit |

Must not change: the document view (AC-14), existing tests (AC-15, AC-15b).
