# Extraction test: lessons learned

What we learned from the first end-to-end extraction test in a cloud session on 2026-10-26, and what to change in the code.

## The test

| | |
|---|---|
| Universe | 10 companies (5 US with CIK, 5 EU with LEI/ISIN); 7 reached extraction |
| Schema | `sch_transition_capex` v1, 15 fields, run as `--trial` |
| Documents | US: latest 10-K and DEF 14A from SEC EDGAR. EU: ESEF annual reports from filings.xbrl.org |
| Runs | `extraction_23780d69ceb1`: Claude (Sonnet 5.5 extracts, Opus 5.5 verifies)<br>`extraction_20e59cc761bf`: Gemini (4 Argon extracts, 3.8 Flash verifies)<br>`extraction_5a1654d3aa51`: cheap Claude (Haiku 5.5 → Sonnet 5.5), 5 companies<br>`extraction_eb8668d0177c`: cheap Gemini (3.8 Flash → 3.1 Flash Lite), 5 companies |
| Cost | Claude **$11.44**, Gemini **$4.58**, cheap Claude **$0.42**, cheap Gemini **$0.28**, plus one failed run at $0 |

**Results.** Each model found 35 values; 33 (Claude) and 32 (Gemini) were grounded in the source text. Of the 37 values at least one model found, 28 agree, 5 differ, 2 were found by only one model, and in 2 cases the models put a value under different years. In 86 of the 123 company × field × year rows, neither model found anything.

**Left out.** Siemens, Heidelberg Materials and Ørsted: no usable annual report could be downloaded. Microsoft and Nucor ran but returned nothing, because of lesson 1.

---

## 1. Document ingestion (biggest source of error)

### 1.1 10-K text extraction loses ~99% of some filings

- **What happened:** `arp/ingestion/html_text.py` kept 4,812 of 439,248 characters of Nucor's 10-K, about the cover page. Microsoft's 10-K was cut the same way; both were filed through the same filing agent (accession prefix `0001193125`). Caterpillar, which files its own, parsed fine (527k characters). Both models then reported "no disclosed value" for every field. Nothing in the run flags this.
- **Solution:**
  1. After parsing, treat a suspiciously short result as a failure. For example, a 10-K under about 50k characters is held, never extracted from.
  2. Fall back to plain `lxml` `text_content()`, which gave the full 439k characters for the same file, or fix the trafilatura settings that drop the body.
  3. Add a regression test with a 10-K from this filing agent.
- **Impact:** silent data loss for many large US filers. **Fix first.**

### 1.2 Report discovery is blocked from cloud sessions

- **What happened:** `arp discover run` uses DuckDuckGo, which shows cloud IPs a bot challenge every time. The Ørsted and ArcelorMittal IR sites returned HTTP 403.
- **Solution:**
  1. For EU companies, use ESEF filings first. `EsefDocumentSource` is already enabled by default (`esef_enabled=True`) and finds the filing by **LEI**, so every universe file should carry LEIs.
  2. Run discovery from a laptop or an allow-listed host, or let people upload reports by hand.
  3. Report "search blocked" separately from "nothing found".

### 1.3 Discovery saves junk as reports

