# Watch-check golden set: drafted labels for the owner's check

This set measures how well a real model does the two stewardship tasks: `check` (does one document show
that a watch item was met, was not met, or say nothing about it) and `find` (which commitments did the
company make in a call or meeting note). The builder drafted every label on 2026-11-14.
**The owner has not checked the labels yet.**

Run it with:

```
arp stewardship watch-golden --kind check --cases tests/golden/watch_check/cases.json \
  --documents-dir tests/golden/watch_check/documents --min-precision 0.9 --min-coverage 0.6
arp stewardship watch-golden --kind find --cases tests/golden/watch_check/cases.json \
  --documents-dir tests/golden/watch_check/documents --min-precision 0.8 --min-coverage 0.7
```

## How it was built

- **check (25 cases: 9 found, 8 against, 8 silent; 11 objectives, 9 commitments, 5 topics).** Each
  document in `documents/` is a verbatim excerpt of a real SEC filing (10-K, 20-F, DEF 14A), 6-11k
  characters. The first line gives the filing URL. Only whitespace and line breaks were changed. In the
  BP, HSBC and Unilever 20-F excerpts, lines wrapped by the two-column layout were joined. The items are
  written as an analyst would have phrased them before the filing came out. Every `evidence` sentence
  appears verbatim in its document, ignoring whitespace. `silent` items are on topics the excerpt does
  not cover, and a keyword search of the excerpt confirmed that.
- **find (11 notes, 14 commitments).** The notes are invented and use fictional companies. Each note has
  0 to 3 explicit commitments plus distractors: past achievements, vague intentions ("would reflect on
  it", "open to the idea"), and investor requests the company turned down. find-03 and find-08 contain
  no commitment. Each key phrase occurs once in its note, inside the commitment sentence.

## Look at these first (judgement calls)

- **check-01 / check-04 (Netflix).** One topic seen from two filings: the failed 2023 say-on-pay vote
  (28.7%, against) and the 2024 vote (82.2%, found).
- **check-03 (Netflix 2024, silent).** The excerpt names "climate" as an engagement topic but says
  nothing about a Scope 3 target.
- **check-06 (Chipotle, found).** The 10-K restates an earlier announcement ("We previously announced
  ... validated by the Science Based Targets Initiative") inside a risk factor.
- **check-09 (bp, against).** The 2030 deadline has not passed, but the aim was cut from 15-20% to
  8-10%, which contradicts the item.
- **check-11 (bp, found).** "Scope 2a": the "a" is a footnote marker joined to the word during extraction.
- **check-12 (HSBC, against).** The net zero date for operations and supply chain moved from 2030 to 2050.
- **check-17 (Coca-Cola, silent).** In reality Coca-Cola dropped its 25% reusable packaging goal in
  December 2024. This excerpt does not say so: it mentions reusable packaging and possible goal
  revisions only in general, hypothetical terms. So the label is silent, based on the document alone.
- **check-19 (Unilever, found).** The evidence is the accreditation as a living wage employer, not a
  statement that every employee was checked.
- **check-21 (Shell, found).** The flaring target was met with effect from 1 January 2025, after the
  SPDC sale (footnote [A] in the excerpt).
- **check-23 (Target, against).** The 10-K says Target "modified and concluded certain" DEI
  initiatives. It does not say which, so "against" depends on reading "certain" as enough.
- **find-07 / find-09.** These notes include company refusals ("will not report it", "no plans to
  propose it"). They are not labelled as commitments.
- **find-11.** "the board will not pay a dividend for the 2025 financial year" is labelled as a
  commitment, because the investor asked for it.
