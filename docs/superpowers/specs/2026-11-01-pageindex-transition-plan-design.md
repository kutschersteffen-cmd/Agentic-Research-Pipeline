# PageIndex transition-plan workflow

Spec slug: `pageindex-transition-plan`.

## Why

Today's transition-plan evidence search (chunks + hybrid embeddings/BM25, top 12) hits about 60% of
gold passages at rank 12 on the SSAB / Heidelberg gold set (`backend/tests/golden/retrieval/`). The owner
wants to try the opposite idea next to it: **PageIndex**. No chunks, no vectors, no keyword index. An LLM
reads a table-of-contents tree of the report and reasons its way to the pages that answer each question,
the way an analyst flips through a report.

## Goals

1. A separate workflow that answers the 64 transition-plan indicators (`transition_plan/data/indicators.json`)
   for one PDF, with YES/NO, the pages it read, and supporting quotes.
2. Pure PageIndex: only tree building and LLM navigation. No embeddings, BM25, rerank or keyword fallback.
3. A score on the existing retrieval gold set, so it can be compared with the current pipeline.

## Non-goals

- Replacing or changing anything in the existing retrieval, extraction or transition-plan code (owner, 2026-11-01).
- UI, API endpoints, Postgres run storage, review queue. CLI and JSON files only *(my call: smallest thing that
  answers "is PageIndex better?"; a run type can follow if it wins)*.
- Other schemas or general Q&A.
- A CI job (needs a paid model key on every PR; run by hand).

## Anti-goals

- Any vector or keyword search sneaking in "to help". That would make the comparison meaningless.
- Calling the open-source `pageindex` package: our own code on `arp/llm` (owner picked approach B over C).

## Approaches considered

| | Approach | Trade-off |
|-|----------|-----------|
| A | Tree + navigation pick pages, existing extractor + `grounding.py` answers | Fair retrieval-only comparison, but answer step is shaped by today's extractor |
| **B** | **Fully standalone: navigation and answer in one LLM loop** | **Purest PageIndex; quotes not checked by `grounding.py`, comparison is end to end** |
| C | Wrap the open-source `pageindex` library | Less code, but an outside LLM client and prompts beside `arp/llm` |

**Owner picked B** (2026-11-01).

## Design

New package `backend/arp/pageindex/`, nothing outside it changes except one CLI registration line.

### 1. Page text

`arp.ingestion.local_files.parse_file_to_text_with_pages(path)` gives the text and page offsets. Page *n*
(1-based) is the text between offsets *n-1* and *n*. Reused as is.

### 2. Tree building (`tree.py`)

- Input: page texts. Output: a tree of nodes `{node_id, title, start_page, end_page, summary, children}`.
- Build: the LLM sees pages in batches of 20, each as its page number plus its first 600 characters, and
  returns the sections that start in that batch (title, start page, level 1 or 2). Consecutive batches are
  stitched: each section ends where the next one of the same or higher level starts. Then one LLM call per
  level-1 section writes a ≤60-word summary from that section's pages (first 6,000 characters).
  *(My call: page heads are where headings sit; full-text batching would cost ~10× more.)*
- Every page belongs to exactly one leaf. Pages before the first section go into a node titled `Front matter`.
- Cache: `<pdf>.pageindex.json` next to the PDF, holding `{sha256, prompt_version, tree}`. Reused when both
  match, rebuilt otherwise.

### 3. Navigate and answer (`navigate.py`)

Per indicator, a loop of at most 6 steps, each one `complete_structured` call. The model sees the question, the
guideline, the tree (titles, page ranges, summaries) and the pages opened so far. It returns one of:

- `open`: up to 3 node IDs. Their pages are added to the context.
- `answer`: `{answer: "YES"|"NO", pages: [int], quotes: [str], reasoning: str}`.

