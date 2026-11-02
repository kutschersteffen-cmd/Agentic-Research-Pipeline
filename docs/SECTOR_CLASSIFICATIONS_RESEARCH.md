# Sector / Industry Classification Systems — Research Note

Date: 2026-11-02. Scope: NACE Rev. 2 / 2.1, ISIC Rev. 4 / 5, NAICS 2022, GICS, BICS, ICB, TRBC, plus EU Taxonomy's use of NACE.

> "BRICS" in the request is read as **BICS** (Bloomberg Industry Classification System). BRICS is a country bloc, not a classification.

Legend: **[V]** verified against the cited primary source in this session. **[U]** not verified here (source was unreachable, only secondary sources confirmed it, or it comes from prior knowledge). Treat [U] as a lead, not a fact.

## 1. Statistical, activity-based systems

These classify **economic activities**, and usually the **establishment / local unit** by its principal activity, measured by value added (output or employment can stand in). They are free and public, and they are revised every few years to a decade.

### ISIC (UN Statistics Division)
- Owner: UNSD, endorsed by the UN Statistical Commission. It is the reference classification that NACE derives from. [V] https://unstats.un.org/unsd/classifications/Econ/isic
- Rev. 5 was endorsed at UNSC 54 (2023). Explanatory notes and the implementation plan were endorsed at UNSC 55 (2024). [V] https://unstats.un.org/unsd/classifications/Econ/isic, https://unstats.un.org/unsd/classifications/Workshops/AddisAbaba2026/Session3-Deck1_WorkshopAddis_intro_to_isic_rev5.pdf
- Hierarchy (section letter / 2-digit division / 3-digit group / 4-digit class):
  - Rev. 4: 21 / 88 / 238 / 419
  - Rev. 5: 22 / 87 / 258 / 463
  - [V, from UNSD workshop slides, not the final structure file] https://unstats.un.org/unsd/classifications/Workshops/AddisAbaba2026/Session3-Deck1_WorkshopAddis_intro_to_isic_rev5.pdf
- Basis: the statistical unit's principal activity, by value added. [U] Introductory text: https://unstats.un.org/unsd/classifications/Econ/Download/In%20Text/ISIC5_Intro_11Mar2024.pdf
- Licensing: free. The structure is downloadable as CSV/XLSX. [V] https://unstats.un.org/unsd/classifications/Econ/isic

### NACE Rev. 2 / Rev. 2.1 (Eurostat)
- Owner: Eurostat / European Commission. Legal basis is Annex I of Regulation (EC) No 1893/2006, which a 2023 delegated act amended to Rev. 2.1. [V] https://ec.europa.eu/eurostat/web/nace
- Rev. 2 covers European statistics for reference years 2008–2024. Rev. 2.1 was adopted in October 2022 and applies "from 2025 onwards". [V] https://ec.europa.eu/eurostat/web/nace, https://ec.europa.eu/eurostat/fr/web/products-eurostat-news/-/wdn-20230210-1
- Hierarchy (section / division / group / class):
  - Rev. 2: 21 (A–U) / 88 / 272 / 615
  - Rev. 2.1: 22 (A–V) / 87 / 287 / 651
  - Old section J (Information and communication) is split in Rev. 2.1, so later section letters shift. [U: confirmed only by national statistical offices and UNSD workshop slides] https://unstats.un.org/unsd/classifications/Workshops/Santiago2025/Session3.3_NACE_Rev2.1.pdf, https://www.cso.ie/en/media/csoie/methods/cars/NACE_Rev._2.1_Manual_and_Guidelines.pdf
- Code format: letter section, then `NN.NN` (for example `C 24.10`). The first two levels are identical to ISIC. The lower levels are ISIC split further for European needs. National extensions add digits (for example German WZ, French NAF). [U]
- Correspondence: Eurostat publishes NACE Rev. 2 ↔ Rev. 2.1 and NACE ↔ ISIC tables in its "Correspondence tables" section. [V that the tables exist] https://ec.europa.eu/eurostat/web/nace
- Licensing: free.

