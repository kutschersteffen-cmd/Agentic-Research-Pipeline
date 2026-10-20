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
  [Unverified / could not access](#11-unverified--could-not-access) and section 10.7 (round 2).

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

**Round 2 changes (updated round 2).** Details and sources are in section 10.

- **ACT Core (WBA/ADEME, Feb 2025)** scores low-carbon capex share in one matrix: power 95%, oil and
  gas **77%**, chemicals **77%**, autos and generic 20/40/60/80% bands. The 77% replaces the sector
  methods' 49% and 54% there, with no stated derivation. WBA used it for 2,000 companies in 2026.
- **Steel, cement, aluminium, aviation, shipping still have no scenario-derived capex share.** ACT
  Core's generic 80% bands apply to them by fallback. The only sector numbers are R&D-based:
  steel and aluminium 80% of R&D low-carbon (65% non-mature); **cement 5% of total capex spent on
  mitigation R&D**; airlines and shipping 80% R&D share.
- **CA100+ 2026:** Indicator 6 unchanged. Capex alignment exists for oil and gas only (CTI: share of
  capex in NZE/APS-incompatible projects; amber <50%, red 50–100%).
- **TPI NZS oil and gas (June 2026):** Yes/No capex disclosure tests needing at least 3 years of
  forward capex, comparable with total capex. No numeric benchmark.
- **Licences:** WBA reports and datasets are CC BY 4.0 (Transport 2022 report: CC BY-NC-ND). ACT
  methodology PDFs, ACT Core included, are not: reproduction needs WBA/ADEME permission. TPI
  methodology notes are CC BY-NC 4.0; TPI data still needs a licence. CTI stays non-commercial.

**Round 3 changes (updated round 3).** Details and sources are in section 12.

- **Use is internal and non-commercial (owner decision).** Benchmark figures and WBA data may be
  used with citation. The "commercial" licence column below is kept for the record only.
- **ACT Core 2026 gives a letter grade, not a score.** A–G from transition plan quality (0–5) and
  contribution to the transition (0–2). No weights, no "4B+" rating. Capex enters through one
  element, D01.a, as a maturity band (Unmet…Low-carbon aligned).
- **D01.a is public for all 2,000 companies** (maturity level only). 76% are Unmet. The underlying
  capex amounts sit in WBA's Data Explorer (free login, API on approval, CSV/JSON, ISIN/LEI).
- **In the 2020–2024 sector benchmarks a capex-share indicator weighed only 3–8%** of the ACT
  performance score. Heavy industry relied on locked-in emissions (8–13%) instead.
- **WBA scores can be a cross-check, not our primary capex input:** bands not amounts, generic
  thresholds for steel/cement/aluminium/aviation/shipping, one 2026 edition, English-only
  disclosure (several Chinese steel mills unscored).
- **Licence wording conflicts:** the WBA disclaimer says CC BY 4.0, the fair-use page says
  CC BY-NC-ND 4.0, and the 2020–2021 datasheets are CC BY-NC-ND. All are fine for internal use.

**Round 4 changes (updated round 4).** Details and sources are in section 13.

- **ACT sector scores are now out of 100, not 20.** ACT Framework v2.1 (December 2025) sets the
  performance score at 0–100. The 0–20 scale in section 12.2.1 is the WBA 2020–2024 editions.
  Narrative stays A–E, trend stays +/=/−.
- **ACT has no test of an absolute capex amount and no carbon-intensive capex indicator.** Every
  ACT capex test is a share. The amount only enters through ACT Core B02.d, which asks for a clear
  link between each lever and its funding.
- **Locked-in emissions has an exact, reproducible formula:** cumulative emissions of existing and
  planned assets to RY+15 divided by the company's carbon budget, scored against a secured-activity
  ratio. It needs asset-level data (capacity, emission factor, commissioning year, lifetime).
- **The owner's shared Gemini link is a near-verbatim reconstruction of ACT Core v1.0.** Most of it
  matches the PDF. Two appendix tables are garbled, one D01.a cell is misplaced, and the D01.a year
  rule and B02.d's link test are missing. It says nothing about the sector methods.
- **Owner decision 2026-10-19:** adopt ACT Core B02.d as the test for investment linked to actions,
  and the D01.a current-plus-planned (RY/RY+1) capex rule. Do not use the undocumented WBA JSON
  feed. Data Explorer registration is deferred (section 9.3, item 8).

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
| Oil & gas | 0.30 | ACT 49% (2021 sector method); ACT Core 77% (2025) (updated round 2) |
| Autos | 0.50 | ACT 80% |

(updated round 2) Steel 0.35, cement 0.25 and aviation/shipping 0.20 still have no primary capex
benchmark. ACT Core's generic bands would put full marks at 80%. Cement's 5% (ACT CEM 3.1) is
mitigation R&D over total capex, a different metric, so it cannot check the 0.25.

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
5. (updated round 2) **Forward horizon and sub-splits.** TPI NZS oil and gas asks for current-year
   and at least 3-year forward capex, in a format comparable with total capex, split by upstream,
   exploration, LNG, climate solutions, removals and operational abatement (section 10.3). ACT Core
   reads RY and RY+1 (section 10.5).
6. (updated round 2) **Low-carbon R&D amount and total R&D.** It is the only sector-specific
   numeric investment test for steel, cement, aluminium, airlines and shipping (section 10.6).

### 9.2 Pathway side: per sector

| Sector | Recommended pathway or benchmark | Why | Licence status |
|---|---|---|---|
| Power | Share benchmark **95%** (ACT, from IEA NZE 2021–30). Plus coal milestones from NZE 2023 (no new unabated coal; phase-out 2030s/2040). | Only published capex-share benchmark with a scenario derivation | ACT reproduction needs permission. The NZE milestones come from report text (CC BY 4.0). Alternatively, derive the share from IEA report figures (not Annex A). |
| Oil & gas | Redline from NZE 2023 (no new long-lead-time projects after 2023). Share benchmark 49% (ACT 2021, WEO 2019 SDS) only if the owner accepts a dated, non-1.5°C basis. (updated round 2) ACT Core 2025 uses 77% instead, with no derivation; pick one and label it. | CTI's compatible-capex test needs Rystad project data and CTI's model, which the platform cannot reproduce | NZE text CC BY 4.0. ACT and CTI need permission or are non-commercial. |
| Chemicals | 54% (ACT, borrowed from O&G). (updated round 2) ACT Core says 77%. | Only figures published. ACT says 54% is a proxy. | ACT permission |
| Autos | NZE sales milestones (65% EV by 2030, no ICE after 2035) as the pathway. 80% (ACT) only as an expert threshold, labelled as such. | No scenario-derived capex benchmark exists | NZE text CC BY 4.0. ACT permission. |
| Steel, cement, aluminium | **No capex-share score.** Report share and amount. Judge alignment on intensity or physical milestones: NZE near-zero production shares (CC BY 4.0), or TPI CP (licence). (updated round 2) Optionally add the ACT R&D tests (steel and aluminium 80%/65% of R&D; cement 5% of capex on mitigation R&D), labelled as R&D tests. WBA Heavy Industries 2024 company scores (locked-in emissions, R&D) are a CC BY 4.0 input. | No primary source gives a scenario-derived capex share. ACT uses locked-in emissions; ACT Core only offers generic 80% bands by fallback. | NZE text OK. TPI and RMI data need a licence. ACT figures need permission. WBA scores CC BY 4.0. |
| Aviation, shipping | **No capex-share score.** Intensity pathways (TPI with ICAO/IMO pledges, RMI airlines). (updated round 2) ACT Transport R&D share 80% as an optional labelled test. | Same | TPI licence. ACT permission. WBA Transport 2022 report is CC BY-NC-ND. |
| Cross-sector / diversified | Taxonomy-aligned share vs PSF *observed* peer levels (16% overall, 76% utilities, ~30% carmakers, 9% manufacturing, 2023). Context only, never "required". (updated round 2) ACT Core Table 11 "typical" levels (e.g. Metals & Mining <25%, Construction Materials <5%) are also observed context, not targets. | No pathway exists | EU CC BY 4.0. Bloomberg/Orbis caveat. ACT Core needs permission. |

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

1. **Licences:** (updated round 3) **Decided by the owner: the platform is non-commercial and for
   internal use, so benchmark data (ACT figures, WBA scores and datasets, TPI, CTI, CA100+) may be
   used with citation.** Store each figure with its source, page and licence line (section 9.2,
   Storage). Ask WBA/ADEME (and CDP for older ACT sector methods) only if outputs will be shared
   outside the organisation; WBA's own wording ranges from CC BY 4.0 to CC BY-NC-ND 4.0 (section
   12.5). Original text: request permission from ADEME/CDP (ACT) to store and display the 95%, 49%, 54%
   and 80% benchmarks commercially, or derive the platform's own figures from IEA CC BY 4.0 report
   content. CTI, CA100+ and TPI are non-commercial or licence-only (TPI MQ via LSEG).
   (updated round 2) WBA now co-owns ACT (ACT Core is "© World Benchmarking Alliance, ADEME 2025"),
   so one request to WBA and ADEME could cover ACT Core and the sector figures. WBA's own reports
   and scores are already CC BY 4.0 and need no request. TPI method text is CC BY-NC 4.0, which
   still excludes commercial use.
2. **Steel, cement, aluminium, aviation, shipping:** accept that these get no capex-share score
   (only share, amount and an intensity or milestone pathway)? Otherwise a non-published benchmark
   would have to be invented and labelled. (updated round 2) Round 2 found no scenario-derived
   capex share for any of them. Two published options now exist, both needing ACT permission:
   (a) ACT Core's generic 20/40/60/80% bands, an expert threshold; (b) the ACT R&D tests (cement 5%
   of capex; steel and aluminium 80%/65% of R&D).
3. **Oil & gas basis:** use ACT 49% (SDS 2019, 2021), or only the NZE 2023 no-new-projects redline
   and system ratio. (updated round 2) Or ACT Core's 77% (2025, used by WBA in 2026, no stated
   derivation). The three must not be mixed.
4. **What counts as "green":** `green.py` keeps nuclear and gas out of green (as transition),
   while ACT electricity counts nuclear and fossil with CCUS as low-carbon. A benchmark only
   applies if the numerator uses the same definition.
5. **Denominator:** Taxonomy CapEx or cash-flow capex. They must not be mixed.
6. **Current-year vs planned capex:** primary methods favour planned (3–10-year) shares. That
   needs new extraction fields (section 9.1, items 1–3).
7. **ETF/portfolio aggregation:** whether to aggregate at all across sectors with different
   benchmarks, and how to treat unscored holdings.
