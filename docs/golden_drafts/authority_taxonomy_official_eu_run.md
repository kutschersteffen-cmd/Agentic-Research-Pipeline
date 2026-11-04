# Authority taxonomy agent on the official EU Taxonomy Annex I

Date: 2026-11-03. Branch `ccr-7a69f1a4-v60isp` (PR #325), commit `1fc35e1`.

## Setup

- Source: Commission Delegated Regulation (EU) 2021/2139, Annex I (climate change mitigation), official PDF
  <https://ec.europa.eu/finance/docs/level-2-measures/taxonomy-regulation-delegated-act-2021-2800-annex-1_en.pdf>.
  196 pages, 427,657 characters of extracted text. EUR-Lex itself answers automated requests with HTTP 202 and
  an empty body, so it cannot be used as a fetch source.
- Run: `extract_source` + `consolidate` on the first 400,000 characters (the fetch cap of this path), scope
  "manufacture of equipment for the production and use of hydrogen", theme "hydrogen", `value_chain=True`, no IO
  model loaded.
- Model: `gemini-4-argon`, verifier `gemini-3.8-flash` (Anthropic key had no credit).
- One run only.

## What the official activity 3.2 says

Section 3.2 "Manufacture of equipment for the production and use of hydrogen" (page 40):

- Description: "Manufacture of equipment for the production and use of hydrogen."
- NACE codes: C25, C27, C28.
- Enabling activity under Article 10(1)(i) of Regulation (EU) 2020/852.
- Substantial contribution: manufactures equipment for the production of hydrogen compliant with Section 3.10, and
  equipment for the use of hydrogen.
- DNSH: Appendices A, B, C, D, plus circular-economy measures.

It does not name electrolysers, fuel cells or hydrogen storage/compression equipment.

## Result

| Checklist item | Result | Assessment |
|---|---|---|
| theme_description | found | Correct: "manufacture of equipment for the production and use of hydrogen … NACE C25, C27, C28" |
| activities | found, 1 activity | Correct count. Name and in-scope text match 3.2 |
| sector_codes | found: NACE C25, C27, C28 (origin `source`) | Correct |
| technologies | found: production equipment, use equipment | Correct but thin, as is the source |
| boundaries | not_in_source | Missed: 3.2 limits production equipment to equipment compliant with Section 3.10 |
| definitions | not_in_source | Acceptable: 3.2 defines no terms |
| thresholds | not_in_source | Missed: the numeric criteria sit in Section 3.10, which 3.2 refers to (not checked which numbers) |
| value_chain | found | Inconsistent: every activity in the draft is `core`, so the found items were lost |

## Gaps

1. **Citation from the table of contents.** The activity's quote is
   `3.2. Manufacture of equipment for the production and use of hydrogen .......................... 40`, the
   contents line, not the activity text on page 40. It passes grounding because the words occur in the document,
   but it is not evidence. Cause (likely): BM25 chunk ranking scores the contents page highly for the item
   keywords.
2. **Cross-references are not followed.** 3.2's substantial-contribution criterion depends on Section 3.10. The
   per-item chunk ranking has no notion of "Section x.y", so boundaries and thresholds stated there are missed.
3. **Value-chain items lost.** `report["value_chain"]` says `found` but no `upstream`/`enabling` activity survives
   consolidation. Not investigated; likely dropped when attaching to activities or by grounding.
4. **Golden case is wrong.** `backend/tests/golden/authority_taxonomy/hydrogen_eu_taxonomy/` uses an excerpt
   written from memory with three activities (electrolysers, fuel cells, storage/compression) that the official
   3.2 text does not contain. Its expected answers need to come from the official text.

## Not changed

No code, test or golden file was changed (owner choice: report only).