### NAICS 2022 (US Census Bureau; joint US / Canada / Mexico)
- Owner: US ECPC / OMB, published by the Census Bureau. Revised every 5 years (2017, 2022, with 2027 next). [U: census.gov returned 403 in this session] https://www.census.gov/naics/
- Basis: **production-oriented**. An establishment is grouped by its production process. [U] https://www.census.gov/naics/
- Hierarchy: 2-digit sector (20) / 3-digit subsector (96) / 4-digit industry group (308) / 5-digit NAICS industry (689) / 6-digit national industry (1,012). Levels 2–5 are trilateral. The 6-digit level is country-specific. [U: counts from prior knowledge]
- Correspondence: Census publishes NAICS 2022 ↔ 2017 and NAICS ↔ ISIC Rev. 4 concordances. [U] https://www.census.gov/naics/?68967
- Licensing: free.

## 2. Investment, market-based systems

These classify **companies or securities**, not establishments. Each company gets one code for its principal business, judged mainly by **revenue** (and for some systems earnings and market perception). They are proprietary and licensed, and their structures change at index-provider review cycles.

### GICS (MSCI and S&P Dow Jones Indices)
- Developed in 1999 by MSCI and S&P DJI. [V] https://www.spglobal.com/spdji/en/education/article/talkingpoints-an-overview-of-sp-500-sector-indices-and-25-years-of-gics
- **Current structure: 11 sectors / 25 industry groups / 74 industries / 163 sub-industries.** Codes are 2 / 4 / 6 / 8 digits (sub-industry `45102010` = IT Consulting & Other Services). [V] https://www.msci.com/indexes/documents/methodology/0_MSCI_Global_Industry_Classification_Standard_GICS_Methodology_20240801.pdf
- Basis: the company's **principal business activity, with revenue as the main factor**. Earnings and market perception are also considered. [U: wording from the methodology above, not re-read line by line]
- 2023 changes (announced March 2022, effective after the close of 17 March 2023) [V that the reclassification was announced; details U] https://www.msci.com/indexes/index-resources/gics:
  - Transaction & Payment Processing moved from IT to Financials.
  - Data Processing & Outsourced Services moved from IT to Industrials.
  - The Retailing industry group was split into Consumer Discretionary Distribution & Retail and Consumer Staples Distribution & Retail.
  - Department Stores and General Merchandise Stores were merged into Broadline Retail.
  - Several Energy and Real Estate sub-industries were reworked.
  - The structure before 2023 was 11 / 24 / 69 / 158. [U]
- Revision: reviewed annually, with structural changes in some years only. [V] https://www.msci.com/indexes/index-resources/gics
- Licensing: proprietary. The structure and definitions are published, but company assignments and commercial use need an MSCI or S&P licence. [U]

### ICB (FTSE Russell, LSEG)
- Owner: FTSE Russell. The 2019 revision added Real Estate as the 11th industry. [V that the page exists; counts from secondary sources, U] https://www.lseg.com/en/ftse-russell/industry-classification-benchmark-icb
- Structure: 11 industries / 20 supersectors / 45 sectors / 173 subsectors. Codes are 2 / 4 / 6 / 8 digits. The structure before 2019 was 10 / 19 / 41 / 114. [U]
- Basis: the company's main source of revenue. [U] Product overview: https://www.lseg.com/content/dam/ftse-russell/en_us/documents/other/industry-classification-benchmark-product-overview-march-2020.pdf
- Licensing: proprietary (LSEG).

### TRBC (LSEG, formerly Refinitiv / Thomson Reuters)
- Owner: LSEG. 5 levels, with a 10-digit code at the activity level. [U]
- Structure as LSEG's data catalogue states it: 13 economic sectors / 32 business groups (also called business sectors) / 61 industry groups / 153 industries / 895 activities. Wikipedia gives 13 / 33 / 62 / 154 / 898 for the 2020 version. **Counts are inconsistent across sources, so treat them as [U].** https://www.lseg.com/en/data-catalogue/entity/legal-entity-data/industry-classifications
- Basis: revenue-based principal activity. [U] https://www.refinitiv.com/en/financial-data/reference-data/classifications/business-and-industry-classifications/trbc-sector-classification
- Licensing: proprietary.

