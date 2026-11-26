# Risk themes: company risk view, risk mode for theme runs, water-scarcity scorecard

Status: Draft, for owner approval
Slug: `theme-risk-mode`
Risk: `risk:normal` (new CLI, a theme-run mode, two API endpoints, one results region; no auth, money or `risk:high` path)
Size: four slices, `M`, `M`, `S`, `S` (see `## Slices`). R&D Lab plan item 10, fixes finding P6. Mock-up screen 11
(`Risk.dc.html`).

## Decisions for the owner

None needed a question. Every choice is listed under "Defaults taken"; approving the spec approves them. The one
that shapes results most is D2: "disclosed" is decided by search terms in the company's risk section, without a
model.

## Why

**P6, risk themes have no pipeline.** A theme is a list of activities, which suits "who makes electrolysers" but not
"who is exposed to water scarcity". The `water_scarcity_exposed` golden set (67 companies) labels companies
`exposed_disclosed`, `exposed_undisclosed` or `not_exposed`, but no run can produce those labels, so
`arp golden-set theme` refuses risk sets (`theme-precision-scorecard` AC-14). The approved `company-risk-view` spec
(1 Nov), which reads the risks a company names in its own risk section, was never built.

Theme Radar item 21c (dispatcher "Build the Theme Radar upgrade") turns a radar risk into a risk theme in one click,
so it needs a stable way to start one from a topic name and search terms.

## What the user can do afterwards that they cannot do today

1. Run `arp risk-view run` on an annual report PDF or a 10-K and get the risks the company names, each with stated
   mitigations, a house theme and a year-on-year label (the approved `company-risk-view` goals, built here).
2. Start a risk theme from a topic and search terms (`POST /api/themes/risk-runs`, the entry point Theme Radar 21c
   calls) and get, per company, `exposed_disclosed`, `exposed_undisclosed`, `not_exposed` or `not_assessed`, the
   channels it is exposed through, the sentence where it names the risk, and whether it states a mitigation.
3. See those labels on the run's results page in a "Risk exposure" region with Disclosed / Not disclosed /
   Not exposed filters (mock-up screen 11, Companies tab).
4. Score the risk mode on the water-scarcity set: `arp golden-set theme --set water_scarcity_exposed`.

## What exists today (main `e4cb8c3`)

- No `backend/arp/risk_view/` package; `docs/superpowers/specs/2026-11-01-company-risk-view-design.md` is approved and
  unbuilt. Its golden documents are not in the repo.
- `ThemeDefinition` (`backend/arp/schemas/thematic.py`) has no kind; every theme is activities. `pipeline._match_company`
  loops `theme.activities` through `match_graph.match_company_activity` and returns `CompanyMatchesResult`;
  `execute_theme_run` stores one `results.jsonl` row per company, `{"company_matches": [...]}`.
- `POST /api/themes/runs` (`backend/arp/api/routers/themes.py`) only starts runs from a saved taxonomy with a released
  extraction schema; `GET /api/themes/runs/{run_id}/results` returns the stored match dicts.
- A company with no documents gets `verdict: uncertain`, `confidence: 0.0` on every activity; documents with no keyword
  hit give `verdict: exclude`, `confidence: 1.0`, no model call.
- `arp.models.classify(texts, labels, hypothesis)` is the shared NLI model (registry entry `nli`), already used by the
  funnel. `arp.retrieval.embeddings.embed_texts` embeds texts. `arp.grounding.is_grounded(quote, text)` checks a quote.
- `ARP_STANDINS_DIR` (`backend/arp/standins.py`) answers every model call from `model/<OutputClass>.json` and logs it
  to `calls.jsonl`.
- `theme-precision-scorecard` (merged spec, slice 1 being built): `arp golden-set theme`, per-split text block, JSON
  report, holdout gate, stored scorecard. Its AC-14 refuses risk sets.
- `matcher-shared-retrieval` (merged spec, not built): adds `EvidenceRef`, `CompanyMatch.evidence_status` and
  `CompanyMatch.evidence`. This spec does not touch those keys.

## Goals

- G1 Build the company risk view as approved, with the amendments below.
- G2 A risk theme: `ThemeDefinition.kind = "risk"`, built from a topic and search terms, with three channel activities.
- G3 Risk mode: each company of a risk run gets a `RiskAssessment` with the golden set's labels plus `not_assessed`.
- G4 A stable entry point for Theme Radar 21c: `POST /api/themes/risk-runs` and `create_risk_theme_run(...)`.
- G5 `GET /api/themes/runs/{run_id}/risk` and a "Risk exposure" region on the results page.
- G6 `arp golden-set theme` scores risk sets; a risk taxonomy for `water_scarcity_exposed` ships with the set.

## Non-goals

- Site and basin checks (WRI Aqueduct, plant locations). Mock-up screen 11 says these need location data (later
  phase); until then exposure comes from what the documents say about operations, inputs and suppliers.
- The rest of screen 11: Exposure map, Run quality, Ask this theme and Dossier tabs, the "Why … is exposed" side panel
  with per-channel quotes, "Send to StewardIQ", "Draft an engagement question", Download. Theme Workbench (item 13) and
  Ask this theme (item 14) own those.
- A form in Theme Builder to start a risk theme. Theme Radar 21c starts them; the API is open to any caller.
- Resuming an interrupted risk run (`arp/orchestration/jobs.py` refuses theme runs without an extraction schema; a
  risk run has none). Start it again instead.
- The Run quality box (`theme-precision-scorecard` slice 3) for risk runs.
- Ratings, likelihood or impact scores; the ESRS matrix image; feeding the risk view into stewardship ranking (as in
  the approved spec).
- A golden-set merge gate. Golden checks are off as a gate; no workflow changes.

## Anti-goals (must stay true)

- An activity theme (`kind` `activity`, the default) runs, stores and shows exactly as on `main`.
- No risk or mitigation quote is stored unless `grounding.is_grounded` finds it in the source text.
- No model call decides whether a company discloses the risk.
- No real model call in any `holdout` or `unit` row.

## Design

### Slice 1: company risk view (item 10a)

Build `docs/superpowers/specs/2026-11-01-company-risk-view-design.md` (steps, output JSON, CLI, roadmap) with these
amendments. Where the two disagree, this section wins.

