# Golden set G: drafted labels for the owner's check

Golden set G scores phase-3 fact extraction (spec section 8, AC-123). The builder drafted these
labels on 2026-10-19. **The owner has not checked them yet (D2).** Phase 3 merges only after that check.

Run it with:

```
arp transition-barrier golden --cases tests/golden/transition_barrier/cases.json \
  --documents-dir tests/golden/transition_barrier/documents --min-precision 0.95 --min-coverage 0.5
```

## How to check a row

1. Open the document and go to the **page**. The page is the PDF page index counted from 1, the page
   number a PDF viewer shows. It is not the number printed on the page: for example, page 15 of the
   MEE allocation plan is printed "— 17 —".
2. Find the **quote** on that page. Text extraction splits lines, so search for a few words of it.
   `test_tb_golden.py::test_golden_set_shape` already checks that every quote is on its page (ignoring
   whitespace) and that every number label can be read from its quote.
3. Read the fact's definition in `arp/transition_barrier/data/rule_book.json`. Check that the quote
   supports the **value** for that cell. Numbers are in the rule book's unit and compared at two
   decimals; booleans are true/false; enums use the exact allowed value.
4. If a row is wrong, fix `cases.json` and the row here. If no single page carries the answer,
   delete the row from both.

**absent** rows name a fact that the document does not address. The correct result is "not found":
such a row only counts against coverage, and a counted value for it scores as incorrect, for every
fact type.

## Look at these first

These rows needed a judgement call, or rely on a conversion or on picking one page out of several:

- **19, 21 (EU carbon price, 90.43 USD/tCO2).** The rows convert EUR 83.60 to USD at the 2023 rate
  in the rule book (1.0817), because the quote states 2023. The figure is the average EUA *auction*
  price in 2023. If the model leaves `period_text` empty, the code uses the PDF's /CreationDate year,
  2024 (rate 1.082 gives 90.46), and the row fails. That failure would be a real miss of the as-of
  rule, so keep the row.
- **27–29 (US LCOE, EIA AEO2022).** The rows use Table 1a on page 8, the capacity-weighted average
  that the definition asks for. Table 1b on page 9 holds the unweighted values (solar 36.49,
  combined cycle 39.94, solar with credit 33.83). The figures are for plants entering service in 2027,
  in 2021 dollars. Solar (36.09) is cheaper than onshore wind (37.80), so solar is the renewable
  figure. The "d" in "standaloned" is a footnote marker that extraction joined to the word.
- **31 (US SCM programme = true).** This rests on PLC (Type IL) approval by every state DOT, as
  USGS reports it. Decide whether state DOT specifications count as "a standard … in force in the
  region".
- **34 (US SAF mandate = announced_or_voluntary).** The document is the 2022 SAF Grand Challenge
  roadmap, which sets a voluntary volume goal. The label is what this document says; it is not
  today's US status.
- **37 (China steel free-allocation phase-out = false).** The plan keeps free allocation and says
  it "lays the ground for" mixed free and paid allocation in later years, with no end date or
  schedule. The label reads that as "no phase-out legislated".
- **38 (China power carbon price coverage = region_wide).** The quote says the plan covers power
  companies on the national ETS list of key emitting units.
- **10 (EU chemicals levy = false).** The rule book's own definition cites recital 34.
- **Several pages support the answer.** These rows name the page with the operative text:
  1 (Article 4, p. 15; Annex I on p. 29 also supports it), 8 and 9 (Article 22, p. 28; Annex I on
  pp. 39–40 lists the goods), 11 and 12 (Article 11, p. 26; recital on p. 7 repeats 27 months),
  16 (Article 14 LDAR, p. 25; Article 15 venting and flaring would also do). If the model cites the
  other page, the row counts as incorrect. Decide whether to keep these rows.
- **5 and 25 (shipping carbon price) also have support on other pages.** Row 5 cites Article 3gb
  on p. 28; a recital on p. 5 says the same. Row 25 cites the scope section on p. 4; chapter 10 on
  p. 38 says the same.