`steps` counts every LLM call for the indicator, the answer call included. Call 6 is always forced to answer, so
`steps` ≤ 6. A forced call sends a response schema that allows only `answer`. Budget: at most 12 distinct pages opened per indicator, recorded in `pages_opened`. Once the budget
is reached, the next call is forced to answer. A node that would go over the budget opens only its first pages,
up to the budget. A retry (see Failure handling) does not count as a step.
Indicators run concurrently, 8 at a time. Model: the default from `arp/llm` factory and `arp/config.py`.

### 4. CLI (`arp pageindex`, registered in `arp/cli/__init__.py`)

- `arp pageindex run --pdf <file> --out <file.json> [--indicator <identifier> ...]`
  writes `{document, sha256, model, tree_nodes, results: [{identifier, answer, pages, pages_opened, quotes, reasoning, steps}]}`
  (`pages` = cited pages; `tree_nodes` = node count) and prints
  `PageIndex: <n> indicators, <y> YES, <k> pages read, $<cost>`, where `<k>` = the sum of `len(pages_opened)` and
  `<cost>` has 2 decimals. Without `--indicator` all 64 run. The output file is written only when the tree is built.
- `arp pageindex golden --cases <cases.json> [--documents-dir <dir>] [--min-recall <0..1>]`
  runs every document in the cases file (documents fetched and hash-checked exactly as the retrieval cases mode
  does), then prints `PageIndex golden: recall <r> (<hit>/<total>), yes-rate <y>, stale <s>`.
  **Hit:** the indicator's case was answered YES *and* a cited page contains the gold span after
  `grounding.py` normalisation. Stale spans (not in the parsed text) are left out and counted. Exit 1 if
  recall < `--min-recall`. Only the indicators that have cases are run. `yes-rate` = YES answers ÷ cases run. Stale cases are still run and count in yes-rate; they are left out of recall only.
  Recall and yes-rate have 2 decimals. When there are 0 non-stale cases, recall is `0.00`. `--documents-dir`
  defaults to the cases file's `documents/` sibling.

### Failure handling

- An LLM error or invalid output on one indicator: one retry, then the result is
  `{answer: "ERROR", error: <message>}`. Other indicators carry on. The run exits 0, and the summary line adds `, <e> errors`.
- Tree building failing is fatal: exit 1 with `Could not build page tree: <message>`.

## Left to the builder

Prompt wording, the Pydantic models, the module layout inside `arp/pageindex/`, test stand-ins for the LLM.

## Acceptance

`HOLDOUT_TOKEN` status was not checked when this was written, so deterministic rows are `unit`. If the token is
set, AC-1 to AC-19, AC-21, AC-22 and AC-24 to AC-28 move to `holdout`. Otherwise the PR lists them as owed.

