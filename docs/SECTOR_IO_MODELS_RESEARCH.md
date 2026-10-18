# Sector-level input-output tables for the indirect-exposure tier

Which IO / MRIO tables could feed `backend/arp/research/indirect_exposure/` besides the OECD ICIO
and EXIOBASE loaders it already has. For each one: who publishes it, what it covers, the licence
for internal commercial use, the format, and whether it is detailed enough to isolate
semiconductors, grid equipment and data centres.

Status: **desk review, 2026-10-18.** Primary sources only. Some publisher sites were down or
blocked while this was written (OECD returned 403, IDE-JETRO returned 503 "under maintenance").
Where a fact comes only from a search-engine snippet of the publisher's own page, it is tagged
**[snippet]**. Where no primary source confirmed it, it says **not confirmed**.

---

## 1. What the loaders need

- `ICIOData` (`icio_loader.py`) holds `codes`, `labels`, `total_output` and an n×n `matrix`, where
  `matrix[i, j]` is the flow from supplier industry i to user industry j. Countries are summed away.
- `load_icio` reads a square CSV plus `industries.csv` (`isic_code,label,total_output`).
- `build_icio_from_long_format` (`exiobase_loader.py`) reads one row per flow. Its column names
  are parameters (`supplier_code_col`, `user_code_col`, `value_col`), and any extra columns, such
  as region, are summed over.
- `leontief.py` divides each column by `total_output` and inverts (I − A).
- The LLM prompts in `company_mapper.py` and `core_sectors.py` say "ISIC Rev.4". The data
  structure accepts any string code, but a non-ISIC table would need that wording changed.

So any table works if it gives an industry×industry (or product×product) intermediate-flow
matrix plus gross output per sector. Because regions are summed away, **sector detail and
licence matter more than country coverage**.

## 2. Comparison table

"Commercial use" means internal use by a for-profit firm. Nothing is resold.