### BICS (Bloomberg)
- Owner: Bloomberg. Every company is classified to **level 4 (sub-industry)**, and where useful to **segment levels 5–7**. [V via Bloomberg professional page, as summarised by search] https://www.bloomberg.com/professional/?p=54487
- Basis: Bloomberg's revenue-segmentation product is built on BICS and supports portfolio revenue exposure by BICS segment. Bloomberg does not publish the exact rule for assigning a company's primary code. [U] https://professional.content.cirrus.bloomberg.com/professional2023/insights/webinar/revenue-segmentation-financial-analysis-and-regulatory-transparency-webinar/
- Level counts: **not verified**. The methodology is not public.
- Licensing: proprietary, available through a Bloomberg Terminal or data licence.

## 3. Correspondences

| From ↔ To | Official? | Publisher |
|---|---|---|
| NACE Rev. 2 ↔ NACE Rev. 2.1 | Yes | Eurostat [V] |
| NACE ↔ ISIC (Rev. 4 / 5) | Yes. NACE is ISIC split further, so the top 2 levels are identical | Eurostat / UNSD [V that tables exist] |
| NAICS ↔ ISIC Rev. 4 | Yes | US Census [U] |
| NAICS 2022 ↔ 2017 | Yes | US Census [U] |
| GICS ↔ ICB / TRBC / BICS | **No official public table** | none. Vendors and data providers sell proprietary mappings [U] |
| GICS / ICB ↔ NACE / ISIC / NAICS | **No official public table** | none [U] |

There is no official bridge between the statistical family and the investment family. Any mapping between them is a judgement and loses information in both directions.

## 4. EU Taxonomy and NACE
The EU Taxonomy Climate Delegated Act (Reg. (EU) 2021/2139) lists NACE Rev. 2 codes against each activity. The Regulation says these codes are **indicative** and do not define eligibility: the activity description decides. [U] https://eur-lex.europa.eu/eli/reg_del/2021/2139/oj
Once NACE Rev. 2.1 applies, the Taxonomy annexes still cite Rev. 2 codes, so users need the Eurostat Rev. 2 ↔ 2.1 table. [U]

## 5. Granularity comparison

| System | Owner | Unit / basis | L1 | L2 | L3 | L4 | L5+ | Free? |
|---|---|---|---|---|---|---|---|---|
| ISIC Rev. 4 | UNSD | establishment, value added | 21 | 88 | 238 | 419 | – | yes |
| ISIC Rev. 5 | UNSD | establishment, value added | 22 | 87 | 258 | 463 | – | yes |
| NACE Rev. 2 | Eurostat | local unit, value added | 21 | 88 | 272 | 615 | national | yes |
| NACE Rev. 2.1 | Eurostat | local unit, value added | 22 | 87 | 287 | 651 | national | yes |
| NAICS 2022 | Census / ECPC | establishment, production process | 20 | 96 | 308 | 689 | 1,012 [U] | yes |
| GICS (2023–) | MSCI / S&P | company, revenue | 11 | 25 | 74 | 163 | – | licence |
| ICB (2019–) | FTSE Russell | company, revenue | 11 | 20 | 45 | 173 [U] | – | licence |
| TRBC | LSEG | company, revenue | 13 | 32 | 61 | 153 | 895 [U] | licence |
| BICS | Bloomberg | company, revenue segments | ? | ? | ? | ? | levels 5–7 | licence |