- **A1, section finder on text, shared.** New `arp/risk_view/section.py` with
  `find_risk_section(text: str) -> tuple[int, int] | None` (char offsets, end exclusive). It works on lines of plain
  text (split on `\n`; each line compared after stripping whitespace and leading/trailing `#` and `*`):
  - A *start line* matches, case-insensitive, one of: `^Item 1A\b`, `^(D\.\s*)?Risk Factors$`,
    `^Risk and opportunity report`, `^Principal risks`, `^Risk report`, `^Risikobericht`.
  - A *stop line* matches one of: `^Item 1B\b`, `^Item 1C\b`, `^Item 2\b`, `^Item 4\b`, or starts with an entry of
    `risk_view/data/section_stops.json` (the approved stop list: `Outlook`, `Forecast`, `Prognosebericht`,
    `Corporate governance`, `Remuneration report`, `Consolidated financial statements`).
  - Each start line opens a span from the first character of the start line up to, not including, the first
    character of the first later stop line (or to the end of the text when none follows). The longest span wins (so a
    table of contents loses to the body); on a tie, the first. No start line: `None`.
  Step 2 of the risk view uses it on the PDF's full text (pages via `page_breaks`) and on the 10-K's text.
  - *10-K/20-F text* = `BeautifulSoup(html, "lxml").get_text("\n")` (not `extract_html_text`, whose trafilatura pass can
    merge or drop short lines). *PDF text* = `parse_file_to_text_with_pages` (docling, unchanged), called as
    `local_files.parse_file_to_text_with_pages(...)` on the module `arp.ingestion.local_files`.
- **A2, 20-F.** The `Risk Factors` start line and the `Item 4` stop line cover a 20-F (Item 3.D to Item 4). A 20-F
  HTML goes through the 10-K path; its locator is `"section": "Item 3.D"`.
- **A3, headings made exact.** 10-K/20-F HTML: a heading is the stripped text of a `<b>`, `<strong>`, `<i>` or `<em>` element,
  or of an element whose inline style sets `font-weight: bold|600|700` or `font-style: italic`, inside the section and
  not itself a start line, located in the text above as the first occurrence of that string at or after the previous
  heading. More than 40 characters: a risk heading. 40 or fewer: a category heading, carried as
  `category` by the risk headings after it. PDF/text: a heading is a line of 41 to 200 characters that does not end in
  `.`, `,`, `;` or `:`; PDFs have no categories (`category` null).
- **A4, mitigation call named.** Step 4's call uses output class `MitigationQuotes` (`quotes: list[str]`) in
  `arp/risk_view/mitigations.py`, with `MITIGATION_SYSTEM` as its system prompt. Slice 2 reuses both.
- **A5, NLI from the shared model layer.** Step 6 calls `arp.models.classify([heading], labels, hypothesis="This risk is about {}.")`
  with the labels of `risk_view/data/themes.json`, not a new `transformers` pipeline; no new dependency. The file maps
  key to label: `climate_transition` "climate policy and the energy transition", `climate_physical` "physical climate
  hazards such as floods, storms and heat", `water` "water availability, water stress and drought", `supply_chain`
  "suppliers, raw materials and logistics", `regulation` "laws, permits and regulation", `cyber` "cyber security and IT
  systems", `people` "employees, health and safety", `financial` "interest rates, currency, credit and liquidity",
  `market` "demand, prices and competition", `geopolitical` "war, sanctions and trade restrictions". Highest score
  ≥ 0.5 wins, else `other`.
- **A6, test seams.** The risk view calls `models.classify` as `from arp import models` / `models.classify(...)` and
  embeddings as `from arp.retrieval import embeddings` / `embeddings.embed_texts(...)`, and the PDF parse through the
  module as in A1, so a test patches `arp.models.classify`, `arp.retrieval.embeddings.embed_texts` and
  `arp.ingestion.local_files.parse_file_to_text_with_pages`. The LLM is built with `build_llm_client`, so
  `ARP_STANDINS_DIR` answers it.