| Table | Publisher | Coverage (latest) | Licence for internal commercial use | Format | Isolates semis / grid equipment / data centres? |
|---|---|---|---|---|---|
| **OECD ICIO 2025** | OECD | 80 economies + RoW, 50 ISIC Rev.4 industries, 1995–2022 | Not confirmed for data (terms page 403). OECD content from 1 Jul 2024 defaults to CC BY 4.0 | CSV (year blocks), R | No: C26, C27, D35 and 62–63 are aggregates |
| **EXIOBASE 3.11.2** | EXIOBASE consortium (XIO SA AS, WU) | 44 countries + 5 RoW, 163 industries / 200 products, 1995–2024 (core data to 2023, then nowcast) | **Paid licence needed.** The non-commercial licence excludes "any use by for-profit or commercial entities" | TSV in zip (`Z.txt`, `x.txt`, `Y.txt`), ixi and pxp | Grid: yes (transmission, distribution, power by technology). Semis: no. Data centres: no |
| **WIOD 2016** | GGDC, Univ. Groningen | 43 countries + RoW, 56 ISIC Rev.4 sectors, 2000–2014 | CC BY 4.0 | Excel (.xlsb), Stata, R | No. Also stale (ends 2014, no update) |
| **Eora2 / Eora26** | KGM & Associates / Eora team | 190 countries; full table 19,640 country-specific sectors, 1990–2024; Eora26 1990–2023 | **Paid annual subscription** for non-academic use; price not published; at most 200 raw data points may be published | TSV in zip (Eora26: `T`, `VA`, `FD`, `Q`) | Eora26: no (26 sectors). Full Eora: depends on each country's national table, not confirmed |
| **GLORIA 060** | Global MRIO Lab (Univ. Sydney, NIES), distributed by UNSW | 164 regions, 120 sectors, 1990–2028 (release 059 note) | **Not free:** CC BY-NC 3.0 AU; "commercial applications are managed by FootprintLab"; price not published | Not confirmed | Not confirmed (sector list not reachable) |
| **Eurostat FIGARO 2026** | Eurostat / JRC | 49 countries + RoW, 64 NACE Rev.2 industries and 64 CPA products, 2010–2024 | **Yes, free:** CC BY 4.0, commercial reuse allowed with attribution | CSV flat and CSV matrix (Excel only at 21 industries) | No: same two-digit level as ICIO |
| **ADB MRIO** | Asian Development Bank | 62 / 72 / 74 economies + RoW, 35 sectors, 2000 and 2007–2024 | **Yes, free:** KIDB terms allow commercial use with attribution | .xlsx, one file per year | No: "Electrical and optical equipment" is a single sector |
| **GTAP 12** | Center for Global Trade Analysis, Purdue | 163 regions (145 countries), 65 sectors, reference years 2004…2019, 2023 | **Paid:** USD 10,000 one-off for a for-profit organisation (perpetual) | GTAPAgg / FlexAgg packages, GDX (GEMPACK/GAMS) | No (`ele`, `eeq`, `ely`) |
| **US BEA IO accounts** | US Bureau of Economic Analysis | US only. Detail: 402 industries, benchmark years (latest 2017). Summary: 71 industries, annual from 1997 | **Yes, free:** public domain | Interactive tables, API, xlsx | **Yes:** semiconductors (334413), transformers (335311), switchgear (335313), storage batteries (335911), data processing/hosting (518200). Electricity is one row (221100) |
| **USEEIO v2.5** | US EPA | US, BEA Detail/Summary 2017 schema, data years 2017–2022 | **Yes, free:** EPA data public domain by default | .xlsx per model | Same detail as BEA (built on it) |
| **IDE-JETRO AIIOT** | IDE-JETRO | 10 economies, 76 sectors, latest table 2005 | Not confirmed (site down) | Not confirmed | No, and far too old |
| **OECD national IOTs 2025** | OECD | OECD + G20 + others, 1995–2022, single-country tables | Same as ICIO (not confirmed) | .zip | No (same industries as ICIO) |
| **Open CEDA 2025** (extra) | Watershed | 148 countries, 400 sectors, base year 2023 | CC BY-SA, free | .xlsx | Publishes emission factors, not flow matrices, so the loaders cannot use it |
| **CEADs China MRIO** (extra) | CEADs | 31 Chinese provinces, 42 sectors, 2012/2015/2017/2018/2020 | Not confirmed | Not confirmed | No |

## 3. Per-dataset notes

### OECD ICIO (already supported): real-data status