## 6. Practical guidance
- **Regulatory or EU reporting** (EU Taxonomy, CSRD/ESRS sector agnostics, ECB/EBA Pillar 3 NACE splits): use **NACE**. From 2025 the version is Rev. 2.1, but keep the Rev. 2 codes that the Taxonomy cites.
- **Joining statistics** such as input-output tables, emissions per sector or employment: use **ISIC or NACE at division level**. That is where official stats and IO tables (OECD ICIO, EXIOBASE, and similar) usually line up.
- **US government data** such as Census or BLS: use **NAICS**.
- **Portfolio, index, peer and benchmark work**: use **GICS** (for most mandates) or **ICB** (for FTSE/STOXX benchmarks). Pick whichever one your benchmark uses.
- **Revenue-exposure or thematic purity**: one code per company is too coarse. Use segment revenue (BICS levels 5–7, FactSet RBICS, or your own extraction from filings) mapped to activities.

Pitfalls:
1. **Multi-activity firms.** Statistical systems classify establishments, while market systems give one code to the whole company. A conglomerate gets one GICS code but many NACE codes across its local units. Do not treat a company's GICS code as its activity mix.
2. **Version drift.** GICS 2023, NACE 2.1 (2025), ISIC 5 and the coming NAICS 2027 all change codes. Store the version next to every code, and use the official tables to map between versions. For example, sub-industry `25503010` Department Stores no longer exists after 2023. [U]
3. **No official cross-family bridge.** Any NACE ↔ GICS mapping is a judgement. Label it as such and keep the rationale.
4. **Licensing.** You can redistribute the GICS, ICB, TRBC or BICS structure only under a licence. Company-level assignments are always licensed data. Open-source code should ship with samples only.
5. **Granularity mismatch.** Hierarchical prefix matching only works within one family. NAICS 6-digit and NACE classes do not nest into each other.

## 7. In this repo
- `backend/arp/schemas/common.py:57` defines `isic_code` (ISIC Rev. 4) on activities as the join key for indirect exposure.
- `backend/arp/research/standards_mapping/crosswalk.py:10-68` is a deterministic ISIC Rev. 4 → target-code lookup from a CSV (`isic_code,target_code,target_label`). It matches on code prefix in both directions.
- `backend/arp/research/standards_mapping/gics.py:14-97` classifies GICS with an LLM against a closed reference list. The docstring at :73-75 notes there is no public ISIC → GICS table, which matches §3.
- `backend/arp/research/standards_mapping/mapper.py:19-22,41-57,69-94` builds NACE, NAICS and SIC by crosswalk from the activity's `core_isic_codes`, and classifies GICS directly. The comment at :31 says a deployment can have a NACE table but no GICS licence.
- `backend/arp/config.py:276-287` holds the paths for the NACE (labelled "ISIC Rev.4 -> NACE Rev.2"), NAICS and SIC crosswalks, the GICS reference, and the company → 8-digit GICS mapping.
- `backend/arp/research/indirect_exposure/company_mapper.py:16-44` resolves a company to an ISIC Rev. 4 code. Without an LLM, it falls back to an ISIC-division or NACE-class match (:28-34).
- Sample data lives in `backend/arp/research/standards_mapping/sample_data/` (`isic_nace_sample.csv`, `isic_naics_sample.csv`, `isic_sic_sample.csv`, `gics_reference_sample.csv`).
  - **Finding:** `gics_reference_sample.csv` has 11 sectors, 23 industry groups, 71 industries and 159 sub-industries. That matches neither the 2023 structure (11/25/74/163) nor the pre-2023 one (11/24/69/158). It also still contains `25503010` Department Stores (line 184), a code discontinued in 2023. The sample is out of date and incomplete.
- Other files that touch these codes, not reviewed in detail: `backend/arp/research/indirect_exposure/criticality.py`, `core_sectors.py`, `backend/arp/transition_alignment/benchmarks.py`, `backend/arp/research/revenue_exposure/resolver.py`, `backend/arp/cli/taxonomy.py`, `backend/arp/api/routers/taxonomies.py`.
- `backend/arp/agents/taxonomy_researcher.py` has no NACE, GICS or ISIC references.
- Gaps: no ICB, TRBC or BICS support. NACE and ISIC are pinned to Rev. 2 / Rev. 4, with no Rev. 2.1 / Rev. 5 or version field.
