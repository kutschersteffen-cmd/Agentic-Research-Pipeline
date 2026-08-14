# Transition Barrier Assessment — Automation Pipeline

## What this project is

Automates retrieval and verification of a 105-cell transition-feasibility
assessment (35 criteria × 3 regions: European Union / United States / China)
currently populated by manual research. The assessment scores how feasible
decarbonisation is for 9 hard-to-abate sectors, across three constraint
categories per sector: Technology, Regulation, Demand & Economics.

The manual baseline is done and verified. This project is about closing the
loop so the baseline stays current without a human re-running the same
research every quarter.

## Data files — read these first, in this order

1. **`data/criteria_schema.json`** — the 35 criteria. Each criterion has a
   `code` (e.g. `PWR-R1`), a `metric` (what to measure), a `rating_rubric`
   (H/M/L thresholds), and a `primary_sources[]` array. **This is the join
   table** — each entry in `primary_sources[]` is where a specific fact for
   that criterion should be checked, and carries (where populated):
   - `url` — the actual page to fetch
   - `locator` — human-written instructions on *where inside that page/report*
     the number lives (e.g. "sub-page /hydrogen-production", "Annex I for
     sectoral scope")
   - `access_pattern` — one of `structured_api_or_dashboard`,
     `legal_regulatory_text`, `periodic_pdf_report`,
     `government_agency_publication`, `industry_tracker_database`,
     `company_disclosure`
   - `refresh_cadence` — how often the *source* changes, not how often to check it
   - Older entries also carry `url_pattern` / `data_field` (pre-verification
     placeholders) — prefer `url`/`locator` when both exist.

2. **`data/assessment_scores.json`** — the current 105 ratings. Each record
   has `sector` + `criterion` + `region` (matches back to criteria_schema.json
   via `code`), plus `rating` (H/M/L), `confidence` (high/medium/low),
   `evidence` (the sentence justifying the rating), and `source` (free-text
   citation — not yet linked to a specific `primary_sources[]` URL).
   `assessment_scores.json.source_verification` records what's been verified
   and when.

3. **`data/source_registry.json`** — 86 distinct sources deduplicated across
   the schema, keyed by an internal name (e.g. `EU_CBAM_Regulation`,
   `IEA_Global_Hydrogen_Review`). This is the same `url`/`locator`/
   `access_pattern` data as in criteria_schema.json's `primary_sources[]`,
   but flattened for reference. Treat criteria_schema.json as authoritative
   if the two ever disagree — this file is a derived view.

4. **`docs/`** — human-readable versions (the Excel workbook is the working
   research tool this pipeline is meant to eventually update automatically;
   the two Word docs explain the criteria rationale and the intended pipeline
   architecture in prose). Read `docs/Automation_Pipeline_Design.docx` before
   writing pipeline code — it defines the five-stage architecture (Source
   Router → Retriever → Extractor → Rater → Reconciler) and the confidence/
   staleness/conflict-handling rules this code should follow. If code and
   that doc disagree, treat the doc as design intent and flag the conflict —
   don't silently pick one.

## The honest state of source machine-readability — do not assume more than this

Only **7 of 86** sources are `access_pattern: structured_api_or_dashboard`,
and even those are mostly *dashboard front-ends*, not documented REST APIs:

- `EU_ETS_Price` (EEX) — dashboard, no public API found during verification
- `World_Bank_Carbon_Pricing_Dashboard` — interactive dashboard; check for a
  CSV export or underlying API before assuming one exists
- `China_National_ETS_Price` (cneeex.com) — dashboard, Chinese-language
- `USGS_Mineral_Commodity_Summaries` — has a real DOI per year
  (`10.3133/mcs2025`) and structured data releases at data.usgs.gov — this
  one genuinely has machine-readable exports, verify the current year's DOI
- `US_DOE_AFDC` — has a documented API (afdc.energy.gov has a public API for
  station location data)
- `NGFS_Scenario_Explorer` — genuinely downloadable as CSV/XLSX via IIASA,
  confirmed during verification
- `LSE_Grantham_CCLW` (climate-laws.org) — full-text search, not an API in
  the traditional sense, but reliably queryable

**Do not build a script that assumes `requests.get(url).json()` works for
all 7.** Check each one's actual export/API mechanism before writing the
Retriever for it. This is deliberately the *first* task below.

EU legal sources (`legal_regulatory_text`, ~15 sources) are the strongest
near-term automation target even though they're not tagged
`structured_api_or_dashboard`: EUR-Lex uses stable ELI URIs
(`eli/reg/2023/956/oj`) that don't break when a regulation is amended, and
EUR-Lex exposes a SPARQL/CELLAR web service
(https://eur-lex.europa.eu/content/help/webservices.html) for programmatic
querying. This is close to zero-LLM automation once the query pattern is
built.

## Build order (matches `docs/Automation_Pipeline_Design.docx` Section 8, refined)

1. **Verify and document the actual access mechanism for the 7
   `structured_api_or_dashboard` sources.** Some will turn out to need an
   LLM-assisted dashboard read rather than a clean API call — find out which,
   before building anything else.
2. **EUR-Lex ELI/CELLAR sources** — build the fetch + diff logic here next;
   highest confidence, least ambiguity, ~15 sources covered.
3. **`periodic_pdf_report` sources** (IEA, IRENA, BloombergNEF, ETC, IPCC) —
   this is where an LLM extraction step is actually justified. Use the
   `locator` field as the extraction instruction (e.g. "find the sub-page
   /hydrogen-production, extract the figure for [metric]") rather than asking
   a model to read an entire report cold.
4. **`government_agency_publication`** sources — weakest single-source
   reliability, especially non-English ones. Route China sources through
   `LSE_Grantham_CCLW` as a secondary check where `fallback_url` is present
   in the schema.
5. **`company_disclosure`** sources — do not attempt auto-extraction. Build
   discovery/triage only (detect a new filing exists, surface it to a human).
   This is intentional, not a shortcut — see the design doc Section 5.6 for
   why.

## Non-negotiable rules from the design doc

- **Never auto-commit a rating change that moves H/M/L.** Queue it for human
  review. Auto-updating the `evidence` text or `Last Verified` date when the
  rating is unchanged is fine.
- **Every extracted value needs a confidence tier and an exact source quote**
  before it's written anywhere — no bare numbers.
- **Staleness and confidence are tracked separately.** A high-confidence
  rating that hasn't been re-checked in 18 months is stale, not low-confidence
  — don't conflate the two fields.
- **When a primary source and a fallback source disagree, surface both.**
  Never silently pick one (see design doc Section 6.3).
- Two rating changes already happened this way during manual verification —
  `MIN-R2` (US) and `OGU-R1` (US) both moved because US federal policy
  reversed in 2025 (One Big Beautiful Bill Act; Congressional Review Act
  repeal of the EPA methane fee). Neither would have been caught by
  re-reading the original source page — both were caught by searching news
  coverage of the policy itself. **Build a policy-change search step, not
  just a source-re-fetch step**, for every `legal_regulatory_text` and
  `government_agency_publication` source.

## What "done" looks like for a first slice

Not "the pipeline." A script that, for one `access_pattern` category, fetches
current data for every source in that category, diffs it against
`assessment_scores.json`, and prints what changed — without writing anything
back automatically. Start there.
