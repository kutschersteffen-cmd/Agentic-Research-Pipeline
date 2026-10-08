# Deck design rules

These rules are shared by the slide-fill prompt, the visual QA prompt and the deck-design skill. The code that
enforces them lives in `art_direct.py` (layout choice and rhythm) and `browser.py` (the measured design check).
DESIGN.md stays locked: monochrome, metric numbers in ink, mono labels, square corners, light and dark.

## Principles

- The headline is the slide's conclusion: one full sentence with a verb and, where there is one, a number. It runs to two lines at most (about 20 words).
- Each slide makes one point and has one focal element. Everything else on it supports that point.
- Every list becomes structure: cards, rows, steps, a flow, a profile or a decision list. A plain bullet slide never ships.
- Pick the layout from the shape of the content. The model's layout pick is a hint; the art director has the last word.
- Colour carries status only. Ratings and scores use the four DESIGN.md status tints (high, mid, low, neutral). No brand colours, no decorative colour.
- Never rewrite an approved headline. Never invent a number to fill a layout.

Two densities, chosen per request. Committee is the default.

| | committee (pre-read, consulting style) | present (spoken pitch) |
|---|---|---|
| Words per content slide | 80 to 150; above 180 the slide splits | 30 to 60; above 60 the slide splits |
| Eyebrow (small uppercase mono kicker above the headline) | on every content slide, naming the section | optional |
| Body | an exhibit (chart, table, diagram) with commentary beside it | one exhibit or one statement, large type |
| Takeaway bar (tinted box, bold label) | allowed on any content slide, 16 words or fewer, written `Label: text` | optional, rarely needed |
| Type | prose sets at the body role, 28px | short content steps up to larger roles |

The word count covers the headline and every slot. The eyebrow and the footer do not count.

## Benchmark

The committee benchmark is *Transition Plan Credibility*, a 50-slide stewardship committee deck the user reviewed. What it does well, and what we copy:
- An eyebrow on every slide tells the reader where they are in the argument.
- Every headline is an action title that states the finding.
- Most slides pair one exhibit (a scored table, a scatter, a flow, a decision tree) with a short commentary panel.
- A tinted takeaway bar ends the slide with the ask.
- The close is a numbered list of decisions requested, and heavy detail moves to an appendix.

What it does badly, and what our rules prevent:
- Some slides carry about 400 words. Our cap is 180 words; above it the slide splits or moves to the appendix.
- Some titles run to three lines and run into the subtitle below. Our headline box holds two lines; a longer headline is an overflow finding.
- It uses brand teal, navy and gold for emphasis. We use ink plus the status tints only.

## Layouts

List items in the committee layouts use `::` between parts. Write each format exactly as shown. A malformed item costs the slide its structure: at fill time the slide falls back to cards, and an item that breaks later is drawn as a plain list. Either way it is reported as a data finding.

