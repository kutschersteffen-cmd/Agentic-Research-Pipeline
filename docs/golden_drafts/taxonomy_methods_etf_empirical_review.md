# Taxonomy methods review: `etf_index_holdings` and `empirical`

Date: 2026-11-03. Base: `main` at `23e0493`. One run per method, no code changed.

Theme for both runs: "Hydrogen electrolysers" / "Companies that manufacture and sell electrolysers or electrolyser
stacks for producing hydrogen from water". Reference points: the golden set
`backend/tests/golden/exposure/electrolyser_makers/cases.json` (66 companies, labels core / peripheral / not, four
roles `make_electrolysers`, `supply_components`, `produce_hydrogen`, `fuel_cells`) and the authority agent's run on
EU Taxonomy Annex I (`authority_taxonomy_official_eu_run.md` on PR #325).

Model: `claude-sonnet-5-5` (Anthropic key worked).

## 1. `etf_index_holdings` on Global X Hydrogen ETF (HYDR)

Input: the real HYDR full-holdings CSV as of 2026-11-02
(`https://assets.globalxetfs.com/funds/holdings/hydr_full-holdings_20261102.csv`). Columns: `% of Net Assets,
Ticker, Name, SEDOL, Market Price ($), Shares Held, Market Value ($)`. 26 companies plus 4 cash/currency lines.

### The real file does not load

| # | What happens | Where |
|---|---|---|
| 1 | Crash: two title lines ("Global X Hydrogen ETF", "Fund Holdings Data as of …") sit above the header, so `csv.DictReader` takes the title as the header and later rows have a `None` key | `etf_holdings.py:25` (`key.strip()`) |
| 2 | Crash after removing the title: the disclaimer footer is a short row, so cells are `None` | `etf_holdings.py:26` (`row[key].strip()`) |
| 3 | Cash and currency rows (`CASH`, `BRITISH STERLING POUND`, `EURO`, `OTHER PAYABLE & RECEIVABLES`) are kept as corpus snippets | `etf_holdings.py:84-93` |

For the run the title and footer lines were cut by hand; nothing else was changed.

### What the corpus looks like

Each snippet is the company name only, e.g. `BLOOM ENERGY CORP- A`, `NEL ASA`. HYDR has no sector or description
column, so `load_holdings_corpus` (`etf_holdings.py:84-93`) has nothing else to add. Weights (Bloom 16.2 %, Nel 5.1 %)
are parsed (`_parse_weight`) but not passed to synthesis; only `overlap.py` uses them.

### Result: 4 activities, 1 LLM call (~2k tokens in, 2.5k out)

| Activity | Names the model put in it |
|---|---|
| PEM and alkaline electrolyser system manufacturing | Nel, ITM Power, Plug Power, Cummins, possibly Guofu |
| Solid oxide electrolyser and cell technology | Ceres Power, Bloom Energy, FuelCell Energy |
| Electrolyser stack components and catalysts | Johnson Matthey, Nanofilm, possibly Mico, S-Prism |
| Hydrogen production equipment and plant supply (adjacent) | Air Products, Guofu |

`corpus_assessment` was honest: "each is only a ticker and company name … I know that from outside knowledge, not
from the corpus text". It also said most holdings are fuel-cell, vehicle and tank makers and left them out as
off-theme.

### Against the golden set

13 HYDR holdings are golden companies. 9 of them are placed by name in the draft; 7 agree with the golden label:

| Company | Draft | Golden | Agree |
|---|---|---|---|
| Nel, ITM Power, Plug Power | electrolyser maker | core, make_electrolysers | yes |
| Bloom Energy, Ceres Power | solid oxide electrolysers | peripheral, make_electrolysers | yes |
| Johnson Matthey | components | not, supply_components | yes |
| Air Products | adjacent production | not, produce_hydrogen | yes |
| **Cummins** | electrolyser maker | not (halted new electrolyser sales Feb 2026) | **no** |
| **FuelCell Energy** | solid oxide electrolysers | not (ceased most solid oxide development 2025) | **no** |

Both misses are stale model knowledge, which is what this method relies on when the file has names only. The
golden set splits by role (maker / supplier / producer / fuel cells); the draft splits makers by technology (PEM +
alkaline vs solid oxide) and has no fuel-cell boundary activity. The company placements live only in the
in-scope prose, not as data.

## 2. `empirical` on 10 golden companies

Input: 10 golden companies in mixed order: 3 core (Nel, ITM Power, thyssenkrupp nucera), 1 core US (Plug Power),
2 peripheral (Bloom Energy, Siemens Energy), 4 not (Air Products, Johnson Matthey, Ballard Power, Martin
Marietta). Documents: the golden annual-report PDFs for the 5 non-US companies (local files), EDGAR 10-K / 40-F
for the 5 US/CA filers.

### Running it

| # | What happens | Where |
|---|---|---|
| 1 | First run crashed after a few companies: the model returned a malformed verifier reply (`confidence='0.88</parameter>…'`), the `ValidationError` was not caught, and the whole run ended with nothing saved | `empirical.py:48-50` (no per-company `try`) |
| 2 | The verifier is the extractor's own model: `empirical.py:49` passes no `verifier_llm`, so `field_graph.py:456` uses `llm`. Setting `ARP_LLM_VERIFIER_MODEL` has no effect on this method | `empirical.py:49` |
| 3 | Needs Postgres with pgvector even for a one-off draft (document content store) | `cli/_shared.py:60-71` |

### Cost

Second run: **44.6 minutes**, about **199k input + 14k output tokens** (extraction 196k + 12k, synthesis 3k + 2k),
companies processed one at a time. The ETF run: about 1 minute and 4.5k tokens.

### Corpus: 8 of 10 companies returned a description

The 8 descriptions are accurate and match the golden rationales (Nel: "two divisions: Nel Alkaline Electrolyser
and Nel PEM Electrolyser"; nucera: "two reportable segments: Green Hydrogen and Chlor-Alkali"; Bloom: "solid oxide
fuel cell-based onsite power … also offers the Bloom Electrolyzer").

**Ballard Power and Martin Marietta returned nothing**, although both had documents loaded (40-F, 10-K). Both are
golden "not" companies, so the boundary evidence (fuel cells, unrelated industry) dropped out of the corpus. Cause
not investigated; a likely cause is that the field asks for activities "especially related to" the theme and seeds
retrieval with the theme name only (`empirical.py:17-25`).

### Result: 7 activities

| Activity | Assessment against the golden set |
|---|---|
| Alkaline electrolyser systems and plants | good; maps to `make_electrolysers` |
| PEM electrolyser systems and stacks | good; maps to `make_electrolysers` |
| Solid oxide (high-temperature) electrolysers | good; out-of-scope correctly excludes Bloom's fuel-cell server |
| Electrolyser components and catalyst materials | good; maps to `supply_components` (Johnson Matthey) |
| Integrated electrolyser portfolio within diversified groups | **not an activity**: a company type (Siemens Energy). Overlaps the three technology activities, so not MECE. The golden set handles this with the label `peripheral`, not with an activity |
| Electrolyser project engineering, consulting, build-own-operate | thin (one snippet) |
| Adjacent hydrogen value-chain equipment (fuel cells, liquefaction, storage) | **in scope where the golden set says `not`**: fuel cells and hydrogen production are `fuel_cells` / `produce_hydrogen` boundary roles |

Keywords overfit to the sampled companies' product names: `TRIDENT stack`, `NEPTUNE`, `POSEIDON`, `scalum module`,
`Nel Alkaline`, `Hydropulse`. They help find those 8 companies again and little else.

### What the two methods have in common

Both drafts split electrolyser makers by technology and agree on components. Neither produces the golden set's
role boundaries (supplier / producer / fuel cells) as explicit out-of-scope activities. Empirical has real
evidence per company but loses it before synthesis; ETF has no evidence and fills the gap with model memory.

## 3. Both methods against what the authority agent (PR #325) produces

| Field | Authority agent (PR #325) | etf_index_holdings | empirical |
|---|---|---|---|
| Activities with in/out scope + keywords | yes | yes | yes |
| Quote per activity (`citations`) | yes, grounding-checked | no (corpus is names) | no: the extractor's cited quote is dropped at `empirical.py:52-54` |
| Sector codes (`sector_codes`, `core_isic_codes`) | from source when stated | no | no |
| Value-chain role (core / upstream / enabling) | yes | no (`tier` always default `core`) | no |
| Boundaries with quotes (`out_of_scope_citations`) | yes | no | no |
| `lifecycle_stage` | no | no | no |
| Checklist report (found / not_in_source) | yes | no | no |
| Merge with other sources (activity matcher) | yes | no | no |

All three gaps come from the shared synthesis step: `corpus_synthesis.py:24-28` asks only for name, in-scope,
out-of-scope and keywords, and `corpus_synthesis.py:64-72` builds `ActivityDefinition` from those four fields.

## 4. Code weaknesses checked

| Claim | Verdict | Where |
|---|---|---|
| ETF corpus is thin (name, ticker, sector, optional description) | true; HYDR gives name only | `etf_holdings.py:84-93` |
| Capped at 40 snippets | true, both methods | `corpus_synthesis.py:55` |
| Weights ignored by synthesis | true (used by `overlap.py` only) | `etf_holdings.py:84-93` |
| Empirical sample is the first N rows | true; on the golden file the first 25 rows are 9 core + 16 peripheral + 0 not | `empirical.py:45` |
| Empirical is the most expensive method | true; see run cost in section 2 | `empirical.py:48` (one company at a time) |
| No sector codes, value-chain role, quoted boundaries, lifecycle | true | `corpus_synthesis.py:64-72` |
| Doesn't use PR #325 matcher or checklist | true | PR #325 not merged; no import in `taxonomy_sources/` |
| New: real provider CSV crashes the parser | found in this run | `etf_holdings.py:25-26` |
| New: one company's LLM failure ends the whole empirical run | found in this run | `empirical.py:48-50` (no per-company error handling) |
| New: empirical verifies with the extractor's own model | found in this run | `empirical.py:49` passes no `verifier_llm`; `field_graph.py:456` falls back to `llm` |

## 5. Improvement options (for the owner to choose)

| # | Option | What it fixes | Size |
|---|---|---|---|
| A | **Robust holdings loader**: skip title/footer lines, find the header row, drop cash/currency rows | Crashes 1-2 and cash rows; the method does not work on a real Global X file today | small (hours) |
| B | **Reliable empirical run**: per-company error handling, pass the separate verifier model, run companies concurrently, sample by stratum or at random instead of the first N rows | Crash 1, self-verification, 45-minute runtime, order-dependent sample | small to medium |
| C | **Keep the evidence**: carry the extractor's verified quote into `source_citation` / `citations`; for ETF, run empirical extraction on the top holdings by weight so the corpus has descriptions instead of names | ETF relying on model memory (Cummins, FuelCell misses); empirical dropping its citations | medium |
| D | **Authority-shaped output**: have the shared synthesis fill `value_chain_role`, explicit boundary activities (supplier / producer / fuel cells) and run `map-standards` for sector codes; output in the PR #325 shape so the activity matcher can merge these drafts with authority drafts | Missing fields in section 3; "company type as activity"; no merge path | large (depends on PR #325 merging) |

Raw outputs of both runs are in the session scratchpad, not committed.
