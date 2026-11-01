# Extraction cost and quality roadmap

Spec slug: `extraction-cost-quality-roadmap`.
Date: 2026-11-01
Status: approved by the owner, 2026-11-01
Source: the 30–31 October model tests on RWE, Siemens and BASF (transition plan and green capex), the answer-check
sheet (https://claude.ai/artifact/NWaSvVmWwoXBJ3afzWputo), the merged quick wins (PR #279) and the paused
table-aware branch (`table-aware-extraction`).

## Why

Measured on three real reports:

| Setup | Cost per company | Transition plan correct | Green capex correct |
|---|---|---|---|
| Sonnet extracts, Opus checks (today's default) | $7.09 | 58/64 (RWE only) | 22/41 answered |
| Haiku extracts, Sonnet checks | ~$2.10 | 169/192 | 17/45 |
| Haiku + Sonnet, check only doubtful answers | ~$1.25 | 168/192 | 15/45 |
| Gemini Flash-Lite + 3.8 Flash | ~$1.10–1.70 | 141/192 | 18/45 |

"Correct" is against Claude-proposed answers the owner has not yet approved. Two conclusions: yes/no questions can
run ~5× cheaper at almost the same quality; numbers from tables are wrong in every setup and need a different fix
than a bigger model.

## Scope: what is already covered elsewhere

Not repeated here; this roadmap only links to them:

- Retrieval gold set and question-based queries (`2026-10-31-retrieval-gold-set-and-question-queries-design.md`, merged).
- Section chunks, context headers and the document tree (`2026-10-31-section-chunks-context-headers-document-tree-design.md`).
- PageIndex transition-plan workflow (`2026-11-01-pageindex-transition-plan-design.md`).
- Table-aware extraction (`2026-10-31-table-aware-extraction-design.md`): **paused** after a Gemini measurement
  (capex 18→16/45, transition plan 141→115/192). Its metadata and whole-table evidence may come back on top of the
  document tree above; its hard-filter routing does not.

## Workstreams

Each item below ships as its own small PR with its own acceptance rows from this spec. Order is the recommended
build order; an item never waits on a later one.

### A. Measurement first

**A1. Approved answer set.** The owner approves (or corrects) the 237 cards in the answer-check sheet. A script
exports approved cards to `backend/tests/golden/answer_check/approved.json`, keeping only cards with status
`checked`, each with `approved_by` and `approved_at`. `scripts/answer_check_score.py` (already on the paused
branch at `3d263b6`, with `--min-correct` and `--max-not-found`) moves to `main` unchanged.

**A2. Answer-set CI gate.** A CI job runs Haiku + Sonnet on the three committed reports for the green capex and
transition-plan schemas and scores them with `answer_check_score.py`. It runs on PRs that touch `arp/extraction`,
`arp/llm`, `arp/grounding.py` or `arp/presets`, needs the `ARP_ANTHROPIC_API_KEY` secret, and fails below the
thresholds recorded in `backend/tests/golden/answer_check/thresholds.json` (initially the Haiku + Sonnet score on the approved set, per schema, as `correct` counts).
The three PDFs (≈27 MB) are committed under `backend/tests/golden/answer_check/documents/` with Git LFS.

**A3. "Not found" diagnosis.** For every field whose answer is not found, the walkthrough trace records
`not_found_reason`: `no_passage` (retrieval returned nothing), `passages_silent` (passages returned, model found
nothing), or `held` (documents held). The run results page shows the count per reason; a reason with count 0 is not shown.

### B. Cost

**B1. Skip rule.** A field setting `verify_policy: "on_doubt"` (default `"always"`, so nothing changes unless set)
skips the second model when every quote grounds, the answer has at least one quote, and extractor confidence is
≥ 0.75 (`settings.verify_skip_min_confidence`). A skipped check is recorded in the trace as
`verifier: {"skipped": "grounded_confident"}` and the row can never auto-accept: it carries review reason
`verification_skipped` until a person or a later check confirms it.

**B2. Model choice per schema.** `DataPointSchema` gains `run_mode: "cheap" | "normal" | "max" | None`, applied when
a run does not name models. The transition-plan preset sets `cheap` with extractor `claude-haiku-5-5`, verifier
`claude-sonnet-5-5` and `verify_policy: "on_doubt"`; the green, EU taxonomy and transition-capex presets keep
`normal` (Sonnet + Opus). `arp/extraction/steps.py` `MODES["cheap"]` changes to those models.

**B3. Batch by default for large runs.** A run over more than `settings.batch_threshold_companies` (default 200)
companies uses the Message Batches API unless the user turns it off. The cost estimate shown before start is the
non-batch estimate × 0.5.

**B4. Prices.** `cost_tracker._PRICE_PER_MILLION_TOKENS` gains `claude-haiku-5-5` ($0.10 / $0.50) and
`gemini-3.5-flash-lite` (price from Google's pricing page at build time); an unknown model is logged once per run.

### C. Quality

**C1. Number cross-checks.** New check-config entries on the green preset (each a warn check, each fires only when
both values exist for the same period and unit): `green_<m>_total ≤ <m>_total`; `green_<m>_eu_aligned ≤
green_<m>_total`; sum of the ten category amounts ≤ `green_<m>_total`; a change against the prior year with
`max(this, prior) / min(this, prior) > 10` warns, in either direction (exactly 10× passes). Uses existing `le_of` / `sum_of` machinery where it fits.

**C2. Entity check noise.** `consistency.entity` reports `ambiguous` today when a report's cover page names no legal
entity. When the document was filed by the user under that company (local upload or import folder), an ambiguous
match is treated as confirmed and the check passes; LEI or name mismatches still fail.

**C3. More documents per company.** The universe can list several documents per company per year. For the three
test companies, Siemens' full annual report and RWE's and BASF's supplementary sustainability data are added to the
committed test set, and the answer set is re-scored.

**C4. Table reading, later.** Revisit after the document tree spec ships: table metadata and whole-table evidence
from the paused branch, with routing only as a ranking boost. Not built under this spec.

### D. Infrastructure

**D1. CI secrets.** Add `ARP_ANTHROPIC_API_KEY` (golden set, A2) and `HOLDOUT_TOKEN` repository secrets; document
both in `docs/` with who owns rotation. Owner action.

**D2. Holdout job runner.** Find why the Holdout acceptance job never gets a runner (stuck "in progress" with no log,
twice on PR #279) and fix the workflow or its runner label.

**D3. Session environment.** Replace the invalid `ARP_ANTHROPIC_API_KEY` in the cloud environment. Owner action.

## Non-goals

- Retrieval changes covered by the three linked specs.
- Changing grounding, review routing rules or the reviewer UI beyond A3's count.
- Building C4 now.

## Anti-goals

- A cheaper setup ships without being scored against the approved answer set (B1/B2 depend on A1).
- A skipped verification can ever auto-accept a value.
- Any default changes cost or behaviour for a schema that does not opt in (B1 default `always`, B2 only on presets
  named here).

## Acceptance

Rows marked `unit` become `holdout` once `HOLDOUT_TOKEN` works. Rows needing the owner say so.

| ID | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-A1 | The sheet with N cards marked checked | the export script runs | `approved.json` holds exactly those N cards | unit |
| AC-A1c | Same | the export script runs | every card in `approved.json` has non-empty `approved_by` and `approved_at` | unit |
| AC-A1b | The owner's review | owner action | at least the 45 green-capex cards are checked | owner |
| AC-A1d | `main` after A1 | read | `backend/scripts/answer_check_score.py` is byte-identical to the copy on branch `table-aware-extraction` at commit `3d263b6` | unit |
| AC-A2 | `.github/workflows/answer-set.yml` | its path filter is read | it lists exactly `backend/arp/extraction/**`, `backend/arp/llm/**`, `backend/arp/grounding.py`, `backend/arp/presets/**` | unit |
| AC-A2b | A PR changing `backend/arp/extraction` | the job "Answer set (real model)" runs | its log prints `correct <c>/<n>` once for `green-capex` and once for `transition-plan` | evaluator |
| AC-A2c | The scorer with `--min-correct` set from `thresholds.json[schema]` and c below it | runs | exits non-zero | unit |
| AC-A2f | The scorer with `--max-not-found M` and a not-found count above M | runs | exits non-zero | unit |
| AC-A2d | The three committed report PDFs | `git lfs ls-files` | lists all three under `backend/tests/golden/answer_check/documents/` | unit |
| AC-A2e | `thresholds.json` at A2 merge | read | each schema's value equals the Haiku + Sonnet `correct` count on the approved set recorded in the PR | evaluator |
| AC-A3 | A field whose evidence selection returns no passage | the field graph runs with a trace sink | its trace entry has `not_found_reason == "no_passage"` | unit |
| AC-A3b | A field with passages whose extractor returns no value | same | `not_found_reason == "passages_silent"` | unit |
| AC-A3d | A field of a company whose documents are all held | same | `not_found_reason == "held"` | unit |
| AC-A3c | A run with 3 no_passage, 2 passages_silent and 0 held rows | the results page loads | it shows "Not found: 3 no passage · 2 passages silent" and no "held" entry | evaluator |
| AC-B1 | A field with `verify_policy: "on_doubt"`, one grounded quote, confidence 0.80; a stand-in | extracted | the verifier stand-in receives 0 calls | unit |
| AC-B1h | Same | extracted with a trace sink | the trace entry's `verifier == {"skipped": "grounded_confident"}` | unit |
| AC-B1f | Same, confidence exactly 0.75 | extracted | the verifier receives 0 calls | unit |
| AC-B1b | Same, confidence 0.70 | extracted | the verifier receives 1 call | unit |
| AC-B1c | Same as AC-B1, the quote not grounded | extracted | the verifier receives 1 call | unit |
| AC-B1g | Same as AC-B1, an answer with a value and zero quotes | extracted | the verifier receives 1 call | unit |
| AC-B1d | Same as AC-B1, confidence 0.99, released field, first audit passed | routed | route is `review` | unit |
| AC-B1i | Same | routed | `review_reasons` contains `verification_skipped` | unit |
| AC-B1e | A field without `verify_policy` | extracted | the verifier receives 1 call | unit |
| AC-B2 | The transition-plan preset | built | `run_mode == "cheap"` | unit |
| AC-B2f | Same | built | every field has `verify_policy == "on_doubt"` | unit |
| AC-B2g | The green, EU taxonomy and transition-capex presets | built | each has `run_mode == "normal"` and no field sets `verify_policy` | unit |
| AC-B2b | `MODES["cheap"]` | read | `llm_model == "claude-haiku-5-5"` and `llm_verifier_model == "claude-sonnet-5-5"` | unit |
| AC-B2c | A transition-plan run request with no `llm_model`, `llm_verifier_model` or `run_mode` | started | the run manifest records extractor `claude-haiku-5-5` | unit |
| AC-B2h | Same | started | the manifest records verifier `claude-sonnet-5-5` | unit |
| AC-B2d | A green-capex run request with no `llm_model`, `llm_verifier_model` or `run_mode` | started | the manifest records `claude-sonnet-5-5` / `claude-opus-5-5` | unit |
| AC-B2e | The approved set; a fresh cheap-setup transition-plan run; `thresholds.json["sonnet_opus_transition_plan"]` recorded in the B2 PR | `answer_check_score.py --schema transition-plan --min-correct <that value − 3>` | exits 0 | golden |
| AC-B3 | A run over 201 companies, batch not turned off | started | `params.batch == true` | unit |
| AC-B3b | A run over exactly 200 companies | started | `params.batch == false` | unit |
| AC-B3c | A run over 201 companies with batch turned off | started | `params.batch == false` | unit |
| AC-B3d | A run over 201 companies, batch on | the cost estimate is shown | it equals the non-batch estimate × 0.5 | unit |
| AC-B4 | 1M input and 1M output tokens on `claude-haiku-5-5` | `estimate_cost_usd` | returns 0.60 | unit |
| AC-B4c | The price table | read | it has an entry for `gemini-3.5-flash-lite` with non-zero prices | unit |
| AC-B4b | A model missing from the price table | two calls in one run | exactly one warning is logged | unit |
| AC-B4d | Same, a second run | one call | one more warning is logged | unit |
| AC-C1 | Green capex rows: total 1000, green total 1200, same period and unit | checks run on green total | a warn check fails with detail `green_capex_total 1200 exceeds capex_total 1000` | unit |
| AC-C1f | Green total 800, total 1000 | checks run on green total | that check passes | unit |
| AC-C1b | EU-aligned 300, green total 250 | checks run on EU-aligned | a warn check fails | unit |
| AC-C1c | Ten category amounts summing to 900, green total 800 | checks run on green total | a warn check fails | unit |
| AC-C1d | An amount 4.0 this year, 4000 last year, same unit | checks run | a warn check fails on the change | unit |
| AC-C1g | An amount 400 this year, 40 last year | checks run | the change check passes (exactly 10×) | unit |
| AC-C1h | An amount 401 this year, 40 last year | checks run | the change check fails (rise above 10×) | unit |
| AC-C1e | Green total present, total missing | checks run on green total | the total check is `not_applicable` | unit |
| AC-C1i | EU-aligned present, green total in another unit | checks run on EU-aligned | that check is `not_applicable` | unit |
| AC-C1j | Category amounts present, green total missing | checks run | the category-sum check is `not_applicable` | unit |
| AC-C1k | An amount with no prior-year value | checks run | the change check is `not_applicable` | unit |
| AC-C2 | A user-uploaded document whose entity match is ambiguous | checks run | `consistency.entity` is `pass` | unit |
| AC-C2d | An import-folder document whose match is ambiguous | checks run | `consistency.entity` is `pass` | unit |
| AC-C2b | A fetched (not user-filed) document whose match is ambiguous | checks run | `consistency.entity` fails with severity warn | unit |
| AC-C2c | A user-uploaded document whose LEI names another company | checks run | `consistency.entity` fails with severity block | unit |
| AC-C2e | A user-uploaded document whose title names another legal entity | checks run | `consistency.entity` fails with severity block | unit |
| AC-C3 | A universe row listing two documents for one company | a run starts | both documents appear in the run's document list | unit |
| AC-C3c | The C3 PR | read | Siemens' annual report and RWE's and BASF's supplementary data exist under `backend/tests/golden/answer_check/documents/` | unit |
| AC-C3b | The approved set; `thresholds.json["not_found_before_c3"]` recorded in the C3 PR | `answer_check_score.py --schema transition-plan --max-not-found <that value>` on a fresh run with the added documents | exits 0 | golden |
| AC-D2 | A PR whose description says `Spec: <slug>` | the Holdout acceptance job runs | it ends (pass or fail) within 30 minutes of starting | evaluator |

Must not change: AC-B1e, AC-C2b, AC-C2c, AC-C2e.

## Left to the builder

- The export script's name and whether it reads the sheet via the artifact database API or a manual JSON export.
- Whether B3's threshold lives in settings or the run form.
- Exact detail texts for C1 (pattern: `<field> <v> exceeds <other> <w>`).