Common stand-in **S**: a 3-page PDF `f.pdf`. For tree calls S returns one level-1 section per page, titled
`P1`..`P3`. For every navigation call S returns `answer` YES citing page 1 with quote `q`. S costs $0.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | S | `arp pageindex run --pdf f.pdf --out o.json` | Exit 0, and `o.json` `results` has 64 entries | unit |
| AC-2 | S | same | Every result has `answer`=`YES`, `pages`=[1], `quotes`=[`q`] | unit |
| AC-3 | S | same | stdout equals `PageIndex: 64 indicators, 64 YES, 0 pages read, $0.00` | unit |
| AC-4 | S | same | `o.json` top-level keys are exactly `document, sha256, model, tree_nodes, results`; each result's keys are exactly `identifier, answer, pages, pages_opened, quotes, reasoning, steps` | unit |
| AC-5 | S | `... --indicator A_headline_1` | `results` has exactly 1 entry, with `identifier`=`A_headline_1` | unit |
| AC-6 | S, run once; then S changed to raise on any tree call | second run | Exit 0, 64 results | unit |
| AC-7 | S, after a run | read `f.pdf.pageindex.json` | Its `sha256` equals `sha256sum f.pdf` | unit |
| AC-8 | S, after a run; PDF content changed | run again | Cache `sha256` equals the new file's | unit |
| AC-25 | As AC-8, tree calls now return titles `Changed` | run again | Every tree node title is `Changed` | unit |
| AC-9 | S, after a run; cache `prompt_version` edited to `old`; tree calls now return titles `Changed` | run again | Every tree node title is `Changed` | unit |
| AC-10 | S, with the first section starting on page 2 | run | The tree has a node titled `Front matter` covering pages 1–1 | unit |
| AC-26 | Same as AC-10 | run | Leaf page ranges cover pages 1..3 with no overlap | unit |
| AC-11 | 20-page PDF; tree stand-in returns 20 one-page level-1 sections; navigation stand-in returns `open` of the next unopened node, or `answer` NO when the call is forced | `--indicator A_headline_1` | That result has `steps`=6 and `answer`=`NO` | unit |
| AC-12 | 20-page PDF; tree has a 10-page node N1 (pp 1–10) and a 5-page node N2 (pp 11–15); stand-in opens N1, then N2, then answers | `--indicator A_headline_1` | `pages_opened` = [1..10, 11, 12] | unit |
| AC-13 | S, but navigation raises `RuntimeError('x')` on every call for `A_headline_1` | run | That result has `answer`=`ERROR` and `error`=`x` | unit |
| AC-27 | Same as AC-13 | run | The other 63 results have `answer`=`YES` | unit |
| AC-14 | Same as AC-13 | run | Exit 0, stdout ends with `, 1 errors` | unit |
| AC-15 | S, but navigation raises once for `A_headline_1`, then behaves as S | `--indicator A_headline_1` | `answer`=YES, `steps`=1 | unit |
| AC-16 | S, but the first tree call raises `RuntimeError('boom')` | `run --out o.json` | Exit 1, stderr equals `Could not build page tree: boom`, `o.json` does not exist | unit |
| AC-17 | `c.json` with one case for `d.pdf` (in `dir/<company_id>/`, sha256 matches), gold span only on page 2; stand-in answers YES citing page 2 | `arp pageindex golden --cases c.json --documents-dir dir --min-recall 1` | Exit 0, stdout equals `PageIndex golden: recall 1.00 (1/1), yes-rate 1.00, stale 0` | unit |
| AC-18 | As AC-17, but citing page 3 | same | Exit 1, stdout equals `PageIndex golden: recall 0.00 (0/1), yes-rate 1.00, stale 0` | unit |
| AC-19 | As AC-17, but the gold span text is not in the parsed PDF | same with `--min-recall 0` | Exit 0, stdout equals `PageIndex golden: recall 0.00 (0/0), yes-rate 1.00, stale 1` | unit |
| AC-20 | The real gold set and the real model | `arp pageindex golden --cases backend/tests/golden/retrieval/cases.json --min-recall 0.30` | Exit 0 | golden |
| AC-21 | The repo after the change | Command 1 below | Exits 1 (no match) | unit |
| AC-22 | The repo after the change | Command 2 below | Exits 1 | unit |
| AC-28 | The repo after the change | `grep -i pageindex backend/pyproject.toml` | Exits 1 | unit |

Commands for AC-21 and AC-22:

```
# 1
grep -rniE 'embed|bm25|rerank|select_evidence|index_cache' backend/arp/pageindex
# 2
grep -rE '^(import|from) pageindex' backend/arp
```

The PR reports AC-20's measured recall next to today's recall@12 (~0.60).

AC-20's floor of 0.30 only catches a broken pipeline. It is not a claim that PageIndex wins: the number itself is the
experiment's result. *(My call; raise it once a real number exists.)*

Must not change:

| ID    | Given | When | Then | Checked by |
|-------|-------|------|------|------------|
| AC-23 | The existing retrieval gold set | `arp golden-set retrieval --cases backend/tests/golden/retrieval/cases.json` on the PR and on `main` | recall@12 on the PR ≥ the value on `main` minus 0.02 | golden |
| AC-24 | The PR diff | `git diff --name-status origin/main` | Only `A` entries under `backend/arp/pageindex/`, `backend/tests/` and `docs/`, plus `M backend/arp/cli/__init__.py` | unit |