- The 2025 edition covers 1995–2022. It adds Angola, the UAE, DR Congo and São Tomé and Príncipe;
  splits agriculture and mining into two-digit divisions; splits basic metals into iron and steel
  versus non-ferrous; and separates shipbuilding.
  [OECD 2025 edition note](https://stats.oecd.org/wbos/fileview2.aspx?IDFile=a9868f6c-31ed-4943-95cd-6c42afa2c2a9)
- Coverage: "38 OECD countries, 42 non-OECD economies, the Rest of the World and split tables for
  China and Mexico". The industry table in the same note lists 50 ISIC Rev.4 activities. Among
  them: "Manufacture of computer, electronic and optical products" (26), "Manufacture of
  electrical equipment" (27), "Electricity, gas, steam and air conditioning supply" (35) and
  "Computer programming and information service activities" (62, 63).
  [same note](https://stats.oecd.org/wbos/fileview2.aspx?IDFile=a9868f6c-31ed-4943-95cd-6c42afa2c2a9)
- Versions and timing **[snippet]**: there is a regular ICIO (80 economies + RoW) and an extended
  one (China and Mexico split). The tables are CSV in year blocks (1995–2000 … 2016–2022), and the
  extended version also comes as R files. The current database was "released mid-January 2026"
  as a second revision of the August 2025 release.
  [OECD ICIO dataset page](https://www.oecd.org/en/data/datasets/inter-country-input-output-tables.html)
  The launch event was in November 2025.
  [OECD blog](https://www.oecd.org/en/blogs/2025/11/oecd-inter-country-input-output-icio-tables-and-trade-in-value-added-tiva-database-launch-of-the-2025-edition.html)
  No 2026 edition was found.
- Licence **[snippet]**: content published from 1 July 2024 is "generally available under CC
  licences. The default licence applied by the OECD is Creative Commons Attribution 4.0 (CC BY
  4.0), but others might apply in exceptional cases."
  [OECD open-by-default policy](https://www.oecd.org/en/about/oecd-open-by-default-policy.html).
  The "Data" section of the
  [OECD Terms & Conditions](https://www.oecd.org/en/about/terms-conditions.html) warns that data
  "may be subject to restrictions beyond the scope of these Terms". **Not confirmed** which
  licence the ICIO files themselves carry: both pages returned 403 to direct fetches.
- Fit: the format matches the existing loader. It cannot isolate any of the three themes: semis
  sit inside 26, grid equipment inside 27, and data centres (ISIC 63.11) inside 62–63.

### EXIOBASE (already supported): real-data status and a licence warning

- The latest release is **v3.11.2, published 2026-09-30**
  ([Zenodo record](https://zenodo.org/records/23039074), concept DOI 10.5281/zenodo.3583070). It
  has ixi and pxp archives for 1995–2024. Per the record, the latest data year for the core
  economic tables is 2023, and later years are nowcast. The changelog says "FIGARO available
  through 2023 and most other source data updated through 2024".
  [Changelog.txt](https://zenodo.org/records/23039074/files/Changelog.txt)
- The coverage is "44 countries (27 EU member states plus 17 major economies) and five rest of
  the world regions". [Zenodo record](https://zenodo.org/records/23039074)
- Contents, checked by reading `IOT_2022_ixi.zip` from that record: it holds `Z.txt` (flows),
  `x.txt` (output), `Y.txt`, `unit.txt` and `file_parameters.json` (two index columns, two header
  rows). `unit.txt` lists 49 regions × 163 sectors. Relevant sector labels:
  - "Manufacture of office machinery and computers (30)"
  - "Manufacture of electrical machinery and apparatus n.e.c. (31)"
  - "Manufacture of radio, television and communication equipment and apparatus (32)"
  - "Production of electricity by" coal, gas, nuclear, hydro, wind, petroleum, biomass, solar PV,
    solar thermal, tide, geothermal, nec
  - "Transmission of electricity", "Distribution and trade of electricity"
  - "Computer and related activities (72)"

  The codes in brackets are ISIC Rev.3-style, which confirms the README's warning that a
  crosswalk is needed.
- **Licence.** The current `LICENSE.txt` is stricter than the "CC BY-SA 4.0" line still shown on
  [exiobase.eu](https://www.exiobase.eu/). For v3.9 and later, non-commercial use falls under "a
  customized derivative of the CC-BY-SA-NC license". It explicitly excludes "(i) Contracted or
  commissioned activities … (ii) Any use intended to generate revenue … and (iii) Any use by
  for-profit or commercial entities". Even derived results may not publish "the original or
  derived coefficients (e.g., direct or full supply chain multipliers …)". Commercial licences
  "can be provided" via exiobase-support@googlegroups.com. The price is not published.
  [LICENSE.txt](https://zenodo.org/records/23039074/files/LICENSE.txt).
  **Result: a for-profit firm needs a paid EXIOBASE licence before using the existing loader on
  real data.**
- Fit: this is the only multi-country table here that splits grid transmission and distribution
  from generation. Semiconductors are not a separate sector.

### WIOD

- The 2016 release covers 43 countries + RoW, 2000–2014, 56 ISIC Rev.4 sectors. The licence is
  "Creative Commons Attribution 4.0 International License". The wiod.org site is archived and "no
  longer maintained".
  [GGDC WIOD](https://www.rug.nl/ggdc/valuechain/wiod/)
- Files: Excel (.xlsb), Stata and R zips on Dataverse
  ([DOI 10.34894/PJ2M1C](https://doi.org/10.34894/PJ2M1C)), in USD millions.
  [WIOD 2016 release page](https://www.rug.nl/ggdc/valuechain/wiod/wiod-2016-release)
- The "New WIOD" page lists no release after 2016.
  [GGDC](https://www.rug.nl/ggdc/valuechain/new-wiod/)
- Fit: the licence is fine, but the data are 12 years old and no more detailed than ICIO. Skip.

### Eora (Eora2, Eora26)

- Eora2: "a balanced global MRIO table documenting purchases and sales amongst 19640 sectors
  across 190 countries", "a complete timeseries for 1990-2024". "The licensing has shifted to an
  annual subscription model". Academic use is free; "other users will need to purchase a
  license". [eora.org](https://eora.org/)
- Licence terms: "Bulk republishing, reselling, and redistribution are not allowed. Not more than
  200 individual raw data points may be published at any one location". Data "may be used only
  while a license subscription is active". No prices are published (storefront only).
  [eora.org/licensing](https://eora.org/licensing)
- Eora26 (on the old site): 1990–2023, tab-separated `.txt` files `T`, `VA`, `FD`, `Q` per year,
  login required. [worldmrio.com/eora26](https://worldmrio.com/eora26/). The old site "will be
  kept open through June 30, 2026". [worldmrio.com](https://worldmrio.com/)
- Fit: Eora26 is too coarse. Full Eora uses a different sector list for each country, so it
  would need a crosswalk per country. It is paid. Skip unless a subscription already exists.

### GLORIA (Global MRIO Lab)

- "Version 060 of the global multi-region input-output database GLORIA has been released",
  announced in IIOA Newsletter 63 (Feb 2026). The release date itself is not confirmed. Licence:
  "GLORIA is made available under a Creative Commons Attribution NonCommercial license
  (https://creativecommons.org/licenses/by-nc/3.0/au/). Commercial applications are managed by
  FootprintLab (https://www.footprintlab.io)".
  [IIOA Newsletter 63](https://www.iioa.org/news/newsletters/Newsletter63.pdf)
- Size: "(164 × 164) × [120 × (120+6+6)] × 5 … elements … for a time series spanning the years
  1990 to 2028" (release 059 note).
  [GLORIA Release Note 059 excerpt](https://isa.sydney.edu.au/wp-content/uploads/2024/12/MRIO_excerpt_ReleaseNote059.pdf)
- Download: [ielab.info/resources/gloria](https://ielab.info/resources/gloria). The page is a
  JavaScript app, so the file format and the 120-sector list are **not confirmed**. The
  FootprintLab site lists no MRIO prices. [footprintlab.io](https://www.footprintlab.io)
- Fit: it may be more detailed than ICIO, but that is unverified, and commercial use is paid.

### Eurostat FIGARO

- 2026 edition: supply, use, ixi and pxp IO tables, 2010–2024, "64 industries (NACE Rev. 2) and
  64 products (CPA 2.1)". "CSV for all tables, in flat and matrix layouts". Downloads are in the
  [CIRCABC FIGARO space](https://circabc.europa.eu/ui/group/cec66924-a924-4f91-a0ef-600a0531e3ba/library/460a20fc-5956-44f9-8633-2821eb48dd62).
  [Eurostat database page](https://ec.europa.eu/eurostat/web/esa-supply-use-input-tables/database)
- Countries: EU27, Norway, Switzerland, 5 candidate countries and 15 trading partners (incl. US,
  CN, JP, KR, IN, UK), plus RoW. Updated annually for 2010 to T-2.
  [Eurostat information on data](https://ec.europa.eu/eurostat/web/esa-supply-use-input-tables/information-data)
- Timing: Eurostat "usually releases the FIGARO data in July each year". The metadata were
  updated 20 July 2026; the exact release date is not confirmed. Previous-year-price tables are
  due by December 2026.
  [naio_10_fcp metadata](https://ec.europa.eu/eurostat/cache/metadata/en/naio_10_fcp_esms.htm)
- Licence: Eurostat content "is licensed under the Creative Commons Attribution 4.0 International
  licence", and reuse "for commercial or non-commercial purposes is authorised provided the source
  is acknowledged". This excludes third-party material and some Swiss/Liechtenstein/Austrian trade
  detail.
  [Eurostat copyright notice](https://ec.europa.eu/eurostat/help/copyright-notice)
- Classification: "the first level and the second level of ISIC Rev. 4 (sections and divisions)
  are identical to sections and divisions of NACE Rev. 2", so FIGARO's two-digit codes are
  already ISIC Rev.4 divisions.
  [NACE Rev. 2 methodology](https://ec.europa.eu/eurostat/documents/3859598/5902521/KS-RA-07-015-EN.PDF)
- Fit: best licence and freshness among the multi-country tables, and it needs no crosswalk. The
  flat CSV is long format, so it should go through `build_icio_from_long_format` with the column
  names passed in. The exact column names are not confirmed. The detail is the same as ICIO, so it
  does not isolate any of the three themes.

### ADB MRIO

- KIDB lists 62-economy tables for 2000 and 2007–2024, 72-economy tables for 2017–2024, and
  74-economy tables for 2022–2024, one .xlsx per year. The latest files were "Updated on August
  2025". [ADB KIDB, MRIO at current prices](https://kidb.adb.org/globalization/current)
- Sectors: "35 sectors of 62 distinct economies", including a single "Electrical and optical
  equipment" sector.
  [ADB, Economic Insights from Input–Output Tables](https://www.adb.org/sites/default/files/publication/808866/economic-insights-input-output-tables-asia-pacific.pdf)
- Licence: "all data and metadata provided in ADB's Key Indicators Database System (KIDB) Online
  may be copied, downloaded, distributed, adapted, duplicated, linked, displayed or included in
  other products for commercial and noncommercial purposes at no cost". Attribution is required.
  [KIDB terms](https://kidb.adb.org/terms)
- Fit: free, current, good Asia coverage, but 35 sectors is coarser than ICIO. It cannot
  separate semis from electrical equipment.

### GTAP

- GTAP 12: "145 countries and 18 aggregate regions", "65 goods and services sectors", reference
  years 2004, 2007, 2011, 2014, 2017, 2019 and 2023.
  [JGEA article](http://jgea.org/ojs/index.php/jgea/article/view/344)
  The sectors include `ele` (Computer, electronic and optical products), `eeq` (Electrical
  equipment) and `ely` (Electricity).
  [GTAP 12 sectors](https://www.gtap.agecon.purdue.edu/databases/v12/v12_sectors.aspx)
  Release month February 2026 **[snippet]**.
  [GTAP databases](https://www.gtap.agecon.purdue.edu/databases/)
- Price: Private Sector (for profit) "$10,000" new, or "$6,500" as an upgrade, shareable within
  the organisation. "All purchases are perpetual". Not sold to resellers.
  [GTAP pricing](https://gtap.agecon.purdue.edu/databases/pricing.asp)
  The terms-and-conditions document was not read.
- GTAP says itself that "the objective of the GTAP Data Base is not to provide I-O tables", and
  that users who build IO tables from it "do that under their own risk". It is delivered for the
  GTAPAgg/FlexAgg tools or as GDX files.
  [GTAP 12 Data Base](https://www.gtap.agecon.purdue.edu/databases/v12/)
- Fit: poor. It is paid, CGE-oriented, and no more detailed than ICIO.

### US BEA input-output accounts

- Levels: "sector (15 industry groups), summary (71 industry groups), underlying summary (138
  industry groups), and detail (402 industry groups)". Detail is available "only for benchmark
  years (years ending in 2 or 7) beginning in 2007".
  [BEA guide](https://www.bea.gov/resources/guide-interactive-industry-input-output-accounts-tables)
  "Input-output data are updated each year and provide information on 71 industry categories";
  "Data released each September".
  [BEA IO accounts](https://www.bea.gov/data/industries/input-output-accounts-data)
- The latest benchmark is 2017, from the 2023 comprehensive update.
  [SCB Nov 2023](https://apps.bea.gov/scb/issues/2023/11-november/1123-nea-comprehensive-update.htm)
  The 2026 annual update came out on 30 Sept 2026.
  [BEA 2026 annual update](https://www.bea.gov/information-updates-national-regional-economic-accounts)
  **Not confirmed:** the latest annual year in the summary tables, and when a 2022 benchmark will
  be published.
- Codes, from BEA's own concordance: `334413` Semiconductor and related device manufacturing,
  `335311` Power, distribution, and specialty transformer manufacturing, `335313` Switchgear and
  switchboard apparatus manufacturing, `335911` Storage battery manufacturing, `518200` Data
  processing, hosting, and related services. Electricity is one detail row, `221100` Electric
  power generation, transmission, and distribution.
  [BEA Industry and Commodity Codes and NAICS Concordance (xlsx)](https://www.bea.gov/sites/default/files/2023-10/BEA-Industry-and-Commodity-Codes-and-NAICS-Concordance.xlsx)
- Download: interactive tables and the API (free key).
  [BEA IO interactive](https://www.bea.gov/itable/input-output),
  [API guide](https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf)
- Licence: "Unless stated otherwise, the information posted on this web site is in the public
  domain and may be used or reproduced without specific permission". Citation is requested.
  [BEA FAQ 147](https://www.bea.gov/help/faq/147)
- Fit: the only free source with the detail the themes need. The limits: US only, a 2017
  structure, and NAICS-based codes instead of ISIC. The Use table gives industry×commodity flows
  plus a total industry output row, which is enough to build `matrix` and `total_output`. Turning
  it into an industry×industry matrix (via the Make table, or the direct-requirements tables) is
  a small preprocessing step.

### USEEIO

- v2.5 models: detailed (catbird, kinglet, waxwing) and summary (oriole, kingbird, yellowthroat),
  each with a different import-emissions source (CEDA 2024, EXIOBASE 3.8.2, GLORIA 059a). Files
  are `.xlsx` under `https://pasteur.epa.gov/uploads/10.23719/1532178/`, last modified
  2025-04-16. "Detailed models use underlying U.S. IO data for 2017".
  [data.gov USEEIO v2.5](https://catalog.data.gov/dataset/useeio-v2-5-models)
- Version list: v2.5.1 (data years 2022–2023) is still draft; v2.5 is the latest published.
  [USEEIO models.md](https://github.com/USEPA/USEEIO/blob/master/models.md)
- Licence: "all data produced by the U.S EPA is by default in the public domain".
  [EPA ScienceHub licence](https://pasteur.epa.gov/license/sciencehub-license.html)
- Fit: same economic detail as BEA, already packaged as matrices. Useful if emissions are wanted
  later. For pure exposure work, BEA is the upstream source. The sector count is not confirmed.

### IDE-JETRO Asian International IO tables

- The latest Asian International IO table is 2005: "10 countries, covering 76 sectors" **[snippet]**.
  [IDE DP 663](https://www.ide.go.jp/English/Publish/Reports/Dp/663.html)
- The data page ([ide.go.jp/English/Data/Io.html](https://www.ide.go.jp/English/Data/Io.html))
  returned 503 "under maintenance". Licence, price and format are **not confirmed**.
- Fit: far too old. Skip.

### OECD national IOTs

- "Data are published for the time period 1995-2022, in .zip format", for "all OECD countries and
  several non-member economies (including all G20 countries)" **[snippet]**.
  [OECD Input-Output Tables](https://www.oecd.org/en/data/datasets/input-output-tables.html)
- They use the same industries as ICIO and the same (unconfirmed) licence. They add nothing for
  this tier, because the loader sums countries anyway.

### Others found

- **Open CEDA (Watershed)**: "400 industries, 148 countries and regions", and "Open CEDA is
  offered for free under CC BY-SA license and requires attribution in the form of CEDA by
  Watershed". It is described as "60,000 emission factors", with no flow matrices published.
  [openceda.org](https://openceda.org/), [AWS registry](https://registry.opendata.aws/open-ceda/).
  Watershed's Cornerstone project plans to merge USEEIO and CEDA into an open global EEIO model;
  it is not released yet. [cornerstonedata.org](https://cornerstonedata.org/). Worth watching
  for the 400-sector detail, but the loaders cannot use it today.
- **CEADs China provincial MRIO**: 31 regions × 42 sectors for 2018 and 2020, consistent with the
  2012, 2015 and 2017 tables. Published via
  [CEADs](https://www.ceads.net/data/input_output_tables/) (announced in
  [IIOA Newsletter 63](https://www.iioa.org/news/newsletters/Newsletter63.pdf)). The licence is
  not confirmed.
- **FIGARO-NAM 2025**: experimental national accounting matrices built on FIGARO (49 countries +
  RoW, 64×64). It adds nothing over FIGARO for Leontief exposure.
  [IIOA Newsletter 63](https://www.iioa.org/news/newsletters/Newsletter63.pdf)

## 4. Recommendation

**Add Eurostat FIGARO first, then the US BEA detail (2017 benchmark) tables.**

- **FIGARO** is the only multi-country table here whose licence plainly allows commercial reuse
  (Eurostat CC BY 4.0, attribution only). It is the freshest (2010–2024, refreshed every July),
  and its 64 NACE Rev.2 two-digit codes are ISIC Rev.4 divisions, so it needs no crosswalk. Its
  flat CSV should feed the existing long-format loader with only a column-name mapping and a code
  strip (e.g. `C26` → `26`). It gives the tier a properly licensed, current baseline in place of
  ICIO 2022, whose licence is unconfirmed. It does **not** isolate semiconductors, grid equipment
  or data centres.
- **BEA detail** fills that gap. It is public domain and has 402 industries, with separate rows
  for semiconductor devices (334413), transformers (335311), switchgear (335313), storage batteries
  (335911) and data processing/hosting (518200). The costs: it is US-only, it reflects 2017, and
  its codes are BEA/NAICS rather than ISIC. The `isic_code` column name and the "ISIC Rev.4"
  wording in `company_mapper.py` and `core_sectors.py` would need generalising.
- **Hold EXIOBASE, GLORIA, Eora and GTAP** until a paid licence exists. EXIOBASE's own
  `LICENSE.txt` excludes for-profit users, which also affects the loader the repo already ships.
- **ADB MRIO** is free and current, but at 35 sectors it adds little over FIGARO.

## 5. Not confirmed

- The licence of the OECD ICIO and national-IOT data files, and the exact 2025-edition release
  dates (the OECD pages returned 403; the facts come from search snippets of OECD's own pages).
- GLORIA 060: release date, file format, the 120-sector list, and commercial pricing.
- EXIOBASE, Eora and GLORIA commercial prices (none published).
- GTAP 12 terms-and-conditions text (pricing page read, T&C not read).
- BEA: latest annual year in the summary tables; timing of a 2022 benchmark.
- FIGARO: exact 2026 release date, and the flat-CSV column names.
- IDE-JETRO: licence, format, and whether anything newer than 2005 exists (site returned 503).
- USEEIO v2.5 sector counts; CEADs licence.