- `title`: the opening slide. Deck title, subtitle and an optional key figure.
- `section`: a divider with a section number and title. Exempt from rhythm and from the sparse check.
- `statement`: one big claim, with or without a support line. Six words or fewer set at display size.
- `cards`: three or four parallel points, each written `Short title: one line`. Variant `rows` sets the same items as full-width numbered rows; it is where a thin cards slide goes.
- `steps`: an ordered sequence of three to five steps on a connector line.
- `stat_row`: one to four key figures, each a big number over a short label.
- `split`: a claim on the left and its evidence on the right (a chart, a table or a short list). The main committee layout for exhibit plus commentary.
- `chart_focus`: one full-width chart with a one-sentence callout of 24 words or fewer.
- `compare`: two mirrored panels, before and after or us and them. Start each panel with `Label: `.
- `flow`: numbered stage columns with boxes and arrows between them. Items: `Stage title :: box 1 :: box 2`, two to five stages, one to three boxes each; a `*` before a box marks it preferred.
- `profile`: one entity's profile. `meters` items `Label :: 54%`, a `total` such as `34 / 64`, and `left` and `right` panels whose first item is the panel title (for example "What holds up" and "What breaks").
- `scatter_zone`: a scatter with a shaded target zone (`chart.zone` as x0, x1, y0, y1) and an optional diagonal, plus signed callouts. Items: `+11 :: explanation`.
- `table/heat`: a table whose score cells are tinted by status. `table.heat` maps a column to `[low, high]`: under low is tinted low, under high is mid, the rest is high. Commentary sits beside it.
- `matrix2x2`: four tinted quadrants with axis titles and a side panel. `quadrants`: exactly four items `Title :: subtitle :: text :: status` (top left, top right, bottom left, bottom right; status is high, mid, low or neutral). `x_axis`, `y_axis`, and `items` for the side panel (first item is its title).
- `tree`: a yes/no decision tree into outcome boxes, at most four questions deep and six outcomes. Items: `id :: question :: yes_id :: no_id`, or `id :: =outcome :: status` for an outcome. The first item is the root.
- `decisions`: a numbered list of decisions for the close. Items: `Decision :: one-line detail`, each decision starting with a verb.
- `table`: a data table, compact or with a takeaway line. Table text never drops below 24px.
- `quote`: a pull quote with its attribution.
- `summary`: a closing recap of up to four items.
- Kept so old plans still load, and moved by the art director: `bullets`, `big_number`, `chart_takeaway`, `two_column`, `timeline`, `matrix`, `image`.

## Content to layout

The art director reads the shape of each filled slide and tries these picks in order. A pick is skipped when it would drop a filled slot, put more items or words in a slot than it holds, or fail its item format.

| Content | Picks, in order |
|---|---|
| a table | `table/highlight` or `split/table` when there is text, else `table/compact`; `table/heat` when heat columns are set |
| a chart with 25 words of text or fewer | `chart_focus`, then `split/chart`, then `chart_takeaway` |
| a chart with more than 25 words | `split/chart`, then `chart_takeaway` |
| one number and its label | `stat_row/one`, then `big_number/one` |
| two to four numbers | `stat_row`, then `big_number` (up to three) |
| two contrasting blocks (left and right) | `compare`, then `two_column` |
| three to five ordered items (dates, quarters, years, "1.", First, Then, Next, Finally) | `steps`, then `timeline` |
| three or four parallel items, each under 12 words | `cards`, then `cards/rows`, then `summary` |
| one sentence and no data | `statement` |
| an old `bullets` slide with three or four items | `cards`, then `cards/rows`, then `summary` |

In committee decks these picks come first:
- On the last content slide, items that all start with a verb such as Agree, Approve, Adopt, Decide or Fund go to `decisions`.
- Four to six ordered stages, or a list the model already set as steps, timeline or flow, go to `flow` when the items use the stage format.
- A chart with commentary goes to `scatter_zone` (scatter charts only) and then `split/chart`.
- A table with commentary goes to `table/heat` (when heat columns are set) and then `split/table`.
- Any list is tried as a `profile`; it only fits when the items are meters.

Every change is logged as an info finding, for example "bullets/three → cards/three (legacy bullets)".

## Rhythm

The title slide and section dividers are left out of every rule below.
- Never the same layout on three slides in a row.
- At least one visual slide in every three content slides. A visual slide is a chart, numbers (stat row or big number), steps (steps or a timeline), or a structured card or row set (cards, a flow, a profile, a heat table or a diagram).
- In decks of 12 slides or more, a section divider every 5 to 7 slides. One is inserted before the seventh content slide since the last divider, unless fewer than two content slides follow.

When a pick breaks a rule, the art director takes the next pick for the same content that keeps both rules. The design retry follows the same rhythm rules.

## Focal point and whitespace

- The largest type on a slide is a number, a statement, a chart or a diagram, never a paragraph. It is at least 1.6 times the 28px body size.
- In present decks the headline does not count: the focal element sits below it. A chart, table or diagram drawn as an image is the focal element itself; a list of cards or summary rows sets its index at headline size. In committee decks the headline is the focal element, so the check is skipped.
- Fill by design. When content is short, the layout steps up to a larger fixed type role (body 28px to subhead 36px; a statement of six words or fewer to display size). Type never shrinks below its role, and no slide text goes under 24px except the footer.
- Whitespace is planned. The content spans at least 55% of the body height in present decks and 70% in committee decks. A slide that uses only its top third is a design failure.
- Content sits on its anchor. Layouts anchored to the middle may drift at most 20% of the body height from the centre.
- Blocks keep the 32px gutter between them.
- The headline holds two lines. A longer one overflows its box and is reported, never rewritten.