- **A7, golden documents not committed.** `arp risk-view golden --documents-dir <dir> [--labels <file>]
  [--min-recall 0.90] [--min-precision 0.90] [--min-yoy 0.90]` (the approved `--cases` option is replaced by
  `--labels`, default `backend/tests/golden/risk_view/labels.json`). Labels file: a JSON list of
  `{"company_id", "fiscal_year", "file", "prior_file", "risks": [{"heading", "mitigations": [<quote>], "change"}]}`
  (`prior_file` null or another entry's `file`); `file` is relative to `--documents-dir`. Slice 1 ships the runner but
  no labels: the four documents (Heidelberg Materials FY2024/FY2025 PDF, Martin Marietta FY2024/FY2025 10-K) are
  downloaded and hand-labelled later, by the owner or a labelling session, in a labels PR (not docs-only) that adds
  `labels.json` and posts the output of `arp risk-view golden --documents-dir <dir>`, run by hand with the real model;
  that output is AC-19's evidence. Labels file missing:
  exit 1 with `Golden labels missing: <path>`. A listed document missing: exit 1 with `Golden document missing: <path>`.
  Both checks run before any model call.
- **A8, roadmap.** The roadmap line "Heavy encoders run on the existing Cloud Run L4 compute" is out of date: the GCP
  deploy path was removed (PR #681). Heavy encoders run on the portable compute container (`arp compute`) or locally.
- **A9, rows.** The approved spec's rows were all `unit` and are replaced by AC-1 to AC-19 here (synthetic fixtures,
  `holdout`), which need no real filing. No hidden test exists for them.
- **A10, year-on-year pairs.** A pair counts as matched only when its similarity is ≥ 0.60. Greedy one-to-one over
  the pairs ≥ 0.60, highest first; a current risk left without a pair is `new` with `"prior_id": null`, and every
  prior risk left without one is appended once as `dropped`.

### Slice 2: risk mode (items 10b and the Radar entry point)

**Risk theme.** `ThemeDefinition` gains `kind: Literal["activity", "risk"] = "activity"` and
`risk_terms: list[str] = Field(default_factory=list)` (the terms that count as naming the risk). New module
`backend/arp/research/risk_mode.py`:

```python
def build_risk_theme(topic: str, search_terms: list[str], exposure_terms: list[str] | None = None) -> ThemeDefinition
def create_risk_theme_run(topic: str, search_terms: list[str], companies: list[CompanyRef],
                          settings: Settings, run_store: RunStore) -> str   # run_id; execute with execute_theme_run
async def assess_risk(theme: ThemeDefinition, documents: list[SourceDocument], matches: list[CompanyMatch],
                      llm: LLMClient) -> tuple[RiskAssessment, list[LLMUsage]]
```

- `build_risk_theme` strips `topic`; blank raises `ValueError("Provide a topic.")`. Search terms are stripped, empty
  ones dropped, and duplicates (case-insensitive) dropped keeping the first spelling, in order; none left raises
  `ValueError("Provide at least one search term.")`. Exposure terms are cleaned the same way and may be empty.
- Result: `kind` `risk`, `name` = topic, `description` = `Companies exposed to <topic>.`, `risk_terms` = the cleaned
  search terms, and three activities in this order, each with `seed_keywords` = cleaned search terms followed by the
  cleaned exposure terms not already in them, `tier` core:

| `activity_id` | `name` | `in_scope_description` | `out_of_scope_description` |
|---|---|---|---|
| `risk_operations` | `Operations` | `The company's own sites or processes depend on resources or conditions that <topic> affects, so <topic> could disrupt them, raise their cost or restrict them.` | `Generic lists of climate or natural hazards that do not tie <topic> to the company's own sites; risks only to customers or the wider economy.` |
| `risk_supply_chain` | `Supply chain` | `Key suppliers, inputs or raw materials the company relies on are exposed to <topic>.` | `Suppliers named without any link to <topic>; the company's own sites (see Operations).` |
| `risk_regulation` | `Regulation` | `Rules, permits, licences, quotas or prices tied to <topic> restrict the company's activities or raise their cost.` | `General compliance statements that do not name rules tied to <topic>.` |

  (`<topic>` is the topic as given, after stripping.)
- `create_risk_theme_run` calls `build_risk_theme` (no exposure terms) and creates the run the way `create_theme_run`
  does (`run_type` `theme`, `theme.json` in the run directory), with the manifest params also holding
  `"mode": "risk"`, `"topic"` and `"search_terms"` (cleaned); `taxonomy_id` and `taxonomy_version` are null.
- **Stable contract for Theme Radar 21c:** `POST /api/themes/risk-runs` with body
  `{"topic": str, "search_terms": [str], "companies": [CompanyRef] | null, "universe_path": str | null, "batch": bool = false}`.
  Companies as in `POST /api/themes/runs` (`companies`, else the saved universe at `universe_path`; neither: 400
  `Provide either \`companies\` or \`universe_path\`.`). `ValueError` from `build_risk_theme`: 400 with its message.
  Success: 200 `{"run_id", "theme_id", "company_count"}`, and the run is scheduled with `schedule_llm_run`, executed by
  `execute_theme_run` with no indirect, revenue or R&D resolver. These request and response keys, and the three
  function signatures above, change only through a spec that names Theme Radar 21c.

**Assessment.** New models in `arp/schemas/thematic.py`:

```python
class RiskDisclosure(BaseModel):
    term: str            # the search term as spelled in theme.risk_terms
    quote: str           # the whole line holding the hit, stripped, first 400 characters
    doc_id: str
    page: int | None = None   # 1-based PDF page of the hit (grounding's _page_for_offset); None without page_breaks
    where: Literal["risk_section", "document"]

class RiskAssessment(BaseModel):
    company_id: str
    name: str
    label: Literal["exposed_disclosed", "exposed_undisclosed", "not_exposed", "not_assessed"]
    channels: list[str]          # names of the activities with verdict include, in theme order
    disclosure: RiskDisclosure | None
    mitigation: Literal["stated", "none_stated"] | None
    mitigation_quotes: list[str] = Field(default_factory=list)
```

`assess_risk` rules, in order:

1. **Not assessed.** `documents` empty: `label` `not_assessed`, `channels` [], `disclosure` null, `mitigation` null.
2. **Exposed** = at least one match has `verdict` `include`. `uncertain` does not count.
3. **Disclosure.** For each document in list order: `find_risk_section(full_text)`; if it returns a span, search only
   that span (`where` `risk_section`), else the whole text (`where` `document`). A hit is a case-insensitive match of
   a term of `theme.risk_terms` as a whole word, with an optional trailing `s` (regex `\b<escaped term>s?\b`). The
   disclosure is the earliest hit by offset in the first document that has one; `null` when no document has one.
   Disclosure is recorded for every assessed company, exposed or not.
4. **Label.** Exposed and disclosure set: `exposed_disclosed`; exposed, no disclosure: `exposed_undisclosed`;
   otherwise `not_exposed`.
5. **Mitigation**, only for `exposed_disclosed`: one call `llm.complete_structured(system=MITIGATION_SYSTEM, prompt=…,
   output_model=MitigationQuotes)` (slice 1) on the *risk body* = the searched text from the start of the hit line,
   at most 3,000 characters, ending at the searched span's end. Quotes that `grounding.is_grounded` finds in the risk
   body are kept in `mitigation_quotes`; at least one kept: `stated`, else `none_stated`. Every other label:
   `mitigation` null, no call.

**In the run.** In `pipeline._match_company`, after the activity loop, when `theme.kind == "risk"`:
`assess_risk(theme, documents, matches, llm)`; the assessment goes on `CompanyMatchesResult.risk` (new attribute,
default `None`) and its usages into the cost. `execute_theme_run`'s row becomes
`{"company_matches": [...], "risk": <assessment>}` for a risk theme; an activity theme's row stays
`{"company_matches": [...]}`. Review items, matches and everything else are unchanged.

**Reading it.** `GET /api/themes/runs/{run_id}/risk`: when the manifest is a `theme` run with `params.mode == "risk"`,
200 with `{"topic", "counts", "results"}`: `counts` = `{"exposed_disclosed", "exposed_undisclosed", "not_exposed",
"not_assessed"}` (each an int, zeros included), `results` = the rows' `risk` objects in results order. Unknown run or
any other run: 404 `Not a risk run.` A response model, so regenerate the OpenAPI types (also for the two new
`ThemeDefinition` fields) and add the contract line (`.claude/CLAUDE.md`, Checks).

### Slice 3: scorecard on risk sets (item 10c)

Changes to `arp golden-set theme` (`theme-precision-scorecard` slice 1); everything not named here stays as that spec
says.

- A set whose `kind` is `risk` is scored, no longer refused (retires `theme-precision-scorecard` AC-14). Its taxonomy
  must be a risk theme: else exit 1, before any model call, with `Taxonomy <id> is not a risk theme.` An activity set
  given a risk taxonomy exits 1 with `Taxonomy <id> is a risk theme; this set needs an activity theme.`
- Per company: *predicted* = the `RiskAssessment.label` that `_match_company` returns; *put in* = predicted is
  `exposed_disclosed` or `exposed_undisclosed`; *belongs* = the golden label is one of those two. *Adjudicated* and
  *deciding match* as in that spec; *correct* = the deciding match is `include` and the company belongs, or it is not
  `include` and the label is `not_exposed`.
- Metrics per split: `precision` = put in and belongs / put in; `recall exposed_disclosed` = predicted
  `exposed_disclosed` among `exposed_disclosed` cases / those cases; `recall exposed_undisclosed` likewise;
  `label accuracy` = predicted equals label / all cases of the split (not assessed is wrong); `quotes found in source`
  and the confidence table as in that spec. Rounding and `n/a` as there.
- Text block for a risk split, exactly these lines:

```
split: tune
companies: 7 (exposed_disclosed 2, exposed_undisclosed 2, not_exposed 3)
not assessed: 1
put in: 4
precision: 0.750
recall exposed_disclosed: 1.000
recall exposed_undisclosed: 0.500
label accuracy: 0.714
quotes found in source: 0.667
confidence 0.90-1.00: calls 1, correct 1, rate 1.000
confidence 0.70-0.90: calls 3, correct 2, rate 0.667
confidence 0.50-0.70: calls 1, correct 1, rate 1.000
confidence 0.00-0.50: calls 0, correct 0, rate n/a
```

- JSON report: top level as in that spec. A risk split's keys are `companies`, `labels`, `not_assessed`, `put_in`,
  `precision`, `recall_exposed_disclosed`, `recall_exposed_undisclosed`, `label_accuracy`, `quotes_found`,
  `confidence`, `cases`; each case is `{"case_id", "label", "predicted", "assessed", "put_in", "confidence", "correct"}`.
- Gate: `--min-precision` works as in that spec. `--min-recall-core` on a risk set exits 1, before any model call,
  with `--min-recall-core needs an activity set.` Stored scorecard as in that spec. `arp golden-set calibrate` reads a
  risk report's tune bins like any other.
- New taxonomy `backend/tests/golden/exposure/water_scarcity_exposed/taxonomies/tax_water_scarcity_exposed/`
  (`latest.json` → 1, `v1.json`): `build_risk_theme("Water scarcity", ["water scarcity", "water stress",
  "water shortage", "water availability", "water supply", "drought", "arid"], ["water withdrawal", "water consumption",
  "cooling water", "process water", "ultrapure water", "groundwater", "aquifer", "water rights", "water permit"])`.
  The search terms are the ones the label review searched.

### Slice 4: Risk exposure region (screen 11, Companies tab)

On `#/theme/<run_id>` (`frontend/src/pages/ThemeBuilder.tsx`), when the run manifest (`GET /api/runs/<run_id>`) has
`params.mode` `risk`, the page fetches `GET /api/themes/runs/<run_id>/risk` and shows, above the existing results card,
a region labelled `Risk exposure`:

- Heading `Risk exposure`.
- One toggle chip per label with a count above 0, in this order and wording: `Disclosed <n>`, `Not disclosed <n>`,
  `Not exposed <n>`, `Not assessed <n>`. Pressing a chip shows only that label's rows (`aria-pressed` true); pressing
  it again shows all rows. One chip at a time.
- The note `“Not disclosed” means the company does not name the risk, but its documents show it is exposed.`
- A table with columns `Company`, `Exposure`, `Channels`, `Mitigation`, one row per result in API order. Exposure
  reads `Disclosed`, `Not disclosed`, `Not exposed` or `Not assessed`; Channels = channel names joined by `, `, or `–`
  when empty; Mitigation reads `stated`, `none` (for `none_stated`) or `–` (null).
- Pressing a row expands it with: when `disclosure` is set, `Named as a risk: “<quote>”` and
  `Found in: risk section, page <page>` (`, page <page>` only when `page` is set; `document text` instead of
  `risk section` when `where` is `document`), then one line `Stated mitigation: “<quote>”` per mitigation quote;
  when `disclosure` is null, `Not named as a risk in the documents checked.`
- The risk call fails (any non-200): the region holds the heading and `Risk results could not be loaded.`; the rest
  of the page still loads.
- Activity runs (no `params.mode`, or not `risk`) show no such region and make no `/risk` call.

Matches the mock-up's dark theme tokens and the page's existing table style; no new design tokens.

## Defaults taken

1. **D1 Three fixed channels** (Operations, Supply chain, Regulation), as on screen 11, built from a template, no model
   call. A caller only names the topic and terms, which is all Theme Radar has.
2. **D2 Disclosure without a model.** "Discloses" = a search term appears in the company's risk section (or anywhere,
   when no risk section is found). The golden labels were made with the same term search; a model would add cost and
   run-to-run drift to the one step a rule can do. The scorecard (slice 3) measures it.