- **What happened:** blog pages were saved as sustainability reports, and two short press-release PDFs as Heidelberg's "10-K".
- **Solution:** check each file before saving it: minimum length (a 100 KB PDF isn't an annual report), a title or period that matches the expected fiscal year, and an annual-report keyword in the first pages.

### 1.4 ESEF coverage gaps

- **What happened:** Siemens and Heidelberg (Germany) aren't on filings.xbrl.org. Ørsted's latest filing is a **half-year** report (2026-06-30), and ArcelorMittal's latest is FY2024.
- **Solution:** when choosing the "latest" filing, prefer full-year periods (period length about 12 months). Expect gaps for German companies and route them to manual upload or the Bundesanzeiger.

### 1.5 Non-English reports don't ground

- **What happened:** for Schneider Electric's French ESEF report, most quotes failed the exact-match grounding check, so the values were marked not grounded.
- **Solution:** normalise typographic apostrophes (`’` vs `'`), non-breaking and thin spaces, and French number formats (`1 234,5`) before matching. Tell the extractor to quote in the source language, never translated.

---

## 2. Runtime and resources

### 2.1 The reranker is unusable on CPU

- **What happened:** with `ARP_RERANK_ENABLED=true`, one field on the Schneider report took **283 s and 8.7 GB**. The reranker tried to allocate a 3.1 GB buffer to score 40 long chunks at once, and 8 fields in parallel pushed the process past 14 GB, where it was killed. With the reranker off, the same field took 4 s and 1.1 GB.
- **Solution:** refuse `rerank_enabled` when no GPU or Cloud Run compute is set up (log a warning and fall back), or score in small batches with truncated chunks. Use it only together with `ARP_COMPUTE_MODELS_URL`.

### 2.2 Parallel fields crash on large reports (fixed)

- **What happened:** with 3 or more fields in flight, every thread split the same 1–3M-character report at once. NLTK 3.10's 5-second ReDoS timer counts wall-clock time, so threads competing for the GIL tripped it and raised `TimeoutError`.
- **Solution:** compute each document's sentence split once, with other threads waiting on a per-key lock (`arp/ingestion/chunk_spans.py`). **Fixed in PR #247** (merged). Lesson: CI fixtures are too small to catch this, so test with a real large report too.

### 2.3 Memory budget

- About 4 GB per extraction process at 8 parallel fields (`max_concurrent_llm_calls=8`). Two runs fit side by side in a 15 GB container; three don't.

---

## 3. Extraction quality

### 3.1 Unit and scale errors get through

- **What happened:** Claude reported Caterpillar's 2025 capex as `2.794` with unit **"Millions of dollars"** while quoting "$2.794 billion". The existing `numeric.caption_scale` check didn't catch it. The verifier disagreed, so it went to review.
- **Solution:** add a check that compares the extracted unit's scale (thousand, million, billion) with the scale word in the grounded quote, and fails on a mismatch.

### 3.2 Planned and actual values get mixed up

- **What happened:** Gemini filed Dow's **2026 guidance** ($2.5bn) as actual 2026 capex. Both models filed ArcelorMittal's old guidance for 2024 as "planned 2024", a year the report already covers.
- **Solution:** in the schema and the extractor prompt, *planned* means only periods after the report's balance-sheet date, and *actual* only periods up to it. A deterministic check against the document's period end enforces it.

### 3.3 Categorical fields are ambiguous

- **What happened:** for NextEra's "Capex denominator", Claude chose `cash_flow` and Gemini `other`, consistently across 3 years. The cheap Gemini run wrote "cash-flow capex" instead of the allowed value `cash_flow`, so the row matched nothing.
- **Solution:** define each allowed value precisely in the field definition, with one example of the source wording that maps to it. Map near-miss labels to the allowed values deterministically and reject anything that doesn't map.

### 3.4 Most fields find nothing, and every field ran on every company

- **What happened:** neither model found anything in 86 of 123 rows. The sector filter in `arp/planning/applicability.py` only applies when a company has an `isic_code`, and the test universe had none, so barrier-sector fields were also extracted (and paid for) at Microsoft. Many of the fields (low-carbon R&D, new coal plants) are disclosed in sustainability reports, not 10-Ks.
- **Solution:**
  1. Make `isic_code` part of the universe template, and warn when a schema has sector rules but companies have no `isic_code`.
  2. For transition fields, feed the sustainability report as well as the annual report.

### 3.5 One field yields several years

- **What happened:** one filing produces a row per fiscal year (for example NextEra capex for 2023, 2024 and 2025).
- **Solution:** any comparison, export or report must match rows by company × field × **year**. The first comparison script matched by field only and silently dropped years.

### 3.6 Cheap models drop the fiscal year

- **What happened:** the cheap runs often returned the right value with no fiscal year. Haiku found NextEra's $1,575m carbon-intensive capex but left 2023 off. This was the most common reason a cheap run missed a value the expensive runs agreed on.
- **Solution:** require a fiscal year on every value. When the model leaves it out, take it from the report's period end, or re-prompt once, and never store a period-less number for a per-year field.

---

## 4. Model choice, cost and the two-stream approach

### 4.1 Expensive pairs

- **Gemini found the same number of values for 40% of the cost** ($0.13 vs $0.33 per value found), using 2.7M vs 4.0M input tokens. Claude found 2 values Gemini missed (Schneider's planned low-carbon capex of €290m; NextEra's "no new coal plant") but made the one unit error.
- The estimate held: $8–20 estimated, $11.44 actual for Claude.

### 4.2 Cheap pairs

Same schema, same 5 companies (Caterpillar, Dow, ArcelorMittal, NextEra, Schneider):

| | Claude | Gemini | **Claude, cheap** | **Gemini, cheap** |
|---|---|---|---|---|
| Extractor → verifier | Sonnet 5.5 → Opus 5.5 | 4 Argon → 3.8 Flash | Haiku 5.5 → Sonnet 5.5 | 3.8 Flash → 3.1 Flash Lite |
| Run cost | $11.44* | $4.58* | **$0.42** | **$0.28** |
| Values found | 35 | 35 | 31 | 29 |
| Grounded in source | 33 | 32 | 28 | 26 |
| Match the 28 values both expensive runs agreed on (value and year) | reference | reference | 21 / 28 | 21 / 28 |

\*The expensive runs also covered Microsoft and Nucor, whose truncated 10-Ks used few tokens, so most of their cost is these 5 companies.

- **The verifier reads far less than the extractor**, so the extractor's price sets the bill. Swapping the extractor for a cheap model cuts cost by about 97%.
- **What the cheap models got wrong:** mostly bookkeeping. Years were left off (3.6) and labels didn't match the allowed values (3.3). Each made one real error, and both were caught:
  - Haiku: Caterpillar 2025 capex as "2,821 USD **billion**" (should be million). Flagged as not grounded; the verifier disagreed and a check failed → review.
  - Gemini Flash: Dow's 2025 actual ($2,479m) filed under 2026. The verifier disagreed and a check failed → review.
- In both cheap runs the error was caught by a verifier **from the same provider** (Sonnet over Haiku, Flash Lite over Flash). Mixing providers isn't needed to catch extractor slips.

### 4.3 Recommended approach: two separate streams

Run Claude and Gemini as **two independent pipelines that never mix**. Claude models only check Claude output and Gemini models only check Gemini output, so each stream's result stays attributable to one provider.

| Step | Claude stream | Gemini stream |
|---|---|---|
| 1. Cheap pass on every company | Haiku 5.5 → Sonnet 5.5 (≈ $0.08 per company) | 3.8 Flash → 3.1 Flash Lite (≈ $0.06 per company) |
| 2. Escalate flagged rows only (not grounded, verifier disagrees, a check failed, or no year) | Sonnet 5.5 → Opus 5.5 | 4 Argon → 3.8 Flash |
| 3. Compare the finished streams | Both grounded with the same value and year: **accept**. Different, or only one found: **review queue**, with both answers attached. | ← same rule |

- **Estimate:** about **$0.90 per company** for both streams, instead of about **$2.90** for both expensive pairs, if a quarter of rows escalate in each stream. Measure the real escalation rate on the next run before relying on it.
- **The comparison in step 3 only reads finished results.** No model sees the other stream's output.
- **Configuration today:** each stream is set with `ARP_LLM_MODEL` / `ARP_LLM_VERIFIER_MODEL`, as in these runs. The built-in `cheap` run mode in `arp/extraction/steps.py` mixes providers (Gemini extracts, Claude verifies), so it doesn't fit this approach.
- **Missing in code:**
  1. One run mode per provider (for example `cheap_claude`, `cheap_gemini`).
  2. A command that re-runs only a run's flagged rows with the stronger pair (step 2).
  3. A cross-stream comparison that writes accept/review decisions (step 3). Today it's the script `data/test/four_way.py`, outside the repo.

### 4.4 Cost levers

- `--batch` (Message Batches API): half price, slower.
- `ARP_EXTRACTION_GROUP_SIZE` extracts several fields per call over shared evidence; 4M tokens for 105 cells is mostly repeated evidence.

---

## 5. Process

| Lesson | What to do |
|---|---|
| Preset schemas ship with unreleased fields, and normal runs refuse them (`UnreleasedFieldError`) | Use `--trial` for tests. An approver releases the fields before production runs. |
| The cloud container is temporary. Postgres and the run results disappeared on restart. | Export results (Excel, JSON) right after a run, or use a persistent database. |
| An outdated branch failed hidden acceptance tests that `main` had since changed (Holdout `theme-dossier-design AC-2/AC-28`) | Merge `main` into the branch before CI and holdout runs. |
| SEC returned one HTTP 429 (too many requests) | Set `ARP_EDGAR_USER_AGENT` to a real contact address before large runs. |
| API keys | Store `ARP_ANTHROPIC_API_KEY` and `ARP_GEMINI_API_KEY` as cloud environment secrets, never in chat. Add `ARP_ANTHROPIC_API_KEY` as a GitHub secret for the golden-set CI check. |

---

## Recommended fix order

| # | Fix | Lessons | Size |
|---|---|---|---|
| 1 | 10-K text extraction: full-text fallback, regression test (**PR #250**) | 1.1 | ~2 h |
| 2 | Universe template with required `lei`, `isin`, `isic_code`, plus a warning for missing ISIC | 1.2, 3.4 | ~30 min |
| 3 | Required fiscal year, label mapping, unit-vs-quote scale check, planned/actual period rule | 3.1, 3.2, 3.3, 3.6 | ~1 day |
| 4 | Two-stream support: per-provider run modes, "escalate flagged rows" command, cross-stream comparison | 4.3 | ~1–2 days |
| 5 | Reranker CPU guard | 2.1 | ~30 min |
| 6 | Discovery quality check and full-year preference for ESEF | 1.3, 1.4 | ~½ day |
| 7 | Grounding normalisation for non-English text | 1.5 | ~½ day |

## Universe file for the next run

```csv
company_id,name,ticker,website,cik,lei,isin,country,sector,isic_code,fiscal_year_end
NUE,Nucor,NUE,https://www.nucor.com,73309,549300GGJCRSI2TIEJ46,US6703461052,US,Materials,2410,12-31
```

## Reference

- Comparison page: https://claude.ai/artifact/BFBf7em7oa3NahSgqAxTdm
- Exports (shared separately, not in the repo): `capex_claude_vs_gemini.pptx`, `capex_claude_vs_gemini.xlsx`
- Fix for 2.2: PR #247 (merged). Fix for 1.1: PR #250.