The measured design check runs on every rendered slide:

| Rule | Fails when |
|---|---|
| `sparse` | content spans less than 55% (present) or 70% (committee) of the body height |
| `unbalanced` | content is more than 20% of the body height off its middle anchor |
| `small_text` | any slide text is under 24px |
| `no_focal` | present decks only: with no chart, table or diagram, the largest text below the headline is under 1.6 times the body size |
| `crowded` | two blocks are closer than the 32px gutter |
| `dense` | the slide holds more than 60 (present) or 180 (committee) words |

A failing slide gets one retry. A dense slide splits its list over two slides, or moves to the appendix when there is nothing to split. Any other failure moves the slide to its next fitting layout that keeps the rhythm. The deck is then fitted and measured again, and whatever still fails stays as a warning.

## Review checklist

Look at each rendered slide and check:
- Hierarchy: the headline reads first, then one focal element (a number, a statement, a chart or a diagram), then the support.
- The headline fits in two lines and does not touch the eyebrow or the content below it.
- Whitespace looks planned: no empty lower half, no lone item in a big box, no orphan word on its own line.
- No plain bullet list. A list reads as cards, rows, steps, a flow or decisions.
- The exhibit supports the headline, and its callout or commentary says what to see in it.
- Committee slides carry an eyebrow, and a takeaway bar when there is an ask.
- Colour appears only as status tints on ratings and scores, never as decoration.
- Text is legible from the back of the room: nothing under 24px except the footer, and enough contrast in both themes.
- Edges line up with the grid, gaps between blocks are even, and no text is clipped or overlaps a chart.
- Across the deck: no layout three times in a row, and a visual slide in every three.

## Examples

These four pairs come from the transition plan assessment pitch, from its first build to the present and committee versions.

1. Three short bullets became cards.
   Before: `bullets/three` with "Each verdict cites a verbatim passage from the company's own report.", "Code checks every quote against the source document before the verdict counts." and "A verdict whose quote cannot be found is flagged for review." The list filled the top third and left the rest of the slide empty.
   After: `cards/three` with items such as "Quote: each verdict cites a verbatim passage from the company's report". When the cards still look thin, the retry sets the same items as `cards/rows`, which share the full body height.

2. A chart with a takeaway became a claim beside its evidence.
   Before: `chart_takeaway/chart_left`, a bar chart of walk and talk indicators per category with the takeaway "Strategy and tracking hold most walk indicators, 17 and 15. Target indicators are all talk, so a plan built on targets scores low on walk."
   After: `split/chart`, the same takeaway as the statement on the left and the chart filling the right. At 25 words the takeaway is one word over the `chart_focus` callout limit of 24; a takeaway of 24 words or fewer would get the full-width chart with a one-line callout instead.

3. Two big numbers became a profile.
   Before: `big_number/two`, "64 indicators" and "4 categories". The numbers were large and said nothing about how the indicators split.
   After, in the committee version: `profile` with meters "Target :: 0%", "Governance :: 22%", "Strategy :: 71%" and "Tracking :: 79%", a total of "34 / 64", a walk panel and a talk panel side by side, and a takeaway bar: "Illustration: the meters show each category's walk share, not a company score."

4. A closing recap became a decision list.
   Before: `summary` with three sentences starting "We run the assessment…", "Your analysts review…" and "We agree…".
   After, in the committee version: `decisions` with "Agree the pilot sample :: We run the assessment on a sample of your holdings and share the grids", "Calibrate with your analysts :: Review the flagged verdicts together" and "Pick the engagement gaps :: Agree which walk-score gaps to raise in your next cycle". Each item opens with a verb, so the art director keeps it as the closing decision slide.