3. **D3 Exposure = any channel `include`.** The existing advocate/opposing/adjudicator debate decides each channel;
   `uncertain` is not exposure but stays in Needs you as today.
4. **D4 Exposure terms only in the golden taxonomy.** The API takes topic and search terms; `exposure_terms` is a
   function argument for hand-made taxonomies. Without them, a company that never uses the search terms gets no
   evidence and counts as not exposed, so `exposed_undisclosed` relies on terms outside the risk section.
5. **D5 Mitigation only for `exposed_disclosed`**, one call per such company, reusing the risk view's prompt.
6. **D6 `not_assessed`** is a fourth label for companies with no documents; the scorecard counts it as wrong.
7. **D7 Risk runs are `theme` runs** with `params.mode: "risk"`, so they list, export and show where theme runs do.
8. **D8 Risk view amendments A1 to A10** (above); the approved spec's other choices stand.
9. **D9 No resume, no Theme Builder start form, no Run quality box** for risk runs (Non-goals).

## Supersedes

- `theme-precision-scorecard` **AC-14** (`Risk sets can't be scored yet: water_scarcity_exposed`) is retired:
  risk sets are scored (AC-60 to AC-70 here). The test writer retires its hidden test (`specs/theme-precision-scorecard/`
  or `regression/`) in the same holdout PR. That spec's anti-goal and default 8 ("Water scarcity is refused until
  plan item 10") end with it.
- `company-risk-view` (`docs/superpowers/specs/2026-11-01-company-risk-view-design.md`, approved, unbuilt): its rows
  AC-1 to AC-33 are replaced by AC-1 to AC-19 here (A9); no hidden test existed. Its file is left as it is (this PR
  holds only this spec); a later docs PR sets its `Status:` to `built by theme-risk-mode`.

## Acceptance

All rows run with `ARP_STANDINS_DIR` = a temporary folder (every stand-in entry wrapped as `{"output": …}`),
`ARP_HYBRID_RETRIEVAL_ENABLED=false` and `ARP_MODELS_UNIVERSE_FUNNEL_ENABLED=false`. CLI rows run the Typer app
in-process (so patches apply). "Output contains" means stdout and stderr combined. "MitigationQuotes calls" = lines
of `calls.jsonl` with `"name": "MitigationQuotes"`, likewise `AdjudicatorOutput`.

### Company risk view (slice 1)