- **27–29 and the appendix.** Appendix A of the EIA report (p. 17 onwards) repeats the tables for
  plants entering service in 2024, and retrieval shows them. The rows use the main tables (2027).
- **Licence of the Chinese document (35–38).** The task's licence list does not name it. It is an
  MEE administrative normative document. PRC Copyright Law Article 5(1) excludes documents of a
  legislative, administrative or judicial nature from copyright. Remove the document and its four
  rows if you do not accept that basis.

## What a perfect model could score

A stand-in model ran through the real `golden.score`. It answers every row with its own label, quoting
the page text the way extraction gives it. Barrier extraction ranks passages by keyword only (BM25,
the owner's decision), using the curated keywords in `data/fact_keywords.json` and 12 passages per
fact. The stand-in reached precision 1 and coverage 31/43 = 0.72.

The 5 absent rows can never count. Rows 8, 9, 14, 27 and 35–37 hold their answer, but retrieval does
not show the model the passage. A real model will score at or below 0.72. For comparison, the same run
scored 0.60 with hybrid ranking, and 0.49 with the label's words as the only keywords.

## Documents

Every file was fetched on 2026-10-19. Each is under 5 MB and has a text layer; together they come to
about 20 MB. EUR-Lex itself answered with a bot challenge, so the EU files were fetched from the
Publications Office repository that EUR-Lex serves its PDFs from
(`http://publications.europa.eu/resource/celex/<CELEX>` with `Accept: application/pdf`). Each is the
English Official Journal or COM PDF.

| File | Document | URL | Licence basis | Pages |
|---|---|---|---|---|
| eu-reg-2023-2405-refueleu-aviation.pdf | Regulation (EU) 2023/2405 (ReFuelEU Aviation), CELEX 32023R2405 | https://eur-lex.europa.eu/eli/reg/2023/2405/oj | Commission Decision 2011/833/EU (reuse of Commission documents; EUR-Lex legal notice) | 30 |
| eu-reg-2023-1805-fueleu-maritime.pdf | Regulation (EU) 2023/1805 (FuelEU Maritime), CELEX 32023R1805 | https://eur-lex.europa.eu/eli/reg/2023/1805/oj | Decision 2011/833/EU | 53 |
| eu-dir-2023-959-ets-amendment.pdf | Directive (EU) 2023/959 amending the EU ETS Directive, CELEX 32023L0959 | https://eur-lex.europa.eu/eli/dir/2023/959/oj | Decision 2011/833/EU | 69 |
| eu-reg-2023-956-cbam.pdf | Regulation (EU) 2023/956 (CBAM), CELEX 32023R0956 | https://eur-lex.europa.eu/eli/reg/2023/956/oj | Decision 2011/833/EU | 53 |
| eu-reg-2024-1252-critical-raw-materials-act.pdf | Regulation (EU) 2024/1252 (Critical Raw Materials Act), CELEX 32024R1252 | https://eur-lex.europa.eu/eli/reg/2024/1252/oj | Decision 2011/833/EU | 67 |
| eu-reg-2024-1610-hdv-co2-standards.pdf | Regulation (EU) 2024/1610 amending Regulation (EU) 2019/1242 (heavy-duty CO2 standards), CELEX 32024R1610 | https://eur-lex.europa.eu/eli/reg/2024/1610/oj | Decision 2011/833/EU | 67 |
| eu-reg-2024-1787-methane.pdf | Regulation (EU) 2024/1787 (methane emissions in the energy sector), CELEX 32024R1787 | https://eur-lex.europa.eu/eli/reg/2024/1787/oj | Decision 2011/833/EU | 61 |
| eu-dir-2023-2413-renewable-energy.pdf | Directive (EU) 2023/2413 amending the Renewable Energy Directive, CELEX 32023L2413 | https://eur-lex.europa.eu/eli/dir/2023/2413/oj | Decision 2011/833/EU | 77 |
| eu-com-2024-538-carbon-market-report.pdf | COM(2024) 538 final, Report on the functioning of the European carbon market in 2023, CELEX 52024DC0538 | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52024DC0538 | Decision 2011/833/EU | 50 |
| us-eia-lcoe-aeo2022.pdf | EIA, Levelized Costs of New Generation Resources in the Annual Energy Outlook 2022 (March 2022) | https://www.eia.gov/outlooks/aeo/pdf/electricity_generation.pdf | US federal government work, not subject to copyright (17 U.S.C. 105) | 26 |
| us-usgs-mcs2025-iron-steel.pdf | USGS, Mineral Commodity Summaries 2025: Iron and Steel | https://pubs.usgs.gov/periodicals/mcs2025/mcs2025-iron-steel.pdf | US federal work (17 U.S.C. 105) | 2 |
| us-usgs-mcs2025-cement.pdf | USGS, Mineral Commodity Summaries 2025: Cement | https://pubs.usgs.gov/periodicals/mcs2025/mcs2025-cement.pdf | US federal work (17 U.S.C. 105) | 2 |
| us-fr-2025-05212-eo14241-mineral-production.pdf | Executive Order 14241, Immediate Measures To Increase American Mineral Production, 90 FR 13673 (25 March 2025) | https://www.govinfo.gov/content/pkg/FR-2025-03-25/pdf/2025-05212.pdf | US federal work (17 U.S.C. 105) | 5 |
| us-fr-2025-21788-oil-gas-deadline-extension.pdf | EPA final rule, Oil and Natural Gas Sector Climate Review: Extension of Deadlines (OOOOb/OOOOc), 90 FR 55671 (3 December 2025); the PDF also carries the end of the rule before it and the start of the rule after it | https://www.govinfo.gov/content/pkg/FR-2025-12-03/pdf/2025-21788.pdf | US federal work (17 U.S.C. 105) | 11 |
| us-doe-saf-grand-challenge-roadmap-2022.pdf | DOE, DOT, USDA and EPA, SAF Grand Challenge Roadmap (September 2022) | https://www.energy.gov/sites/default/files/2022-09/beto-saf-gc-roadmap-report-sept-2022.pdf | US federal work (17 U.S.C. 105); national-laboratory staff contributed and the disclaimer covers contractors, so a few figures may come from other sources | 128 |
| cn-mee-2026-ets-allocation-plan.pdf | MEE, 全国碳排放权交易市场2025、2026年度发电行业以及2026年度钢铁、水泥、铝冶炼行业配额总量和分配方案 (national ETS allocation plan: power for 2025 and 2026; steel, cement and aluminium for 2026). The file is the plan attached to the notice, starting at printed page 3; PDF created 3 September 2026 | https://www.mee.gov.cn/xxgk2018/xxgk/xxgk03/202609/W020260903551498752549.pdf | PRC Copyright Law Article 5(1): documents of an administrative nature are not protected (see above) | 27 |

## Cases

One row per entry of `cases.json`, in the same order. `test_golden_set_shape` reads the Document,
Page and Quote columns, so keep the table format. Quotes in the Chinese rows are written without the
line-break spaces that extraction adds. In English: "Key emitting units shall, before 31 December
each year, surrender to the provincial environment authority allowances equal to their verified
emissions" (35, 36); "allocate allowances free of charge on the basis of carbon-intensity control,
keep improving the allocation method, and lay the ground for introducing a mix of free and paid
allocation in later years" (37); "for the power sector, [the plan] applies to the companies on the
national ETS list of key emitting units for 2025 and 2026" (38).

| # | Cell | Fact | Value | Unit | Document | Page | Quote |
|---|---|---|---|---|---|---|---|
| 1 | AVI-R1 · European Union | SAF blending mandate (`status`) | "in_force" | — | eu-reg-2023-2405-refueleu-aviation.pdf | 15 | aviation fuel suppliers shall ensure that all aviation fuel made available to aircraft operators at each Union airport contains the minimum shares of SAF |
| 2 | AVI-R1 · European Union | Mandated share rises by law (`escalating`) | true | — | eu-reg-2023-2405-refueleu-aviation.pdf | 29 | (a) From 1 January 2025, each year a minimum share of 2 % of SAF; (b) From 1 January 2030, each year a minimum share of 6 % of SAF |
| 3 | AVI-R1 · European Union | Penalties for missing the mandate (`penalties`) | true | — | eu-reg-2023-2405-refueleu-aviation.pdf | 21 | any aviation fuel supplier that fails to comply with the obligations laid down in Article 4 relating to the minimum shares of SAF is liable to a fine |
| 4 | SHP-R1 · European Union | Binding fuel GHG intensity mandate applies (`mandate_applies`) | true | — | eu-reg-2023-1805-fueleu-maritime.pdf | 19 | The yearly average GHG intensity of the energy used on board by a ship during a reporting period shall not exceed the limit set out in paragraph 2. |
| 5 | SHP-R1 · European Union | Carbon price applies to shipping (`price_applies`) | true | — | eu-dir-2023-959-ets-amendment.pdf | 28 | Shipping companies shall be liable to surrender allowances according to the following schedule: (a) 40 % of verified emissions reported for 2024 |
| 6 | STL-R1 · European Union | Free allocation phase-out legislated (`fa_phaseout`) | true | — | eu-dir-2023-959-ets-amendment.pdf | 36 | shall be equal to 97,5 % in 2026, 95 % in 2027, 90 % in 2028, 77,5 % in 2029, 51,5 % in 2030, 39 % in 2031, 26,5 % in 2032 and 14 % in 2033. From 2034, no CBAM factor shall apply. |
| 7 | CEM-R1 · European Union | Free allocation phase-out legislated (`fa_phaseout`) | true | — | eu-dir-2023-959-ets-amendment.pdf | 36 | shall be equal to 97,5 % in 2026, 95 % in 2027, 90 % in 2028, 77,5 % in 2029, 51,5 % in 2030, 39 % in 2031, 26,5 % in 2032 and 14 % in 2033. From 2034, no CBAM factor shall apply. |
| 8 | STL-R1 · European Union | Border carbon levy in force (`levy`) | true | — | eu-reg-2023-956-cbam.pdf | 28 | By 31 May of each year, and for the first time in 2027 for the year 2026, the authorised CBAM declarant shall surrender via the CBAM registry a number of CBAM certificates that corresponds to the embedded emissions declared |
| 9 | CEM-R1 · European Union | Border carbon levy in force (`levy`) | true | — | eu-reg-2023-956-cbam.pdf | 28 | By 31 May of each year, and for the first time in 2027 for the year 2026, the authorised CBAM declarant shall surrender via the CBAM registry a number of CBAM certificates that corresponds to the embedded emissions declared |
| 10 | CHM-R1 · European Union | Border carbon levy in force for chemicals (`levy`) | false | — | eu-reg-2023-956-cbam.pdf | 6 | organic chemicals should not be included in the scope of this Regulation |
| 11 | MIN-R1 · European Union | Fast-track permitting for strategic minerals projects (`regime`) | "statutory" | — | eu-reg-2024-1252-critical-raw-materials-act.pdf | 26 | For Strategic Projects in the Union, the permit-granting process shall not exceed: (a) 27 months for Strategic Projects involving extraction |
| 12 | MIN-R1 · European Union | Statutory maximum permitting time (`max_months`) | 27 | months | eu-reg-2024-1252-critical-raw-materials-act.pdf | 26 | (a) 27 months for Strategic Projects involving extraction |
| 13 | MIN-R2 · European Union | Domestic or allied content requirement (`rule`) | "other" | — | eu-reg-2024-1252-critical-raw-materials-act.pdf | 21 | Union capacity approaches or reaches the following benchmarks: (i) Union extraction capacity is capable of extracting the ores, minerals or concentrates needed to produce at least 10 % of the Union’s annual consumption of strategic raw materials |
| 14 | HDT-R1 · European Union | Heavy truck CO2 standard or ZEV mandate (`status`) | "in_force" | — | eu-reg-2024-1610-hdv-co2-standards.pdf | 12 | (a) 15 % for vehicle sub-groups 4-UD, 4-RD, 4-LH, 5-RD, 5-LH, 9-RD, 9-LH, 10-RD and 10-LH for the reporting periods of the years 2025 to 2029 |
| 15 | HDT-R1 · European Union | Penalties for missing the standard (`penalties`) | true | — | eu-reg-2024-1610-hdv-co2-standards.pdf | 17 | the Commission shall impose an excess CO2 emissions premium |
| 16 | OGU-R1 · European Union | Binding methane limit or fee (`status`) | "in_force" | — | eu-reg-2024-1787-methane.pdf | 25 | By 5 May 2025 for existing sites and within 6 months from the date of start of operations for new sites, operators shall submit a leak detection and repair programme |
| 17 | OGU-R1 · European Union | Enforcement mechanism (`enforcement`) | true | — | eu-reg-2024-1787-methane.pdf | 43 | The penalties provided for shall be effective, proportionate and dissuasive and shall include at least: (a) fines |
| 18 | PWR-R2 · European Union | Renewable target status (`target`) | "binding" | — | eu-dir-2023-2413-renewable-energy.pdf | 26 | Member States shall collectively ensure that the share of energy from renewable sources in the Union’s gross final consumption of energy in 2030 is at least 42,5 %. |
| 19 | PWR-R1 · European Union | Effective carbon price on power (`price`) | 90.43 | USD/tCO2 | eu-com-2024-538-carbon-market-report.pdf | 10 | The average price in 2023 was EUR 83.60, up from EUR 80.18 in 2022. |
| 20 | PWR-R1 · European Union | Carbon price coverage (`scope`) | "region_wide" | — | eu-com-2024-538-carbon-market-report.pdf | 4 | The EU ETS applies in all 27 EU Member States plus Iceland, Liechtenstein and Norway, as well as to electricity generation plants in Northern Ireland |
| 21 | STL-R1 · European Union | Carbon price on steel (`price`) | 90.43 | USD/tCO2 | eu-com-2024-538-carbon-market-report.pdf | 10 | The average price in 2023 was EUR 83.60, up from EUR 80.18 in 2022. |
| 22 | STL-R1 · European Union | Carbon price applies to steel (`applies`) | true | — | eu-com-2024-538-carbon-market-report.pdf | 13 | In certain EU ETS-covered industry sectors (cement, aluminium, fertilisers, hydrogen, iron and steel), the CBAM will gradually replace free allocation |
| 23 | CEM-R1 · European Union | Carbon price applies to cement (`applies`) | true | — | eu-com-2024-538-carbon-market-report.pdf | 13 | In certain EU ETS-covered industry sectors (cement, aluminium, fertilisers, hydrogen, iron and steel), the CBAM will gradually replace free allocation |
| 24 | STL-R1 · European Union | Border carbon levy in force (`levy`) | true | — | eu-com-2024-538-carbon-market-report.pdf | 13 | As of 2026, importers of goods in CBAM sectors to the EU will need to buy and surrender certificates for the embedded emissions. |
| 25 | SHP-R1 · European Union | Carbon price applies to shipping (`price_applies`) | true | — | eu-com-2024-538-carbon-market-report.pdf | 4 | As of 1 January 2024, the EU’s fair share of CO2 (carbon dioxide) emissions from maritime transport has also been included in the EU ETS |
| 26 | AVI-D1 · European Union | Premium offset mechanism in force (`offset_mech`) | true | — | eu-com-2024-538-carbon-market-report.pdf | 37 | This incentive has been available for eligible fuels uplifted on ETS routes since 1 January 2024. |
| 27 | PWR-T1 · United States | Renewable LCOE (`re_lcoe`) | 36.09 | USD/MWh | us-eia-lcoe-aeo2022.pdf | 8 | Solar, standaloned 29% $26.35 $6.34 $0.00 $3.41 $36.09 -$2.64 $33.46 |
| 28 | PWR-T1 · United States | New-build fossil LCOE (`fossil_lcoe`) | 37.05 | USD/MWh | us-eia-lcoe-aeo2022.pdf | 8 | Combined cycle 87% $8.56 $1.68 $25.80 $1.01 $37.05 NA $37.05 |
| 29 | PWR-T1 · United States | Subsidised renewable LCOE (`re_lcoe_sub`) | 33.46 | USD/MWh | us-eia-lcoe-aeo2022.pdf | 8 | Solar, standaloned 29% $26.35 $6.34 $0.00 $3.41 $36.09 -$2.64 $33.46 |
| 30 | STL-T2 · United States | Crude steelmaking capacity (`capacity_mt`) | 107 | Mt | us-usgs-mcs2025-iron-steel.pdf | 1 | Combined raw steel production capacity was about 107 million tons per year. |
| 31 | CEM-T2 · United States | Active SCM substitution programme (`scm_programme`) | true | — | us-usgs-mcs2025-cement.pdf | 2 | In April 2024, the Connecticut Department of Transportation approved the use of portland-limestone cement (PLC), signifying its adoption by all 50 States and the District of Columbia. |
| 32 | MIN-R1 · United States | Fast-track permitting for strategic minerals projects (`regime`) | "discretionary" | — | us-fr-2025-05212-eo14241-mineral-production.pdf | 1 | identify priority projects that can be immediately approved or for which permits can be immediately issued, and take all necessary or appropriate actions within the agency’s authority to expedite and issue the relevant permits or approvals |
| 33 | OGU-R1 · United States | Binding methane limit or fee (`status`) | "phase_in" | — | us-fr-2025-21788-oil-gas-deadline-extension.pdf | 4 | Extended the deadline to January 22, 2027, for States to submit to the EPA plans to address existing oil and natural gas sources pursuant to the 2024 Emission Guidelines (EG). |
| 34 | AVI-R1 · United States | SAF blending mandate (`status`) | "announced_or_voluntary" | — | us-doe-saf-grand-challenge-roadmap-2022.pdf | 7 | is a U.S. government-wide approach to work with industry to reduce cost, enhance sustainability, and expand production to achieve 3 billion gallons per year of domestic sustainable aviation fuel production |
| 35 | STL-R1 · China | Carbon price applies to steel (`applies`) | true | — | cn-mee-2026-ets-allocation-plan.pdf | 15 | 重点排放单位应于每年12月31日前按照履约通知书向省级生态环境主管部门清缴与其经核查排放量等量的配额 |
| 36 | CEM-R1 · China | Carbon price applies to cement (`applies`) | true | — | cn-mee-2026-ets-allocation-plan.pdf | 15 | 重点排放单位应于每年12月31日前按照履约通知书向省级生态环境主管部门清缴与其经核查排放量等量的配额 |
| 37 | STL-R1 · China | Free allocation phase-out legislated (`fa_phaseout`) | false | — | cn-mee-2026-ets-allocation-plan.pdf | 1 | 基于碳排放强度控制实施配额免费分配，持续优化分配方法，为后续年度有序推行免费和有偿相结合的碳配额分配方式打好基础 |
| 38 | PWR-R1 · China | Carbon price coverage (`scope`) | "region_wide" | — | cn-mee-2026-ets-allocation-plan.pdf | 2 | 发电行业实施范围为纳入全国碳排放权交易市场2025、2026年度重点排放单位名录的企业 |
| 39 | CHM-T2 · European Union | Commercial-scale electric cracker operating or at FID (`commercial`) | absent | — | eu-reg-2023-1805-fueleu-maritime.pdf | — | — |
| 40 | MIN-T1 · European Union | Battery-electric equipment at an operating mine (`deployed`) | absent | — | eu-reg-2023-2405-refueleu-aviation.pdf | — | — |
| 41 | CEM-T2 · United States | Active SCM substitution programme (`scm_programme`) | absent | — | us-fr-2025-05212-eo14241-mineral-production.pdf | — | — |
| 42 | STL-D1 · United States | Offtake agreements signed (`offtake_signed`) | absent | — | us-eia-lcoe-aeo2022.pdf | — | — |
| 43 | SHP-D1 · European Union | Corridor with signed cargo commitment (`committed_any`) | absent | — | eu-reg-2024-1610-hdv-co2-standards.pdf | — | — |
