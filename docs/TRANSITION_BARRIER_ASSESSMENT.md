# Transition Barrier Assessment

A structured, sourced answer to a question that sits upstream of every company-level
climate judgement: **how feasible is decarbonisation in this sector, in this region, at all?**

The assessment scores 9 hard-to-abate sectors against 35 criteria, each rated for the
European Union, the United States and China — a 105-cell matrix. Each cell carries an
H/M/L rating, a confidence tier, the evidence it rests on, the sources behind it, and the
date it was last verified.

**Where it lives.** `backend/arp/transition_barrier/` · `arp transition-barrier ...` ·
`GET /api/transition-barrier/...` · the "Transition Barrier Assessment" tab under
Portfolio Analysis.

## Read the rating the right way

**H means transition is *more* feasible — fewer barriers — not that the barrier is high.**
This is the single most common way to misread the matrix. A sector-region cell rated `L`
is one where decarbonisation is hard: the technology is not ready, the regulation is
absent, or the economics do not close.

| Rating | Meaning |
| --- | --- |
| `H` | High feasibility — the enabling condition is in place |
| `M` | Moderate — partially in place, or in place with material caveats |
| `L` | Low feasibility — the enabling condition is largely absent |

Confidence (`high` / `medium` / `low`) is a separate axis: it records how sure the analyst
was about the rating, given the evidence available. It is **not** a measure of how recently
the cell was checked — see [Staleness](#staleness-is-not-confidence).

## How it relates to the Transition Plan Assessment

The two modules answer complementary questions and are deliberately kept separate:

| | Transition **Plan** Assessment | Transition **Barrier** Assessment |
| --- | --- | --- |
| Unit of analysis | One company | One sector × region |
| Question | Is this company credible about transitioning? | Is transition feasible here at all? |
| Method | 64-indicator grounded RAG over company disclosures | Curated research matrix, verified against primary sources |
| Output | Walk/talk verdicts per indicator | H/M/L feasibility per criterion per region |
| Source | Colesanti Senni et al. (2024) | In-house research, Aug 2026 |

Read together, they separate *ambition* from *headroom*: a company rated poorly on its
transition plan in a sector where barriers are rated `L` is a different investment case
from the same rating in a sector rated `H`.

## Structure

Every sector is assessed across three constraint pillars, so the matrix is MECE by
construction:

| Pillar | Criteria | What it asks |
| --- | --- | --- |
| Technology | 13 | Does the technology exist at the cost and scale required? |
| Regulation | 13 | Does policy require or reward the transition? |
| Demand & Economics | 9 | Will anyone pay the premium? |

Sector coverage: Power & Utilities (5), Steel (5), Cement (5), Chemicals (4),
Critical Minerals & Mining (4), Aviation (3), Shipping (3), Heavy-Duty Road Transport (3),
Oil & Gas Upstream (3).

## What the matrix currently says

Across all 105 cells: **24 H · 49 M · 32 L**. By region:

| Region | H | M | L | Reading |
| --- | ---: | ---: | ---: | --- |
| European Union | 16 | 16 | 3 | Regulation is largely in place; the binding constraints are technological and economic |
| United States | 3 | 22 | 10 | Mostly moderate, and materially weaker on regulation after the 2025 federal reversals |
| China | 5 | 11 | 19 | Strong on deployment and manufacturing scale, weak on binding carbon pricing and mandates |

Confidence across the matrix: 32 high, 52 medium, 21 low.

## Why this needs automated re-verification

Two US cells moved during the August 2026 verification pass, and **neither would have been
caught by re-fetching the same government page** — both required searching for news of the
policy change itself:

- **`MIN-R2` (United States), downgraded to `M`.** The Section 30D critical-minerals
  sourcing requirement lost its financial mechanism when the New Clean Vehicle Credit
  terminated for vehicles acquired after 30 September 2025 under the One Big Beautiful Bill
  Act (P.L. 119-21). Residual effect persists through Section 45X, which is why this is a
  downgrade to Moderate rather than Low.
- **`OGU-R1` (United States), downgraded to `L`.** The EPA's Waste Emissions Charge
  implementing rule was nullified by a Congressional Review Act joint resolution
  (H.J.Res.35, P.L. 119-2) signed 14 March 2025. The statutory fee remains on the books but
  EPA is barred from collecting it until 2034.

This is the argument for a **policy-change search step**, not merely a source re-fetch step,
for every `legal_regulatory_text` and `government_agency_publication` source.

## Operating rules

These are non-negotiable and are enforced in code, not just documented:

1. **Never auto-commit a rating change.** A refresh may propose an H/M/L move; only a human
   may accept it. Enforced by `is_auto_applicable()` in
   `backend/arp/transition_barrier/refresh/reconciler.py` and covered by
   `tests/test_transition_barrier_refresh_pipeline.py`, which asserts the bundled data file
   is byte-identical after a run that proposed a change for every cell it touched.
   Updating evidence text or the last-verified date on an *unchanged* rating is fine.
2. **Every extracted value needs a confidence tier and an exact source quote** before it is
   written anywhere. No bare numbers.
3. **Staleness and confidence are tracked separately.** See below.
4. **When sources disagree, surface both.** Never silently pick one — a conflict becomes a
   review item carrying both versions and no proposed rating.

### Staleness is not confidence

A high-confidence rating that has not been re-checked in 18 months is **stale**, not
low-confidence. Collapsing the two would hide exactly the case this module exists to catch:
`OGU-R1` was high-confidence and correct when it was set, and wrong eight months later.

The threshold is `ARP_TRANSITION_BARRIER_STALENESS_DAYS`, default 548 days. Every bundled
cell was verified on 2026-08-14, so the matrix tips into stale on **2028-02-13**.

## The refresh pipeline

The design is a five-stage flow — Source Router → Retriever → Extractor → Rater →
Reconciler. **What is built today is the first slice: EUR-Lex legal sources only.**

`GET /api/transition-barrier/refresh/coverage` reports this honestly: **15 of 86 sources**
are automatable, 71 still require manual verification. The router returns a reason for every
source it cannot handle rather than silently skipping it.

EUR-Lex was chosen first because it is the only category with genuinely stable identifiers:
ELI URIs (`eli/reg/2023/956/oj`) survive amendment, so "has this act changed?" is answerable
without scraping prose. CELEX links (`CELEX:32023R1805`) are parsed onto the same reference,
which is what brings FuelEU Maritime into scope.

The pipeline is gated behind `ARP_TRANSITION_BARRIER_REFRESH_ENABLED` (default `false`)
because it makes live outbound requests; the matrix itself is always queryable. Outbound
fetches route through the shared SSRF guard in `backend/arp/net_safety.py`.

Findings are classified as `unchanged`, `evidence_drift`, `rating_change_candidate`,
`not_automated` or `fetch_failed`. Only the first two are auto-applicable, and even then
only for evidence text and the verification date.

### Why the other five categories are not automated yet

Not an oversight — most of them genuinely resist it:

- **`structured_api_or_dashboard` (6).** Despite the name, most are dashboard front-ends,
  not documented REST APIs. `backend/scripts/investigate_structured_sources.py` probes each
  one and reports what automated retrieval would actually mean. Run it before writing any
  retriever for them.
- **`periodic_pdf_report` (27).** Annual PDFs where the `locator` field is the extraction
  instruction — the natural place for an LLM extraction step, once the EUR-Lex loop is proven.
- **`government_agency_publication` (21).** The weakest single-source reliability, especially
  for non-English sources.
- **`industry_tracker_database` (10).** Mostly subscription or session-gated.
- **`company_disclosure` (7).** Deliberately **never** auto-extracted — discovery and triage
  only, surfacing new filings to a human. These are the 7 sources with no fixed URL, because
  which company matters depends on who is being assessed.

## Usage

```bash
arp transition-barrier criteria --sector Steel
arp transition-barrier scores --region China --pillar Regulation
arp transition-barrier sources --code OGU-R1
arp transition-barrier staleness
arp transition-barrier coverage          # what the refresh pipeline can and cannot do
arp transition-barrier refresh           # needs ARP_TRANSITION_BARRIER_REFRESH_ENABLED=true
```

## The Word report

A formatted, shareable version of this document — the same criteria and source
tables, rendered landscape with the H/M/L rubrics colour-coded — lives at
[`docs/transition_barrier/Transition_Barrier_Assessment_Report.docx`](transition_barrier/Transition_Barrier_Assessment_Report.docx).

It is generated from the same JSON, so it cannot drift from the data:

```bash
npm install docx adm-zip
node scripts/build_transition_barrier_report.js docs/transition_barrier/Transition_Barrier_Assessment_Report.docx
```

Regenerate it whenever the bundled data changes.

## Provenance and known data issues

The three JSON files under `backend/arp/transition_barrier/data/` are derived from the
working research tool kept in `docs/transition_barrier/` (the `.xlsx` is the original;
`Automation_Pipeline_Design.docx` is the architecture this module implements). The JSON is
authoritative; `criteria_schema.json` in turn wins over `source_registry.json`, which is a
derived view.

Recorded rather than silently patched:

- **Two source URLs look copy-pasted from a neighbouring entry** and have been left as-is
  rather than guessed at: `US_SAF_Grand_Challenge_IRA_40B_tax_credit` points at
  `sustainability.gov/buyclean` (the Buy Clean entry's URL), and `IEA_CCUS_Projects_Database`
  points at `co2re.co` (the Global CCS Institute's URL). Both need a human to re-source.
- **95 criterion-source links dedupe to 86 registry entries.** The registry keeps
  per-criterion duplicates for company disclosures rather than sharing one key.
- **Source count corrected from 7 to 6** for `structured_api_or_dashboard`. The original
  notes claimed 7 and named an `LSE_Grantham_CCLW` entry that does not exist in the registry;
  the corresponding dead entry has been removed from the investigation script.
- **Criterion codes normalised to hyphens.** Shipping originally used underscores
  (`SHP_T1`); all 35 now match `^[A-Z]{3}-[TRD]\d+$`, pinned by a Pydantic pattern and a test.
- **7 of 95 source entries carry no URL.** These are the `company_disclosure` entries, which
  correctly record a retrieval methodology instead.

---
### The 35 criteria


#### Power & Utilities (5 criteria)

| Code | Pillar | Criterion | Metric | Unit |
| --- | --- | --- | --- | --- |
| `PWR-T1` | Technology | Levelised cost of renewable generation vs. new-build fossil | LCOE of utility-scale solar PV and onshore wind (USD/MWh) vs. LCOE of new-build CCGT/coal in the same region | USD/MWh, ratio |
| `PWR-T2` | Technology | Grid-scale storage / firming technology readiness | Deployed grid-scale battery storage capacity (GWh) relative to variable renewable capacity (GW) in the region; TRL of long-duration storage | GWh storage per GW variable renewables |
| `PWR-R1` | Regulation | Effective carbon price on power generation | Carbon price applicable to power sector emissions (ETS price, carbon tax, or implicit price via clean energy mandate penalty) | USD/tCO2 |
| `PWR-R2` | Regulation | Renewable deployment target and permitting regime | Legally binding renewable capacity target (GW or % of generation) by target year; average grid connection queue time (years) | GW target, years to connect |
| `PWR-D1` | Demand & Economics | Corporate and utility PPA market depth | Annual volume of signed corporate/utility power purchase agreements (GW) for renewable generation in the region | GW/year signed |

<details><summary>Rating rubrics for Power & Utilities</summary>

| Code | H (more feasible) | M | L (less feasible) |
| --- | --- | --- | --- |
| `PWR-T1` | Renewable LCOE at or below new-build fossil LCOE without subsidy | Renewable LCOE within 10-30% of new-build fossil LCOE, or below only with subsidy | Renewable LCOE more than 30% above new-build fossil LCOE |
| `PWR-T2` | Storage-to-renewables ratio and grid flexibility sufficient to avoid material curtailment (region-specific benchmark, informed by IEA grid integration studies) | Storage deployment underway but curtailment or grid congestion already material | Storage capacity negligible relative to variable renewable penetration |
| `PWR-R1` | Effective carbon price exceeds USD 60/tCO2 or binding 100% clean generation mandate with penalty | Effective carbon price USD 15-60/tCO2, or clean generation target without binding penalty | No material carbon price or clean generation mandate |
| `PWR-R2` | Legally binding target with permitting reform reducing connection queue below 3 years | Target exists (binding or aspirational) but connection queue exceeds 3 years | No binding target, or connection queue exceeds 7 years |
| `PWR-D1` | PPA market established and growing; multi-year forward contracting standard practice | PPA market exists but thin or concentrated in few counterparties | PPA market negligible; renewable generation sold predominantly on spot/merchant basis |

</details>

#### Steel (5 criteria)

| Code | Pillar | Criterion | Metric | Unit |
| --- | --- | --- | --- | --- |
| `STL-T1` | Technology | Green hydrogen cost vs. DRI-H2 breakeven | Delivered cost of green hydrogen (USD/kg) at production site, vs. estimated breakeven cost for DRI-H2 route to be cost-competitive with BF-BOF at prevailing carbon price | USD/kg H2 |
| `STL-T2` | Technology | Scrap steel availability (EAF route feasibility) | Domestic scrap steel collection and availability as % of crude steel production capacity | % of production |
| `STL-R1` | Regulation | Effective carbon price on steel production incl. border adjustment | ETS/carbon tax price applicable to steel production, adjusted for free allocation phase-out and any import border levy (e.g. CBAM) | USD/tCO2 net of free allocation |
| `STL-R2` | Regulation | Green/low-carbon steel public procurement or building-code mandate | Existence and scope of government mandate requiring low-carbon steel in public infrastructure procurement or building codes | Binary/scope descriptor |
| `STL-D1` | Demand & Economics | Green steel price premium and recoverability | Market premium for certified low-carbon steel (USD/tonne) vs. conventional, and share of premium covered by signed offtake contracts | USD/tonne premium; % under contract |

<details><summary>Rating rubrics for Steel</summary>

| Code | H (more feasible) | M | L (less feasible) |
| --- | --- | --- | --- |
| `STL-T1` | Green hydrogen cost at or below breakeven (typically cited ~USD 1.5-2.0/kg range, region-specific) | Green hydrogen cost within 2x of breakeven | Green hydrogen cost more than 2x breakeven, or no green hydrogen supply chain present |
| `STL-T2` | Scrap availability exceeds 50% of production capacity, supporting EAF as viable low-carbon route without new technology | Scrap availability 25-50% of production capacity | Scrap availability below 25% of production capacity |
| `STL-R1` | Effective carbon price (net of free allocation) exceeds USD 50/tCO2 with border levy protecting domestic producers from unpriced imports | Carbon price applies but free allocation still material, or no border levy protecting against unpriced competition | No material carbon price on steel production |
| `STL-R2` | Binding mandate in force covering material share of public procurement or construction | Voluntary standard or pilot mandate exists | No mandate or standard exists |
| `STL-D1` | Documented offtake contracts (e.g. automotive OEM commitments) cover a material share of announced low-carbon capacity at a disclosed premium | Premium exists and some pilot offtake agreements signed, but limited volume | No documented premium recovery mechanism; no material offtake contracts identified |

</details>

#### Cement (5 criteria)

| Code | Pillar | Criterion | Metric | Unit |
| --- | --- | --- | --- | --- |
| `CEM-T1` | Technology | CCS capture technology deployment status | Number and capacity (Mtpa CO2) of operational or under-construction full-scale cement CCS facilities in the region | Mtpa capacity, facility count |
| `CEM-T2` | Technology | Clinker substitution rate (SCM availability) | Average clinker-to-cement ratio in the region; availability of supplementary cementitious materials (fly ash, slag, calcined clay) | Clinker ratio (%) |
| `CEM-R1` | Regulation | Effective carbon price on cement production incl. border adjustment | ETS/carbon tax price applicable to cement, net of free allocation, adjusted for any import border levy | USD/tCO2 net of free allocation |
| `CEM-R2` | Regulation | CCS infrastructure support scheme | Existence of public funding mechanism for CCS infrastructure (capture, transport, storage) applicable to cement plants | Binary/scope, EUR or USD committed |
| `CEM-D1` | Demand & Economics | Low-carbon cement premium recoverability | Market premium for low-carbon/CCS-derived cement (USD/tonne) vs. conventional; share recoverable via green public procurement | USD/tonne premium; % public procurement covered |

<details><summary>Rating rubrics for Cement</summary>

| Code | H (more feasible) | M | L (less feasible) |
| --- | --- | --- | --- |
| `CEM-T1` | At least one full-scale (>0.3 Mtpa) operational facility in the region with a track record | Facility under construction or in final investment decision (FID) stage | No full-scale facility operational, under construction, or FID-approved in the region |
| `CEM-T2` | Regional clinker ratio below 0.65 with active SCM substitution programmes | Clinker ratio 0.65-0.80 | Clinker ratio above 0.80 with limited SCM availability |
| `CEM-R1` | Effective net carbon price exceeds USD 50/tCO2 with border levy in force | Carbon price applies but free allocation still material or no border levy | No material carbon price on cement production |
| `CEM-R2` | Dedicated public funding scheme active with disbursed grants to cement CCS projects | Funding scheme exists but no disbursement to cement sector yet, or funding limited/competitive | No public funding mechanism identified for industrial CCS |
| `CEM-D1` | Green public procurement rules or embodied-carbon building codes create binding demand covering a material share of low-carbon capacity | Voluntary standards or pilot procurement commitments exist | No recoverable premium mechanism identified |

</details>

#### Chemicals (4 criteria)

| Code | Pillar | Criterion | Metric | Unit |
| --- | --- | --- | --- | --- |
| `CHM-T1` | Technology | Green/blue hydrogen availability for ammonia and feedstock use | Delivered cost of low-carbon hydrogen (USD/kg) vs. grey hydrogen cost at prevailing natural gas price | USD/kg H2, cost ratio |
| `CHM-T2` | Technology | Electrification of process heat (steam cracking) readiness | TRL of electric steam cracker technology; number of announced/piloted electric cracker projects | TRL, project count |
| `CHM-R1` | Regulation | Effective carbon price on chemicals production incl. border adjustment | ETS/carbon tax price applicable to chemicals production, net of free allocation, adjusted for any border levy where scope includes chemicals | USD/tCO2 net of free allocation |
| `CHM-D1` | Demand & Economics | Green ammonia/methanol offtake market | Volume (tonnes/year) of signed offtake agreements for green ammonia or green methanol, primarily driven by shipping fuel demand | Tonnes/year signed offtake |

<details><summary>Rating rubrics for Chemicals</summary>

| Code | H (more feasible) | M | L (less feasible) |
| --- | --- | --- | --- |
| `CHM-T1` | Low-carbon hydrogen cost within 20% of grey hydrogen cost, or carbon price closes the gap | Low-carbon hydrogen cost 20-100% above grey hydrogen cost | Low-carbon hydrogen more than 2x grey hydrogen cost, or no low-carbon hydrogen supply chain present |
| `CHM-T2` | TRL 7+ with commercial-scale pilot operating or announced FID | TRL 5-6, demonstration scale only | TRL below 5, lab/concept stage only |
| `CHM-R1` | Effective net carbon price exceeds USD 50/tCO2 with border levy protection in force | Carbon price applies but free allocation material or no border levy | No material carbon price on chemicals production |
| `CHM-D1` | Material signed offtake volume from shipping or industrial buyers at disclosed premium | Pilot-scale offtake agreements signed, limited volume | No material offtake agreements identified |

</details>

#### Critical Minerals & Mining (4 criteria)

| Code | Pillar | Criterion | Metric | Unit |
| --- | --- | --- | --- | --- |
| `MIN-T1` | Technology | Mine electrification and processing technology readiness | Share of new mining equipment orders that are battery-electric; TRL of electrified ore processing | % of equipment orders |
| `MIN-R1` | Regulation | Fast-track permitting regime for strategic minerals projects | Statutory maximum permitting timeline (months) for a designated strategic minerals project | Months |
| `MIN-R2` | Regulation | Domestic sourcing / content requirement policy | Existence and threshold of domestic or allied-sourcing content requirements tied to subsidy eligibility or public procurement | Binary, % threshold |
| `MIN-D1` | Demand & Economics | Committed offtake and supply agreements vs. identified demand gap | Volume of long-term offtake agreements signed (tonnes/year) as a share of the region's projected NZE-scenario demand gap for the mineral | % of demand gap covered |

<details><summary>Rating rubrics for Critical Minerals & Mining</summary>

| Code | H (more feasible) | M | L (less feasible) |
| --- | --- | --- | --- |
| `MIN-T1` | Battery-electric equipment commercially deployed at scale (multiple operating mines) | Pilot deployments underway, limited scale | Battery-electric equipment not yet deployed at operating mines in the region |
| `MIN-R1` | Statutory fast-track permitting in force with maximum timeline below 30 months | Fast-track process exists but timeline exceeds 30 months or is discretionary | No fast-track permitting regime; standard permitting exceeds 5 years |
| `MIN-R2` | Binding domestic/allied content requirement in force tied to material subsidy value | Requirement exists but threshold low or enforcement unclear | No domestic content requirement policy identified |
| `MIN-D1` | Signed offtake agreements and committed expansion capacity cover a material share of the identified regional supply gap | Some offtake agreements signed but gap remains largely uncovered | Minimal offtake activity relative to the scale of the demand gap |

</details>

#### Aviation (3 criteria)

| Code | Pillar | Criterion | Metric | Unit |
| --- | --- | --- | --- | --- |
| `AVI-T1` | Technology | SAF production capacity vs. jet fuel demand | Regional SAF production capacity (million litres/year) as a share of total regional jet fuel demand | % of jet fuel demand |
| `AVI-R1` | Regulation | SAF blending mandate | Legally binding minimum SAF blending percentage by target year | % mandate by year |
| `AVI-D1` | Demand & Economics | SAF price premium and corporate offtake coverage | SAF price premium vs. conventional jet fuel (USD/litre or multiple); volume covered by corporate/airline offtake agreements | Price multiple; % covered by offtake |

<details><summary>Rating rubrics for Aviation</summary>

| Code | H (more feasible) | M | L (less feasible) |
| --- | --- | --- | --- |
| `AVI-T1` | SAF capacity exceeds 5% of regional jet fuel demand with credible near-term expansion pipeline | SAF capacity between 1-5% of demand | SAF capacity below 1% of regional jet fuel demand |
| `AVI-R1` | Binding blending mandate in force with escalating schedule and penalties for non-compliance | Mandate announced but not yet in force, or voluntary target only | No blending mandate or target identified |
| `AVI-D1` | Premium substantially offset by mandate compliance value or tax credit, with material offtake agreements in place | Premium partially offset; limited offtake agreements | Full premium borne by airline/passenger with no offset mechanism or offtake coverage |

</details>

#### Shipping (3 criteria)

| Code | Pillar | Criterion | Metric | Unit |
| --- | --- | --- | --- | --- |
| `SHP-T1` | Technology | Dual-fuel/alternative-fuel vessel order book | Share of new vessel orders (by gross tonnage or vessel count) specified as methanol, ammonia, or LNG dual-fuel capable | % of new orders |
| `SHP-R1` | Regulation | Effective carbon price / fuel intensity mandate on shipping | Carbon price applicable to shipping emissions (e.g. EU ETS maritime inclusion) and/or binding fuel greenhouse gas intensity reduction mandate | USD/tCO2; % intensity reduction mandate |
| `SHP-D1` | Demand & Economics | Green shipping corridor and cargo owner offtake commitments | Number of announced green shipping corridors; volume of freight committed by cargo owners (via Cargo Owners for Zero Emission Vessels or equivalent) to low-carbon shipping | Corridor count; committed freight volume |

<details><summary>Rating rubrics for Shipping</summary>

| Code | H (more feasible) | M | L (less feasible) |
| --- | --- | --- | --- |
| `SHP-T1` | Alternative-fuel-capable vessels exceed 30% of new orders in the relevant vessel class | Alternative-fuel-capable vessels 10-30% of new orders | Alternative-fuel-capable vessels below 10% of new orders |
| `SHP-R1` | Both a carbon price and a binding fuel intensity mandate apply to shipping in this region | One of the two mechanisms applies | Neither mechanism applies; shipping decarbonisation remains voluntary |
| `SHP-D1` | Multiple active green corridors with committed cargo volumes and disclosed premium mechanism | Green corridors announced but limited committed volume | No active green corridor commitments in the region's main trade routes |

</details>

#### Heavy-Duty Road Transport (3 criteria)

| Code | Pillar | Criterion | Metric | Unit |
| --- | --- | --- | --- | --- |
| `HDT-T1` | Technology | Battery-electric/fuel-cell truck TCO parity | Total cost of ownership (TCO) of battery-electric heavy truck vs. diesel equivalent for the dominant regional duty cycle (regional distribution vs. long-haul) | TCO ratio (BEV:diesel) |
| `HDT-R1` | Regulation | Zero-emission heavy vehicle sales mandate or CO2 standard | Binding CO2 emission standard or zero-emission sales mandate for new heavy trucks, with target year and stringency | % reduction or % ZEV by year |
| `HDT-D1` | Demand & Economics | Charging/refuelling infrastructure density on freight corridors | Number of public heavy-duty charging/hydrogen refuelling points per 100km on the region's primary freight corridors | Points per 100km |

<details><summary>Rating rubrics for Heavy-Duty Road Transport</summary>

| Code | H (more feasible) | M | L (less feasible) |
| --- | --- | --- | --- |
| `HDT-T1` | TCO parity or advantage achieved for at least regional/depot-based duty cycles | TCO within 20% of parity for depot-based cycles; long-haul not yet competitive | TCO more than 20% above diesel for all duty cycles |
| `HDT-R1` | Binding standard/mandate in force with penalties, requiring material ZEV share within the assessment horizon | Standard announced but not yet binding, or binding with limited near-term stringency | No binding CO2 standard or ZEV mandate for heavy trucks |
| `HDT-D1` | Infrastructure density sufficient for unconstrained long-haul operation on primary corridors | Infrastructure present but limited to depot/regional use, gaps on long-haul corridors | Minimal public infrastructure; operation restricted to depot-based captive fleets |

</details>

#### Oil & Gas Upstream (3 criteria)

| Code | Pillar | Criterion | Metric | Unit |
| --- | --- | --- | --- | --- |
| `OGU-T1` | Technology | Methane abatement technology deployment | Share of regional upstream production covered by leak detection and repair (LDAR) programmes and flaring reduction technology | % of production covered |
| `OGU-R1` | Regulation | Methane regulation and fee structure | Existence of a binding methane emission limit or fee applicable to upstream operations | Binary; USD/tonne methane fee where applicable |
| `OGU-D1` | Demand & Economics | Market demand trajectory / structural decline exposure | Projected regional oil and gas demand trajectory to 2035 under stated policy vs. announced pledges scenarios (IEA) | % change in demand 2024-2035 |

<details><summary>Rating rubrics for Oil & Gas Upstream</summary>

| Code | H (more feasible) | M | L (less feasible) |
| --- | --- | --- | --- |
| `OGU-T1` | LDAR and flaring reduction technology deployed across a majority of regional production | Deployed at major operators but not sector-wide | Minimal deployment; routine flaring and unmonitored leakage remain common |
| `OGU-R1` | Binding methane limit and/or fee in force with enforcement mechanism | Regulation announced or in phase-in, not yet fully enforced | No binding methane regulation identified |
| `OGU-D1` | Demand trajectory stable or growing under stated policies (lower stranding risk near-term, i.e. more 'feasible' to continue operating economically) | Demand trajectory flat to moderate decline | Demand trajectory in structural decline under regional policy settings |

</details>

---

### The 86 sources


#### Legal / regulatory text (15)

| Source | Publisher | Criteria | Refresh cadence | URL |
| --- | --- | --- | --- | --- |
| EU Alternative Fuels Infrastructure Regulation (2023/1804) compliance tracking | European Commission | `HDT-D1` | quarterly | [link](https://eur-lex.europa.eu/eli/reg/2023/1804/2026-01-08/eng) |
| EU CBAM Regulation (2023/956) and implementing acts | European Commission / Official Journal of the EU | `STL-R1` | check for amending acts quarterly; consolidated text updates automatically at EUR-Lex | [link](https://eur-lex.europa.eu/eli/reg/2023/956/oj/eng) |
| EU CBAM Regulation - cement sector scope | European Commission / Official Journal of the EU | `CEM-R1` | check for amending acts quarterly; consolidated text updates automatically at EUR-Lex | [link](https://eur-lex.europa.eu/eli/reg/2023/956/oj/eng) |
| EU CBAM scope review - chemicals inclusion status | European Commission | `CHM-R1` | check for amending acts quarterly; consolidated text updates automatically at EUR-Lex | [link](https://eur-lex.europa.eu/eli/reg/2023/956/oj/eng) |
| EU CO2 emission standards for heavy-duty vehicles (Regulation 2024/1610) | Official Journal of the European Union | `HDT-R1` | quarterly | [link](https://eur-lex.europa.eu/eli/reg/2024/1610/oj) |
| EU Critical Raw Materials Act (Regulation 2024/1252) | Official Journal of the European Union | `MIN-R1` | quarterly | [link](https://eur-lex.europa.eu/eli/reg/2024/1252/2024-05-03/eng) |
| EU Critical Raw Materials Act - benchmarks | Official Journal of the European Union | `MIN-R2` | quarterly | [link](https://eur-lex.europa.eu/eli/reg/2024/1252/2024-05-03/eng) |
| EU ETS free allocation benchmarks - cement clinker | European Commission DG CLIMA | `CEM-R1` | annual (benchmark periods run in multi-year blocks; check for new implementing regulation at each period start) | [link](https://eur-lex.europa.eu/eli/reg_impl/2021/447/2026-03-18/eng) |
| EU ETS free allocation benchmarks - chemicals subsectors | European Commission DG CLIMA | `CHM-R1` | annual (benchmark periods run in multi-year blocks; check for new implementing regulation at each period start) | [link](https://eur-lex.europa.eu/eli/reg_impl/2021/447/2026-03-18/eng) |
| EU ETS free allocation benchmarks - steel | European Commission DG CLIMA | `STL-R1` | annual (benchmark periods run in multi-year blocks; check for new implementing regulation at each period start) | [link](https://eur-lex.europa.eu/eli/reg_impl/2021/447/2026-03-18/eng) |
| EU ETS Maritime inclusion (Directive 2023/959) | Official Journal of the European Union | `SHP-R1` | quarterly | [link](https://eur-lex.europa.eu/eli/dir/2023/959/oj) |
| EU FuelEU Maritime Regulation (2023/1805) | Official Journal of the European Union | `SHP-R1` | quarterly | [link](https://eur-lex.europa.eu/legal-content/en/LSU/?uri=CELEX%3A32023R1805) |
| EU Methane Regulation (2024/1787) | Official Journal of the European Union | `OGU-R1` | quarterly | [link](https://eur-lex.europa.eu/eli/reg/2024/1787/oj/eng) |
| EU ReFuelEU Aviation Regulation (2023/2405) | Official Journal of the European Union | `AVI-R1` | quarterly | [link](https://eur-lex.europa.eu/eli/reg/2023/2405/oj) |
| EU REPowerEU / Fit for 55 targets | European Commission | `PWR-R2` | quarterly | [link](https://eur-lex.europa.eu/eli/dir/2018/2001/oj) |

#### Structured API or dashboard (6)

| Source | Publisher | Criteria | Refresh cadence | URL |
| --- | --- | --- | --- | --- |
| China national ETS price | Shanghai Environment and Energy Exchange | `PWR-R1` | continuous | [link](https://www.cneeex.com/) |
| EU ETS carbon price | European Energy Exchange (EEX) / European Commission | `PWR-R1` | continuous / check at each review cycle | [link](https://www.eex.com/en/market-data/environmental-markets/spot-market) |
| NGFS Climate Scenarios | Network for Greening the Financial System (127 central banks and supervisors), hosted by IIASA | `CEM-R1`, `CHM-R1`, `PWR-R1`, `STL-R1` | new phase roughly every 12-18 months (Phase 5 released Nov 2024; short-term scenarios added May 2025) | [link](https://www.ngfs.net/ngfs-scenarios-portal/data-resources/) |
| US National Electric Vehicle Infrastructure / DOE Alternative Fuels Data Center | US Department of Energy | `HDT-D1` | continuously updated | [link](https://afdc.energy.gov/) |
| USGS Mineral Commodity Summaries | United States Geological Survey | `MIN-D1` | annual, published January/February; data-only releases also available via data.usgs.gov by commodity | [link](https://www.usgs.gov/publications/mineral-commodity-summaries-2025) |
| World Bank Carbon Pricing Dashboard | World Bank Group | `PWR-R1` | continuous; annual report each spring | [link](https://carbonpricingdashboard.worldbank.org/) |

#### Industry tracker / database (10)

| Source | Publisher | Criteria | Refresh cadence | URL |
| --- | --- | --- | --- | --- |
| China charging infrastructure statistics | China Electric Vehicle Charging Infrastructure Promotion Alliance | `HDT-D1` | monthly, publisher updates | [link](http://www.evcipa.org.cn/) |
| Clarksons Research World Fleet Register | Clarksons Research | `SHP-T1` | continuous (subscription required for full access) | [link](https://www.clarksons.net/wfr/) |
| DNV Alternative Fuels Insight platform | DNV | `SHP-T1` | continuously updated by publisher | [link](https://afi.dnv.com/) |
| First Movers Coalition Cement & Concrete commitments | World Economic Forum / US State Department | `CEM-D1` | annual, updated at major COP/WEF events | [link](https://www.weforum.org/communities/first-movers-coalition/) |
| Getting to Zero Coalition Green Corridors tracker | Global Maritime Forum | `SHP-D1` | check semi-annually | [link](https://www.globalmaritimeforum.org/green-corridors) |
| Global CCS Institute CO2RE database | Global CCS Institute | `CEM-T1` | continuously updated by publisher; check quarterly | [link](https://co2re.co/FacilityData) |
| Global Cement and Concrete Association (GCCA) sustainability data | GCCA | `CEM-T2` | annual | [link](https://gccassociation.org/sustainability-innovation/gnr-gcca-in-numbers/) |
| IEA CCUS Projects Database | International Energy Agency | `CEM-T1` | continuously updated by publisher; check quarterly | [link](https://co2re.co/FacilityData) |
| Oil and Gas Methane Partnership (OGMP 2.0) reporting | United Nations Environment Programme | `OGU-T1` | annual | [link](https://www.ogmpartnership.com/) |
| S&P Global Market Intelligence - Metals & Mining | S&P Global | `MIN-T1` | continuous | [link](https://www.spglobal.com/marketintelligence/en/sector/metals-mining) |

#### Periodic PDF report (27)

| Source | Publisher | Criteria | Refresh cadence | URL |
| --- | --- | --- | --- | --- |
| BloombergNEF Corporate Energy Market Outlook | BloombergNEF | `PWR-D1` | varies by report series, generally annual | [link](https://about.bnef.com/) |
| BloombergNEF Energy Storage Outlook | BloombergNEF | `PWR-T2` | varies by report series, generally annual | [link](https://about.bnef.com/) |
| BloombergNEF Green Steel Tracker / Premium report | BloombergNEF | `STL-D1` | varies by report series, generally annual | [link](https://about.bnef.com/) |
| BloombergNEF Hydrogen Levelized Cost Report | BloombergNEF | `STL-T1` | varies by report series, generally annual | [link](https://about.bnef.com/) |
| IATA SAF price tracking | International Air Transport Association | `AVI-D1` | periodic, check quarterly | [link](https://www.iata.org/en/programs/environment/sustainable-aviation-fuels/) |
| IATA Sustainable Aviation Fuel Fact Sheet / SAF Tracker | International Air Transport Association | `AVI-T1` | annual, with interim updates | [link](https://www.iata.org/en/iata-repository/publications/economic-reports/sustainable-aviation-fuel-fact-sheet/) |
| ICCT Total Cost of Ownership analyses | International Council on Clean Transportation | `HDT-T1` | annual, check for new regional TCO updates | [link](https://theicct.org/publications/) |
| IEA Aviation tracking report | International Energy Agency | `AVI-T1` | annual, typically published October | [link](https://www.iea.org/reports/world-energy-outlook-2024) |
| IEA Cement Technology Roadmap | International Energy Agency | `CEM-T2` | annual | [link](https://www.iea.org/energy-system/industry/cement) |
| IEA Critical Minerals Outlook | International Energy Agency | `MIN-T1` | annual | [link](https://www.iea.org/reports/global-critical-minerals-outlook-2024) |
| IEA Critical Minerals Outlook - demand-supply gap tables | International Energy Agency | `MIN-D1` | annual | [link](https://www.iea.org/reports/global-critical-minerals-outlook-2024) |
| IEA Energy Storage | International Energy Agency | `PWR-T2` | annual | [link](https://www.iea.org/energy-system/electricity/grid-scale-storage) |
| IEA Global EV Outlook - heavy-duty vehicles chapter | International Energy Agency | `HDT-T1` | annual, typically published October | [link](https://www.iea.org/reports/world-energy-outlook-2024) |
| IEA Global Hydrogen Review | International Energy Agency | `CHM-T1`, `STL-T1` | annual, typically published October | [link](https://www.iea.org/reports/global-hydrogen-review-2024) |
| IEA Methane Tracker | International Energy Agency | `OGU-T1` | annual, typically published March | [link](https://www.iea.org/reports/global-methane-tracker-2025) |
| IEA Renewables market report | International Energy Agency | `PWR-R2` | annual, typically published October | [link](https://www.iea.org/reports/renewables-2024) |
| IEA The Future of Petrochemicals | International Energy Agency | `CHM-T1`, `CHM-T2` | annual, typically published October | [link](https://www.iea.org/reports/world-energy-outlook-2024) |
| IEA World Energy Investment | International Energy Agency | `PWR-T1` | annual, typically published June | [link](https://www.iea.org/reports/world-energy-investment-2025) |
| IEA World Energy Outlook - regional demand scenarios | International Energy Agency | `OGU-D1` | annual, typically published October | [link](https://www.iea.org/reports/world-energy-outlook-2024) |
| IRENA Renewable Power Generation Costs | International Renewable Energy Agency | `PWR-T1` | annual, typically published September | [link](https://www.irena.org/Publications/2024/Sep/Renewable-Power-Generation-Costs-in-2023) |
| Lazard Levelized Cost of Energy Analysis | Lazard | `PWR-T1` | annual | [link](https://www.lazard.com/research-insights/levelized-cost-of-energyplus/) |
| Mission Possible Partnership Steel sector tracker | Mission Possible Partnership | `STL-D1` | annual, but publication timing is less regular than IEA/IRENA | [link](https://missionpossiblepartnership.org/publications/) |
| Mission Possible Partnership Steel Transition Strategy | Mission Possible Partnership / Energy Transitions Commission | `STL-T1` | annual, but publication timing is less regular than IEA/IRENA | [link](https://missionpossiblepartnership.org/publications/) |
| Mission Possible: Reaching Net-Zero Carbon Emissions from Harder-to-Abate Sectors | Energy Transitions Commission (ETC) | `AVI-T1`, `CEM-T1`, `CHM-T1`, `SHP-T1`, `STL-T1` | irregular — ETC publishes updates and sector-specific follow-ons rather than a fixed annual cycle; check publications page each review | [link](https://www.energy-transitions.org/publications/mission-possible/) |
| OECD Steel Market Developments | OECD Steel Committee | `STL-T2` | semi-annual | [link](https://www.oecd.org/en/topics/sub-issues/steel-market-developments.html) |
| RE100 Annual Report | Climate Group / CDP | `PWR-D1` | annual | [link](https://www.there100.org/re100-progress-and-insights-annual-report) |
| World Steel Association Steel Statistical Yearbook | World Steel Association (worldsteel) | `STL-T2` | annual | [link](https://worldsteel.org/data/world-steel-in-figures/) |

#### Government agency publication (21)

| Source | Publisher | Criteria | Refresh cadence | URL |
| --- | --- | --- | --- | --- |
| California Advanced Clean Fleets / Advanced Clean Trucks regulation | California Air Resources Board | `HDT-R1` | monitor closely given ongoing litigation/waiver status | [link](https://ww2.arb.ca.gov/our-work/programs/advanced-clean-fleets) |
| China industrial decarbonisation funding programmes | National Development and Reform Commission (China) | `CEM-R2` | quarterly given active expansion phase | [link](https://www.mee.gov.cn/) |
| China methane control action plan | Ministry of Ecology and Environment (China) | `OGU-R1` | annual | [link](https://www.mee.gov.cn/) |
| China Ministry of Natural Resources mining approval process | Ministry of Natural Resources (China) | `MIN-R1` | annual | [link](https://www.mnr.gov.cn/) |
| China national ETS sector coverage roadmap | Ministry of Ecology and Environment (China) | `STL-R1` | quarterly given active expansion phase | [link](https://www.mee.gov.cn/) |
| China NEA renewable targets | National Energy Administration (China) | `PWR-R2` | quarterly | [link](https://www.nea.gov.cn/) |
| China NEV mandate - commercial vehicles | Ministry of Industry and Information Technology (China) | `HDT-R1` | annual | [link](https://www.miit.gov.cn/) |
| EU Green Public Procurement - construction criteria | European Commission DG ENV | `CEM-D1` | annual, criteria updated periodically per sector | [link](https://green-business.ec.europa.eu/green-public-procurement_en) |
| EU Green Public Procurement criteria - construction | European Commission DG ENV | `STL-R2` | annual, criteria updated periodically per sector | [link](https://green-business.ec.europa.eu/green-public-procurement_en) |
| EU Innovation Fund award decisions | European Climate, Infrastructure and Environment Executive Agency (CINEA) | `CEM-R2` | per call round (roughly annual) | [link](https://cinea.ec.europa.eu/programmes/innovation-fund_en) |
| ICAO CORSIA scheme status | International Civil Aviation Organization | `AVI-R1` | annual, check ahead of each phase transition | [link](https://www.icao.int/environmental-protection/CORSIA/Pages/state-pairs.aspx) |
| IMO GHG Strategy implementation tracker | International Maritime Organization | `CHM-D1` | check ahead of each MEPC session (roughly biannual) for mid-term measures progress | [link](https://www.imo.org/en/OurWork/Environment/Pages/2023-IMO-Strategy-on-Reduction-of-GHG-Emissions-from-Ships.aspx) |
| IMO Revised GHG Strategy and mid-term measures | International Maritime Organization | `SHP-R1` | check ahead of each MEPC session (roughly biannual) for mid-term measures progress | [link](https://www.imo.org/en/OurWork/Environment/Pages/2023-IMO-Strategy-on-Reduction-of-GHG-Emissions-from-Ships.aspx) |
| National/state building codes register | Various national standards bodies | `STL-R2` | annual, varies significantly by jurisdiction | [link](https://www.iccsafe.org/) |
| US DOE Industrial Demonstrations Program awards | US Department of Energy | `CEM-R2` | monitor closely for continuity under current administration | [link](https://www.energy.gov/oced/industrial-demonstrations-program) |
| US EPA Heavy-Duty Phase 3 GHG standards | US Environmental Protection Agency | `HDT-R1` | monitor closely given litigation risk | [link](https://www.epa.gov/regulations-emissions-vehicles-and-engines/final-rule-greenhouse-gas-emissions-standards-heavy) |
| US EPA Methane Emissions Reduction Program / Waste Emissions Charge (IRA) | US Environmental Protection Agency | `OGU-R1` | monitor closely | [link](https://www.federalregister.gov/documents/2025/05/19/2025-08688/congressional-review-act-revocation-of-waste-emissions-charge-for-petroleum-and-natural-gas-systems) |
| US Federal Buy Clean Initiative | US General Services Administration / EPA | `STL-R2` | annual, monitor for continuity under current administration priorities | [link](https://www.sustainability.gov/buyclean/) |
| US Fixing America's Surface Transportation Act / permitting reform tracker | US Department of Interior / Congressional Research Service | `MIN-R1` | monitor closely given active legislative attention | [link](https://www.congress.gov/bill/118th-congress/house-bill/1) |
| US Inflation Reduction Act Section 30D critical minerals requirements | US Internal Revenue Service / US Treasury | `MIN-R2` | monitor closely — credit status changed materially in 2025 | [link](https://www.energy.gov/mesc/30d-new-clean-vehicle-credit) |
| US SAF Grand Challenge / IRA 40B tax credit | US Department of Energy / US Treasury | `AVI-R1` | annual, monitor for continuity under current administration priorities | [link](https://www.sustainability.gov/buyclean/) |

#### Company disclosure (7)

| Source | Publisher | Criteria | Refresh cadence | URL |
| --- | --- | --- | --- | --- |
| Company disclosures | Airlines and SAF producers | `AVI-D1` | per company reporting cycle (typically annual, some quarterly) | _varies by company_ |
| Company disclosures | e.g. Maersk, cargo owner coalitions (coZEV) | `SHP-D1` | per company reporting cycle (typically annual, some quarterly) | _varies by company_ |
| Company investor disclosures | Individual cement producers (e.g. Heidelberg Materials, Holcim) | `CEM-D1` | per company reporting cycle (typically annual, some quarterly) | _varies by company_ |
| Company investor disclosures | Individual miners (e.g. Freeport-McMoRan, Albemarle) | `MIN-D1` | per company reporting cycle (typically annual, some quarterly) | _varies by company_ |
| Company investor disclosures | Individual steelmakers (annual reports, capital markets days) | `STL-D1` | per company reporting cycle (typically annual, some quarterly) | _varies by company_ |
| Company investor disclosures | e.g. Maersk, Yara, OCI | `CHM-D1` | per company reporting cycle (typically annual, some quarterly) | _varies by company_ |
| Company/consortium technical disclosures | e.g. BASF/SABIC/Linde electric cracker pilot | `CHM-T2` | per company reporting cycle (typically annual, some quarterly) | _varies by company_ |