Fixtures:
- **K1**, a 10-K HTML file. In body order: `<p>Item 1A. Risk Factors 12</p>`, `<p>Item 1B. Unresolved Staff Comments 20</p>`
  (a table of contents), `<p><b>Item 1A. Risk Factors</b></p>`, `<p><b>Industry Risk Factors</b></p>`,
  `<p><b>Our business depends on construction activity in our markets</b></p>`,
  `<p>Construction fell in 2025. We diversify across regions to reduce this risk.</p>`,
  `<p><b>Water scarcity could limit the operation of our quarries</b></p>`,
  `<p>Some quarries are in dry regions. We recycle process water at our quarries.</p>`,
  `<p><b>Item 1B. Unresolved Staff Comments</b></p>`,
  `<p><b>Our competitors are larger than we are in most of our regions</b></p>`, `<p>None.</p>`.
- PDF rows give any file with suffix `.pdf` and patch `arp.ingestion.local_files.parse_file_to_text_with_pages` to
  return `(text, page_breaks, [])` for it, so no docling parse runs. Pages are joined with `\n\n`, lines within a
  page with `\n`, and `page_breaks` holds each page's start offset (first entry 0), as docling's path produces.
- **P1** pages: 1 `Annual report 2025`; 2 `Risk report`, `Our risk management is described below.`;
  3 `Rising energy prices could raise our production costs sharply`, `Energy is a large share of our costs.`,
  `We hedge energy purchases two years ahead.`; 4 `Outlook`, `Demand should stay stable next year while our costs keep falling`.
- **P0** one page: `Annual report 2025`, `We make cement in three countries.`
- Stand-in `model/MitigationQuotes.json` is as the row says; a row that names none uses `[{"output": {"quotes": []}}]`.
- NLI: `arp.models.classify` patched to return `([{<label text>: score, …} for each text], {})` with the row's scores
  (label texts as in A5); default every label 0.1.
- Year-on-year rows: `arp.retrieval.embeddings.embed_texts` patched to return unit vectors whose pairwise cosine
  similarities are the row's values.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | P0 | `arp risk-view run --input P0 --company Z --year 2025 --out O` | Exit code 0; `O/Z/2025.json` has `"status": "no_section"` and `"risks": []` | holdout |