8. (updated round 2) **Use WBA company scores as an input?** The Heavy Industries 2024 datasheet
   (CC BY 4.0) gives company-level ACT results, including locked-in emissions and R&D. WBA also
   publishes datasheets for oil and gas, utilities, transport and transport makers (not opened, so
   their licence lines are unchecked). They are 2021–2024 snapshots, and WBA "reserves the right to
   review and amend" its licence terms.
   (updated round 3) Recommended: yes, as a cross-check and fallback, not as the primary capex
   input (section 12.6). Decide (a) whether to register for WBA's Data Explorer and request API
   access, to get the D01.a capex amounts behind the public maturity levels; (b) whether to use the
   undocumented public D01.a JSON meanwhile; (c) whether to adopt ACT Core's RY/RY+1 rule for
   combining current and planned capex; (d) whether to use ACT Core B02.d ("a clear link between
   the identified action and the financial requirements") as the acceptance test for capex behind
   an extracted plan action. All other datasheets are now checked: 2023–2024 are CC BY 4.0,
   2020–2021 are CC BY-NC-ND 4.0.
   (updated round 4) **Decided by the owner on 2026-10-19:**
   - (c) **Adopted.** Combine current and planned capex with ACT Core D01.a's rule: if only RY is
     known, use RY; if RY+1 is higher, use RY+1; if lower, use the average of RY and RY+1
     ([ACT Core p.61](https://actinitiative.org/wp-content/uploads/pdf/act-core-methodology.pdf)).
   - (d) **Adopted.** B02.d is the acceptance test for investment behind an extracted plan action:
     funding is described, a clear link to the action exists, and needs are split from funds
     allocated ([ACT Core p.37](https://actinitiative.org/wp-content/uploads/pdf/act-core-methodology.pdf)).
   - (b) **Rejected.** Do not use the undocumented public WBA D01.a JSON feed.
   - (a) **Deferred.** No Data Explorer registration for now.
   Still open: which share thresholds sit on top of the RY/RY+1 value (ACT Core bands, or the sector
   ratio min(share / benchmark, 1)), and the oil and gas benchmark (item 3). See section 13.4.

---

## 10. Round 2: Carbon Tracker, TPI, CA100+ and WBA capex guidance

Status: **round 2 research note, 2026-10-19.** Every PDF below was downloaded and read as text,
except the WBA oil and gas 2023 methodology (a scanned PDF, read page by page as images). Page
numbers in this section are **PDF page numbers** unless marked otherwise. No site returned HTTP
403 in round 2. Failures were HTTP 404s and login walls (section 10.7).

### 10.1 What is new versus round 1

1. **ACT Core (WBA and ADEME, v1.0, 24 February 2025)** puts the ACT capex-share benchmarks in one
   cross-sector matrix. It uses **77%** for oil and gas and for chemicals, not the 49% and 54% of the
   sector methods. Sectors with no ACT capex benchmark (steel, cement, aluminium, aviation, shipping)
   fall back to a **generic 20/40/60/80% band**. WBA scored 2,000 companies with it in its 2026
   Climate Benchmark. [verified, section 10.5]
2. **Cement has one capex-denominated number:** ACT Cement CEM 3.1 compares mitigation **R&D**
   with **total capex**, against a **5%** benchmark. It is an R&D intensity, not a low-carbon capex
   share. [verified, section 10.5]
3. **Steel and aluminium** have only R&D-share benchmarks (80% of R&D low-carbon, 65% of that
   non-mature). Aviation and shipping have none beyond round 1's ACT Transport R&D threshold.
   No scenario-derived low-carbon capex share exists for any of these five sectors.
4. **CA100+ 2026 (30 April 2026):** Indicator 6 is unchanged. CTI's oil and gas alignment keeps only
   its two capex indicators, and drops production and oil price. WBA joins as a provider (governance
   and absolute emissions), not for capex. [verified, section 10.4]
5. **TPI Net Zero Strategies framework for oil and gas (v1.0, 16 June 2026)** adds Yes/No capex
   *disclosure* tests: current-year and at least three years of forward capex, split by upstream,
   exploration, LNG, climate solutions, removals and operational abatement. Still no numeric capex
   benchmark. [verified, section 10.3]
6. **Licences:** WBA's own reports and datasets are CC BY 4.0, with one exception (Transport 2022
   report, CC BY-NC-ND 4.0). The ACT methodology PDFs, where every benchmark number lives, are
   still "reproduction … prohibited" without permission, ACT Core included. TPI methodology notes
   are CC BY-NC 4.0, while TPI data stays licence-only. [verified, sections 10.3 and 10.5]

### 10.2 Carbon Tracker Initiative (CTI)

**CA100+ oil and gas alignment, by edition.** All three editions measure the share of upstream
capex in projects that are *not* needed under a scenario. None measures a green capex share.

| Edition | Scenarios | Capex metric | Thresholds | Source |
|---|---|---|---|---|
| Nov 2021 | IEA B2DS (core), SDS, STEPS as business as usual | Unsanctioned capex inconsistent with B2DS, as % of unsanctioned capex inside STEPS | Green 0%. Amber 0–25%. Red >25% ("significant misalignment"). Projects ranked by breakeven at a 15% IRR hurdle. | [PDF p.4](https://www.climateaction100.org/wp-content/uploads/2021/11/CTI-CA100-Benchmark-Alignment-Indicators-Methodology_Nov21.pdf) [verified] |
| Aug 2023 | IEA WEO 2022 NZE, APS, STEPS | Ind. 1: recent (2022) sanctioned capex. Ind. 2: potential future capex. Both % and $. | Ind. 1: green if not incompatible with NZE, amber if not incompatible with APS, red otherwise. Ind. 2: green NZE-compatible; amber <50% APS-incompatible; red 50–100%. Price deck: NZE $35/bbl (2030), $24 (2050); APS $64, $60 (USD 2021). | [PDF pp.7–9, 16](https://www.climateaction100.org/wp-content/uploads/2023/10/2023-CTI-Oil-and-Gas-Methodology.pdf) [verified] |
| Aug 2025 | IEA WEO 2024 NZE, APS, STEPS | Same as 2023, sanction year 2024 | Same as 2023. Formula: "% of CapEx incompatible with APS = CapEx associated with projects that are incompatible with APS as a % of total CapEx with projects that are compatible with STEPS". The $42/bbl cut-off in Figure 1 is illustrative. | [PDF p.15](http://www.climateaction100.org/wp-content/uploads/2025/10/CarbonTracker_CA100methodology_OilandGas_202521-copy.pdf) [verified] |
| 2026 | as 2025 | Indicators 1 and 2 only | Production and oil price indicators "discontinued in 2026" | [CA100+ 2026 updates, PDF p.2](http://www.climateaction100.org/wp-content/uploads/2026/05/CA100-03-2026-Net-Zero-Company-Benchmark-Framework-Updates-v12.pdf) [verified] |

**Utilities.** The last CTI utilities assessment is 2023 (section 2.3), a retirement test. CTI's
data portal lists coal and gas power companies with "View chart" links but shows no values on the
index page. Footer: "All Rights Reserved".
[verified](https://data.carbontracker.org/companies/alignment-benchmarks)

**CTI's own reports (outside CA100+).**

- *Paris Maligned III* (8 April 2025) grades 30 producers on six metrics, among them "Investment
  options" and "Recent project sanctions". The web page gives no weights or thresholds; the PDF
  needs a login and was not read. [verified for the page](https://carbontracker.org/reports/paris-maligned-iii/)
  An earlier edition weighted future investment options 30% and recent sanctions 10%. [search
  extract, edition not identified]
- *Absolute Impact 2026* (22 April 2026) assesses the emissions targets of 30 companies. The page
  names no capex metric; the flash note needs a login.
  [verified for the page](https://carbontracker.org/reports/absolute-impact-2026/)
- **No CTI capex method for steel, cement, autos, aviation or shipping was found.** Industry
  Tracker, a separate group started by CTI's founders, works on steel. [search extract](https://carbontracker.org/industry-tracker-new-climate-research-house-for-investors-launches-today)

**Licence.** The methodology PDFs (2023 and 2025) say readers may reproduce material "as long as
they are not being sold commercially" (2023 PDF p.2). The website says "All Rights Reserved". The
terms page returned 404. So CTI is still non-commercial. [verified]

### 10.3 TPI Centre (LSE)

**Management Quality (MQ).** The framework is still v5.0 with 23 Yes/No indicators. The LSEG
scoring methodology (July 2026) confirms the capex items.
[verified, PDF pp.9, 19, 22](https://www.lseg.com/content/dam/data-analytics/en_us/documents/methodology/lseg-transition-pathway-initiative-tpi-management-quality-scores.pdf)

| Item | Level | Text | Data point |
|---|---|---|---|
| MQ15 | 4 | Discloses the impact of climate risks and opportunities "on financial planning (OPEX, CAPEX, M&A, debt)" | DP162 |
| MQ21 | 5 | "explicitly commit to a time-bound phase-out of investments in carbon intensive assets or products" | DP178 |
| MQ22 | 5 | "commit to align all future capital expenditures with their long-term GHG targets or with the Paris Agreement's objective of limiting global warming to 1.5°", and "disclose the methodology used" | DP177, DP179 |

- No MQ item has a numeric capex threshold. [verified; also v5.0 report PDF pp.13–14]
- Uptake is tiny. "Fewer than 1% of companies have committed to align capital expenditure with
  their decarbonisation goals (MQ22)"; "only 2%" commit to phase out carbon-intensive capex. MQ22
  is the only indicator that did not improve.
  [State of the Corporate Transition 2025, PDF pp.15–16](https://researchonline.lse.ac.uk/id/eprint/130118/1/State_of_Transition_Report_2025_v25_-_final_cover.pdf) [verified]
  That report labels the phase-out item MQ19, while LSEG labels it MQ21. Use the text, not the
  number.

**Net Zero Strategies (NZS) framework for oil and gas, v1.0 (16 June 2026).**
[verified, PDF pp.7, 14–15, 24](https://www.transitionpathwayinitiative.org/asset-library/methodologies/26-06-nzs-oil-and-gas-methodology-v1.pdf)

- Four indicator types. "Capital expenditure and planning" indicators are Yes/No.
- Capex indicators: OE.3 (operational emissions reduction capex), UP.5 (upstream capex), UP.6
  (exploration capex), MD.3 (LNG capex), NM.4 (technology-based removals capex), CS.4 (climate
  solutions capex).
- Each needs the current-year value and "a forward-looking value at least three years in the
  future". It must be "disclosed in a format consistent with the company's disclosed total capex to
  enable the calculation of ratios".
- UP.8: a commitment to stop approving new oil and gas fields, citing the IEA NZE.
- Alignment indicators (UP.a, UP.b, CS.a, ME.a) score production or methane paths against TPI's
  1.5°C, Below 2°C and National Pledges scenarios. **They do not score capex.**
- A diversified mining NZS v1.0 was published the same day. Not read.

**Other TPI items.**

- *Net Zero Banking Assessment Framework v1.2 (12 Oct 2026)*, 4.2 "Capital allocation to misaligned
  activities": bank exclusion policies, e.g. unabated coal phase-out "by 2030 in EU and OECD
  countries and by 2040 in the rest of the world". Bank-level, not company capex.
  [verified, PDF p.24](https://www.transitionpathwayinitiative.org/asset-library/methodologies/26-10-nzbaf-methodology-v1.2.pdf)
- *Carbon Performance sector notes* for steel (v5.0, Oct 2024), cement (v5.0) and airlines (v5.0)
  mention capex only in a stock sentence about "business strategy and capital expenditure plans"
  (steel PDF p.5). They are intensity benchmarks.
  [steel](https://www.transitionpathwayinitiative.org/asset-library/methodologies/24-10-steel-methodology-v5.pdf),
  [cement](https://www.transitionpathwayinitiative.org/asset-library/methodologies/24-10-cement-methodology-v5.pdf),
  [airlines](https://www.transitionpathwayinitiative.org/asset-library/methodologies/24-10-airlines-methodology-v5.pdf) [verified]
- The CP 2026 update moves the short-term year to 2030 and adds chemicals. No capex item.
  [verified](https://www.transitionpathwayinitiative.org/knowledge-hub/insights/carbon-performance-research-update-2026)
- ASCOR is a sovereign framework. Not checked for capex.

**Licence (re-checked).**

- The data terms were "Updated in September 2026". Still restricted without a licence:
  reproduction "for any activity directly related to the generation of revenue", "derived data
  and/or analytics directly related to the generation of revenue", derivative works, indexes and
  funds. Only an "Insubstantial portion" may be reproduced. MQ licences go via LSEG. No Creative
  Commons mention. [verified](https://www.transitionpathwayinitiative.org/use-of-the-centre-s-data)
- **New: TPI methodology notes carry their own licence.** "Published under a Creative Commons CC
  BY-NC 4.0 licence" (NZS oil and gas, NZBAF v1.2, State of the Corporate Transition 2025) or
  "CC BY-NC" (steel and cement v5.0). So the *method text* may be reused non-commercially with
  credit. Commercial reuse still needs permission (tpi.centre@lse.ac.uk). [verified]
- LSEG's scoring document: "Republication or redistribution of LSE Group content is prohibited
  without our prior written consent". [verified]

### 10.4 Climate Action 100+

**Indicator 6 (unchanged).** The full v2.1 text is in section 2.2. The 2026 framework renames it
"Capital Allocation Disclosure" and says "This Indicator remains the same for 2026". The TPI Centre
still assesses it. All metrics are Yes/No. There is no numeric pass mark.
[2026 overview, PDF p.2](http://www.climateaction100.org/wp-content/uploads/2026/04/CA100-03-2026-Net-Zero-Company-Benchmark-Framework-Overview-v9.pdf),
[2026 updates, PDF p.2](http://www.climateaction100.org/wp-content/uploads/2026/05/CA100-03-2026-Net-Zero-Company-Benchmark-Framework-Updates-v12.pdf) [verified]

**Alignment assessments by sector.**

| Sector | Last assessed | Provider | Capex test? | Thresholds |
|---|---|---|---|---|
| Oil and gas | 2025, and 2026 (two indicators) | CTI | Yes: % of capex in NZE/APS-incompatible projects | Section 10.2 |
| Electric utilities | 2023 (CTI); 2024 (RMI) | CTI, RMI | No: retirement schedules, capacity plans | CTI 100% green, 75–99% amber |
| Autos | 2024 | RMI | No: production plans | n/a |
| Steel, cement, airlines | 2024 | RMI | No: intensity gap to 2030 | Section 2.3 table |

- 2025: "these measures have not been reassessed" for steel, cement, autos and utilities (round 1).
- 2026: the overview describes sector-specific alignment for "the oil and gas sector" only: "whether
  companies' recent and potential spending on oil and gas projects are aligned with a Paris-aligned
  climate pathway". [verified, overview PDF p.2]
- **No CA100+ capex alignment for steel or cement has ever been published.** RMI's 2024 steel and
  cement tests use intensity.

**2026 provider changes.** WBA takes over Indicator 8 (governance, from ACT Core) and the absolute
emissions part of Indicator 10. InfluenceMap takes all of Indicator 7. Former Indicator 10
(TCFD/ISSB disclosures) is removed. Results are due October 2026.
[verified, updates PDF p.2](http://www.climateaction100.org/wp-content/uploads/2026/05/CA100-03-2026-Net-Zero-Company-Benchmark-Framework-Updates-v12.pdf)
The 2026 papers show TPI continuing as the main disclosure assessor. No document found says the
Benchmark is being handed over to TPI. [not verified beyond these papers]

**Licence.** Unchanged from section 2.4: CA100+ site content is non-commercial without written
permission. Not re-fetched in round 2.

### 10.5 World Benchmarking Alliance (WBA)

**Role.** WBA hosts ACT with ADEME. Its 2020–2024 Climate and Energy Benchmarks scored each sector
with the ACT sector methods. Its 2026 Climate Benchmark scored 2,000 companies with **ACT Core**.
[verified](https://www.worldbenchmarkingalliance.org/latest/methodology-2026-act-core-assessment)

**ACT Core v1.0, element D01.a "The company is investing in climate solutions".**
[verified, PDF pp.58–62](https://actinitiative.org/wp-content/uploads/pdf/act-core-methodology.pdf)

- Data: total capex and climate-solutions capex for the reporting year (RY) and RY+1; total and
  climate-solutions R&D for RY and RY−1.
- Taxonomy-aligned capex counts. "'Taxonomy eligible' investments/expenditures cannot be used".
- Year rule: if RY+1 is higher, score RY+1. If lower, score the average of RY and RY+1.
- Capex is preferred over R&D where a sector has both.
- Maturity matrix (PDF p.62). LC = low-carbon capex share.

  | Sector | Basic | Standard | Advanced | Next practice | Low-carbon aligned |
  |---|---|---|---|---|---|
  | Electricity | LC/95% < 0.20 | 0.21–0.40 | 0.41–0.60 | 0.61–<1 | ≥ 1 |
  | Oil and gas | LC/77% < 0.20 | 0.21–0.40 | 0.41–0.60 | 0.61–<1 | ≥ 1 |
  | Chemicals | LC/77% < 0.20 | 0.21–0.40 | 0.41–0.60 | 0.61–<1 | ≥ 1 |
  | Automotive | < 20% | 21–40% | 41–60% | 61–80% | > 80% |
  | Generic | < 20% | 21–40% | 41–60% | 61–80% | > 80% |
  | Agriculture (capex) | < 10% | (blank) | 11–20% | (blank) | > 20% |
  | Generic (R&D share) | < 20% | 21–40% | 41–60% | 61–80% | > 80% |

- "For industries without specific benchmarks or maturity matrices in existing ACT Sectoral
  methodologies … the generic option in the matrix below should be used". Steel, cement,
  aluminium, aviation and shipping have no ACT capex matrix, so the generic bands apply to them.
  (Our reading of the rule. WBA's per-company data would confirm it.)
- **The 77% for oil and gas and chemicals has no stated derivation.** It differs from ACT O&G 2021
  (49%, still the edition on the ACT site) and ACT Chemicals (54%). Treat it as unexplained.
- Appendix 10.3, Table 11 (PDF pp.116–117) gives **"typical"** low-carbon capex by industry. These
  are observed reference levels, mostly from CDP *Get the money moving 2024* p.26, not pathways:
  Metals & Mining <25%; Construction Materials <5%; Chemicals <10%; Oil & Gas <25%; Utilities
  <50%; Motor Vehicles <50%; Freight & logistics <10%; Capital Goods <5%; Passenger Transport NA.

**WBA 2026 methodological note** (file dated 2026-01, "_v2").
[verified, PDF p.4](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-01/Methodological%20note%20on%20the%202026%20ACT%20Core%20assessments_v2.pdf)

- "Inconsequential planning": "no evidence that the company is mobilizing low-carbon investments
  through capital expenditure (CapEx) or R&D (D01.a is unmet)".
- "Consequential planning": low-carbon capex or R&D that "account for no more than 10–20% of total
  investment, depending on the sector (D01.a at least Basic)".
- "1.5°C aligned and planning": "significant low-carbon investments, typically accounting for 40% or
  more of total investment (D01.a at least Standard)". Note: Standard for oil and gas starts at
  0.21 × 77% ≈ 16%, so "40%" is WBA's rough summary, not the matrix.
- Pathway library (absolute emissions): steel ISF-OECM and SBTi-NZE; cement ISF-OECM; aluminium
  ISF-OECM; shipping use ISF-OECM; plane use IEA-NZE; power Climate Analytics and ISF-OECM; oil
  production IEA-NZE. These score targets and emissions, not capex.

**Sector benchmarks 2020–2024.** Methodologies and datasets are listed on two WBA pages.
[methodologies](https://www.worldbenchmarkingalliance.org/methodologies-climate-and-energy-benchmarks-2020-2024),
[datasets](https://www.worldbenchmarkingalliance.org/data-sets-climate-and-energy-benchmarks-2020-2024) [verified]
WBA ran no separate chemicals benchmark in that period.

| WBA benchmark | ACT method used | Capex-related indicator | Numeric value | Source |
|---|---|---|---|---|
| Heavy Industries 2024 (45 steel, 34 cement, 12 aluminium) | ACT Iron & Steel, Cement, Aluminium v2.0. 60% ACT, 40% social. Pathways: aluminium IAI, cement IEA NZE 2023, steel SBTi. | Locked-in emissions of current and planned assets 2023–2038 vs 1.5°C carbon budget (IS 2.3, CEM 2.2a, AL 2.2). R&D (Module 3). | No capex share | [methodology PDF p.5](https://assets.worldbenchmarkingalliance.org/app/uploads/2023/12/Heavy-Industries-2024-Methodology.pdf), [FAQ PDF pp.6, 8](https://assets.worldbenchmarkingalliance.org/app/uploads/2024/04/Heavy-Industries-FAQ-2024-1.pdf) [verified] |
| ↳ Steel | ACT Iron & Steel IS 3.1 (weight 2–10%) | Low-carbon R&D ÷ total R&D; non-mature ÷ low-carbon R&D (3-year averages) | Full score at **80%** and **65%**; 50/50 | [ACT steel PDF pp.75–76](https://actinitiative.org/wp-content/uploads/act-iron-steel-methodo_v2.0.pdf) [verified] |
| ↳ Aluminium | ACT Aluminium AL 3.1 (10%) | Same as steel | **80%** and **65%** | [ACT aluminium PDF pp.75–76](https://actinitiative.org/wp-content/uploads/act-aluminium_v2.0.pdf) [verified] |
| ↳ Cement | ACT Cement CEM 3.1 (10%) | D = mitigation R&D ÷ **total capex** (3-year averages), vs B_RD | **B_RD = 5%** ("Ecofys-WWF Energy model – benchmark data 5%"). Dim. 1 score = min(D/5%, 1) × 50%. Dim. 2 uses non-mature R&D ÷ capex vs 5%, up to 100%. The higher dimension counts. The text also credits the IEA cement roadmap (2018) for the benchmark. | [ACT cement PDF pp.51–53](https://actinitiative.org/wp-content/uploads/act-cement-v2.0.pdf) [verified] |
| Oil and Gas 2021, 2023 (100 companies) | ACT O&G (Feb 2021) | Low-carbon capex share OG 2.5, CCS share OG 2.6 | 49%, 5% (round 1, section 4) | [2023 methodology PDF pp.7–9](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-04/WBA-climate-and-energy-benchmark-in-the-oil-and-gas-sector-2023-methodology.pdf) [verified, scanned PDF] |
| Electric Utilities 2021, 2023 | ACT Electricity v2.0 | "assessed on their low-carbon capital expenditure (especially concerning electricity generators)" | 95% (round 1) | [2023 methodology PDF p.6](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-04/Electric-Utilities-2023-Methodology-report-1.pdf) [verified] |
| Automotive and Transportation Manufacturers 2024 (cars, aircraft, rolling stock, heavy vehicles, ships) | ACT Auto and ACT Generic | Low-carbon capex share; Module 3 R&D | 80% expert threshold (round 1) | [2024 methodology PDF pp.5–6](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-04/Transport-Manufacturers-Methodology-report-2024-1.pdf) [verified] |
| Transport 2022 (airlines, shipping, rail, trucking) | ACT Transport v2.1 | Fleet locked-in emissions over 15 years; R&D TR 3.1 | R&D 80% (50% if mostly subcontracted), round 1 | [2022 methodology PDF p.7](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-04/Methodology_report_transport_sector_apr22_V3.pdf) [verified] |
| Buildings 2023 | ACT Property Developer, Construction, Real Estate | Not checked for capex | – | [2023 methodology](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-04/WBA-Climate-and-Energy-Benchmark_Methodology-Report_Buildings_December-2023-.pdf) |

**Licence: what CC BY 4.0 covers.**

- WBA site: "Our work is licensed under the Creative Commons Attribution 4.0 International License"
  and WBA "reserves the right to review and amend these license terms at any time". No carve-outs
  are listed. [verified](https://www.worldbenchmarkingalliance.org/disclaimer)
- **WBA benchmark methodology reports: CC BY 4.0** (Heavy Industries 2024 PDF p.11; Oil and Gas 2023
  PDF p.19; Electric Utilities 2023; ATM 2024; Buildings 2023). **Exception: Transport 2022 is
  CC BY-NC-ND 4.0** (PDF p.19). [verified]
- **WBA datasets:** the Heavy Industries 2024 datasheet's tab "8. Disclaimer" says CC BY 4.0. It holds
  company-level ACT scores, including IS 2.3 / CE 2.2 / AL 2.2 locked-in emissions, "R&D in
  low-carbon technologies", and analyst commentary. The datasets page itself shows no licence text.
  [verified](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-06/Datasheet_2024-Heavy-Industries-HI-Benchmark-20-May.xlsx)
  Other datasheets were not opened.
- **ACT methodology PDFs are not CC BY.** ACT Core: "© World Benchmarking Alliance, ADEME 2025.
  Reproduction of all or part of work without licence of use permission of World Benchmarking
  Alliance & ADEME is prohibited" (PDF p.2). Steel, cement and aluminium: "© CDP Worldwide & ADEME"
  2021–2022, same wording. [verified]
- **So:** WBA's own reports and scores may be reused commercially with attribution. The benchmark
  *figures and methods* (95%, 49%, 77%, 80%, 5%, the bands) sit in the ACT documents and need
  WBA/ADEME (and, for older sector methods, CDP) permission to store or reproduce. The 2026
  methodological note has no licence line of its own; the site-wide CC BY 4.0 statement would cover
  it, but it restates ACT content, so ask before relying on that.

### 10.6 Revised per-sector table

"Permission" means WBA/ADEME (ACT Core) or CDP/ADEME (ACT sector methods) must grant use.

| Sector | Best available capex metric | Benchmark value(s) | Source | Licence | Still missing |
|---|---|---|---|---|---|
| Power | Low-carbon capex share, next 3 years | **95%**; ACT Core bands at 0.2/0.4/0.6/1 × 95% | ACT Electricity v2.0 pp.50–52; ACT Core PDF p.62 | Permission | No CA100+ capex test since 2023 |
| Oil and gas | (a) % of upstream capex in NZE/APS-incompatible projects; (b) low-carbon capex share | (a) green 0% NZE-incompatible; amber <50% APS-incompatible; red 50–100%. (b) **49%** + 5% CCS (ACT 2021) or **77%** (ACT Core 2025) | CTI 2025 PDF p.15; ACT O&G p.126; ACT Core PDF p.62 | CTI non-commercial; ACT permission | (a) needs Rystad data and CTI's model. 77% has no derivation. |
| Chemicals | Low-carbon capex share | **54%** (ACT Chemicals) or **77%** (ACT Core) | Section 4; ACT Core PDF p.62 | Permission | Values conflict; neither is chemicals-specific |
| Autos | Low-carbon capex share | **80%** expert threshold; ACT Core bands 20/40/60/80% | ACT Auto pp.38–41; ACT Core PDF p.62 | Permission | No scenario-derived figure |
| Steel | No capex share. Locked-in emissions (IS 2.3); low-carbon R&D share (IS 3.1) | R&D: **80%** of R&D low-carbon, **65%** of that non-mature. Capex: ACT Core generic bands by fallback. Typical Metals & Mining capex <25% (observed). | ACT steel PDF pp.75–76; ACT Core PDF pp.62, 116 | Permission. WBA HI scores CC BY 4.0. | Any scenario-derived capex share |
| Cement | Mitigation R&D ÷ total capex (CEM 3.1); locked-in emissions (CEM 2.2a) | **5% of capex** (Ecofys-WWF). Typical Construction Materials capex <5% (observed). | ACT cement PDF pp.51–53; ACT Core PDF p.116 | Permission (© CDP & ADEME 2021). WBA HI scores CC BY 4.0. | A low-carbon capex share benchmark. The 5% is R&D, from a 2021 method. |
| Aluminium | Locked-in emissions (AL 2.2); R&D share (AL 3.1) | R&D **80%** / **65%**. Capex: ACT Core generic bands by fallback. | ACT aluminium PDF pp.75–76 | Permission. WBA HI scores CC BY 4.0. | Any capex share |
| Aviation (airlines) | No capex share. Fleet locked-in emissions; low-carbon R&D share (TR 3.1) | R&D 80% (50% if mostly subcontracted) | ACT Transport v2.1 pp.43, 57–58 | Permission. WBA Transport 2022 report CC BY-NC-ND. | Any capex share. TPI and RMI give intensity only. |
| Shipping | Same as aviation | Same | Same | Same | Same |
| Aircraft and ship makers | Low-carbon capex share (ACT Generic via WBA ATM 2024) | 80% expert threshold | ACT Generic p.47; WBA ATM 2024 PDF p.5 | Permission; WBA report CC BY 4.0 | A sector benchmark |
| Cross-sector | ACT Core generic matrix; Taxonomy-aligned share | Bands 20/40/60/80%. WBA 2026 classes: ≤10–20% "consequential", ~40%+ "1.5°C aligned". PSF observed 16% (section 3.2). | ACT Core PDF p.62; WBA note PDF p.4 | Permission; WBA site CC BY 4.0; EU CC BY 4.0 | A pathway-derived figure |
| Any sector (disclosure tests) | CA100+ 6.1/6.2; TPI MQ21/MQ22; TPI NZS capex indicators | Yes/No. Absolute amounts. At least 3 years of forward capex, comparable with total capex. | Sections 2.2, 10.3, 10.4 | CA100+ non-commercial; TPI method text CC BY-NC 4.0, data licence-only | n/a |

### 10.7 Could not access or not verified (round 2)

- **carbontracker.org:** the terms page returned 404. The *Paris Maligned III* and *Absolute Impact
  2026* PDFs are behind a login, so their weights and capex figures are not verified.
- **TPI site:** a JavaScript app. Publication URLs redirect to pages, not PDFs. Guessed asset paths
  for the electricity, aluminium, shipping, autos and oil and gas CP notes returned 404, so those
  notes were not read. *State of the Corporate Transition 2025* was read from LSE Research Online.
- **WBA:** the 2026 note URL without "_v2" returned 404; the "_v2" file worked. The 2023 oil and gas
  methodology is a scanned PDF, read visually. The Heavy Industries datasheet was the only
  dataset opened.
- **ACT Core 77%:** no derivation found in the document.
- **ACT Cement CEM 3.1:** the data table names the Ecofys-WWF model for the 5%, while the text
  credits the IEA cement roadmap. Which one is the real source is unclear.
- **CA100+ terms:** not re-fetched in round 2 (verified in round 1).
- **No HTTP 403** was met in round 2.

---

## 11. Unverified / could not access

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

---

## 12. Round 3: WBA methodology and scoreboard in detail

Status: **round 3 research note, 2026-10-19.** Sources are WBA's own pages, the ACT Core PDF, the
2026 methodological note, the nine 2020–2024 datasheets (downloaded and read with openpyxl) and the
public data behind WBA's 2026 company pages. Downloads sit in the session scratchpad, not in the
repo. ACT Core page numbers are the printed page numbers. The 2026 note prints "1" on every page,
so it is cited by PDF page.

Short links used below:

- **ACT Core** = [ACT Core v1.0, 24 Feb 2025](https://actinitiative.org/wp-content/uploads/pdf/act-core-methodology.pdf)
- **Note 2026** = [Methodological note on the 2026 ACT Core assessments (v2)](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-01/Methodological%20note%20on%20the%202026%20ACT%20Core%20assessments_v2.pdf)
- **ACT Core page** = [WBA benchmark page "ACT Core"](https://www.worldbenchmarkingalliance.org/benchmark/act-core)
- **Datasets page** = [Data sets from the Climate and Energy Benchmarks (2020–2024)](https://www.worldbenchmarkingalliance.org/data-sets-climate-and-energy-benchmarks-2020-2024)

### 12.1 Which WBA climate benchmarks exist

There are two generations. From 2020 to 2024 WBA ran one benchmark per sector, scored with the ACT
sector methods. In 2026 it replaced them with one cross-sector **ACT Core** assessment of its
2,000-company list (the "SDG2000").

| Edition | Published (datasheet version) | Companies | ACT method | Source |
|---|---|---|---|---|
| Automotive 2020 | 2020 | 30 carmakers | ACT Auto | [datasheet](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-06/WBA-Climate-and-Energy-2020-Automotive-Results-Data.xlsx) [verified] |
| Electric Utilities 2021 | 30 Nov 2021 | 51 | ACT Electricity | [datasheet](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-06/Electric-utilities-Data-scores-and-additional-commentary-2021-final.xlsx) [verified] |
| Oil and Gas 2021 | 6 Dec 2021 | 100 | ACT O&G (2021) | [datasheet](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-06/Datasheet_2021-Oil-and-Gas-Benchmark_updated-in-November-2021.xlsx) [verified] |
| Transport 2022 | 18 Oct 2022 | 90: air 25, shipping 17, rail 9, road 6, multi-modal 33 | ACT Transport v2.1 | [datasheet](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-06/Datasheet_2022-Transport-Benchmark-5.xlsx) [verified] |
| Oil and Gas 2023 | 29 Jun 2023 | 99: integrated 64, semi-integrated 19, upstream 12, midstream 4 | ACT O&G (2021) | [datasheet](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-06/Datasheet_2023-Oil-and-Gas-Benchmark-17-July.xlsx) [verified] |
| Buildings 2023 | 2023 (intro tab says "Version 18 October 2022") | 50 | ACT Construction, Real Estate, Property Developer | [datasheet](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-06/Datasheet-2023-Buildings-Benchmark-v1.xlsx) [verified] |
| Electric Utilities 2023 | 15 Nov 2023 | 68 | ACT Electricity v2.0 | [datasheet](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-06/Datasheet_2023-Electric-Utilities-EU-Benchmark-16-Nov.xlsx) [verified] |
| Heavy Industries 2024 | 20 May 2024 | 91: steel 45, cement 34, aluminium 12 | ACT Iron & Steel, Cement, Aluminium v2.0 | [datasheet](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-06/Datasheet_2024-Heavy-Industries-HI-Benchmark-20-May.xlsx) [verified] |
| Automotive and Transportation Manufacturers 2024 | 3 Dec 2024 | 44: 30 carmakers, 14 aircraft/rail/truck/ship makers | ACT Auto, ACT Generic | [datasheet](https://www.worldbenchmarkingalliance.org/sites/default/files/2026-06/Datasheet_2024-ATM-Benchmark-04-Dec.xlsx) [verified] |
| **ACT Core 2026 ("Climate Benchmark")** | 13 Jan 2026 | 2,000 listed; 1,955 graded; 45 "Not Scored" (non-English disclosure) | ACT Core v1.0 | [ACT Core page](https://www.worldbenchmarkingalliance.org/benchmark/act-core), [press release](https://www.worldbenchmarkingalliance.org/latest/over-1-trillion-climate-investment-could-be-unlocked-according-new-analysis-2000-companies) [verified] |

- The datasets page says WBA assessed "450 companies from the highest-emitting sectors" in
  2020–2024. [verified, Datasets page]
- **No separate WBA steel, cement, chemicals, aviation or shipping benchmark exists.** Steel,
  cement and aluminium were in Heavy Industries 2024. Airlines and shipping were in Transport 2022.
  Chemicals were first covered in ACT Core 2026 (71 graded). [verified, datasheets and 2026 listing]
- **Food and agriculture:** WBA runs a separate Food and Agriculture Benchmark, not climate-scored
  with ACT. ACT Core covers agri-food companies with its own capex and R&D bands (12.2). Not studied
  further. [verified, [company scoreboard](https://www.worldbenchmarkingalliance.org/company-scoreboard) benchmark list]
- **Just Transition 2026** is a separate assessment of the same 2,000 companies, scored 0–100 on
  three indicators (social dialogue, just transition planning, decent work and skills). It does not
  feed the ACT Core grade. [verified, [Just Transition page](https://www.worldbenchmarkingalliance.org/benchmark/just-transition)]
- **TransitionArc** (Arc, with WBA, CTI, TPI, InfluenceMap, SBTi and others) will publish a subset
  of ACT Core data free of charge, "on a rolling basis … throughout 2026 and 2027". The subset
  includes "CAPEX and low-carbon CAPEX values" (D01.a). The FAQ says it considers disclosures
  "publicly available by 31 December 2026". It "will not lead to a score or a revision of the
  current ACT Core scores". [verified, [TransitionArc FAQ, 7 Sep 2026](https://www.worldbenchmarkingalliance.org/latest/transitionarc-2026-data-update-faq)]
- No date for a second ACT Core edition was found. [not verified]

### 12.2 Methodology in detail

#### 12.2.1 ACT sector methods as used by WBA (2020–2024)

**Rating.** Each company gets a three-part ACT rating such as "12.7 B +": [verified, O&G 2023
datasheet, tab 3.1 "ACT rating guidance"]

- **Performance score**, 0–20: the weighted sum of the indicator scores in nine modules.
- **Narrative score**, A (best) to E: the analyst's holistic view of Paris alignment.
- **Trend score**, "+", "=" or "−": the expected near-term direction.

**How the 0–100 WBA total is built.** The datasheets only state "Total ACT score has been
normalised out of 60" and that social adds 40 (just transition 20 + core social 20). [verified, tab 2]
Recomputing from the data gives an exact fit on every row checked:

- Total ACT (0–60) = (Performance + Narrative points + Trend points) / 42 × 60.
- Narrative points: A 20, B 15, C 10, D 5, E 0. Trend points: + 2, = 1, − 0.
- WBA total (0–100) = Total ACT + Total social.
- Example: Ampol (O&G 2023) has performance 2.1, narrative D (5), trend − (0). (2.1 + 5 + 0) / 42 ×
  60 = 10.1, which is its published Total ACT. Plus social 9.4 gives the published total 19.5.

[derived from O&G 2023 and HI 2024 datasheets, tabs 2 and 3.1; the formula itself is not printed]

**Module weights.** Tab 4 "Max ACT Performance Scores" gives each company's maximum points per
module, out of 20 performance points. Weights vary by company (for example by business mix), so
the table shows the typical (modal) values. [verified, tab 4 of each datasheet]

| Sector (edition) | 1 Targets | 2 Material investment | 3 Intangible investment | 4 Sold product | 5 Management | 6 Supplier eng. | 7 Client eng. | 8 Policy eng. | 9 Business model |
|---|---|---|---|---|---|---|---|---|---|
| Oil & gas, integrated (2023) | 3 | 3 | 1.6 | 4.6 | 2 | 0.8 | 2 | 1 | 2 |
| Oil & gas, upstream (2023) | 3 | 8 | 2 | 2 | 2 | 0 | 0 | 1 | 2 |
| Electric utilities (2023), e.g. Enel | 3 | 4.7 | 1.3 | 2.9 | 2.4 | 1.2 | 1.6 | 1 | 2 |
| Electric utilities (2023), e.g. AES | 3 | 5.6 | 1.3 | 2.3 | 2.4 | 1.0 | 1.4 | 1 | 2 |
| Steel (2024) | 3 | 6 | 2 | 2.4 | 2 | 0.4 | 1.2 | 1 | 2 |
| Cement (2024) | 3 | 6.6 | 2 | 0 | 2 | 1.2 | 2 | 1.2 | 2 |
| Aluminium (2024) | 3 | 6.2 | 2 | 2.1 | 2 | 0.8 | 0.8 | 1 | 2 |
| Carmakers (2024), e.g. BMW | 3 | 1.4 | 1 | 6.6 | 2 | 1 | 2 | 1 | 2 |
| Aircraft / transport makers (2024), e.g. Airbus | 3 | 3 | 1 | 3.9 | 2 | 1.6 | 2.4 | 1 | 2 |
| Airlines, shipping, rail, road (2022) | 3 | 6 | 1 | 0 | 2 | 3 | 2 | 1 | 2 |

Divide by 20 for the percentage weight (for example steel material investment 6/20 = 30%).

**Material investment (module 2) indicators and their own weights** (max points of 20, tab 4):

| Sector | Capex or asset indicator in module 2 | Max points | Benchmark (from sections 4 and 10) |
|---|---|---|---|
| Oil & gas | 2.5 low-carbon and mitigation capex share; 2.6 CCS/CDR capex share; 2.4 share of unsanctioned projects within carbon budget; 2.2 emissions lock-in | Integrated: 0.6 / 0.4 / 0.4 / 0.6. Upstream: 1.2 / 1.2 / 1.6 / 1.4 | 49% and 5% (ACT O&G 2021) |
| Electric utilities | 2.4 share of low-carbon capex; 2.2 locked-in emissions | Enel: 1.42 / 1.28 | 95% (ACT Electricity) |
| Carmakers | AU 2.2 share of low-carbon capex | 1.0 | 80% threshold |
| Aircraft / ship / rail makers | GE 2.3 share of low-carbon capex; GE 2.4 locked-in emissions | 1.5 / 0 (Airbus) | 80% threshold |
| Steel | IS 2.3 locked-in emissions of crude steel assets | 2.2 | Carbon budget (SDA) |
| Cement | CE 2.2 locked-in emissions | 1.6 (Holcim) | Carbon budget (SDA) |
| Aluminium | AL 2.2 locked-in emissions | 2.66 (Norsk Hydro) | Carbon budget (SDA) |
| Airlines, shipping | TR 2.3 fleet locked-in emissions; TR 2.4 share of low-carbon vehicles | (not split in round 3) | Carbon budget |

So a **capex-share indicator carries only 3–8% of the ACT performance score** (0.6–1.5 of 20), and
none exists for steel, cement, aluminium, airlines or shipping. Locked-in emissions carry 8–13% in
heavy industry. [verified, tab 4 values; benchmarks per sections 4 and 10.5]

**Intangible investment (module 3)** is low-carbon R&D share and low-carbon patents (for example
EU 3.1 and 3.2, O&G 3.1 and 3.2, HI 3.1 and 3.2). The R&D benchmarks are in section 10.6
(steel and aluminium 80% / 65%; cement 5% of capex; transport 80%). [verified, tab 3.1 headers]

**ACT updates since the WBA editions.** ACT harmonised some weights after these benchmarks:
"time horizon of targets" 3% and "achievement of previous targets" 2% in all sectors; module 5
items 3/1/3/1/2%. No capex indicator or capex benchmark was changed.
[verified, [ACT methodology updates page](https://actinitiative.org/fr/mise-a-jour-methodologies-act/)]

#### 12.2.2 ACT Core (2026)

**Structure.** Six measurement areas, ten indicators, 30 elements. [verified, ACT Core pp.9, 16–17]

| Area | Indicators | Elements | Axis |
|---|---|---|---|
| A. GHG reporting and targets | A01 | A01.a reporting; A01.b targets; A01.c 1.5°C pathway used; A01.d no offsets/avoided emissions | Transition plan quality (TPQ) |
| B. Planning | B01, B02, B03 | B01.a–c plan, coverage, review; B02.a–e levers, near/long term, GHG savings, **B02.d investments per lever**, risks; B03.a–e supplier and client engagement | TPQ |
| C. Governance and policy | C01, C02 | C01.a–d board responsibility, teams, expertise, pay; C02.a–b policy support, associations | TPQ |
| D. Low-carbon investments | D01, D02 | **D01.a investing in climate solutions** (capex or R&D share); **D02.a business model** (low-carbon revenue share and plans) | Contribution to the transition (CTT) |
| E. Target alignment | E01 | E01.a–d near/long-term, S1+2 and S3 targets vs a company-specific 1.5°C path | CTT |
| F. Performance | F01 | F01.a realignment needed for the past trajectory | CTT |

**No weights and no 0–20 score.** "ACT Core does not generate a quantitative score (e.g., the ACT
performance score)". It places companies on a stepwise scale using element thresholds, and "does
not make use of the ACT trend nor narrative scores". [verified, ACT Core p.10] So there is no
"4B+"-style rating in 2026.

**Element scoring.** Elements are either met/unmet, or placed on a maturity matrix: Basic,
Standard, Advanced, Next practice, Low-carbon aligned. [verified, ACT Core pp.17–18]

**How the 2026 grade was actually set (Note 2026, which overrides Tables 6/7 of ACT Core).**

- WBA dropped A01.d, B02.e and C01.b–C02.b from scoring, and treated A01.c as context only.
  [verified, Note 2026 PDF pp.1–2]
- TPQ runs 0–5 and CTT runs 0–2. The letter grade combines them. [verified, ACT Core page]

| Grade | Class | TPQ | CTT | Key conditions (Note 2026) |
|---|---|---|---|---|
| G | Uncommitted | 0 | any | A01.b unmet: no valid target (baseline, ≤2034, ≥95% S1+2 or ≥40% S3) |
| F | Non-mature | 1 | any | A01.b at least Basic |
| E | Committed but not planning | 2 | any | A01.b at least Standard, no plan |
| D | Unstructured plan execution | 3 | any | B01.a, B01.b and C01.a met |
| C | Inconsequential planning | 4–5 | 0 | A01.a ≥ Basic, but **D01.a unmet** and F01.a below Basic |
| B | Consequential planning | 4–5 | 1 | **D01.a ≥ Basic** ("no more than 10–20% of total investment"), F01.a ≥ Standard, ≥1 of E01.a–d met |
| A | 1.5°C aligned and planning | 4–5 | 2 | **D01.a ≥ Standard** ("typically … 40% or more"), F01.a ≥ Next practice, ≥2 of E01.a–d met, ≥5 of B02/B03 elements met |

[verified, Note 2026 PDF pp.2–3; ACT Core page "How are companies scored?"] The ACT Core page also
says CTT "only contributes to the total score when TPQ is above 4", while its table uses "4 or 5".
Read it as TPQ ≥ 4.

**D01.a, the capex element (exact rules).** [verified, ACT Core pp.58–62]

- Data: total capex and climate-solutions capex for RY and RY+1 (amount and %); total and
  climate-solutions R&D for RY and RY−1. Currency as ISO 4217.
- Taxonomy-aligned spending counts. "'Taxonomy eligible' investments/expenditures cannot be used".
  A company's own definition counts only if it details what is low-carbon.
- Year rule: if only RY exists, score RY. If RY+1 is higher, score RY+1. If RY+1 is lower, score
  the average. R&D compares RY−1 with RY the same way.
- Capex is preferred over R&D where a sector has both. Sectors without an ACT matrix use the
  generic row.
- Matrix (LC = low-carbon capex share):

| Row | Basic | Standard | Advanced | Next practice | Low-carbon aligned |
|---|---|---|---|---|---|
| Electricity | LC/95% < 0.20 | 0.21–0.40 | 0.41–0.60 | 0.61–<1 | ≥ 1 (LC ≥ 95%) |
| Oil and gas | LC/77% < 0.20 | 0.21–0.40 | 0.41–0.60 | 0.61–<1 | ≥ 1 (LC ≥ 77%) |
| Chemicals | LC/77% < 0.20 | 0.21–0.40 | 0.41–0.60 | 0.61–<1 | ≥ 1 (LC ≥ 77%) |
| Automotive | < 20% | 21–40% | 41–60% | 61–80% | > 80% |
| Generic (steel, cement, aluminium, airlines, shipping, others) | < 20% | 21–40% | 41–60% | 61–80% | > 80% |
| Agriculture (capex) | < 10% | – | 11–20% | – | > 20% |
| Agriculture (R&D) | < 10% | 10–15% | 15–25% | 25–40% | > 40% |
| Generic (R&D) | < 20% | 21–40% | 41–60% | 61–80% | > 80% |

- In absolute terms the oil and gas and chemicals bands are: Standard from about 16%, Advanced from
  about 32%, Next practice from about 47%. Electricity: about 20%, 39%, 58%. (Our arithmetic.)
- "Unmet" (shown in the 2026 data) means "no evidence that the company is mobilizing low-carbon
  investments through capital expenditure (CapEx) or R&D" (Note 2026 PDF p.2).
- The 77% still has no stated derivation (section 10.5).

**D02.a, business model.** A matrix of low-carbon revenue share (< industry average, < 50%,
51–70%, 71–90%, > 90%) against plans to create or grow low-carbon business models over five years.
A committed, planned phase-out of the main high-emitting business "over a timeline relevant to the
sector (e.g. 2035 for automotive sector; 2030/40 for electricity, 2040 for shipping)" scores
Low-carbon aligned. [verified, ACT Core pp.63–66]

**B02.d, investments per lever.** Met if the company "provides financial elements detailing how it
will fund its decarbonisation levers/actions", with "a clear link between the identified action and
the financial requirements" and a breakdown of needs vs funds allocated. This is a disclosure test,
not a level test. [verified, ACT Core pp.36–37] Appendix 10.2 lists decarbonisation levers by WBA
industry. [verified, ACT Core table of contents, p.4; appendix not read in full]

**E01 and F01, the trajectory tests.** [verified, ACT Core pp.70–82]

- E01: build a sector 1.5°C path in absolute emissions from 2019 (s1.5C). Then make it
  company-specific (c1.5C): any excess emitted above s1.5C since 2019 must be recovered by a
  steeper path, so the company stays inside its 2050 carbon budget (after Rekker et al. 2022).
- Alignment = company target / 1.5°C-compatible target (EQ3). Met if ≤ 1.10. Intensity targets are
  converted with activity data; if activity is expected to grow and no forecast exists, WBA
  assumes 1.5% a year growth. [ACT Core pp.72–74]
- F01.a: realignment factor = (required S1+2 trend / observed trend) × S1+2 share + (required S3
  trend / observed trend) × S3 share, between 2019–RY and RY+5 (EQ4). Bands: > 3 Basic;
  1.5–3 Standard; 1.2–1.5 Advanced; 1–1.2 Next practice; ≤ 1 Low-carbon aligned. [ACT Core pp.81–82]
- Climate-solution providers are scored instead on deployment (e.g. GW, TW) vs 1.5°C technology
  pathways: < 50%, 50–70%, 70–80%, 80–95%, ≥ 95% of required. [ACT Core p.82]

**What ACT Core does not use.** No locked-in emissions, no intensity pathways ("ACT Core only
considers global and sectoral pathways based on absolute emissions"), no sold-product module, no
trend or narrative score. [verified, ACT Core pp.10, 87]

### 12.3 Pathways per sector

**ACT Core 2026: absolute-emissions pathways only.** Fallback is SBTi cross-sector. [verified,
Note 2026 PDF pp.3–4]

| Our sector | Pathway(s) used by WBA 2026 | Scope |
|---|---|---|
| Steel | ISF-OECM; SBTi-NZE (iron and steel) | S1+2 |
| Cement | ISF-OECM | S1+2 |
| Aluminium | ISF-OECM | S1+2 |
| Chemicals | ISF-OECM | S1+2 |
| Power | Climate Analytics (SR1.5/SSP1); ISF-OECM; power purchase ISF-OECM | S1+2; S3 |
| Oil and gas | Oil production IEA-NZE (S1+2); oil consumption ISF-OECM (S3) | S1+2; S3 |
| Autos | LDV manufacture ISF-OECM (S1+2); LDV use IEA-NZE (S3); heavy trucks ISF-OECM / IEA-NZE | S1+2; S3 |
| Aviation | Plane use IEA-NZE; plane manufacture ISF-OECM | S1+2 or S3 |
| Shipping | Shipping use ISF-OECM; ship manufacture ISF-OECM | S1+2 or S3 |
| Mining | Diversified mining TPI (NZE/IPCC) | S1+2 |

- Allowed pathway sources must be 1.5°C with ≥ 50% probability, little or no overshoot before 2050,
  and ≤ 10% reliance on negative emissions. [verified, ACT Core p.87]
- **Capex is not compared with a pathway in ACT Core.** D01.a uses fixed thresholds (95%, 77%,
  80% bands). Only E01 and F01 use pathways.

**2020–2024 sector benchmarks: intensity pathways via SDA.** Heavy Industries used IAI
(aluminium), IEA NZE 2023 (cement) and SBTi (steel). Capex shares there were checked against the
fixed ACT benchmarks (95%, 49%, 80%). [verified, section 10.5]

**How company trajectories are compared:** ACT sector methods compare intensity trends and
locked-in emissions of assets with an SDA carbon budget. ACT Core compares absolute emissions
targets and the 2019–RY trend with a company-specific absolute 1.5°C path.

### 12.4 Scoreboard and data

**What is public per company on the website (no login).** [verified, [ArcelorMittal scorecard](https://www.worldbenchmarkingalliance.org/company/arcelormittal) and ACT Core page]

- Grade A–G and class name, TPQ (0–5) and CTT (0–2), with an explanatory paragraph.
- Region, WBA industry, HQ country, ownership, and a footprint panel (revenue, production, S1+2
  emissions, employees).
- A chart of D01.a ("Investment in climate solutions") against all companies, and a TPQ × F01.a
  chart.
- Scores from the other 2026 benchmarks (Just Transition, Nature, Social, Gender).

**The charts carry element-level data for all 2,000 companies.** The page loads it as JSON from two
endpoints, readable without login:

- `/company_benchmarks/elements-beeswarm/GEC_01207.1/<WBA ID>`: D01.a maturity for every company,
  as `{"value": 0–5, "maturity": "Unmet"…"Low-Carbon Aligned", "name": "Company PT_xxxxx"}`.
- `/performance_planning_comparison/data/<WBA ID>`: that company's TPQ (x) and F01.a maturity (y),
  plus the distribution.

These are undocumented website endpoints, not an API contract. They give the maturity level, not
the underlying capex amounts or percentages. [verified, fetched 2026-10-19]

**Data Explorer and API (registration).** [verified, [User Guide](https://www.worldbenchmarkingalliance.org/documentation/user-guide),
[API Specification](https://www.worldbenchmarkingalliance.org/documentation/api-specification),
[Data Dictionary](https://www.worldbenchmarkingalliance.org/documentation/data-dictionary)]

- Free registration is required. The API needs a separate approval ("may take several days"),
  then a Bearer key. Without it every dataset call returns HTTP 401 "Not authenticated" (tested).
- Hierarchy: company → benchmark score → measurement area → indicator → element → attribute
  values. "Attributes … individual data points or metrics" are where the reported capex figures
  should sit, with "evidence sources". The D01.a data requirements in 12.2.2 list what those
  attributes cover. Not inspected (no account). [not verified for content]
- Datasets: companies, footprintattributes, climateprofiles, emissions, targets, sources;
  methodologies…; benchmarks, measurementareas, indicators, elements, attributevalues.
- Company identifiers: "Core company information including identifiers (ISIN, LEI), industry
  classification, geographic location". The WBA ID has the form `PT_00001`.
- Formats: on-screen tables; download as a ZIP of CSV files (full tables only, no filtered
  download); REST JSON, at most 1,000 rows per page and 1 request per second.
- The data dictionary has 357 fields (134 company, 68 methodology, 155 benchmark).
- Cadence: "annual assessment cycle". "Once published, benchmark data is not modified unless
  exceptional circumstances." The Data Explorer is in beta.
- The OpenAPI spec is public at `https://data.worldbenchmarkingalliance.org/api/data/v1/openapi.json`;
  it lists the endpoints but not the columns. [verified]

**2020–2024 datasheets (Excel, no login).** Each has 8–9 tabs: overall scores (ISIN, country,
region, sub-sector, total /100, Total ACT /60, performance, narrative, trend, social); ACT
normalised and raw scores per module and indicator (0–100, with ranks); maximum points per
indicator (the weights); module summaries (analyst text per module); data availability; just
transition and core social element scores; disclaimer. [verified, all nine files]

- Identifiers: ISIN in 2021–2023 files (NULL for state-owned companies such as ADNOC or Basra Oil);
  WBA ID (`PT_…`) in 2023–2024 files; HI 2024 and ATM 2024 have no ISIN. Names are not normalised
  (for example "United States of America of America" in HI 2024).
- **Data defect:** in HI 2024 tab 2 the WBA ID column does not follow the sorted rows. ArcelorMittal
  shows PT_02125 there but PT_00130 in tab 4 and in 2026; PT_00130 in tab 2 is Norsk Hydro. Join on
  the other tabs or on 2026 IDs, not on HI tab 2. [verified]
- The underlying company capex figures are not in the datasheets, only the indicator scores.

**2026 coverage of our sectors (graded companies, from the public listing on 2026-10-19).**
Sub-sector counts are by company name and approximate.

| Sector | Graded | Grade mix (A…G) | D01.a met (≥ Basic) | Europe & C. Asia / China / US |
|---|---|---|---|---|
| Utilities (power, plus water and grids) | 116 (+6 not scored) | A 6, B 2, C 10, D 30, E 17, F 14, G 37 | 41 | 27 / 9 / 19 |
| Oil & gas | 93 (+1) | D 7, E 51, F 13, G 22 | 33 | 26 / 5 / 18 |
| Metals & mining | 88 (+6) | C 9, D 36, E 18, F 8, G 17 | 25 | 22 / 25 / 9 |
| ↳ steel (approx.) | ~39 (+5 Chinese mills not scored) | C 1, D 16, E 5, F 4, G 13 | 10 | |
| ↳ aluminium (approx.) | ~9 | D 3, E 3, F 2, G 1 | 3 | |
| Construction materials | 41 | B 2, C 4, D 14, E 8, F 5, G 8 | 17 | 8 / 7 / 5 |
| ↳ cement (approx.) | ~30 (+Cemros not scored) | B 2, C 4, D 9, E 7, F 2, G 6 | 15 | |
| Chemicals | 71 | C 11, D 23, E 27, F 5, G 5 | 31 | 23 / 4 / 18 |
| Motor vehicles & parts | 44 | B 2, C 10, D 18, E 7, F 2, G 5 | 20 | 11 / 12 / 6 |
| Passenger transport | 89 (+9) | C 6, D 29, E 14, F 7, G 33 | 19 | 27 / 9 / 12 |
| ↳ airlines (approx.) | ~26 | C 2, D 15, E 5, F 2, G 2 | 7 | |
| Freight & logistics | 34 | C 5, D 6, E 12, F 6, G 5 | 9 | 7 / 2 / 4 |
| ↳ shipping lines (approx.) | ~22 | C 5, D 6, E 6, F 3, G 2 | 8 | |
| All 2,000 | 1,955 (+45) | A 7, B 16, C 128, D 668, E 383, F 269, G 484 | 467 | 525 / 191 / 458 |

[verified: grades from the public listing behind the ACT Core page; D01.a from the beeswarm JSON;
regions from the listing's region/country filters. "Europe & Central Asia" is WBA's region and
includes the UK, Switzerland, Norway, Russia and Türkiye, so it is wider than the EU.]

- Across all companies, D01.a is Unmet 1,488, Basic 266, Standard 100, Advanced 44, Next practice
  30, Low-carbon aligned 27. **76% are Unmet: WBA found no evidence of low-carbon capex or R&D.**
- WBA's own summary: "25% of companies … are now reporting low-carbon investments", median "7%
  share of total capital expenditure"; leaders in 19 industries at "30%". [verified, press release]

**Example rows, 2026 (ACT Core) and the last sector edition.**

| Company | 2026 grade | TPQ | D01.a (2026) | F01.a (2026) | Last sector edition: rating; Total ACT /60; MI module /100 |
|---|---|---|---|---|---|
| Enel | A | 5 | Next practice | Low-carbon aligned | EU 2023: 12.7 B +; 42.4; MI 72, capex-share indicator 84.7 |
| Holcim | B | 5 | Basic | Low-carbon aligned | HI 2024: 8.9 C +; 29.9; MI 26, CE 2.2 locked-in 39.8 |
| BASF | C | 5 | Basic | Unmet | (no WBA chemicals edition) |
| ArcelorMittal | D | 3 | Basic | Low-carbon aligned | HI 2024: 6.4 C −; 23.5; MI 47.8, IS 2.3 locked-in 80.1 |
| SSAB | D | 3 | Basic | Unmet | HI 2024: 8.1 B −; 33.0; MI 79.9, IS 2.3 100 |
| Norsk Hydro | D | 3 | Standard | Next practice | HI 2024: 7.6 C =; 26.5; MI 25.2, AL 2.2 0 |
| Heidelberg Materials | D | 3 | Basic | Next practice | (in HI 2024, not extracted) |
| TotalEnergies | D | 3 | Standard | Low-carbon aligned | O&G 2023: 7.6 D =; 19.4; MI 13.3, 2.5 capex share 0 |
| Shell | E | 2 | Basic | Low-carbon aligned | O&G 2023: 5.0 D −; 14.3; MI 15.4, 2.5 capex share 0 |
| Saudi Aramco | E | 2 | Advanced | Unmet | O&G 2023: 2.2 E −; 3.1; MI 0, 2.5 capex share 0 |
| Volkswagen | D | 3 | Standard | Basic | (in ATM 2024, not extracted) |
| A.P. Moller - Maersk | D | 3 | Basic | Basic | (Transport 2022, not extracted) |
| Delta Air Lines | D | 3 | Unmet | Basic | (Transport 2022, not extracted) |
| NTPC | F | 1 | Basic | Basic | EU 2023: 2.9 E −; 4.1; MI 7.7, capex-share indicator 2.8 |

[verified: 2026 columns from the scorecard JSON; sector columns from the datasheets' tabs 2 and 3.1.
"MI" and indicator values are WBA's normalised 0–100 scores.]

Two things stand out. Saudi Aramco is "Advanced" on D01.a in 2026 but scored 0 on the 2023
low-carbon capex indicator. TotalEnergies and Shell also scored 0 there in 2023. The editions use
different definitions and thresholds (77% vs 49%, RY/RY+1 vs 5-year plans), so the two cannot be
read as a trend. Check the 2026 attribute values before using any single D01.a level.

### 12.5 Licence (verified 2026-10-19)

The wording conflicts between WBA pages.

| Item | Wording found | Source |
|---|---|---|
| WBA website, site-wide | "Our work is licensed under the Creative Commons Attribution 4.0 International License … World Benchmarking Alliance reserves the right to review and amend these license terms at any time." | [Disclaimer](https://www.worldbenchmarkingalliance.org/disclaimer) [verified] |
| WBA "Fair use donation" page | "all our methodologies and benchmarks are free, publicly available on our website, and licensed under Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International". Entities that benefit financially are asked for a donation. | [Fair use donation](https://www.worldbenchmarkingalliance.org/fair-use-donation) [verified] |
| Datasheets 2023–2024 (O&G 2023, EU 2023, Buildings 2023, HI 2024, ATM 2024) and Transport 2022 datasheet | CC BY 4.0 | Disclaimer tab of each file [verified] |
| Datasheets 2020–2021 (Automotive 2020, Electric Utilities 2021, O&G 2021) | CC BY-NC-ND 4.0 | Disclaimer tab of each file [verified] |
| Transport 2022 methodology report | CC BY-NC-ND 4.0 | section 10.5 [verified round 2] |
| ACT Core and ACT sector methodology PDFs | "© World Benchmarking Alliance, ADEME 2025. Reproduction of all or part of work without licence of use permission of World Benchmarking Alliance & ADEME is prohibited." (Sector PDFs: CDP Worldwide & ADEME, same wording.) | ACT Core p.2 [verified] |
| 2026 methodological note | No licence line; site-wide terms would apply | Note 2026 [verified] |
| Data Explorer / API | Registration "confirms your acceptance of the Terms of Use". The OpenAPI file points `termsOfService` to the disclaimer page. No separate terms page found (three guessed URLs 404). | User Guide; openapi.json [verified]; terms text [not verified] |

**What this means for internal, non-commercial use (owner decision).** Every Creative Commons
licence above allows internal non-commercial use with attribution. The ACT notice bars
reproduction without permission; citing single benchmark figures for internal use is the owner's
recorded position (section 9.3). CC BY-NC-ND only bars sharing *adapted* material, so
an internal derived score is fine. If outputs are ever shared outside the organisation, the
stricter reading (BY-NC-ND) and the ACT reproduction notice would apply to anything built on the
2020–2021 data, on WBA methods, or on the ACT tables. Attribution: "World Benchmarking Alliance,
<benchmark> <year>, CC BY 4.0" (or BY-NC-ND), with the URL.

### 12.6 Fit for this platform

**Can WBA material-investment scores be the "capex credibility" input?** Partly.

| Option | What it gives | Fit |
|---|---|---|
| A. 2026 D01.a maturity (public JSON) | One level, Unmet…Low-carbon aligned, for 2,000 companies, all our sectors | Usable as a coarse, current flag. It is a share band, not an amount. For steel, cement, aluminium, airlines and shipping it uses the generic 20/40/60/80% expert bands, not a pathway. 76% are Unmet. |
| B. 2026 D01.a attribute values (Data Explorer, login) | Reported capex total and low-carbon capex, RY and RY+1, plus R&D, with evidence sources (expected from the D01.a data list) | Best fit: it is what our own extraction tries to produce. Needs an account and API approval; content not yet checked. |
| C. 2020–2024 ACT module 2 scores (datasheets) | Module and indicator scores 0–100, including locked-in emissions for steel, cement, aluminium, fleets | Rich, but 2–6 years old, fixed company lists, older benchmarks (O&G 49%). Locked-in emissions is the only asset-based test for heavy industry. |
| D. TransitionArc (from 2026–2027) | Same D01.a capex values, free | Watch; not yet published. |

**Recommendation:** use B (or A until B is available) as a **cross-check and fallback**, not as the
primary capex input. Keep our own extracted share and amount as primary (section 9.1). Reasons:

1. **Not an amount.** A maturity band cannot answer CA100+-style absolute questions.
2. **Thresholds, not pathways.** For our five hardest sectors the D01.a bands are ACT Generic's
   expert thresholds. They add no sector evidence beyond section 10.6.
3. **Freshness.** One edition so far, published January 2026 on disclosures up to roughly FY2024
   (emissions series 2019–2024, Note 2026 PDF p.2). The next date is unknown. "Once published …
   not modified".
4. **Coverage gaps.** English-language disclosure only: 45 companies "Not Scored", including several
   Chinese steel mills (Baotou, Hunan Valin, Liuzhou, Xinyu, Guangxi Shenglong), Cemros and China
   Southern Power Grid. China coverage is thin outside metals (5 oil and gas, 4 chemicals,
   9 utilities). Only the SDG2000 list, so mid-caps are missing.
5. **Definition drift.** D01.a accepts Taxonomy-aligned capex or a company's own detailed definition
   and counts nuclear and CCUS where the ACT sector method does (section 4). Our `green.py` keeps
   nuclear and gas out (section 9.3 item 4). Compare like with like.

**Company matching.** Use ISIN or LEI from the Data Explorer companies table as the join key, and
keep the WBA ID (`PT_xxxxx`) as a stable secondary key (stable across 2023, 2024 and 2026 files,
except the HI 2024 tab 2 defect). The public website gives only name and WBA ID. State-owned
companies often have no ISIN (NULL in the datasheets).

**Combining with the barrier matrix (EU / US / China).** The matrix
(`backend/arp/transition_barrier/data/assessment_scores.json`) rates external barriers per sector
and region. WBA rates the company. They answer different questions and should stay separate:

- Read a WBA D01.a level *with* the barrier rating of the company's main operating region. Example:
  a Chinese steel mill with D01.a Unmet faces different technology and policy barriers than an EU
  mill with the same level. The barrier matrix explains context; it should not change the WBA level.
- WBA uses HQ country. Our matrix is by operating region. Map by HQ first and flag multi-region
  companies (for example ArcelorMittal, Holcim) for manual region weighting.
- Sector mapping: WBA industries are broader than the matrix sectors. Steel and aluminium sit in
  "Metals & Mining", cement in "Construction Materials & Supplies", airlines in "Passenger
  Transport", shipping in "Freight & Logistics". Map at company level. The matrix has no autos or
  aluminium row; WBA has no "heavy-duty road transport" industry (truck makers are in Motor
  Vehicles / Capital Goods).

**Plan-action extraction.** ACT Core's planning elements line up with what our extraction reads
from transition plans:

- B02.a (sector levers), B02.c (GHG savings per lever) and **B02.d (investment per lever)** are the
  checks for each extracted plan action. B02.d's test ("a clear link between the identified action
  and the financial requirements", plus a needs-vs-allocated breakdown) is a usable acceptance rule
  for "credible capex behind an action".
- Appendix 10.2 (levers by WBA industry, pp.103–115) could seed the lever vocabulary per sector.
  Reproducing it needs WBA/ADEME permission if it leaves internal use.
- D01.a's RY/RY+1 rule (score RY+1 if higher, else the average) is a simple, published way to
  combine current and planned capex. We could adopt it for our own share.

**Gaps that remain after round 3.**

- No scenario-derived capex share for steel, cement, aluminium, aviation or shipping, in WBA either.
- Data Explorer attribute content (whether raw capex numbers and units are there) is unverified.
- Mid-cap and non-English companies are outside WBA's universe.
- WBA licence wording conflicts (CC BY vs CC BY-NC-ND). Fine for internal use; ask WBA before any
  external sharing.

### 12.7 Could not access or not verified (round 3)

- **Data Explorer content:** needs an account and API approval. Not registered (that would use the
  owner's identity). Column names come from the user guide and data dictionary page, not the data.
- **Data dictionary:** an Airtable embed; the field list was not extracted.
- **Data Explorer terms of use:** no page found.
- **Steel / cement / airline / shipping counts** are by company name within WBA industries, so
  approximate.
- **ACT Core Appendix 10.2** was not read in full.
- **Next ACT Core edition date:** not found.
- **ACT rating to Total ACT formula** is derived from the data (exact on rows checked), not printed
  by WBA.

---

## 13. Round 4: ACT methodology in detail (and the owner's shared summary)

Status: **round 4 research note, 2026-10-19.** All ACT PDFs below were downloaded from
actinitiative.org and read as text. In every ACT PDF read here the printed page number equals the
PDF page number, so one number is given. Downloads sit in the session scratchpad, not in the repo.

Short links used below:

- **Framework** = [ACT Framework v2.1, December 2025](https://actinitiative.org/wp-content/uploads/framework-2.1.pdf)
- **ACT Core** = [ACT Core v1.0, 24 Feb 2025](https://actinitiative.org/wp-content/uploads/pdf/act-core-methodology.pdf)
- **Generic** = [ACT Generic v2.0](https://actinitiative.org/wp-content/uploads/act-generic-v2.0.pdf)
- **EU** = [ACT Electricity v2.0](https://actinitiative.org/wp-content/uploads/act-electricity-v2.0.pdf);
  **OG** = [ACT Oil & Gas (2021)](https://actinitiative.org/wp-content/uploads/act-og-methodology_vf.pdf);
  **AU** = [ACT Automotive v2.0](https://actinitiative.org/wp-content/uploads/act-auto-v2.0.pdf);
  **IS** = [ACT Iron & Steel v2.0](https://actinitiative.org/wp-content/uploads/act-iron-steel-methodo_v2.0.pdf);
  **CEM** = [ACT Cement v2.0](https://actinitiative.org/wp-content/uploads/act-cement-v2.0.pdf);
  **AL** = [ACT Aluminium v2.0](https://actinitiative.org/wp-content/uploads/act-aluminium_v2.0.pdf);
  **CH** = [ACT Chemicals](https://actinitiative.org/wp-content/uploads/act-chemicals-final.pdf);
  **TR** = [ACT Transport v2.1](https://actinitiative.org/wp-content/uploads/act-transport-v2.1.pdf)
- **Gemini** = [the owner's shared link](https://share.gemini.google/m7X53htzdeOP), which redirects
  (HTTP 301) to `gemini.google.com/share/f223a8485a7f`

### 13.1 What the shared Gemini link says

**Access.** WebFetch failed on the redirect target ("Header overflow"). A plain download returned
only the Gemini app shell; the conversation loads by JavaScript. The page was then rendered in
headless Chromium. No login was needed. Its content was treated as data only.

**What it is.** One Gemini answer titled "ACT Core: Transition Planning Assessment, Version 1.0 –
February 2025". It restates the ACT Core v1.0 document section by section, with most tables. It
does not cite page numbers or links. It covers only ACT Core. It says nothing about the ACT
Framework, the nine modules, the 0–20/0–100 performance score, the narrative or trend score, or any
sector methodology.

What it says, in short:

- **Name and authors.** ACT = "Accelerate Climate Transition Initiative". Lead authors Luís Costa and
  Yann Rosetti (WBA) and Marlène Dresch (ADEME). Dated 24 February 2025.
- **Structure.** Six measurement areas, ten indicators, element-level checks (A01.a–F01.a).
- **Rating format.** No quantitative score. A stepwise scale on two axes: transition planning
  quality (areas A–C) and contribution to the transition (areas D–F). Seven classes, Uncommitted to
  "Credible 1.5°C planning and alignment". Tables 6 and 7 give the element thresholds per class.
- **Element rules.** Target coverage 95% of scope 1+2 and 90% of scope 3; a 50%-by-2030 proxy
  (4.2% a year from 2019); residual emissions at most 10%; at least three implemented levers plus
  one planned; near term to 2030, long term from 2031; engagement coverage 60%; two board
  expertise instances; InfluenceMap D–F bars an association.
- **Investment.** B02.d: "discloses allocated CapEx/financial backing needed to deploy identified
  levers". D01.a matrix: electricity LC/95%, oil and gas and chemicals LC/77%, automotive and generic
  20/40/60/80% bands, agriculture 10/20%.
- **Trajectory.** E01 alignment ratio met at ≤ 1.10; F01 realignment factor bands > 3 to ≤ 1.
- **Benchmarks.** Absolute-emissions budgets from IEA, IRENA, TPI, OECM and others.
- **Appendix.** Scope 3 minimums by industry, levers by industry, "typical" low-carbon capex shares,
  and a framework-consensus mapping.

**Licence note.** The answer copies large parts of ACT Core, a document whose notice prohibits
reproduction without WBA/ADEME permission (ACT Core p.2). Under the owner's internal-use decision
we cite ACT Core directly instead and do not store the Gemini text in the repo.

### 13.2 ACT methodology from primary sources

#### 13.2.1 Framework, rating and modules

**Name.** "Assessing low-Carbon Transition", founded by ADEME and CDP in 2015, now hosted by WBA.
"ACT has been renamed Accelerate Climate Transition Initiative in 2024." [verified, ACT Core p.92;
Generic p.169]

**Rating format (sector methods).** Three parts: [verified, Framework p.13]

- Performance score, **0 to 100** (Framework v2.1). ACT announced the move "from a mark out of 20
  to a mark out of 100" on 17 December 2025.
  [verified, [ACT news](https://actinitiative.org/en/act-mitigation-assessment-performance-score-out-of-100/)]
  The WBA 2020–2024 datasheets use the older 0–20 scale (section 12.2.1).
- Narrative score, A (best) to E.
- Trend score, "+", "=" or "−".

**Performance score formula.** Each indicator is scored as a percentage. The performance score is
the weighted sum of indicator scores, with sector-specific module and indicator weights.
[verified, Framework p.14] Qualitative indicators use a five-level maturity matrix scored Basic 0,
Standard 0.25, Advanced 0.5, Next practice 0.75, Low-carbon aligned 1. Multi-question matrices weight
each question. [verified, Framework p.18, Table 5; Generic p.18, Table 7]

**Narrative score.** Five equally weighted criteria: business model and strategy, consistency and
credibility, data quality, reputation, risk. Each question scores 0–4 (Basic 0 … Low-carbon aligned
4). A criterion is the mean of its questions. The narrative points are the sum, 0–20.
[verified, Framework pp.21–24] Table 8 converts 16–20, 12–<16, 8–<12, 4–<8 and 0–<4 to letters;
the letters are an image in the PDF, so A…E in that order is our reading. [verified ranges, Framework
p.25; letters not verified]

**Trend score.** Each forward-looking indicator gets +1 if met, else −1. Met means: target
alignment ≥ 100%, other quantitative indicators ≥ 50%, qualitative ≥ Advanced. The average gives an
indicative trend: < −0.5 strong negative; −0.5 to 0 potential negative; 0 to 0.5 potential positive;
> 0.5 strong positive. The assessor then sets +, = or −. ACT says a new trend set-up is in
development. [verified, Framework pp.25–27] Generic Table 11 lists the indicators used.
[verified, Generic p.165]

**The nine modules** [verified, Framework pp.15–17, Tables 3–4; Framework p.20, Table 7]:

| # | Module | Weight range (Framework v2.1) | Generic v2.0 indicators |
|---|---|---|---|
| 1 | Targets | 15% fixed | 1.1 S1+2 target alignment; 1.2/1.3 S3 upstream/downstream alignment; 1.4 time horizon; 1.5 achievement of past targets |
| 2 | Material investment | 0–35% | 2.1 past S1+2 intensity trend; 2.2 future trend; **2.3 share of low-carbon capex**; **2.4 locked-in emissions** |
| 3 | Intangible investment | 0–10% | **3.1 low-carbon R&D**; 3.2 low-carbon patents |
| 4 | Sold product performance | 0–35% | 4.1 product interventions; 4.2 past product performance; 4.3 locked-in emissions of sold products; 4.4 sub-contracted transport |
| 5 | Management | 10% fixed | 5.1 oversight; 5.2 oversight capability; 5.3 transition plan; 5.4 incentives; 5.5 scenario testing |
| 6 | Supplier engagement | 0–20% | 6.1 strategy; 6.2 activities |
| 7 | Client engagement | 0–20% | 7.1 strategy; 7.2 activities |
| 8 | Policy engagement | 5% fixed | 8.1 policy on associations; 8.2 associations not climate-negative; 8.3 climate-policy position; 8.4 local authorities |
| 9 | Business model | 10% fixed | 9.1 low-carbon revenue; 9.2 business model changes; 9.3 sales used in client low-carbon products |

- Generic v2.0 itself still prints module 3 at 5% and module 9 at 10–15% (Generic pp.3–4). The
  Framework v2.1 ranges are newer.
- ACT harmonised weights in all sectors: 1.3 time horizon 3%, 1.4 achievement 2%, module 5 items
  3/1/3/1/2%. [verified, [ACT updates page](https://actinitiative.org/fr/mise-a-jour-methodologies-act/)]
- **Generic capex weight depends on the asset profile.** GE 2.3 = 1/3·M2·L + 1/2·M2·(1−L) and GE 2.4
  = 1/3·M2·L, where M2 is the module 2 weight and L the share of S1+2 emissions from own buildings
  and fleet. [verified, Generic pp.156–157, Table 9]
- Weighting principles: future orientation and value of information. Share of low-carbon capex is
  weighted higher only "in assessment methodologies for which a sectoral benchmark is available".
  [verified, Framework p.19]

**Module weight ranges by sector method** (module headings, each PDF's table of contents, pp.3–5).
[verified]

| Method | 1 | 2 Material | 3 Intangible | 4 Sold product | 5 | 6 Supplier | 7 Client | 8 Policy | 9 |
|---|---|---|---|---|---|---|---|---|---|
| Electricity v2.0 | 15% | 0–33% | 5–7% | 8–31% | 12% | 4–10% | 6–12% | 5% | 10% |
| Oil & gas 2021 | 15% | 5–40% | 2–10% | 10–23% | 10% | 0–20% | 0–10% | 5% | 10% |
| Automotive v2.0 | 15% | 7% | 5% | 33% | 10% | 5% | 10% | 5% | 10% |
| Iron & steel v2.0 | 15% | 10–32% | 2–10% | 10–32% | 10% | 2–10% | 6% | 5% | 10% |
| Cement v2.0 | 15% | 0–33% | 10% | 0–33% | 10% | 7% | 10% | 5% | 10% |
| Aluminium v2.0 | 15% | 12–35% | 10% | 7–30% | 10% | 4% | 4% | 5% | 10% |
| Chemicals | 15% | 10–32% | 10% | 3–25% | 10% | 10% | 5% | 5% | 10% |
| Transport v2.1 | 15% | own fleet 30% / subcontracting 0% | 5% | own fleet 0% / subcontracting 30% | 10% | 15% (7% public service) | 10% (15% public service) | 5% (8% public service) | 10% |

There is no separate ACT aviation or shipping method. Airlines and shipping are in ACT Transport.
Indicator weights per company (for example oil and gas 2.5 capex share 0–6%) are in section 12.2.1;
OG prints 2.2 lock-in 0–8%, 2.4 unsanctioned projects 2–8%, 2.5 capex 0–6%, 3.1 R&D 2–5%.
[verified, OG pp.3–4]

**Scenarios and pathways.** ACT methods use only two allocation methods: the Sectoral
Decarbonisation Approach (SDA, intensity convergence) and the Absolute Contraction Approach (ACA).
[verified, Framework p.40] Scenarios should be 1.5°C where possible (well-below 2°C minimum), ≥ 50%
probability, no overshoot, limited negative emissions, and a base year at most two years before the
reporting year. [verified, Framework p.38] ACT Core uses absolute-emission pathways only
(section 12.3).

#### 13.2.2 Every investment indicator, with formulas

| Indicator | Formula and horizon | Full score at | Benchmark source | Source |
|---|---|---|---|---|
| GE 2.3 low-carbon capex share (generic) | Score = share × 1/80%, capped at 100%; share in RY | 80% | Expert threshold: "no benchmarks are available" | Generic pp.47–48 [verified] |
| EU 2.4 (electricity) | CAPEX ratio = S_LCT / CB_LCT; score = min(ratio, 1), averaged over each year RY…RY+3 | 95% | IEA NZE electricity investment 2021–30 | EU pp.50–51 [verified]; 95% derivation in section 4 |
| OG 2.5 (oil and gas) | Score = average(S_LCT(Y)/CB_LCT; S_LCT(Y+5)/CB_LCT); CB_LCT is adapted to the company's split of fuels and power revenues | 49% "Total Energy playfield" (5% fuels, 67% power) | IEA WEO 2019 SDS | OG pp.52–53 [verified]; section 4 |
| OG 2.6 CCS/CCUS/CDR capex share | Same structure | 5% | McCollum et al. (2018) | Section 4 [verified round 1] |
| CH 2.4 (chemicals) | min(share/benchmark, 1), RY…RY+3 | 54% (49% + 5%) | O&G benchmarks via SDS; "no sectoral benchmark specific to the chemicals sector" | CH pp.55–56 [verified] |
| AU 2.2 (automotive) | As GE 2.3, next 3 years | 80% | Expert threshold | Section 4 [verified round 1] |
| D01.a (ACT Core) | Maturity band of LC share (or LC/benchmark); RY/RY+1 rule; Taxonomy-eligible not accepted | ≥ 95% / ≥ 77% / > 80% | No derivation for 77% | ACT Core pp.58–62 [verified] |
| Locked-in emissions (EU 2.2, OG 2.2, IS 2.3, CEM 2.2a, AL 2.2, CH 2.3, TR 2.3, GE 2.4) | rLB = L(t)/B(t). L = ∫ activity × intensity of existing and planned assets; B = ∫ projected activity × company benchmark intensity. Secured-activity ratio rSA = secured activity / projected activity, to RY+15. Score 100% if rLB ≤ rSA; (rLB − 1.5)/(rSA − 1.5) if rSA < rLB < 1.5; 0% if rLB ≥ 1.5 | Locked-in within the budget | SDA company pathway from the sector benchmark (e.g. IEA ETP for steel) | IS pp.55–63; Generic pp.48–53 [verified] |
| Horizons of locked-in | RY+15 for power, steel, cement, aluminium, chemicals, transport fleets; **to 2050** for oil and gas upstream and for buildings | – | – | EU p.39; OG p.42; CEM p.36; AL p.51; CH p.48; TR p.44; Generic p.50 [verified] |
| OG 2.4 unsanctioned projects within budget | Score = 100% − SUP, the share of STEPS capex outside the SDS budget (Carbon Tracker band) | 0% outside | Carbon Tracker data | OG p.51 [verified] |
| GE 3.1 / AU 3.1 / EU 3.1 low-carbon R&D | Dim. 1: low-carbon R&D ÷ total R&D (3-year), × 1/80%. Dim. 2 (AU, EU): non-mature (TRL ≤ 8 or < 8) ÷ low-carbon R&D, × 1/65%. 50/50 | 80% and 65% | Expert thresholds | Generic pp.57–58; AU p.44; EU p.57 [verified] |
| OG 3.1 R&D | D/B_RD capped (dim. 1 worth 50%); non-mature D/B_RD (up to 100%) | B_RD from SDS | IEA WEO SDS | OG pp.62–63 [verified] |
| CH 3.1 R&D | Low-carbon R&D ÷ R&D (3-year average) vs 54% | 54% | Proxy: same as capex | CH pp.67–68 [verified] |
| IS 3.1, AL 3.1, CEM 3.1, TR 3.1 R&D | See section 10.6 (80%/65%; cement 5% of capex; transport 80% or 50%) | – | Expert / Ecofys-WWF | Section 10.5 [verified round 2] |
| B02.d investment per lever (ACT Core) | Met if: funding described; "a clear link between the identified action and the financial requirements"; breakdown of needs vs funds allocated | Met / unmet | Disclosure test | ACT Core p.37 [verified] |

- **No ACT indicator measures carbon-intensive capex as an amount or share.** The nearest are
  locked-in emissions (assets, not spend) and OG 2.4 (projects outside the budget). A search of all
  ten PDFs for "carbon-intensive", "high-carbon" and "fossil … capex" found no indicator. [verified]
- **No ACT indicator tests an absolute capex amount.** All capex tests are M$/M$ shares (GE 2.3 p.47;
  EU 2.4 p.50; OG 2.5 p.52). [verified]
- **ACT Core D01.a data list:** total and climate-solutions capex for RY and RY+1; total and
  climate-solutions R&D for RY and RY−1. [verified, ACT Core p.89, Table 8]

#### 13.2.3 ACT Core (A–G) in one place

Section 12.2.2 has the full rules; checked again here against the PDF.

- **Elements.** A01.a–d, B01.a–c, B02.a–e, B03.a–e, C01.a–d, C02.a–b, D01.a, D02.a, E01.a–d, F01.a.
  [verified, ACT Core pp.16–17]
- **No score, two axes.** ACT Core "does not generate a quantitative score" and uses neither trend
  nor narrative scores. [verified, ACT Core p.10]
- **Default classes (ACT Core Table 6/7, p.18).** Plan quality: Uncommitted, Non-mature,
  GHG-committed, Initial planning, Plan developing, Full plan. Contribution: Inconsequential,
  Consequential, Aligned. [verified] WBA's 2026 grading (G…A, plan quality 0–5, contribution 0–2,
  contribution counts only from plan quality 4) is in section 12.2.2 and overrides these defaults.
- **Lever tests.** B02.a: at least three key levers implemented and one more planned (four
  considered if the plan is new); vague levers are rejected. B02.b: near term RY–2030, long term
  "beyond 2031"; actions without a timeframe are ignored. B02.c: a quantified saving with a clear
  link to the action, in tCO2e or %. [verified, ACT Core pp.32–35]
- **Levers by industry (Appendix 10.2, pp.103–115)** list actions per WBA industry. Cement levers
  appear only as the B02.a example (p.33). [verified]

#### 13.2.4 Licence

The Framework, ACT Core and every sector method carry "Reproduction of all or part of work without
licence of use permission … is prohibited" (Framework p.2: © WBA and ADEME 2025; ACT Core p.2: ©
WBA, ADEME 2025; older methods © CDP and ADEME). [verified] **Owner decision (round 3): the
platform is non-commercial and internal, so ACT figures may be used with citation.** Store each
figure with method, version, page and the licence line. Paraphrase rules in code and docs; do not
copy ACT tables wholesale. Ask WBA/ADEME before sharing outputs outside the organisation.

### 13.3 Gemini summary vs primary sources

All page numbers are ACT Core unless marked.

**Confirmed** [verified]:

| Gemini claim | Source |
|---|---|
| Version 1.0, 24 Feb 2025; authors Costa, Rosetti (WBA), Dresch (ADEME) | p.2 |
| "Accelerate Climate Transition Initiative" | p.92 (renamed 2024). Older methods say "Assessing low-Carbon Transition" (Generic p.169). |
| Six areas, ten indicators, element names | pp.9, 16–17 |
| No quantitative score; stepwise; two axes | p.10 |
| Class descriptions Uncommitted … Consequential planning | pp.10–11 |
| Table 6 and 7 class rows and thresholds | p.18 |
| A01.b coverage 95% S1+2, 90% S3 | pp.22–23 |
| 50% by 2030 proxy, 4.2% × (target year − 2019) | p.25 |
| Residual emissions max 10% at net zero | p.26 |
| B02.a three implemented + one planned (four if new) | pp.32–34 |
| B02.b near term to 2030, long term from 2031 | p.34 |
| B02.c quantitative GHG savings per lever | p.35 |
| B03.a/c at least two types (three for financial institutions); B03.b/d 60% (90% banks, 80% investors) | pp.40–47 |
| C01.c two expertise instances; C01.d LTIP linked to GHG metrics; C02.b InfluenceMap D–F | pp.52, 54, 56 |
| D01.a bands for electricity (95%), oil and gas and chemicals (77%), automotive and generic | p.62 |
| E01 met at ratio ≤ 1.10; F01 realignment factor and bands | pp.72–74, 81–82 |
| Five "aligned state" questions | Framework p.9; Generic p.166 |
| Electric utilities levers (coal phase-out, renewables, PPAs, smart grid, CCUS) | p.114 |
| Sources list (ACT Framework 2024, CDP, GFANZ, TPT, HLEG, CSRD, EFRAG, CBI, WBA) | p.91 |

**Wrong or garbled** [verified against the PDF]:

| Gemini claim | Primary source says |
|---|---|
| Final class "Credible 1.5°C planning and alignment" | "Credible 1.5°C" (p.11). Minor. |
| Agriculture D01.a "11–20%" under Standard | 11–20% is the **Advanced** column; Standard and Next practice are blank (p.62; section 12.2.2). |
| B02.d = "discloses allocated CapEx/financial backing" | Also needs "a clear link between the identified action and the financial requirements" and a needs-vs-allocated breakdown (p.37). The link is the part the owner adopted. |
| Table 11 "Agriculture / Food < 25%" | Agricultural Products < 15%; Food Production < 25% (p.116). |
| Table 11 omits heavy industry | Metals & Mining < 25%, Oil & Gas < 25%, Utilities < 50%, Motor Vehicles < 50%, Chemicals < 10% (pp.116–117). |
| Table 12 maps requirements to ACT Core elements (A01.b, D01.a …) with relabelled items | Table 12 maps to **sectoral** ACT indicator numbers (e.g. 8.3, 6.1, 7.1). The 84% item is "climate commitment wording", not "timebound interim metrics" (p.119). |
| "Rekker et al. 2022" in the Sources list | Cited in the E01 text (p.71), not in the Sources list (p.91). Minor. |

**Unsupported (not checked or not in ACT Core)** [not verified]: "financial intensity targets
(CO2/$) are not accepted"; scope 3 proxy 30% by 2030 and "≤ 2040 for power/maritime"; pure-play
companies automatically Low-carbon aligned in D02.a; "Carbon Action Tracker Paris Aligned
Benchmarks" in the benchmark list; the full Table 9 rows.

**Missing from Gemini** (all material for this platform): the D01.a year rule (p.61); R&D rows and
"capex preferred over R&D" (p.61–62); Taxonomy-eligible capex not accepted (p.59); WBA's 2026
grading (Note 2026); everything in section 13.2.1–13.2.2 (sector methods, 0–100 score, narrative,
trend, locked-in, R&D, benchmarks).

**Verdict.** Accurate as a summary of ACT Core's structure and element rules. Not usable as a source:
no page references, two garbled appendix tables, one misplaced cell, and the two investment rules
the owner adopted are incomplete or absent. Cite ACT Core directly.

### 13.4 Mapping ACT to this platform

**(a) Transition-barrier matrix and rule book.** ACT rates the company. It does not rate external
barriers by region. The closest ACT parts are the narrative "Risk" criterion (TCFD transition risks:
policy, legal, market; Framework p.24) and B02.e ("levers account for future risks and
uncertainties", ACT Core pp.38–39). So the matrix fills a gap ACT leaves; keep it separate from any
ACT-style score (as in section 12.6).

The rule book's action ids line up with ACT Core levers (Appendix 10.2 and the B02.a examples).
Matching ACT names in each action's label would let one action id serve both the barrier criteria
and the B02 checks. Our mapping:

| Rule-book actions (`rule_book.json`, "actions") | ACT Core lever wording | ACT Core page |
|---|---|---|
| `pwr.renewables`, `pwr.storage`, `pwr.grid`, `pwr.coal_exit` | Expand renewable capacity; prosumer storage; integrate low-carbon sources into the grid, smart grids; phase out coal, reduce unabated gas | p.114 |
| `cement.clinker_sub`, `cement.alt_fuels`, `cement.ccus` | Reduce clinker-to-cement ratio; low/near-zero fuels incl. kiln electrification, waste fuels; CCUS | p.33 |
| `chem.low_carbon_h2`, `chem.e_cracker`, `chem.ccus` | Green hydrogen/methanol feedstock; electrification of processes; permanent CCUS | pp.33, 106 |
| `steel.scrap_eaf` (`steel.h2_dri`, `steel.ccus` not listed) | Metals & Mining: more scrap, process efficiency, zero-GHG power | p.110 |
| `min.electric_fleet`, `min.recycling` (`min.new_supply` is not a decarbonisation lever) | Electric vehicles and machinery; scrap | p.110 |
| `avi.hefa_saf`, `avi.advanced_bio_saf`, `avi.e_saf` | Bio-sourced SAF, waste and residue fuels, power-to-liquids | p.108 |
| `shp.alt_fuel_vessels`, `shp.green_fuels`, `shp.efficiency` | Low-GHG fuel vessels; near-zero fuels (ammonia, methanol, hydrogen); retrofits, wind | p.109 |
| `hdt.bev_trucks`, `hdt.fcev_trucks`, `hdt.public_charging`, `hdt.h2_refuelling` | Zero-GHG trucks; depot charging and hydrogen refuelling | p.109 |
| `ogu.ldar`, `ogu.flaring`, `ogu.electrification` | Methane reduction, end non-emergency flaring/venting, electrify facilities | p.111 |

ACT Core Table 10 has no steel-specific row, so `steel.h2_dri` and `steel.ccus` come from the ACT
Iron & Steel method or TPT guidance (not checked here). [mapping is ours; ACT wording verified]

**(b) Plan-action extraction matched to barriers.** Each extracted action should carry what the
B02 elements test. Fields and acceptance rules:

| Field per extracted action | ACT test | Rule |
|---|---|---|
| `action_id` (rule-book id) or "other" | B02.a | Sector-specific; vague wording rejected (p.34) |
| status: implemented / planned | B02.a | ≥ 3 implemented + ≥ 1 planned, or 4 considered for a new plan (pp.32–34) |
| timeframe (year or range) | B02.b | Near term RY–2030, long term after 2031; no timeframe → ignore (pp.34–35) |
| GHG saving (tCO2e or %) with link | B02.c | Clear link to the action (p.35) |
| investment amount, currency, years; funds allocated vs needed; quote | **B02.d (adopted)** | Clear link between the action and the money; needs vs allocated (p.37) |

The barrier rating of the action's sector and region then shows whether that action faces a
barrier. A planned action with no B02.d link and a high barrier is the weak case.

**(c) Capex credibility check.**

- **Share.** Compute the low-carbon capex share for RY and RY+1 and combine them with the
  **adopted D01.a rule** (p.61). Taxonomy-eligible-not-aligned capex must not count (p.59).
- **Threshold on the share (owner decision open).** Either the ACT Core bands (p.62), or the
  sector-method ratio min(share/benchmark, 1) (EU p.51, OG p.53, CH p.56, Generic p.47). Both use
  the same benchmarks: 95% power; 77% (ACT Core) or 49%/54% (sector methods) for oil and gas and
  chemicals; 80% elsewhere. Steel, cement, aluminium, aviation and shipping get only the generic 80%
  expert threshold.
- **Absolute amount.** ACT has no amount test. Use B02.d: the sum of linked investments per action
  must be traceable to a reported amount. CA100+ 6.1.b/6.2 stays the source for amount disclosure
  (section 2).
- **Carbon-intensive capex.** ACT has none. Keep CA100+ 6.1.b (section 9.1, item 1).

**Which ACT indicators to reproduce, and what already exists.**

| ACT indicator | Platform status | Recommendation |
|---|---|---|
| D01.a low-carbon capex share, RY/RY+1 | `green.py`: `capex_total`, `green_capex_total`, `green_capex_share_pct`, `green_capex_eu_aligned`, `transition_capex_total`; `eu_taxonomy.py`: `eut_capex_aligned_pct`, `eut_capex_total_amount`. Fiscal years as disclosed; no RY+1 (planned) field. | **Reproduce.** Add planned-year capex and apply the rule. |
| B02.a–d levers, timeframe, savings, investment per lever | 64-indicator set has yes/no checks only: #26–27 (renewables, climate solutions strategy), #29 capex planning, #28 opex planning. No per-action records. | **Reproduce** in the plan-action extraction (b). |
| GE 3.1 family, low-carbon R&D share | Total R&D: `spend_extractor_agent.py` (SpendTopic.RND) and XBRL financials. No low-carbon R&D amount. #31 asks only about an R&D strategy. | **Reproduce** for steel, cement, aluminium, aviation and shipping, where it is the only numeric investment test. Needs a low-carbon R&D field. |
| D02.a / 9.1 low-carbon revenue share | `green.py` revenue fields (`green_revenue_*`), `eut_turnover_*`; #30, #61, #62 | **Covered.** Add the D02.a band only if wanted. |
| Sector capex ratio (EU 2.4, OG 2.5, CH 2.4, AU 2.2, GE 2.3) | Not implemented | Reproduce as the continuous variant of D01.a, if the owner picks it. |
| Locked-in emissions (2.2/2.3/2.4) | Not implemented; no asset-level data | **Skip for now.** Needs plant capacity, emission factor, commissioning year and lifetime for every asset. Revisit with an asset database. |
| A01, C01, C02, B03 (targets, governance, policy, engagement) | 64-indicator set: #1–12 targets and offsets, #13–21 governance, #19 incentives, #32–36 and #63 engagement and policy, #46–48 emissions | **Covered as disclosure checks.** ACT thresholds (95%/90% coverage, InfluenceMap) are not applied. Leave as is. |
| E01, F01 (target and trajectory alignment vs a 1.5°C path) | #10 only asks if targets reference a 1.5°C pathway | **Skip.** Needs pathway data and emission time series; outside the capex check. |
| OG 2.4 unsanctioned projects; 3.2 patents; narrative and trend scores | Not implemented | **Skip.** Carbon Tracker data, patent databases, and analyst judgement. |
| Misaligned capex (#60) | 64-indicator set yes/no | No ACT counterpart; keep under CA100+. |

**Remaining owner decisions** (also in section 9.3):

1. Threshold on the share: ACT Core bands or the continuous sector ratio.
2. Oil and gas and chemicals benchmark: 77% (ACT Core, no derivation) or 49%/54% (sector methods).
3. Whether to add a low-carbon R&D field and use the R&D tests for heavy industry and transport.
4. "Green" definition: ACT counts nuclear and CCUS as low-carbon; `green.py` does not (section 9.3,
   item 4).
5. Whether to align rule-book action labels with ACT Core lever wording.

**Does `openwiki/` need an update?** No. This round changes a research note, not code behaviour.

### 13.5 Could not access or not verified (round 4)

- **Gemini page:** WebFetch failed ("Header overflow"); read via headless Chromium. It may change
  or be deleted by its owner.
- **Framework Table 8 letters** are an image; A…E order is assumed.
- **ACT Iron & Steel lever list** (for `steel.h2_dri`, `steel.ccus`) not read.
- **ACT Transport aviation and shipping indicators** beyond TR 2.3 and TR 3.1 not reread.
- **Sector methods after the 0–100 change:** the PDFs read still state weights in percent; no
  re-issued sector PDFs were found. Whether ACT rescaled any thresholds is not checked.
- **ACT Agriculture, Buildings, Pulp & Paper, Glass, Retail, Fashion and Finance methods** not read.
