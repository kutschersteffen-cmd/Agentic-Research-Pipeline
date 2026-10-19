# Capex alignment against sector pathways: methodology research

How published methodologies compare a company's capex (green or low-carbon share of total
capex, an absolute amount, or both) with a sector pathway for high-emitting sectors. The doc then
checks the owner's uploaded scoring engine (`capex_alignment-2_1.txt`) and template
(`Capex_Alignment_Scoring_Template-2_1.xlsx`) against those sources, and ends with a
recommendation for this platform.

Status: **research note, 2026-10-19.** Primary documents were read in full where linked. Page
numbers are the printed page numbers of the PDF unless marked "PDF p.".

Evidence tags:

- **[verified]**: read in the methodology owner's own document or web page.
- **[search extract]**: the owner's page blocked direct fetching (HTTP 403). The wording comes
  from a search engine's extract of that page, so check it before relying on it.
- **[not verified]**: could not be traced to the owner's document. See
  [Unverified / could not access](#9-unverified--could-not-access).

---

## 1. Summary

**Headline:** none of the established methodologies scores a single 2030 "required green capex
ratio" per sector. Two families exist:

1. **Share-of-capex vs a sector benchmark.** Only ADEME/CDP **ACT** does this numerically, and
   only for some sectors: power 95%, oil & gas 49% (plus 5% for CCS/CDR), chemicals 54%, and an
   80% expert threshold for autos and the generic method.
   [verified](https://actinitiative.org/act-methodologies/)
   ACT steel, cement and aluminium use **locked-in emissions** of assets instead of a capex share.
2. **Disclosure and commitment tests, with absolute amounts required.**
   - CA100+ Indicator 6 asks for the *value* of carbon-intensive capex and of climate-solutions
     capex. A share counts only "as long as the latter is disclosed in absolute terms".
     [verified](https://www.climateaction100.org/wp-content/uploads/2025/01/CA100-Benchmark-2.1-Disclosure-Framework-Methodology_EN.pdf)
   - The CTI and RMI alignment assessments test projects, assets or production against IEA
     scenarios. They do not test a green capex ratio.

So the company side should hold **both** the share and the absolute amount. The pathway side is a
capex-share benchmark only where ACT publishes one. Elsewhere it is an intensity or asset pathway
(TPI, RMI, ACT locked-in) or an IEA NZE milestone.

| Methodology | Company metric | Sectors | Pathway source | Reuse in a commercial platform |
|---|---|---|---|---|
| CA100+ Indicator 6 (v2.2, 2025) | Absolute value of carbon-intensive capex (6.1.b) and of climate-solutions capex, past (6.2.a) and planned (6.2.b). A share counts only if absolute terms can be derived. Yes/No metrics. | All 164 focus companies | None. Disclosure test only. | Site terms: no commercial reproduction without written permission. [verified](https://www.climateaction100.org/terms-of-use/) |
| CTI capital allocation (O&G 2025; utilities 2023) | O&G: % and $ of upstream capex in projects *incompatible* with NZE/APS. Utilities: coal and gas retirement schedules, % of capacity. | 33 O&G (2025). Utilities last assessed 2023. | Own least-cost model on Rystad project data with IEA WEO 2024 NZE/APS/STEPS demand | Non-commercial reproduction only. [verified](http://www.climateaction100.org/wp-content/uploads/2025/10/CarbonTracker_CA100methodology_OilandGas_202521-copy.pdf) |
| RMI/PACTA for CA100+ (2024) | Production or capacity plans (power, autos). Distance of emissions intensity to 2030 (steel, cement, airlines). Not capex. | Power, autos, steel, cement, airlines | IEA WEO 2023 NZE/APS/STEPS; Asset Impact asset data | PACTA is open source. The asset data is commercial. [verified](https://www.climateaction100.org/wp-content/uploads/2024/10/2024-RMI-Methodology.pdf) |
| EU Taxonomy Art. 8 CapEx KPI | Aligned CapEx / CapEx (IAS 16/38/40/41, IFRS 16 additions). Share plus an absolute denominator. | Any activity in the Climate Delegated Act | No pathway. Activity-level screening criteria. PSF publishes observed shares (16% of total CapEx aligned, 2023). | EU content is CC BY 4.0. PSF figures rest on Bloomberg/Orbis data (third-party caveat). [verified](https://commission.europa.eu/legal-notice_en) |
| ACT (ADEME/CDP) | Planned low-carbon capex share (3 or 5 years). Score = min(share / benchmark, 1). | Power, O&G, chemicals, autos, generic. Steel, cement, aluminium and transport have no capex-share indicator. | Power: IEA NZE 2021–30 investment, giving 95%. O&G: IEA WEO 2019 SDS, giving 49%. Chemicals: borrowed from O&G, giving 54%. Autos and generic: 80% threshold "defined accordingly", with no benchmark. | "Reproduction of all or part of work without licence of use permission … is prohibited." [verified](https://actinitiative.org/wp-content/uploads/act-electricity-v2.0.pdf) |
| IEA NZE (2023 update) | n/a (scenario). Clean:fossil investment ratio 10:1 by 2030. USD 4.5 tn per year of clean investment by the early 2030s. No sector "share of capex that must be clean". | Global energy system. Sector milestones are in physical units. | Published report numbers | Report text and figures CC BY 4.0. Annex A data CC BY-NC-SA 4.0. The 2021 NZE report is "All rights reserved". [verified](https://iea.blob.core.windows.net/assets/9a698da4-4002-4e53-8ef3-631d8971bf84/NetZeroRoadmap_AGlobalPathwaytoKeepthe1.5CGoalinReach-2023Update.pdf) |
| TPI Centre (v5.0, 2023) | Carbon Performance: emissions intensity vs 1.5°C / Below 2°C / National Pledges. MQ Level 5: Q21 capex phase-out commitment, Q22 capex alignment methodology (Yes/No). | About 2,000 companies in 24 sectors | IEA ETP/WEO/NZE via the Sectoral Decarbonisation Approach (SDA) | **Not CC BY-NC-SA.** LSE terms: commercial use, derived analytics and redistribution need a licence (MQ via LSEG). [verified](https://www.transitionpathwayinitiative.org/use-of-the-centre-s-data) |

**Uploaded files:** of the 7 `required_green_capex_ratio_2030` figures, **0 are supported by a
primary source**, as figure or as pathway. Cross-sector 0.15 sits close to an *observed* EU 2023
average (16% of total CapEx aligned, PSF), but that is a descriptive statistic, not a required
level. Where a primary benchmark exists, it is well above the template's figure:

| Sector | Template | Primary benchmark |
|---|---|---|
| Power | 0.60 | ACT 95% |
| Oil & gas | 0.30 | ACT 49% |
| Autos | 0.50 | ACT 80% |

The two extra parameters (0.75 × required for maturity level 3, and the 10 pp red threshold) are
invented. Three of the seven redlines paraphrase IEA NZE milestones (oil & gas, power, autos).
The rest are invented.

---

## 2. CA100+ Net Zero Company Benchmark: capital allocation

### 2.1 Indicator numbering across versions

- **v1.1 (2021):** "Indicator 6 – Capital Allocation Alignment". 6.1 = a commitment to align
  capex with the long-term target (a) or with the Paris goal plus a phase-out (b). 6.2 = disclose
  the alignment methodology (a) and quantify its outcomes (b).
  [verified, p.30](https://www.climateaction100.org/wp-content/uploads/2021/10/V1.1-Disclosure-Framework-assessment-methodology-Oct21.pdf)
- **v2.0 (2023):** Indicator 6 "substantially amended".
  [verified](https://www.climateaction100.org/net-zero-company-benchmark/methodology/)
- **v2.1 (2024):** "Indicator 6: Capital Allocation – evaluates whether companies are working to
  decarbonise their capital expenditures and explain how they intend to invest in climate
  solutions."
  [verified](https://www.climateaction100.org/wp-content/uploads/2024/06/Net-Zero-Company-Benchmark-Version-2.1-Framework-v2.pdf)
- **v2.2 (October 2025)** is the current version on the methodology page. Its update note lists
  changes to Indicators 3, 4, 7, 9, 10 and 11 only. All other metrics "remain the same as in the
  version 2.1 framework", so Indicator 6 is unchanged from v2.1.
  [verified](https://www.climateaction100.org/wp-content/uploads/2025/05/Framework-Updates-2025-Net-Zero-Company-Benchmark-Framework-1.pdf)

### 2.2 Indicator 6 in v2.1/v2.2 (assessed by the TPI Centre)

Source: [v2.1 Disclosure Framework methodology, pp.16–18](https://www.climateaction100.org/wp-content/uploads/2025/01/CA100-Benchmark-2.1-Disclosure-Framework-Methodology_EN.pdf) [verified]

**6.1 Capex Allocation**

- **6.1.a** The company states that it has phased out, or plans to phase out, capex in new
  unabated carbon-intensive assets or products by a specified year. Commitments to "align" capex
  with a 1.5°C pathway are "not sufficient". Simply listing green capex plans is also "not
  sufficient".
- **6.1.b** The company discloses "the stated value of its capital expenditure that is going
  towards unabated carbon-intensive assets or products".
  - The disclosure must "allow for the calculation of the absolute value". A share counts only
    "as long as the latter is disclosed in absolute terms".
  - EU Taxonomy reporters should break out non-aligned capex within eligible capex.

**6.2 Climate Solutions Allocation**

- **6.2.a** Climate-solutions capex in the last reporting year, with a stated definition. Any of
  these qualifies:
  - a percentage share disclosed in absolute terms,
  - an absolute amount,
  - a product-category share (e.g. EVs as a share of vehicle investment) given as an amount.

  EU Taxonomy-*aligned* capex is valid. Taxonomy-*eligible* capex "will not count".
- **6.2.b** Planned climate-solutions capex within a clear timeframe ("$3B by 2030", or "50% of
  our total $10B").

**What this means for the platform:** CA100+ compares capex with **no** sector benchmark. It is a
Yes/No disclosure test that requires an **absolute** amount, and it treats a share as acceptable
only when an amount can be derived from it.

### 2.3 Alignment assessments behind Indicator 6

**Carbon Tracker Initiative (CTI): oil & gas.** August 2025, applies to the October 2025 v2.2
assessments, covers 33 companies.
[verified](http://www.climateaction100.org/wp-content/uploads/2025/10/CarbonTracker_CA100methodology_OilandGas_202521-copy.pdf)

The four indicators "complement Indicator 6" (p.3). Demand comes from IEA WEO 2024 STEPS, APS
and NZE. Supply is Rystad Energy project data (p.3).

1. **Recent investments** (2024 sanctions). Green if not incompatible with NZE. Amber if not
   incompatible with APS. Red otherwise. The data point is the **% of upstream capex and $ value**
   sanctioned in projects incompatible with NZE or APS (pp.4–5).
2. **Future investments.** Green if potential future upstream capex is not incompatible with
   NZE. Amber if under 50% is incompatible with APS. Red if 50–100% is (pp.5–6).
3. **Future production** in the 2030s vs NZE-compatible production. Amber up to 50% above, red
   beyond (pp.6–7).
4. **Commodity price deck** vs USD 43/bbl (NZE) and USD 74/bbl (APS) (pp.8–9).

A project is compatible if its breakeven price is below the marginal breakeven of the last
project needed under the scenario (p.5, Section 5). The metric is the **share of capex in
incompatible projects**, not a green share.

**CTI: electric utilities (2023).** 33 utilities.
[verified](https://www.climateaction100.org/wp-content/uploads/2023/10/2023-CTI-Electric-Utility-Methodology.pdf)

- Four indicators cover announced coal and gas **retirement schedules**, plus the % of coal and
  gas capacity aligned with CTI's NZE interpretation. Green at 100%, amber 75–99%, red 0–75%
  (pp.5–6).
- Under NZE, "~95% of unabated gas-fired phased-out globally by 2035 and unabated coal will be
  (~99%) phased-out globally by 2040" (p.5).
- This is a retirement test, not a capex share.

**RMI/PACTA (2024): power, autos, steel, cement, airlines.**
[verified](https://www.climateaction100.org/wp-content/uploads/2024/10/2024-RMI-Methodology.pdf)

- Asset-based data comes from Asset Impact (p.4). Scenarios are IEA WEO 2023 NZE, APS and STEPS
  (p.6).
- Power and autos are assessed on 5-year capacity and production plans by technology (pp.7–10).
- Steel, cement and airlines are assessed on the % cut in emissions intensity needed to reach the
  2030 IEA target (Table 3, p.10):

  | Sector | Approaching (green) | Moderate | Significant (red) |
  |---|---|---|---|
  | Steel | <15% | 15–36% | >36% |
  | Cement | <5% | 5–20% | >20% |
  | Airlines | <15% | 15–30% | >30% |

- PACTA measures "planned outcomes from capital expenditures (CAPEX)" via capacity and
  production, not via the capex amount (p.5).

**2025 status.** "CTI and RMI have in previous years provided assessments for steel, cement,
autos, electric utilities and oil and gas companies. In 2025 these measures have not been
reassessed". Only CTI oil & gas was updated in 2025.
[verified](https://www.climateaction100.org/net-zero-company-benchmark/methodology/)

### 2.4 Licence

**CA100+ site terms.** Content is "for your information and personal use only". It may not be
"copied, reproduced, aggregated, republished … for any commercial purpose whatsoever, without our
express prior written permission".
[verified](https://www.climateaction100.org/terms-of-use/)

**CTI.** "Readers are allowed to reproduce material from Carbon Tracker reports for their own
publications, as long as they are not being sold commercially". CTI asks for acknowledgement and
a link (O&G methodology, PDF p.2).
[verified](http://www.climateaction100.org/wp-content/uploads/2025/10/CarbonTracker_CA100methodology_OilandGas_202521-copy.pdf)

---

## 3. EU Taxonomy CapEx KPI (Disclosures Delegated Act)

### 3.1 Definition

Source: [Commission Delegated Regulation (EU) 2021/2178, Annex I, 1.1.2, OJ L 443/17–18](https://eur-lex.europa.eu/eli/reg_del/2021/2178/oj) [verified]

**Denominator (1.1.2.1).** Additions to tangible and intangible assets during the year, before
depreciation, amortisation and re-measurements, including those from business combinations.
Under IFRS this means:

- IAS 16 §73(e)(i),(iii)
- IAS 38 §118(e)(i)
- IAS 40 §76(a),(b) and §79(d)(i),(ii)
- IAS 41 §50(b),(e)
- IFRS 16 §53(h)

**Numerator (1.1.2.2).** CapEx that falls under any of:

- (a) assets or processes associated with Taxonomy-aligned activities;
- (b) a **CapEx plan** to expand aligned activities or to bring eligible activities into
  alignment;
- (c) purchases of aligned output and individual measures implemented within 18 months.

**CapEx plan conditions:**

- It must achieve alignment "within a period of five years". It may run longer "only where …
  objectively justified …, with a maximum of 10 years".
- It must be disclosed at economic-activity level and approved by the management body.
- If the screening criteria change, the plan must be updated within two years, or the numerator
  restated.
- If the plan fails, the published KPI is restated.

**2026 amendment.** [Delegated Regulation (EU) 2026/73](https://eur-lex.europa.eu/eli/reg_del/2026/73/oj)
(adopted 4 July 2025, OJ 8 January 2026). [verified via the Publications Office text]

- New Art. 2(1b): companies "may omit assessing" activities whose cumulative capex is "below 10 %
  of the denominator of the CapEx KPI". These are reported separately as non-material.
- Annex I is only amended at 1.1.3.2 (OpEx) and 1.2.3.x (non-material disclosures), so the CapEx
  numerator, denominator and CapEx-plan text above stand.
- It applies from 1 January 2026. FY2025 reports may use either version.

**What this means for the platform:** the Taxonomy denominator is **not** the cash-flow
"purchases of PP&E" that `spend_extractor_agent.py` targets. It includes right-of-use assets and
acquisitions, so a Taxonomy share must never be divided into a cash-flow capex figure.

### 3.2 Sector benchmarks and Platform on Sustainable Finance data

The Taxonomy sets **activity-level technical screening criteria, not a required share** for any
sector. The Platform on Sustainable Finance (PSF) report
[Monitoring Capital Flows to Sustainable Investments (March 2025)](https://finance.ec.europa.eu/publications/platform-sustainable-finance-report-monitoring-capital-flows-sustainable-investments_en)
publishes **observed** 2023 levels for 2,180 large listed companies.
[verified, PDF](https://finance.ec.europa.eu/document/download/87c48ab4-34d2-4cd7-997e-efc1310e62c5_en?filename=250311-sustainable-finance-platform-report-capital-flows_en.pdf)

- **All companies (Table 2, p.25):**
  - Aligned CapEx EUR 250 bn.
  - Aligned share of total CapEx **16%**. The average company share is **12.3%**.
  - Among the 667 companies reporting non-zero values: 31% of total CapEx, 24% average company
    share.
- **Utilities (p.23, Fig. 6):** "76% of CapEx in the utilities sector is Taxonomy-aligned"
  (EUR 109 bn). Electricity production alone is 71% aligned (pp.23–24).
- **Manufacturing:** 9% average.
- **Car manufacturers:**
  - p.11 says "30% of car manufacturers' CapEx (EUR 41 billion)".
  - p.24 says EUR 39 bn, 16% of all aligned CapEx.
  - The report is internally inconsistent here.
- **Energy-intensive industries (steel, cement):** aligned CapEx is "altogether a percentage
  point of the EU total" (p.25).

These are **descriptive**, EU-listed-company figures, not pathways. They are useful as peer
context, not as a "required" level.

### 3.3 Licence

- EU-owned content is licensed CC BY 4.0, with reuse implemented under Decision 2011/833/EU.
- For content the EU does not own, reuse "may require permission" from the rightholders.
  [verified](https://commission.europa.eu/legal-notice_en)
- The PSF figures are "own analysis based on Bloomberg, Orbis" (p.23).
- Citing a published aggregate figure is low-risk. Redistributing the underlying company-level
  data is not covered.

---

## 4. ADEME/CDP ACT (Assessing low-Carbon Transition)

Sector list and documents: [ACT methodologies](https://actinitiative.org/act-methodologies/). [verified]

**Mechanics.** Where ACT has a capex indicator, the company metric is a **share**: planned
low-carbon (and mitigation) capex divided by total capex, M$/M$.

- The score for each year is min(share / benchmark, 1).
- Power and chemicals average the score over the reporting year to RY+3.
- O&G averages the score at RY and RY+5. A plan shorter than 5 years is scaled pro rata.

| Sector (version) | Indicator | Benchmark | How derived | Source |
|---|---|---|---|---|
| Electricity (v2.0, 2023) | EU 2.4 share of low-carbon capex, next 3 years | **95%** | IEA NZE average annual electricity investment 2021–30: total USD 1,232 bn, of which 61 bn is "fossil fuels without CCUS". Nuclear and fossil with CCUS count as low-carbon (Table 10). IRENA 1.5°C gives similar values. | [pp.50–52, 134](https://actinitiative.org/wp-content/uploads/act-electricity-v2.0.pdf) |
| Oil & gas (2021) | OG 2.5 low-carbon and mitigation capex share, next 5 years | **49%** | IEA WEO 2019 SDS: 5% for fuels and 67% for power businesses, combined over the "Total Energy playfield" | [pp.52–56, 125–126](https://actinitiative.org/wp-content/uploads/act-og-methodology_vf.pdf) |
| Oil & gas (2021) | OG 2.6 CCS/CCUS/CDR capex share | **5%** | McCollum et al. (2018), an average of energy-economy models | same, p.126 |
| Chemicals (2024) | CH 2.4 low-carbon, mitigation and removal capex share, next 3 years | **54%** | "No sectoral benchmark specific to the chemicals sector has been found", so O&G 49% + 5% | [pp.55–57](https://actinitiative.org/wp-content/uploads/act-chemicals-final.pdf) |
| Automotive (v2.0, 2024) | AU 2.2 share of low-carbon capex, next 3 years | **80%** | "no benchmarks are available for this sector. Therefore, the 80% threshold has been defined accordingly" | [pp.38–41](https://actinitiative.org/wp-content/uploads/act-auto-v2.0.pdf) |
| Generic (v2.0, 2023) | GE 2.3 share of low-carbon capex, reporting year | **80%** threshold | Same expert threshold | [p.47](https://actinitiative.org/wp-content/uploads/act-generic-v2.0.pdf) |
| Iron & steel (v2.0), cement (v2.0), aluminium (v2.0) | No capex-share indicator. IS 2.3 / CEM 2.2a / AL 2.2 **locked-in emissions** of production assets vs an SDA-derived carbon budget. | n/a | Asset-level intensity × activity over remaining lifetime | [steel Table 8](https://actinitiative.org/wp-content/uploads/act-iron-steel-methodo_v2.0.pdf), [cement](https://actinitiative.org/wp-content/uploads/act-cement-v2.0.pdf), [aluminium](https://actinitiative.org/wp-content/uploads/act-aluminium_v2.0.pdf) |
| Transport (v2.1) | No capex share. TR 2.3 fleet locked-in emissions. TR 3.1 low-carbon **R&D** share, full score at 80%, or 50% for mostly subcontracted fleets. | n/a | Expert thresholds | [pp.43, 57–58](https://actinitiative.org/wp-content/uploads/act-transport-v2.1.pdf) |

**Low-carbon definitions differ from this platform's.** ACT electricity counts nuclear and CCUS
as low-carbon (p.51–52), and its sustainable-biomass rule is borrowed from the EU Taxonomy.

**Licence.** Every methodology PDF carries the same notice on PDF p.2. For example: "© World
Benchmarking Alliance, ADEME, and CDP Worldwide 2023. Reproduction of all or part of work without
licence of use permission of World Benchmarking Alliance, ADEME & CDP Worldwide is prohibited."
[verified](https://actinitiative.org/wp-content/uploads/act-electricity-v2.0.pdf)

Citing the 95% / 49% / 54% / 80% figures with attribution is a single-fact reference. Storing
ACT's method or tables in the product needs ADEME/CDP permission (owner decision).

---

## 5. IEA Net Zero Emissions by 2050 (NZE)

Source: [Net Zero Roadmap, 2023 Update (PDF)](https://iea.blob.core.windows.net/assets/9a698da4-4002-4e53-8ef3-631d8971bf84/NetZeroRoadmap_AGlobalPathwaytoKeepthe1.5CGoalinReach-2023Update.pdf). [verified]

**Investment, absolute:**

- Clean energy investment of USD 1.8 tn in 2023 must climb "to around USD 4.5 trillion a year by
  the early 2030s" (p.16). It reaches 4.7 tn by 2050 (p.173).
- In 2030: "around USD 2.5 trillion is invested in clean electricity and low-emissions fuels and
  around USD 1.8 trillion in energy efficiency and end-uses, while investment in fossil fuel
  supply falls to around USD 0.4 trillion" (p.162).

**Investment, as a share:**

- The clean:fossil investment ratio rises from 1.8:1 (2023) "to 10 to 1 in 2030" (p.162). That
  implies about 91% clean across the **whole energy system**, not per sector.
- **No sector-level "share of capex that must be clean" exists** in the report. ACT derived its
  95% power figure itself from IEA investment tables (section 4).

**Sector milestones (physical units, not capex):**

| Sector | Milestone | Page |
|---|---|---|
| Oil & gas | "no new long lead time conventional oil and gas projects are approved for development after 2023" | p.76 |
| Oil & gas (2021 report) | "Beyond projects already committed as of 2021, there are no new oil and gas fields approved for development" | [NZE 2021, p.21](https://iea.blob.core.windows.net/assets/deebef5d-0c34-4539-9d0c-10b13d840027/NetZeroby2050-ARoadmapfortheGlobalEnergySector_CORR.pdf) |
| Power | "no new unabated coal plants beyond the 150 GW under construction at the start of 2023" | p.81 |
| Power | Unabated coal phased out in advanced economies in the 2030s and all unabated coal by 2040 | Figure, p.92 |
| Autos | EVs ~65% of new car sales by 2030. "no new internal combustion engine (ICE) cars are sold after 2035". | p.88 |
| Steel | Near-zero-emission iron production 8% (2030), 27% (2035), 95% (2050) | p.95 |
| Aluminium | Near-zero primary aluminium production 7% (2030) | p.95 |
| Cement | Near-zero clinker 8% (2030), 93% (2050). Clinker ratio 0.65 (2030). | p.96 |

**Licence:**

- **2023 update:** "this work is licenced under a Creative Commons Attribution 4.0 International
  Licence", but "Annex A … is licensed under a Creative Commons Attribution-NonCommercial-ShareAlike
  4.0 International Licence" (copyright page, p.225 of the PDF). The figures are marked
  "IEA. CC BY 4.0." [verified]
- **2021 NZE report:** figures marked "IEA. All rights reserved." [verified]
- **IEA site terms:**
  - Text, reports, standalone graphs and figures default to CC BY 4.0.
  - The default excludes "standalone datasets, data explorers and databases, and data annexes to
    the World Energy Outlook".
  - The WEO 2024 free dataset is CC BY-NC-SA 4.0.
  - Third-party material is excluded.
  - [search extract](https://www.iea.org/terms); the
    [WEO 2024 free dataset page](https://www.iea.org/data-and-statistics/data-product/world-energy-outlook-2024-free-dataset)
    returned HTTP 403 to direct fetch.

**What this means for the platform:** a figure taken from the 2023 report's **text or a chapter
figure** can be stored and redistributed commercially with attribution (CC BY 4.0). A figure from
**Annex A tables or the free datasets** is non-commercial and share-alike, so it is not usable in
a commercial product without an IEA licence. Paid datasets fall under their own licence.

---

## 6. TPI Centre (LSE)

Source: [Methodology report v5.0, Nov 2023](https://www.transitionpathwayinitiative.org/asset-library/methodologies/23-11-cp-mq-methodology-report-v5.pdf). [verified]

**Carbon Performance.**

- Company emissions intensity paths are compared with sector benchmark paths built with the SDA.
- The benchmarks are "1.5 Degrees", "Below 2 Degrees" (1.65°C at 50%) and "National Pledges"
  (IEA 2020 STEPS, 2.6°C) (p.16).
- Airlines and shipping use International Pledges (ICAO and IMO). Paper uses IEA 2017 scenarios
  (p.17).
- The data sources are IEA ETP, WEO and NZE (p.17).
- The pathways are **intensity, not capex**. Capex appears only as an alternative input for
  projecting future intensity (footnote 2, p.16).

**Management Quality.**

- Levels 0–4: Unaware, Awareness, Building capacity, Integrating into operational decision
  making, Strategic assessment. Level 5 "Transition planning and implementation" is in beta
  (p.10).
- **Q21:** "Does the company commit to phasing out capital expenditure in carbon intensive assets
  or products?" This needs a time-bound phase-out of investments.
- **Q22:** "Does the company align future capital expenditures with its long-term decarbonisation
  goals and disclose how the alignment is determined?" (p.14).
- Both are Yes/No questions with no numbers.

**Licence.** TPI data is **not CC BY-NC-SA**. The LSE terms cover "the Carbon Performance data,
the Management Quality indicators and scores … as well as all related methodologies".
[verified](https://www.transitionpathwayinitiative.org/use-of-the-centre-s-data)

- Permitted without a licence: academic use, personal use, asset-owner use, investor engagement,
  media, and internal non-commercial use as a secondary input.
- Requires prior written authorisation or a licence:
  - any "reproduction, redistribution, republication … for any activity directly related to the
    generation of revenue";
  - creating "derived data and/or analytics directly related to the generation of revenue";
  - scraping;
  - building an index or fund.
- MQ licences go through LSEG. Only an "Insubstantial portion" may be reproduced.

---

## 7. Other primary sources (brief)

- **EU Taxonomy CapEx plan vs ACT forward share.** Both compare a *forward* plan, not one year's
  ratio. The Taxonomy plan has a 5-year horizon (10 years maximum). ACT plans run 3 or 5 years.
  See sections 3.1 and 4.
- **SBTi Corporate Net-Zero Standard v2:** no capex-share benchmark found. [not verified]
- **Mission Possible Partnership sector transition strategies:** publish absolute sector
  investment needs (e.g. aluminium ~USD 1 tn over three decades, per search results). The MPP
  pages returned 404 on direct fetch. [not verified]

---

## 8. The uploaded files

Files: `capex_alignment-2_1.txt` (Python) and `Capex_Alignment_Scoring_Template-2_1.xlsx`
(sheets: Instructions, Sector Benchmarks, Company Input, Scoring, ETF Holdings, ETF Dashboard).
Both carry the same seven sector ratios and redline texts. Both label the ratios as placeholders:

- the Python docstring says "values here are placeholders for the template structure, not
  published IEA/CTI figures";
- the xlsx Instructions B14 says "Numeric thresholds are illustrative placeholders".

### 8.1 Benchmark figures

| Sector (file) | `required_green_capex_ratio_2030` | Stated source in file | Primary evidence | Verdict |
|---|---|---|---|---|
| Oil & Gas (Upstream) | 0.30 | "IEA NZE 2050 + CTI … (CA100+ Indicator 6)" | CTI publishes no green-capex ratio. It reports % of upstream capex in *incompatible* projects (section 2.3). ACT O&G benchmark = **49%** (WEO 2019 SDS, p.126). IEA NZE system ratio 10:1 by 2030 (p.162). | **Unsupported placeholder.** The source label misattributes the figure to CTI. |
| Electric Utilities / Power | 0.60 | "IEA NZE + CTI Electric Utilities (CA100+ Ind. 6)" | ACT Electricity = **95%** from IEA NZE 2021–30 investment (p.134). CTI utilities test retirement schedules, not capex. PSF observed EU utilities 76% aligned in 2023 (p.23). | **Unsupported.** The primary benchmark is 95%. |
| Autos | 0.50 | "IEA NZE (ICE phase-out) + sector EV capex/R&D tracking" | ACT Auto uses an **80%** threshold, explicitly "no benchmarks are available" (p.41). IEA gives sales milestones, not capex (p.88). PSF observed EU carmakers ~30% aligned (p.11). | **Unsupported.** |
| Steel | 0.35 | "IEA NZE sector roadmap (EAF/H2-DRI)" | No primary capex-share benchmark. ACT steel uses locked-in emissions. NZE gives near-zero iron at 8% of production by 2030 (p.95), which is not capex. | **Unsupported.** |
| Cement | 0.25 | "IEA NZE sector roadmap (clinker + CCS)" | Same. NZE near-zero clinker 8% by 2030 (p.96). | **Unsupported.** |
| Aviation & Shipping | 0.20 | "IEA NZE + SAF/alt-fuel roadmaps" | None. ACT transport uses fleet locked-in emissions and an R&D threshold. TPI and RMI use intensity. | **Unsupported.** |
| Cross-Sector / Diversified | 0.15 | "EU Taxonomy Monitoring (PSF)" | PSF *observed* 2023 aligned share: 16% of total CapEx, 12.3% average company share (Table 2, p.25). ACT generic threshold 80%. | **Not a pathway.** It approximates an observed average, so it cannot serve as a 2030 requirement. |

Other numeric parameters, all **invented** (no source in any methodology):

- **0.75 × required** ratio to reach maturity level 3.
- **10 pp** gap for Red versus 0–10 pp for Amber.
- The roughly 0.1 traffic-light boundary implied by those two.

### 8.2 Redlines

| Redline text (file) | Closest primary source | Verdict |
|---|---|---|
| O&G: "No sanctioning of new oil/gas fields beyond pre-2021 committed projects" | NZE 2021 p.21 (exact match). NZE 2023 moved the cut-off: no new long-lead-time projects after 2023 (p.76). CTI Indicators 1–2 test this cost-based. CA100+ 6.1.a and TPI Q21 test a phase-out commitment. | Supported, but the wording is the 2021 version. |
| Power: "Coal retirement by ~2030 (OECD) / ~2040 (global); no new unabated coal or gas build" | Coal: NZE p.81 and p.92, CTI utilities p.5. **"No new … gas build" is not an NZE milestone.** NZE keeps gas plants for flexibility; unabated gas falls below 5% of generation by 2040 (p.92 figure). | Partly supported. The gas clause is invented. |
| Autos: "No material new ICE-only platform investment" | NZE: no ICE car sales after 2035 (p.88). Nothing on platform capex. | Loosely derived. |
| Steel: "No new conventional blast-furnace capacity without CCS" | Not found in NZE 2023. | Unsupported as written. |
| Cement: "CCS retrofit or clinker-substitution investment plan disclosed by 2030" | NZE has clinker-ratio and CCUS milestones (p.96), not a disclosure deadline. | Invented. |
| Aviation & Shipping: "SAF / alt-fuel capex share rising" | No primary source. | Invented. |
| Cross-sector: "Taxonomy-aligned capex disclosed and trending upward" | No primary source for a trend test. | Invented. |
| Ratio flat or declining for 2+ years; ratio improving only through divestment (denominator shrink) | No primary methodology tests either. | Invented, though reasonable. |
| "Green capex claim not traceable to taxonomy/lever methodology" | CA100+ 6.2.a requires a clear definition, "with reference to a formal taxonomy" or a stated framework. Eligible-only capex does not count. | Supported in spirit. |
| "No forward capex guidance disclosed" | CA100+ 6.2.b, Taxonomy CapEx plan, ACT planned share | Supported in spirit. |

### 8.3 Framework structure

**Maturity ladder 0–4.** The shape mirrors TPI's MQ levels 0–4 (and Level 5), but the labels and
rules are new. There is a logic gap:

- Level 3 does not require Level 2, in both the Python and the xlsx `G3` formula.
- So a company with `taxonomy_traceable = False` can still reach Level 3 or 4.

**Ratio vs a single 2030 point.** The files compare *this year's* ratio with a *2030* figure. ACT
compares a planned 3–5-year share with a constant decade benchmark. CA100+ and TPI score
commitments and amounts Yes/No. No source compares a current-year ratio with a 2030 point.

**Traffic light.** CA100+ alignment assessments do use traffic lights, but on project, asset or
intensity tests with their own cut-offs (sections 2.3 and 6). The files' gap cut-offs are
invented. ACT uses a continuous score instead: min(share / benchmark, 1).

**ETF aggregation.** No methodology here defines it.

- PACTA aggregates portfolios on production or capacity, not capex ratios.
- A NAV-weighted average of gaps measured against *different* sector benchmarks mixes units.
- **The Python and the xlsx disagree:**
  - Python skips holdings with no score and reports coverage as the scored weight.
  - The xlsx dashboard counts unscored holdings as a 0 ratio and a 0 gap (`IFERROR(…,0)`).
  - The xlsx "Coverage" column (D) is the sum of listed weights, not the scored weight.
- `green_capex_prior_year` and `data_source_quality` are read but never used. The
  `ratio_declining_flag` is typed in by the user rather than computed.

**Example data.** The rows are labelled illustrative. The tickers echo real issuers ("XOMPL",
"SHLPL", "NEEPL", "RWEPL", "VOWPL", "STLAPL", "HOLNPL", "DALPL", "SIEPL") and the ETF names use a
real fund brand ("Xtrackers … (illustrative)"). Don't ship them on a public page.

---

## 9. Recommendation for this platform

### 9.1 Company side: store both share and absolute amount

Every primary method either requires an absolute amount (CA100+ 6.1.b, 6.2.a and 6.2.b; CTI
reports both % and $) or scores a share whose absolute basis must be known (ACT, Taxonomy).

The platform already has most of the fields:

- `backend/arp/presets/green.py`: `capex_total`, `green_capex_total`, `green_capex_share_pct`,
  `green_capex_eu_aligned`, `transition_capex_total`.
- `backend/arp/presets/eu_taxonomy.py`: `eut_capex_aligned_pct`, `eut_capex_total_amount`, the
  eligible and non-eligible shares, enabling and transitional.
- `backend/arp/extraction/spend_extractor_agent.py`: cash-flow capex and its categories.

Gaps against the primary methods:

1. **Carbon-intensive capex amount** (CA100+ 6.1.b).
2. **Phase-out commitment and year** (CA100+ 6.1.a, TPI Q21).
3. **Planned / forward low-carbon capex**, amount and horizon (CA100+ 6.2.b, ACT next 3–5 years,
   Taxonomy CapEx plan).
4. Keep the **denominator source** with each share. The Taxonomy CapEx denominator (IFRS additions
   including right-of-use and acquisitions) is not cash-flow PP&E purchases (section 3.1).

### 9.2 Pathway side: per sector

| Sector | Recommended pathway or benchmark | Why | Licence status |
|---|---|---|---|
| Power | Share benchmark **95%** (ACT, from IEA NZE 2021–30). Plus coal milestones from NZE 2023 (no new unabated coal; phase-out 2030s/2040). | Only published capex-share benchmark with a scenario derivation | ACT reproduction needs permission. The NZE milestones come from report text (CC BY 4.0). Alternatively, derive the share from IEA report figures (not Annex A). |
| Oil & gas | Redline from NZE 2023 (no new long-lead-time projects after 2023). Share benchmark 49% (ACT 2021, WEO 2019 SDS) only if the owner accepts a dated, non-1.5°C basis. | CTI's compatible-capex test needs Rystad project data and CTI's model, which the platform cannot reproduce | NZE text CC BY 4.0. ACT and CTI need permission or are non-commercial. |
| Chemicals | 54% (ACT, borrowed from O&G) | Only figure published. ACT says it is a proxy. | ACT permission |
| Autos | NZE sales milestones (65% EV by 2030, no ICE after 2035) as the pathway. 80% (ACT) only as an expert threshold, labelled as such. | No scenario-derived capex benchmark exists | NZE text CC BY 4.0. ACT permission. |
| Steel, cement, aluminium | **No capex-share score.** Report share and amount. Judge alignment on intensity or physical milestones: NZE near-zero production shares (CC BY 4.0), or TPI CP (licence). | No primary source gives a capex share. ACT replaced it with locked-in emissions. | NZE text OK. TPI and RMI data need a licence. |
| Aviation, shipping | **No capex-share score.** Intensity pathways (TPI with ICAO/IMO pledges, RMI airlines). | Same | TPI licence |
| Cross-sector / diversified | Taxonomy-aligned share vs PSF *observed* peer levels (16% overall, 76% utilities, ~30% carmakers, 9% manufacturing, 2023). Context only, never "required". | No pathway exists | EU CC BY 4.0. Bloomberg/Orbis caveat. |

**Storage.** Keep any adopted figures as a curated, owner-signed, cited data set in the same
pattern as `backend/arp/transition_barrier/data/rule_book.json` (versioned, fingerprinted,
`approved_by`). Each row would carry: figure, unit, scope, scenario, publication, page, licence
and retrieval date.

**What to drop or re-specify from the uploaded engine:**

- the seven ratios;
- the 0.75 factor;
- the 10 pp cut-off;
- the gas-build and steel/cement redlines;
- the xlsx/Python aggregation mismatch.

### 9.3 Owner decisions needed

1. **Licences:** request permission from ADEME/CDP (ACT) to store and display the 95%, 49%, 54%
   and 80% benchmarks commercially, or derive the platform's own figures from IEA CC BY 4.0 report
   content. CTI, CA100+ and TPI are non-commercial or licence-only (TPI MQ via LSEG).
2. **Steel, cement, aluminium, aviation, shipping:** accept that these get no capex-share score
   (only share, amount and an intensity or milestone pathway)? Otherwise a non-published benchmark
   would have to be invented and labelled.
3. **Oil & gas basis:** use ACT 49% (SDS 2019, 2021), or only the NZE 2023 no-new-projects redline
   and system ratio.
4. **What counts as "green":** `green.py` keeps nuclear and gas out of green (as transition),
   while ACT electricity counts nuclear and fossil with CCUS as low-carbon. A benchmark only
   applies if the numerator uses the same definition.
5. **Denominator:** Taxonomy CapEx or cash-flow capex. They must not be mixed.
6. **Current-year vs planned capex:** primary methods favour planned (3–10-year) shares. That
   needs new extraction fields (section 9.1, items 1–3).
7. **ETF/portfolio aggregation:** whether to aggregate at all across sectors with different
   benchmarks, and how to treat unscored holdings.

---

## 10. Unverified / could not access

- **iea.org (terms, dataset pages):** HTTP 403 (Cloudflare) on curl and WebFetch. The IEA site
  terms and the WEO 2024 free-dataset licence (CC BY-NC-SA 4.0) are from search extracts only.
  The NZE 2023 licence *is* verified on the report's own copyright page.
- **IEA WEO 2025 and World Energy Investment 2025:** not opened. Whether WEO 2025 updates the NZE
  investment or ratio figures is unchecked.
- **EUR-Lex HTML and PDF:** blocked (HTTP 202 challenge). Both delegated acts were read from the
  EU Publications Office (`publications.europa.eu/resource/celex/…`) instead. Whether Omnibus I
  changes the Article 8 *scope* (which companies report) was not checked.
- **Mission Possible Partnership:** press-release and report URLs returned 404. Sector investment
  figures are not verified.
- **SBTi Corporate Net-Zero Standard v2:** the standard text was not read. No capex-share
  benchmark was found in search.
- **TPI:** v5.0 (Nov 2023) is the newest methodology report found. A later version may exist.
- **CA100+:** no v2.3 or 2026 framework was found on the methodology page at retrieval
  (2026-10-19).
- **ACT O&G:** the methodology read is the 2021 "vf" edition. A newer O&G edition may exist.
- **PSF:** a second monitoring edition (FY2023–2025 data) was announced for a 20 October 2026
  webinar. It is not yet published, so not read.