| AC-2 | P0 | Same | 0 MitigationQuotes calls | holdout |
| AC-3 | K1 | `arp risk-view run --input K1 --company M --year 2025 --out O` | `O/M/2025.json` `risks` has exactly 2 entries, headings in order `Our business depends on construction activity in our markets`, `Water scarcity could limit the operation of our quarries` | holdout |
| AC-4 | K1 | Same | Both risks have `"section": "Item 1A"`, no `page` key and `"category": "Industry Risk Factors"`; no risk has heading `Industry Risk Factors` | holdout |
| AC-5 | K1 | Same | Exactly 2 MitigationQuotes calls | holdout |
| AC-6 | K1; MitigationQuotes = `[{"quotes": ["We diversify across regions to reduce this risk.", "We own the moon."]}, {"quotes": []}]` | Same | The first risk's `mitigations` is exactly `[{"quote": "We diversify across regions to reduce this risk.", "section": "Item 1A"}]`; the second's is `[]` | holdout |
| AC-7 | As AC-6 | Same | `"dropped_quotes": 1` | holdout |
| AC-8 | P1 | `arp risk-view run --input P1 --company H --year 2025 --out O` | Exactly one risk, heading `Rising energy prices could raise our production costs sharply`, `"page": 3`, `"category": null`; no risk has `page` 4 | holdout |
| AC-9 | P1; MitigationQuotes = `[{"quotes": ["We hedge energy purchases two years ahead."]}]` | Same | That risk's `mitigations` is `[{"quote": "We hedge energy purchases two years ahead.", "page": 3}]` | holdout |
| AC-10 | P1; NLI gives the risk `climate_transition` 0.8, every other label 0.3 | Same | The risk has `"theme": "climate_transition"` | holdout |
| AC-11 | P1; NLI gives every label 0.4 | Same | The risk has `"theme": "other"` | holdout |
| AC-12 | K5 = K1 with its two risk headings and their bodies replaced by five risk headings r1..r5 (each > 40 chars, each followed by a one-sentence body); prior JSON with risks p1..p6 (ids `p1`..`p6`); similarities r1–p1 0.95, r2–p2 0.85, r3–p3 0.70, r4–p4 0.60, r5–p5 0.40, every other pair 0.0 | `arp risk-view run --input K5 … --prior <json>` | The `change` values of r1..r5 in document order are `same`, `same`, `reworded`, `reworded`, `new`; r1..r4 have `prior_id` `p1`..`p4`; r5 has `"prior_id": null` | holdout |
| AC-13 | As AC-12 | Same | Exactly two extra entries with `"change": "dropped"`, with `prior_id` `p5` and `p6` and headings equal to those prior risks', each with `"mitigations": []` | holdout |
| AC-14 | K2 = K1 with its two risk headings replaced by c1, c2 (bodies kept); a prior JSON with one risk P; similarities c1–P 0.95, c2–P 0.90 | `arp risk-view run --input K2 … --prior <json>` | c1 has `prior_id` = P's id and `change` `same`; c2 has `change` `new` | holdout |
| AC-15 | K1 | `arp risk-view run` without `--prior` | Every risk has `"change": null` | holdout |
| AC-16 | A manifest CSV `company_id,year,path` with rows `A,2024,<K1>`, `B,2025,<P1>`, `C,2025,<missing path>` | `arp risk-view batch --manifest <csv> --out O` | `O/A/2024.json` and `O/B/2025.json` exist; no `O/C/` directory exists; output contains `<missing path>`; exit code 1 | holdout |
| AC-17 | An empty folder D; a labels file L with one entry `{"company_id": "m", "fiscal_year": 2025, "file": "m/2025.htm", "prior_file": null, "risks": []}` | `arp risk-view golden --documents-dir D --labels L` | Exit code 1; output contains `Golden document missing:`; `calls.jsonl` has 0 lines | holdout |
| AC-17b | An empty folder D | `arp risk-view golden --documents-dir D --labels D/none.json` | Exit code 1; output contains `Golden labels missing:` | holdout |
| AC-18 | K1 with `arp.grounding.is_grounded` patched to return false for `Water scarcity could limit the operation of our quarries` | `arp risk-view run` | No risk has that heading | unit |
| AC-19 | The four golden documents and their labels file (later PR, A7), real model | `arp risk-view golden --documents-dir <dir>` | Per document: risk-heading recall ≥ 0.90, mitigation quote precision ≥ 0.90, every emitted heading grounded; per year pair: year-on-year accuracy ≥ 0.90 (the approved spec's thresholds) | golden |

### Risk mode (slice 2)

Fixtures. `llm` = `build_llm_client(settings)` under `ARP_STANDINS_DIR`; `model/MitigationQuotes.json` =
`[{"output": {"quotes": []}}]` unless the row says otherwise. **T** = `build_risk_theme("Water scarcity", ["water scarcity", "drought"])`. Matches given to `assess_risk`
are `CompanyMatch` objects for T's three activities with the stated verdicts (other fields any valid value). Documents
are `SourceDocument`s (`company_id` `x`, `doc_type` `10-K` unless stated) with these `full_text`s, lines joined by `\n`:

| doc | lines |
|---|---|
| `d_sec` | `Item 1A. Risk Factors` · `Competition is intense.` · `Drought could stop production at two plants.` · `We recycle water at both plants.` · `Item 1B. Unresolved Staff Comments` · `Water scarcity is a global issue.` |
| `d_out` | `Item 1A. Risk Factors` · `Competition is intense.` · `Item 1B. Unresolved Staff Comments` · `Water scarcity is a global issue.` |
| `d_nosec` | `Our plants need water.` · `Droughts hit our region in 2025.` |
| `d_toc` | `Item 1A. Risk Factors 12` · `Item 1B. Unresolved Staff Comments 20` · `Drought is mentioned in our letter.` · `Item 1A. Risk Factors` · `Competition is intense.` · `We rely on rain.` · `Our suppliers face more storms.` · `Item 1B. Unresolved Staff Comments` |
| `d_20f` | `Item 3. Key Information` · `Our 2025 drought report is online.` · `D. Risk Factors` · `Competition is intense.` · `Drought could reduce our harvest.` · `Item 4. Information on the Company` |
| `d_pdf` | `Annual report` · `Risk report` · `Drought could stop our plants.`, with `page_breaks` = `[0, 14]` (page 2 starts at `Risk report`) |
| `d_arid` | `Item 1A. Risk Factors` · `We sell aridity sensors.` · `Item 1B. Unresolved Staff Comments` |

"Ops include" = Operations `include`, Supply chain and Regulation `exclude`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-30 | — | `build_risk_theme("Water scarcity", ["water scarcity", "drought"])` | `kind` `risk`; `name` `Water scarcity`; `risk_terms` `["water scarcity", "drought"]`; activities in order with `activity_id` / `name` `risk_operations`/`Operations`, `risk_supply_chain`/`Supply chain`, `risk_regulation`/`Regulation`; each `seed_keywords` `["water scarcity", "drought"]`; each `in_scope_description` contains `Water scarcity` | holdout |
| AC-31 | — | `build_risk_theme(" Water scarcity ", [" drought ", "Drought", "", "water stress"], ["cooling water", "drought"])` | `name` `Water scarcity`; `risk_terms` `["drought", "water stress"]`; each `seed_keywords` `["drought", "water stress", "cooling water"]` | holdout |
| AC-32 | — | `build_risk_theme("  ", ["drought"])` / `build_risk_theme("Water", [" ", ""])` | `ValueError` with message `Provide a topic.` / `Provide at least one search term.` | holdout |
| AC-33 | `[d_sec]`, Ops include; MitigationQuotes = `[{"quotes": ["We recycle water at both plants."]}]` | `assess_risk(T, docs, matches, llm)` | `label` `exposed_disclosed`; `channels` `["Operations"]`; `mitigation` `stated`; `mitigation_quotes` `["We recycle water at both plants."]` | holdout |
| AC-34 | As AC-33 | Same | `disclosure` = `{"term": "drought", "quote": "Drought could stop production at two plants.", "doc_id": <d_sec's id>, "page": null, "where": "risk_section"}` | holdout |
| AC-35 | `[d_sec]`, Ops include; MitigationQuotes = `[{"quotes": ["We pray for rain."]}]` | Same | `mitigation` `none_stated`; `mitigation_quotes` `[]` | holdout |
| AC-36 | `[d_out]`, Operations and Supply chain `include`, Regulation `exclude` | Same | `label` `exposed_undisclosed`; `channels` `["Operations", "Supply chain"]`; `disclosure` null; `mitigation` null; 0 MitigationQuotes calls | holdout |
| AC-37 | `[d_nosec]`, Ops include | Same | `label` `exposed_disclosed`; `disclosure.term` `drought`, `quote` `Droughts hit our region in 2025.`, `where` `document` | holdout |
| AC-38 | `[d_sec]`, all three `exclude` | Same | `label` `not_exposed`; `disclosure.quote` `Drought could stop production at two plants.`; `mitigation` null; `calls.jsonl` has 0 lines (no model call of any kind) | holdout |
| AC-39 | `[d_sec]`, all three `uncertain` | Same | `label` `not_exposed`; `channels` `[]` | holdout |
| AC-40 | `[]` (no documents), all three `uncertain` | Same | `label` `not_assessed`; `channels` `[]`; `disclosure` null; `mitigation` null; 0 MitigationQuotes calls | holdout |
| AC-41 | `[d_toc]`, Ops include | Same | `label` `exposed_undisclosed`; `disclosure` null | holdout |
| AC-42 | `[d_20f]` (`doc_type` `other`), Ops include | Same | `disclosure.quote` `Drought could reduce our harvest.`; `where` `risk_section` | holdout |
| AC-43 | `[d_pdf]`, Ops include | Same | `disclosure.page` 2; `where` `risk_section` | holdout |
| AC-44 | `build_risk_theme("Drylands", ["arid"])`; `[d_arid]`, Ops include | Same | `label` `exposed_undisclosed`; `disclosure` null | holdout |
| AC-45 | `[d_out, d_nosec]`, Ops include | Same | `disclosure.doc_id` = d_nosec's id | holdout |
| AC-46 | `create_risk_theme_run("Water scarcity", ["water scarcity", "drought"], [x], settings, run_store)` with a temporary run store; `execute_theme_run` with a registry whose `fetch_all` returns `[d_sec]` for x; `AdjudicatorOutput` = one entry: include, 0.9, no citations, `exposure_estimate` `significant`; `AgentOpinion` one entry; MitigationQuotes `[{"quotes": []}]` | Run to completion | The run's one `results.jsonl` row has keys exactly `company_matches` and `risk`; `company_matches` has 3 entries; `risk.label` `exposed_disclosed`; `risk.channels` `["Operations", "Supply chain", "Regulation"]` | holdout |
| AC-47 | An activity theme (one activity, seed keyword `drought`), same registry and stand-ins | `create_theme_run` + `execute_theme_run` | The row has the single key `company_matches`; 0 MitigationQuotes calls | holdout |

API rows use the app (TestClient or the e2e stack). Companies are `[{"company_id": "x", "name": "X Co"}, {"company_id": "y", "name": "Y Co"}]`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-50 | — | `POST /api/themes/risk-runs` `{"topic": "Water scarcity", "search_terms": [" drought ", "Drought", "water stress"], "companies": <the two>}` | 200; body keys exactly `run_id`, `theme_id`, `company_count`; `company_count` 2 | holdout |
| AC-51 | After AC-50 | `GET /api/runs/<run_id>` | `run_type` `theme`; `params.mode` `risk`; `params.topic` `Water scarcity`; `params.search_terms` `["drought", "water stress"]`; `params.taxonomy_id` null | holdout |
| AC-52 | — | Same POST with `"topic": "  "` | 400; detail `Provide a topic.` | holdout |
| AC-53 | — | Same POST with `"search_terms": ["", " "]` | 400; detail `Provide at least one search term.` | holdout |
| AC-54 | — | Same POST without `companies` and `universe_path` | 400; detail ``Provide either `companies` or `universe_path`.`` | holdout |
| AC-55 | `run_r` in the app's run store: `run_type` `theme`, `params` `{"mode": "risk", "topic": "Water scarcity"}`, three results rows whose `risk` labels are `exposed_disclosed`, `not_exposed`, `exposed_disclosed` (companies a, b, c) | `GET /api/themes/runs/run_r/risk` | 200; body keys exactly `topic`, `counts`, `results`; `topic` `Water scarcity`; `counts` `{"exposed_disclosed": 2, "exposed_undisclosed": 0, "not_exposed": 1, "not_assessed": 0}`; `results` company ids `a`, `b`, `c` in that order | holdout |
| AC-56 | A `theme` run without `params.mode`; and an id that does not exist | `GET /api/themes/runs/<id>/risk` for each | 404 with detail `Not a risk run.` for both | holdout |

### Scorecard on risk sets (slice 3)

Fixtures. **Set R** is a directory `R/` with `cases.json` (`set_id` `fixture_risk`, `kind` `risk`, `labels`
`["exposed_disclosed", "exposed_undisclosed", "not_exposed"]`, valid per `arp golden-set exposure validate`) and
`R/taxonomies/tax_fixture_risk/` (`latest.json` → 1, `v1.json`): a risk theme with `risk_terms` `["water scarcity"]`
and T's three activities but `seed_keywords` Operations `["cooling water"]`, Supply chain `["supplier water"]`,
Regulation `["water permit"]`. Cases in this order, all `split: tune` unless a row says otherwise; each document is
`<docs>/<case>/annual_report/<case>.txt`, lines joined by `\n`:

| case | label | document lines | stand-in `AdjudicatorOutput` (call order p, q, t, u, v) |
|---|---|---|---|
| p | exposed_disclosed | `Item 1A. Risk Factors` · `Water scarcity could disrupt our plants.` · `We recycle water at every plant.` · `Item 1B. Unresolved Staff Comments` · `Our plants use cooling water.` | include, 0.90, citation quote `Our plants use cooling water.` (p's doc id) |
| q | exposed_undisclosed | `Item 1A. Risk Factors` · `Competition is intense.` · `Item 1B. Unresolved Staff Comments` · `Our plants use cooling water in dry regions.` · `Water scarcity is a global issue.` | include, 0.80, no citation |
| r | not_exposed | `Item 1A. Risk Factors` · `Water scarcity may affect cities where we operate.` · `Item 1B. Unresolved Staff Comments` · `We write software.` | (no call: no keyword hit) |
| s | exposed_undisclosed | nothing | (no call) |
| t | not_exposed | `We operate under a water permit.` | exclude, 0.85, no citation |
| u | exposed_disclosed | `Our supplier water use is high.` · `Water scarcity is a risk for us.` | include, 0.60, citation quote `Our supplier water use is high.` (u's doc id) |
| v | not_exposed | `Our plants use cooling water.` | include, 0.75, citation quote `This sentence is not in the file.` (v's doc id) |

Doc ids, `AgentOpinion` stand-in and the citation and `exposure_estimate` details as in `theme-precision-scorecard`'s
fixtures. `model/MitigationQuotes.json` = `[{"quotes": ["We recycle water at every plant."]}, {"quotes": ["We pray for rain."]}]`
(calls for p, then u). "Run R" = `arp golden-set theme --set R/ --documents-dir <docs> --split tune`;
`ARP_SCORECARDS_DIR` an empty temporary directory S. **Set RH** = set R with every `split` `holdout`.

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-60 | Set R | Run R | Exit code 0; the output contains, in this order, the 13 lines of the text block under "Slice 3" | holdout |
| AC-61 | Set R | Run R | Exactly 5 AdjudicatorOutput calls and 2 MitigationQuotes calls | holdout |
| AC-62 | Set R | Run R with `--out r.json` | `splits.tune` keys exactly as listed under "Slice 3", with `companies` 7, `labels` `{"exposed_disclosed": 2, "exposed_undisclosed": 2, "not_exposed": 3}`, `not_assessed` 1, `put_in` 4, `precision` 0.75, `recall_exposed_disclosed` 1.0, `recall_exposed_undisclosed` 0.5, `label_accuracy` 0.714, `quotes_found` 0.667 | holdout |
| AC-63 | Set R | Run R with `--out r.json` | `splits.tune.cases` lists `p`–`v` in order; `s` is `{"case_id":"s","label":"exposed_undisclosed","predicted":"not_assessed","assessed":false,"put_in":false,"confidence":null,"correct":null}`; `v` has `predicted` `exposed_undisclosed`, `put_in` true, `confidence` 0.75, `correct` false; `r` has `predicted` `not_exposed`, `confidence` null | holdout |
| AC-64 | Set R | Run R with `--out r.json` | `splits.tune.confidence` equals `[{"low":0.9,"high":1.0,"calls":1,"correct":1,"rate":1.0},{"low":0.7,"high":0.9,"calls":3,"correct":2,"rate":0.667},{"low":0.5,"high":0.7,"calls":1,"correct":1,"rate":1.0},{"low":0.0,"high":0.5,"calls":0,"correct":0,"rate":null}]` | holdout |
| AC-65 | Set RH | `arp golden-set theme --set RH/ --documents-dir <docs> --split holdout --min-precision 0.8` | Exit code 1; output contains `Holdout precision 0.750 is below 0.8.`; `S/tax_fixture_risk_v1.json` exists | holdout |
| AC-66 | Set RH | Same with `--min-recall-core 0.5` instead | Exit code 1; output contains `--min-recall-core needs an activity set.`; 0 AdjudicatorOutput calls | holdout |
| AC-67 | The repository, empty documents dir | `arp golden-set theme --set water_scarcity_exposed --documents-dir <empty> --split tune` | Exit code 0; output contains `companies: 33 (exposed_disclosed 13, exposed_undisclosed 9, not_exposed 11)`, `not assessed: 33`, `put in: 0`, `precision: n/a`, `label accuracy: 0.000` | holdout |
| AC-68 | The repository | Load `tax_water_scarcity_exposed` latest from `backend/tests/golden/exposure/water_scarcity_exposed/taxonomies` with `TaxonomyStore` | `kind` `risk`; `risk_terms` `["water scarcity", "water stress", "water shortage", "water availability", "water supply", "drought", "arid"]`; 3 activities `Operations`, `Supply chain`, `Regulation`, each with 16 seed keywords | holdout |
| AC-69 | Set R | Run R with `--taxonomies-dir backend/tests/golden/exposure/electrolyser_makers/taxonomies --taxonomy tax_electrolyser_makers` | Exit code 1; output contains `Taxonomy tax_electrolyser_makers is not a risk theme.`; 0 AdjudicatorOutput calls | holdout |
| AC-70 | The repository, empty documents dir | `arp golden-set theme --set electrolyser_makers --documents-dir <empty> --split tune --taxonomies-dir backend/tests/golden/exposure/water_scarcity_exposed/taxonomies --taxonomy tax_water_scarcity_exposed` | Exit code 1; output contains `Taxonomy tax_water_scarcity_exposed is a risk theme; this set needs an activity theme.` | holdout |

### Risk exposure region (slice 4)

UI rows run `#/theme/run_k` with Playwright routes: `**/api/runs/run_k` returns a completed `theme` run manifest with
`params` `{"mode": "risk", "topic": "Water scarcity"}`, `**/api/themes/runs/run_k/results*` 3 include matches,
`**/api/themes/runs/run_k/layers*` an empty layers result, `**/api/themes/runs/run_k/quality` 404, and
`**/api/themes/runs/run_k/risk` the response **K** unless a row says otherwise: `topic` `Water scarcity`, `counts`
`{"exposed_disclosed": 2, "exposed_undisclosed": 1, "not_exposed": 1, "not_assessed": 0}`, `results` in order:

| company_id / name | label | channels | disclosure | mitigation, quotes |
|---|---|---|---|---|
| `ha` / `Halden Beverages` | exposed_disclosed | `["Operations"]` | term `drought`, quote `Drought could stop production at two plants.`, `where` `risk_section`, `page` 12 | stated, `["We recycle water at both plants."]` |
| `os` / `Ostra Gases` | exposed_undisclosed | `["Operations", "Supply chain"]` | null | null, `[]` |
| `me` / `Meridian Membranes` | exposed_disclosed | `["Supply chain"]` | term `water scarcity`, quote `Water scarcity is a risk for us.`, `where` `document`, `page` null | none_stated, `[]` |
| `li` / `Lindqvist Power` | not_exposed | `[]` | null | null, `[]` |

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-80 | K | Page loaded | Region `Risk exposure` has chips reading exactly `Disclosed 2`, `Not disclosed 1`, `Not exposed 1`, in that order, and no `Not assessed` chip; it contains `“Not disclosed” means the company does not name the risk, but its documents show it is exposed.` | holdout |
| AC-81 | K | Page loaded | The region's table header reads `Company`, `Exposure`, `Channels`, `Mitigation`; its rows read `Halden Beverages` · `Disclosed` · `Operations` · `stated`, then `Ostra Gases` · `Not disclosed` · `Operations, Supply chain` · `–`, then `Meridian Membranes` · `Disclosed` · `Supply chain` · `none`, then `Lindqvist Power` · `Not exposed` · `–` · `–` | holdout |
| AC-82 | K | User presses `Not disclosed 1` | The table shows only `Ostra Gases`; that chip has `aria-pressed="true"` | holdout |
| AC-83 | K | User presses `Not disclosed 1` twice | The table shows all four companies | holdout |
| AC-84 | K | User expands `Halden Beverages` | The detail contains `Named as a risk: “Drought could stop production at two plants.”`, `Found in: risk section, page 12` and `Stated mitigation: “We recycle water at both plants.”` | holdout |
| AC-85 | K | User expands `Meridian Membranes` | The detail contains `Found in: document text` and no text `page` | holdout |
| AC-86 | K | User expands `Ostra Gases` | The detail contains `Not named as a risk in the documents checked.` | holdout |
| AC-87 | The risk route returns 500 | Page loaded | Region `Risk exposure` contains `Risk results could not be loaded.`; the results table still shows its 3 matches | holdout |
| AC-88 | The manifest's `params` has no `mode` | Page loaded | No region `Risk exposure`; no request to `**/risk` was made | holdout |

### Must not change

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-90 | The hidden tests of `theme-precision-scorecard` rows AC-1 to AC-13b, AC-15 to AC-17 and AC-19 (activity sets) | Run them on this branch | All pass unchanged | holdout |
| AC-91 | The existing backend and frontend test suites on `main` | Run on this branch, excluding files added by this change | Same pass/fail result per test as on `main` | unit |
| AC-92 | A stored `ThemeDefinition` JSON without `kind` or `risk_terms` | `ThemeDefinition.model_validate_json` | Loads with `kind` `activity` and `risk_terms` `[]` | holdout |

## Slices

Four PRs, each `risk:normal` with `Spec: theme-risk-mode` and its `Rows:` line. Order: 1, then 2, then 3 and 4 (either
order, both after 2). Slice 3 also needs `theme-precision-scorecard` slice 1 merged (it extends that runner); its
builder merges `origin/main` first. Slice 2 touches `schemas/thematic.py` and `pipeline.py`, which
`matcher-shared-retrieval` and `theme-precision-scorecard` slice 2 also change: whichever merges later merges
`origin/main` first.

| Slice | Size | PR contents | Rows |
|---|---|---|---|
| 1 | M | `backend/arp/risk_view/` (section finder, HTML/PDF headings, mitigations, NLI theme, year-on-year, CLI `run`/`batch`/`golden`), data files, CLI registration, tests. AC-19 is owed until the labels PR (A7) | AC-1 to AC-18 (with AC-17b), AC-91 |
| 2 | M | `kind`/`risk_terms` on `ThemeDefinition`, `RiskDisclosure`/`RiskAssessment`, `arp/research/risk_mode.py`, hook in `_match_company` and the run row, `POST /api/themes/risk-runs`, `GET /api/themes/runs/{run_id}/risk`, OpenAPI + generated types + contract line, tests | AC-30 to AC-56, AC-91, AC-92 |
| 3 | S | Risk sets in `arp golden-set theme` (scoring, text, JSON, gate messages), water-scarcity risk taxonomy, tests | AC-60 to AC-70, AC-90, AC-91 |
| 4 | S | Risk exposure region in `ThemeBuilder.tsx`, tests. Needs `UI review (factory)` | AC-80 to AC-88, AC-91 |
