# Tangible function visuals for the ARP deck: design

Date: 2026-11-10. Status: draft for owner approval. Scope: the published slide deck
(https://claude.ai/artifact/DR6xAeoLUSi2tFvJg5X9Rh), not product code.

## Intent and why

The deck explains Argus, the thematic universe (theme funnel) and the Emerging Themes Scanner in boxes
and arrows. Readers cannot *see* what goes in, what the machine does and what comes out. The owner wants
each function shown as a **machine line**: real documents go in, an instruction card (the schema, the
taxonomy) goes into the machine, and concrete output cards come out. The aim is advertising ARP to
analysts and clients, so the visuals have to look real and stay honest.

## Goals

1. Four new slides a first-time viewer can read in ten seconds without a speaker: extraction machine line,
   extraction close-up, theme funnel machine line, emerging themes machine line.
2. One shared layout for the three machine-line slides, so a viewer learns the picture once.
3. Every picture is traceable: a caption names the source document and page, or the run and date.

## Non-goals

- No logos of third-party firms outside the page images themselves (the earlier decision stands).
- No animation beyond the deck's built-in build-in effects.
- No change to existing slides, no new product features, no regenerated PowerPoint until the owner asks.
- No live recordings or videos.

## Anti-goals

- Invented figures, quotes or company results. Mock content that looks real is a failure even if the slide
  is pretty.
- Any wording that implies a filer endorses or partners with ARP.
- Text too small to read on a phone (nothing under 24 px).

## Constraints

- Deck format: 1920x1080 section per slide, inline styles from the closed subset, images only as
  `/_blob/<id>` uploads through the artifact's asset store, at most 200 elements per slide.
- Real report pages come from public filings (owner's choice).
- Output cards come from a recorded ARP run or from an existing deck slide; nothing is typed in by hand.
- Rights: showing pages of public filings for illustration needs the owner's check before the deck leaves
  the firm. The deck stays private until then.

## Approaches considered

1. **Native deck slides with uploaded page images** (chosen, my call). Pages are PNG crops; cards, machine,
   arrows and captions are native shapes and text, so they stay editable and the PowerPoint export keeps
   editable text. Trade-off: more layout work per slide.
2. One pre-rendered illustration per slide. Fast, but text is not editable and goes stale. Rejected.
3. Screen recordings of the running app. Most real, but cannot be exported to PowerPoint. Rejected for now.

The owner asked for "all of that": the machine line, the annotated real page and the close-up. The four
slides combine them.

## Decisions on the how

Decided by the owner: real pages from public filings; all three visual treatments.

My calls (listed so the owner can overrule them):

1. **Extraction outputs come from the real RWE run the deck already shows** (RWE Annual Report 2025,
   transition-plan schema, run of 30 Oct 2026, answers in `docs/RWE-transition-plan-answers-2025.csv`). No new
   model run. All three page images and the close-up come from that one document. *Amended 10 Nov during
   the build: Signify and the green capex schema are replaced by RWE and the transition-plan schema, because
   the repo holds no page, quote or stored values for the Signify run. Pending owner confirmation.*
2. **Theme funnel outputs come from the human-checked golden set** (electrolyser makers: Nel, Siemens Energy, Johnson Matthey; owner's choice, 10 Nov), shown as reference labels, not ARP output. **Emerging themes outputs come from ARP's demo data**, because a live model run needs an
   API key that is not in this session. The slide shows the text "demo data". For emerging themes, the IN
   snippets are the actual source items of the demo scan that produced the topic cards, so input and output
   are causally linked.
3. **Publishing:** the update goes to the existing private deck. The rights check happens before anyone
   outside the firm sees it.
4. **Machine check dots** are not decoration: a dot row under each output card reflects that card's real
   status (code check, second-model check, person review), and a dot is empty when that step did not happen.
5. **Fetching filings:** the builder tries to fetch and render the filings from this environment. If a page
   cannot be fetched, the builder reuses the page image already in the deck and tells the owner.
6. **Placement:** the extraction pair sits around the Argus feature slides, the theme funnel after the
   thematic universe slide, emerging themes after the existing emerging themes explanation.

## The shared layout (machine line)

Three columns on a 1664 px wide area with 32 px gaps: **IN** (left edge x=128, 520 px wide: a stack of two or three page images or
snippets), **MACHINE** (left edge x=680, 520 px wide: the instruction card sliding into one dark rounded shape),
**OUT** (left edge x=1232, 560 px wide: three cards). Headings "IN", "MACHINE", "OUT" in the deck's mono style; one caption
line under each column. Build-in effects reveal IN, then the instruction card, then OUT.

## What each slide shows

| Slide | IN | Instruction card | OUT |
|---|---|---|---|
| Extraction machine line | three real report pages from the documents behind the stored runs | five to seven question ids of the transition-plan schema, listed in the speaker notes | three value cards: value, unit, period, verbatim quote, page, status chip |
| Extraction close-up | the RWE page 107, quote boxed | none | one value card; two checks marked |
| Theme funnel | theme card and the ratified taxonomy card | the taxonomy (activities with an out-of-scope boundary) | exposure cards with a cited quote; three cascade tiers named |
| Emerging themes | three source items of the demo scan: EDGAR, news, regulatory RSS | clustering, lineage and novelty named | three topic cards with transition word and novelty score |

## Left to the builder

Exact crops; card wording within the limits above; exact
slide positions; which demo run feeds the two demo slides.

## Acceptance

Conventions: "character-identical" means after collapsing runs of whitespace to one space, compared with
the text layer of the cited source page (or, for demo and run data, the stored value). "Left to right" means
by the x position of an element's left edge. All slides counted are visible slides.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | The extraction machine-line slide | It is opened | The IN column holds exactly 3 page images | evaluator |
| AC-2 | The same slide | Each page image is inspected | Each has a caption `<company name> · <document title> · p.<page number>` with the middle dot as separator, and the page number is that of the page shown | evaluator |
| AC-3 | The same slide | Its speaker notes are read | They list 3 URLs, each the public filing PDF the image was cropped from, in the same top-to-bottom order as the images, each with its page number | evaluator |
| AC-4 | The same slide | The OUT column is inspected | It holds exactly 3 value cards, each showing the answer or value, the quote, the page number and the confidence; unit and period are shown wherever the answer is a number | evaluator |
| AC-5 | A value card | Its status chip is read | It reads "needs review" when the stored route of that answer is review, and "accepted" when the stored route is accepted | evaluator |
| AC-6 | A value card | Compared with its cited source page and the stored run | The quote is character-identical to the sentence on that page, and the answer or value equals the stored answer of that question | evaluator |
| AC-7 | The instruction card | Its names are compared with the schema as stored in ARP | It lists 5 to 7 names, each a question id of the transition-plan schema (`transition_plan_indicators`) as stored in ARP, and the speaker notes list the full question ids and texts they come from | evaluator |
| AC-8 | The extraction close-up slide | It is opened | One page image of the RWE report shows one visible rectangle around the text lines that hold the quote, and the quoted words are highlighted inside it (amended: in justified text a quote starts mid-line, so one rectangle cannot isolate a sentence) | evaluator |
| AC-9 | The same slide | The highlighted words are compared with the quote on the value card | They are character-identical | evaluator |
| AC-10 | The same slide | The value card is inspected | It shows a filled check mark "grounded in code" only if ARP's grounding function confirms the quote on the cited page text, and a "verified by a second model" mark only if the run recorded that check; a mark whose step is not recorded is absent | evaluator |
| AC-11 | The theme funnel slide | It is opened | Its IN column holds the theme card and the documents; the taxonomy card is the instruction card in the MACHINE column and reads "draft" or "ratified" as its stored status says (amended: the golden-set taxonomy is a draft) | evaluator |
| AC-12 | The same slide | The tier row is inspected | Three tier labels "Catalogue", "Extraction", "Debate" appear in that left-to-right order in one row, and no other tier label appears | evaluator |
| AC-13 | The same slide | The exposure cards are inspected | There are exactly 3 cards, each with one chip whose text is one of "core", "peripheral", "not" (amended: the golden set's own label words) | evaluator |
| AC-14 | An exposure card | It is read | It shows the golden set's one-line rationale for that company (amended: the golden set has rationales, not quotes) | evaluator |
| AC-15 | An exposure card | Its caption is read | It reads "golden set label, checked 2026-11-02" (amended: owner chose golden sets for the funnel, so the cards are reference labels, not ARP output) | evaluator |
| AC-16 | The emerging themes slide | It is opened | The IN column holds exactly 3 snippets, top to bottom, with a label above each reading exactly "EDGAR", "News", "Regulatory RSS" | evaluator |
| AC-17 | The same slide | The OUT column is inspected | It holds exactly 3 topic cards | evaluator |
| AC-18 | A topic card | Compared with the demo scan's stored topic | Its transition word is one of "birth", "growth", "split", "merge" and equals the stored value | evaluator |
| AC-19 | A topic card | Its score is read | It is the stored novelty score of that topic, shown with two decimals between 0.00 and 1.00 | evaluator |
| AC-20 | The emerging themes slide | It is opened | It shows the exact text "demo data"; the theme funnel slide instead shows "golden set" (amended) | evaluator |
| AC-21 | The two extraction slides | They are opened | Neither contains the text "demo data" | evaluator |
| AC-22 | Every figure and quote on the four slides | The speaker notes are read | Each is listed there with its source type (page, run id or slide id) and location, and that source holds the identical string | evaluator |
| AC-23 | Each output card on the four slides | The status and check marks under it are read | A mark is filled only for a step recorded for that card in its run or re-run now with ARP code; a step without evidence shows no mark | evaluator |
| AC-24 | Each emerging themes snippet and the close-up page image | Its caption is read | It names its source and page, or its run and date in the form `<run id> · YYYY-MM-DD` | evaluator |
| AC-25 | The three machine-line slides | Opened one after another | Headings "IN", "MACHINE", "OUT" appear left to right in the deck's mono heading style, each with exactly one caption line below its column | evaluator |
| AC-26 | The same three slides | Rendered at 1920x1080 | Column left edges are at x=128 (IN), x=680 (MACHINE) and x=1232 (OUT), each within 8 px, on all three slides | evaluator |
| AC-27 | The same three slides | The build steps are played | Exactly 3 builds occur in this order: IN column, instruction card, OUT column | evaluator |
| AC-28 | All four slides | Rendered at 1920x1080 | No text element outside the page images renders under 24 px, and no element extends past the canvas | evaluator |
| AC-29 | All four slides | Their markup is counted | Each has at most 200 elements, and every image source starts with `/_blob/` | evaluator |
| AC-30 | The two extraction slides | They are opened | Each has the exact line "Public filings, shown for illustration" in one text element | evaluator |
| AC-31 | All four slides | Their images and text are checked | The only images are the uploaded page images, and no text element contains a filer's name together with "with", "powered by" or "in partnership" | evaluator |
| AC-32 | Three first-time viewers per new slide | Each is shown the slide for 10 seconds | At least 2 of 3 name the input type and the output type correctly (documents or items in, cards out) | evaluator |
| AC-33 | The deck before and after | Slide ids are listed | It has exactly 4 more visible slides; all earlier ids are present in the same relative order | evaluator |
| AC-34 | The deck before and after | Each earlier slide is compared | Its content is unchanged | evaluator |
| AC-35 | The deck | Slide order is read | The extraction pair is adjacent to the Argus feature slides, the theme funnel slide is directly after the thematic universe slide, and the emerging themes slide is directly after the existing emerging themes explanation slide | evaluator |

Must not change: the existing slides' ids, order and content (AC-33, AC-34), and the rule that no figure or
quote is invented (AC-22).
