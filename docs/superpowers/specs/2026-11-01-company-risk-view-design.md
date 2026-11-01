# Company risk view, and where other model families fit ARP

Spec slug: `company-risk-view`.

Status: approved by the owner, 2026-11-01.

## Why

Engagement selection today ranks on a placeholder CLTI score and monitoring triggers
(`arp/stewardship/program.py`). Companies already publish their own view of their biggest risks: the EU
risk report and ESRS double materiality, the US 10-K Item 1A. Reading those for about 4,000 companies gives
selection a second, company-stated input. A hand check on Heidelberg Materials FY2024/FY2025 and Martin
Marietta FY2024/FY2025 (session 2026-11-01) showed:

- the risks can be found from document structure (EU section headings, 10-K bold headings), without a model;
- mitigations need a model, because keyword search catches negations ("unable to mitigate");
- year-on-year change is the useful signal, but string matching calls 14 of 32 reworded 10-K risks "new"
  when about 1 is. Matching has to be semantic.

Phase 1 builds that risk view. The other model families surveyed in the same session are placed on a
roadmap (phases 2–4) so later specs start from one map.

## Goals

1. For one annual report (PDF) or one 10-K (EDGAR HTML), list the risks the company names and, for each,
   the mitigation actions it states, each with a verbatim quote and page or section.
2. Given the prior year's risk view for the same company, label each risk `same`, `reworded`, `new`, or
   `dropped` by semantic matching.
3. Tag each risk with one house theme from a closed list.
4. Run headless from the CLI over a list of companies, writing one JSON file per company and year.

## Non-goals

- Ratings, likelihood, impact or scores (owner, 2026-11-01: risks and mitigations only).
- The ESRS materiality matrix image (needs a vision step, roadmap phase 2).
- Feeding the risk view into `program.simulate` ranking (a later spec once the data exists).
- UI, API endpoints, Postgres storage, review queue. CLI and JSON files only *(my call: smallest thing that
  shows whether the data is usable)*.
- Downloading reports. Input is a local file; discovery (`arp/discovery`) and EDGAR ingestion stay as they are.

## Anti-goals

- A mitigation or risk without a quote that `arp/grounding.py` finds in the source text.
- Calling a model to find risk headings when the structure already gives them.

## Design

New package `backend/arp/risk_view/`; one CLI registration line in `arp/cli/__init__.py`. Nothing else changes.

### Steps per document

| Step | How | Model |
|---|---|---|
| 1. Text | PDF: `parse_file_to_text_with_pages` (existing). 10-K: the primary HTML, bold/italic spans marked as headings | none |
| 2. Section | PDF: first page whose heading matches `Risk and opportunity report`, `Principal risks`, `Risk report`, `Risikobericht` (case-insensitive), up to the first later heading from the stop list in `risk_view/data/section_stops.json` (`Outlook`, `Forecast`, `Prognosebericht`, `Corporate governance`, `Remuneration report`, `Consolidated financial statements`). 10-K: from `Item 1A` body to `Item 1B`/`Item 1C`. Not found: status `no_section`, exit 0, no model call | none |
| 3. Risks | One risk per heading inside the section, longer than 40 characters, with the text up to the next heading as its body. Category sub-headings (10-K "Industry Risk Factors") are carried as `category` | none |
| 4. Mitigations | One LLM call per risk body through `arp/llm` (model from `ARP_LLM_MODEL`, Batch API when the CLI runs over a list): "list the actions the company says it takes to reduce this risk, each as an exact quote; empty list if none" | LLM |
| 5. Grounding | Each quote checked with `grounding.is_grounded` against the risk body; ungrounded quotes are dropped and counted in `dropped_quotes` | none |
| 6. Theme | Zero-shot NLI (`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`) over the risk heading against the house themes in `risk_view/data/themes.json`; highest label, or `other` below 0.5 | encoder |
| 7. Year-on-year | If `--prior` is given: embed both years' headings with `retrieval.embeddings.embed_texts`. Pairs are matched one-to-one, greedily by highest cosine similarity. Similarity ≥ 0.85 → `same`; ≥ 0.60 and < 0.85 → `reworded`; < 0.60 or no prior left → `new`. Each prior risk left unmatched is appended once with `"change": "dropped"` | embeddings |

Thresholds in step 7 are starting values, set in `risk_view/data/thresholds.json`. Without `--prior`, `change` is `null`.

A risk's heading is its own quote: every heading must be found in the source text by `grounding.is_grounded`,
otherwise it is not emitted. Locator: PDFs give `"page": <n>` (1-based); 10-Ks give `"section": "Item 1A"` and
no `page` key. Themes are the keys of `risk_view/data/themes.json` plus `other`; the highest NLI score wins if
≥ 0.5. New dependencies allowed: `transformers` (for step 6) in `backend/pyproject.toml`.

### Output

`<out>/<company_id>/<fiscal_year>.json`:

```json
{"company_id": "...", "fiscal_year": 2025, "source": "hm25.pdf", "status": "ok",
 "risks": [{"id": "r1", "heading": "...", "category": "...", "theme": "climate_transition",
            "page": 76, "change": "same", "prior_id": "r1",
            "mitigations": [{"quote": "...", "page": 76}]}],
 "dropped_quotes": 0}
```

### CLI

`arp risk-view run --input <file> --company <id> --year <yyyy> --out <dir> [--prior <json>]`
`arp risk-view batch --manifest <csv> --out <dir>` (columns `company_id,year,path`; a row whose `path` is
missing is skipped, its path printed to stderr, and the command exits 1 after processing the other rows).
`arp risk-view golden [--cases <dir>] [--min-recall 0.90] [--min-precision 0.90] [--min-yoy 0.90]`: runs the
golden set with the real model, prints per-document scores, exits 1 if any document is below any threshold.

### Golden set

`backend/tests/golden/risk_view/`: Heidelberg Materials FY2024 + FY2025 (PDF) and Martin Marietta FY2024 +
FY2025 (10-K HTML), with hand-labelled risk headings, mitigations and year-on-year labels.

## Roadmap (later specs, one per row)

| Phase | Model family | ARP function | What it adds |
|---|---|---|---|
| 2 | ColPali / vision LLM | Risk view, extraction (#3) | Read ESRS matrices, risk heat maps and KPI tables from page images |
| 2 | Upgraded embeddings (`bge-m3`) | Retrieval, Emerging Themes (#12), Universe (#1) | Better matching everywhere embeddings are used today |
| 3 | BERTopic | Emerging Themes (#12) | Labelled clusters with change over time |
| 3 | Whisper | Engagement, research | Earnings-call and AGM transcripts as evidence |
| 3 | ClimateBERT, FinBERT-FLS | Transition Plan (#8) | Pre-sort passages into talk vs walk before the LLM verdict |
| 3 | ESG topic + NLI on news | Stewardship triggers | Live controversy signals in place of the static list |
| 4 | LightGBM + conformal prediction | Stewardship ranking, review queue | Engagement-success estimate; send only uncertain values to review |
| 4 | Climate TRACE / asset data | Transition Plan, risk view | Independent check of stated emissions ("say vs do") |
| 4 | Small open LLM on Cloud Run L4 | Any LLM step | In-house option where documents may not leave |

Heavy encoders run on the existing Cloud Run L4 compute (`scripts/gcp/setup_compute.sh`) when phase 2+ needs them.

## Left to the builder

Prompt wording for step 4; how the heading detector handles headings split across lines.

## Acceptance

All `unit` rows replace the LLM, `embed_texts` and the NLI model with stand-ins.

| ID    | Given | When | Then (observable, exact) | Checked by |
|-------|-------|------|--------------------------|------------|
| AC-1  | A PDF fixture with no heading matching the step-2 list | `arp risk-view run` | Exit code 0 | unit |
| AC-2  | Same input as AC-1, a counting LLM stand-in | `arp risk-view run` | The stand-in receives 0 calls | unit |
| AC-3  | The Martin Marietta FY2025 10-K HTML fixture, LLM stand-in returning `[]` | `arp risk-view run` | Output has 32 risks; the first `heading` starts with `Our business depends on construction activity` | unit |
| AC-4  | Same input as AC-3, a counting LLM stand-in | `arp risk-view run` | The stand-in receives exactly 32 calls | unit |
| AC-5  | Same input as AC-3 | `arp risk-view run` | The first risk has `"section": "Item 1A"` and no `page` key | unit |
| AC-6  | A PDF fixture whose section heading is on page 2 and whose only risk heading is on page 3 | `arp risk-view run` | That risk has `"page": 3` | unit |
| AC-7  | A PDF fixture with one heading and body B; LLM stand-in returns quote Q1 (in B) and Q2 (not in B) | `arp risk-view run` | The risk's `mitigations` has exactly 1 entry, with `quote` = Q1 | unit |
| AC-8  | Same input as AC-7 | `arp risk-view run` | Output has `"dropped_quotes": 1` | unit |
| AC-9  | An input document with risks r1..r5 (in document order), a prior JSON, and an `embed_texts` stand-in giving r1..r5 best one-to-one similarities 0.95, 0.85, 0.70, 0.60, 0.40, with one prior risk left unmatched | `arp risk-view run --prior <json>` | The `change` values of r1..r5, in document order, are `same`, `same`, `reworded`, `reworded`, `new` | unit |
| AC-10 | Same input as AC-9 | `arp risk-view run --prior <json>` | Exactly one extra risk with `"change": "dropped"`, whose `heading` equals the unmatched prior heading | unit |
| AC-11 | Two current risks whose best prior match is the same prior risk P (similarities 0.95 and 0.90), no other prior risks | `arp risk-view run --prior <json>` | The 0.95 risk has `prior_id` = P's id and `change` `same`; the 0.90 risk has `change` `new` | unit |
| AC-12 | One risk; NLI stand-in scores `climate_transition` 0.8, every other theme ≤ 0.3 | `arp risk-view run` | That risk has `"theme": "climate_transition"` | unit |
| AC-13 | One risk; NLI stand-in scores every theme below 0.5 | `arp risk-view run` | That risk has `"theme": "other"` | unit |
| AC-14 | A manifest with rows `A,2024,<ok pdf>`, `B,2025,<ok pdf>`, `C,2025,<missing path>` | `arp risk-view batch` | Files `<out>/A/2024.json` and `<out>/B/2025.json` exist; no `<out>/C/` directory exists | unit |
| AC-15 | Same input as AC-14 | `arp risk-view batch` | stderr contains `<missing path>`; exit code 1 | unit |
| AC-16 | Golden set (4 documents), real model | `arp risk-view golden` | Printed risk-heading recall ≥ 0.90 for each of the four documents separately | golden |
| AC-17 | Golden set, real model | `arp risk-view golden` | Mitigation quote precision ≥ 0.90 on each document separately (a kept quote counts as correct when the hand labels mark it a mitigation for that risk) | golden |
| AC-18 | Golden set, real model, hand-labelled year-on-year pairs | `arp risk-view golden` | Year-on-year label accuracy ≥ 0.90 on each pair separately (Heidelberg Materials FY2024→FY2025, Martin Marietta FY2024→FY2025) | golden |
| AC-19 | Golden set, real model | `arp risk-view golden` | 100% of emitted risk headings pass `grounding.is_grounded` against their source text | golden |
| AC-20 | The existing backend test suite on `main` (which already replaces the LLM with its stand-ins) | `python3 -m pytest backend/tests` on this branch, excluding `backend/tests/risk_view/` | Same pass/fail result per test as on `main`; no existing test file is modified | unit |
| AC-21 | The PR diff | `git diff --name-only origin/main` | Every path is under `backend/arp/risk_view/`, `backend/tests/`, `docs/`, or is `backend/arp/cli/__init__.py` or `backend/pyproject.toml` | unit |
| AC-22 | Same input as AC-1 | `arp risk-view run` | Output JSON has `"status": "no_section"` and `"risks": []` | unit |
| AC-23 | Golden runner with a stand-in scorer: one document below one threshold | `arp risk-view golden` | Exit code 1 | unit |
| AC-24 | Golden runner with a stand-in scorer: every document meets every threshold | `arp risk-view golden` | Exit code 0 | unit |
| AC-25 | A PDF fixture whose extracted text yields heading H, and `grounding.is_grounded` stubbed to return false for H | `arp risk-view run` | Output has no risk with `heading` = H | unit |
| AC-26 | A 10-K fixture with a 30-character heading inside Item 1A | `arp risk-view run` | No risk has that heading | unit |
| AC-27 | A 10-K fixture with category heading `Industry Risk Factors` followed by one risk heading | `arp risk-view run` | No risk has heading `Industry Risk Factors`; the following risk has `"category": "Industry Risk Factors"` | unit |

| AC-28 | A PDF fixture whose only mitigation quote is on page 4 | `arp risk-view run` (LLM stand-in returns that quote) | That mitigation has `"page": 4` | unit |
| AC-29 | The AC-3 input, LLM stand-in returning one grounded quote per risk | `arp risk-view run` | Every mitigation has `"section": "Item 1A"` and no `page` key | unit |
| AC-30 | Same input as AC-9 | `arp risk-view run --prior <json>` | r5 (the `new` risk) has `"prior_id": null` | unit |
| AC-31 | Same input as AC-9 | `arp risk-view run --prior <json>` | The `dropped` entry has `prior_id` equal to the unmatched prior risk's `id` and `"mitigations": []` | unit |
| AC-32 | A PDF fixture with the risk section on pages 2–3 and the heading `Outlook` (in the stop list) on page 4 | `arp risk-view run` | No risk has `page` ≥ 4 | unit |
| AC-33 | The AC-3 input without `--prior` | `arp risk-view run` | Every risk has `"change": null` | unit |

Must not change: existing extraction, retrieval, transition-plan and stewardship behaviour (AC-20, AC-21).
