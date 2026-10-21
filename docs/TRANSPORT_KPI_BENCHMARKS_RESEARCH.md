# Transport KPI benchmarks: numeric 1.5 °C pathways for TR 2.4 and AU 4.4

Which published numbers can replace the chart-only benchmark in ACT Transport TR 2.4 (share of
low-carbon vehicles and energies, SB_LCV(t)) and the light-vehicle benchmark that ACT Automotive
AU 4.4 would otherwise apply to heavy-truck makers. It answers three questions: (1) do ACT's own
cited sources print SB_LCV as numbers; (2) which current 1.5 °C / net-zero pathways print the four
KPIs for 2030, 2035, 2040 and 2050; (3) which source to use for each, and how well it fits ACT's
definition.

Status: **research note, 2026-10-21.** Context: `docs/ACT_PLAN_ASSESSMENT_RESEARCH.md` (cited as
"ACT research §n"), §13.5 (sector delivery KPIs: fields `ta_zev_sales_share_pct` and
`ta_fleet_lc_share_pct`) and §14 (aviation, shipping, heavy-duty rows). §17 of that note lists
"TR 2.4 benchmark … printed only as a chart" as open. This note closes that item as far as
primary sources allow.

Evidence tags:

- **[verified]**: read in the primary document itself, on the page given.
- **[unverified]**: the primary document could not be opened; the value comes from a search
  snippet or secondary summary. See section 8.
- **[ours]**: a mapping, conversion or recommendation made in this note. No source says it.

Page numbers are the printed page numbers. Where the printed number differs from the PDF page,
both are given.

---

## 1. Summary

**Q1. ACT's cited sources do not print SB_LCV(t) as a yearly table.** None of the five sources
ACT names for TR 2.4 (TR p.56) prints a 2020–2050 series of low-carbon fleet or energy shares.
On the cited pages: ETP 2017 shows stacked-area charts (p.250) and an LNG chart (p.260). The
Future of Trucks prints 2050 stock shares in text (p.124) and an emissions chart (p.126).
DNV GL 2019 prints 2050 fuel shares as pie-chart labels (p.93). ETC 2018 prints 2050 energy
mixes (p.110). Each source gives at most one numeric year, usually 2050. ACT's curve on TR p.55
is therefore ACT's own construction from charts and end points, and it cannot be reproduced from
the sources. [verified]

**Q2/Q3. Recommended benchmarks** (details in section 6, summary table in section 7):

| KPI | Recommended source | Fit to ACT |
|---|---|---|
| (a) ZE share of heavy-truck **sales** (makers, AU 4.4 analogue) | IEA Net Zero Roadmap 2023, p.93 milestone table: 37% (2030), 65% (2035), 100% (2050) | Direct for a sales-share indicator. No 2040 value |
| (b) Low-emission fuel share of **shipping** energy | IEA Net Zero Roadmap 2023, p.94: 19% (2030), 36% (2035), 85% (2050), sum of four fuel rows | Direct (TR 2.4 counts low-carbon energy share). No 2040 value |
| (c) SAF / low-emission fuel share of **aviation** fuel | IEA Net Zero Roadmap 2023, p.94: 11% (2030), 26% (2035), 70% (2050). Cross-check MPP 2022 p.51: 13–15% (2030), 28–32% (2035), 62% (2040) | Direct. MPP is the only source with a 2040 number |
| (d) ZE / low-carbon share of a road-freight operator's **fleet** | No 1.5 °C source prints a global heavy-truck *stock* share by year. Derive it from (a) with a stated stock-turnover conversion [ours]; cross-check MPP trucking 2022 p.42 (95% of trucks on the road by 2040, one policy scenario, four regions) | Needs a conversion. Using (a) unconverted would set a sales share against a fleet share |

**Main mismatches to flag:**

1. **AU 4.4 excludes heavy-duty vehicles.** ACT Auto states "Heavy duty vehicles (HDVs) are not
   considered in the ACT Auto methodology" (AU p.10). Its benchmark (AU Table 9, p.119) is the NZE
   light-duty EV sales share (67% in 2030, 100% in 2035). For a truck maker, the matching NZE row is
   heavy trucks (37% in 2030, 65% in 2035). [verified]
2. **Sales vs fleet.** Every numeric truck pathway found is a sales share, apart from
   single-year stock figures (Future of Trucks 2050, ICCT 2050, MPP 2040). TR 2.4 compares a
   fleet share. A sales share used as a fleet benchmark overstates what a fleet can reach in a
   given year. [ours]
3. **No 2040 value in the NZE milestone tables.** The NZE 2023 tables print 2022, 2030, 2035 and
   2050 (pp.93–94). The annex tables (Table A.2, p.196) give energy by mode but not by fuel within
   a mode. [verified]
4. **WEO 2025's NZE no longer meets ACT Core's overshoot criterion.** WEO 2025 says the NZE
   Scenario "is no longer a limited-overshoot scenario, as warming peaks above 1.6 °C" (WEO 2025
   pp.105–106). ACT Core requires "no or limited temperature overshoot before 2050" for pathways
   not on its list (Core p.87). The 2023 Roadmap peaks "just below 1.6 °C around 2040" (NZE 2023
   p.63) and is on the list by name. [verified] Use the 2023 Roadmap. [ours]

---

## 2. Sources and method

PDFs were downloaded on 2026-10-21 and converted to text page by page (`pdftotext -layout`).
Values were read from the text layer. A value that appears only as a label inside a chart is
called a "chart label". A chart with no printed values is called "chart only" and was not read.

| Short | Document | Where obtained | Printed vs PDF page |
|---|---|---|---|
| **TR** | ACT Transport v2.1 (March 2022) | local copy, as in ACT research §2 | equal |
| **AU** | ACT Automotive v2.0 | local copy | equal |
| **Core** | ACT Core v1.0 (24 Feb 2025) | local copy | equal |
| **ETP17** | IEA, *Energy Technology Perspectives 2017* | [iea.blob](https://iea.blob.core.windows.net/assets/a6587f9f-e56c-4b1d-96e4-5a4da78f12fa/Energy_Technology_Perspectives_2017-PDF.pdf) | equal |
| **FoT17** | IEA, *The Future of Trucks* (2017) | [CORA (UCC) copy of the IEA/OECD PDF](https://cora.ucc.ie/bitstream/handle/10468/7770/TheFutureofTrucksImplicationsforEnergyandtheEnvironment.pdf?sequence=1) | printed = PDF − 2 |
| **DNV19** | DNV GL, *Maritime Forecast to 2050* (2019) | [PNNL copy](https://fathoms.pnnl.gov/sites/default/files/publications/2019_maritime-forecast-2050__auakt.pdf) | equal |
| **ETC18** | Energy Transitions Commission, *Mission Possible* (2018) | [energy-transitions.org](https://www.energy-transitions.org/wp-content/uploads/2020/08/ETC_MissionPossible_FullReport.pdf) | equal |
| **IEA-AVB19** | IEA commentary, "Are aviation biofuels ready for take off?" (2019) | [iea.org](https://www.iea.org/commentaries/are-aviation-biofuels-ready-for-take-off): **HTTP 403, not read** | n/a |
| **NZE23** | IEA, *Net Zero Roadmap: A Global Pathway to Keep the 1.5 °C Goal in Reach, 2023 Update* | [iea.blob](https://iea.blob.core.windows.net/assets/9a698da4-4002-4e53-8ef3-631d8971bf84/NetZeroRoadmap_AGlobalPathwaytoKeepthe1.5CGoalinReach-2023Update.pdf) | equal |
| **WEO24** | IEA, *World Energy Outlook 2024* | [iea.blob](https://iea.blob.core.windows.net/assets/140a0470-5b90-4922-a0e9-838b3ac6918c/WorldEnergyOutlook2024.pdf) | equal |
| **WEO25** | IEA, *World Energy Outlook 2025* | [iea.blob](https://iea.blob.core.windows.net/assets/0a7a40a4-5dcb-4d6e-a7ad-76a1c90ec8eb/WorldEnergyOutlook2025.pdf) | equal |
| **GEVO24** | IEA, *Global EV Outlook 2024* | [iea.blob](https://iea.blob.core.windows.net/assets/a9e3544b-0b12-4e15-b407-65f5c8ce1b5f/GlobalEVOutlook2024.pdf) | equal ("PAGE \| n") |
| **GEVO25** | IEA, *Global EV Outlook 2025* | [iea.blob](https://iea.blob.core.windows.net/assets/0aa4762f-c1cb-4495-987a-25945d6de5e8/GlobalEVOutlook2025.pdf) | equal |
| **MPP-AV** | MPP, *Making Net-Zero Aviation Possible* (July 2022) | [energy-transitions.org](https://www.energy-transitions.org/wp-content/uploads/2022/07/Making-Net-Zero-Aviation-possible.pdf) | equal ("PAGE n") |
| **MPP-TR** | MPP, *Making Zero-Emissions Trucking Possible* (July 2022) | [static.energy-transitions.org](https://static.energy-transitions.org/uploads/resources/Making-Zero-Emissions-Trucking-Possible.pdf) | equal ("PAGE n") |
| **GtZ21** | UMAS for the Getting to Zero Coalition (MPP-funded), *A Strategy for the Transition to Zero-Emission Shipping* (Oct 2021) | [energy-transitions.org](https://www.energy-transitions.org/wp-content/uploads/2022/07/A-Strategy-for-the-Transition-to-Zero-Emission-Shipping.pdf) | equal |
| **ICCT20** | ICCT, *Vision 2050* (Sept 2020) | [theicct.org](https://theicct.org/sites/default/files/publications/ICCT_Vision2050_sept2020.pdf) | printed = PDF − 2 |
| **IMO23** | IMO Resolution MEPC.377(80), *2023 IMO Strategy on Reduction of GHG Emissions from Ships* (MEPC 80 Annex 15) | [imo.org](https://wwwcdn.imo.org/localresources/en/OurWork/Environment/Documents/annex/MEPC%2080/Annex%2015.pdf) | "Annex 15, page n" |
| **ReFuelEU** | Regulation (EU) 2023/2405 | EUR-Lex: **HTTP 202 bot challenge, not read** | n/a |
| **FuelEU** | Regulation (EU) 2023/1805 | EUR-Lex: **HTTP 202 bot challenge, not read** | n/a |

**Which sources ACT Core allows.** ACT Core uses "Only 1.5ºC compatible pathways" and lists,
among others, "IEA Pathways entailed in the 2050 Net-Zero Roadmap", "IEA World Energy Outlook
2022", "Air Transport Action Group (ATAG) Waypoint 2050", "International Council on Clean
Transportation (ICCT) Vision 2050" and "Mission Possible Partnership – Sector transition
Strategies" (Core p.87). Other pathways must have "a temperature ambition of 1.5°C with associated
probability equal to or above 50%", "no or limited temperature overshoot before 2050" and "limited
reliance on 'negative GHG emissions' (… maximum 10% of residual GHG emissions …)" (Core p.87).
[verified]

| Candidate | On Core p.87 list? | Note |
|---|---|---|
| NZE23 | Yes ("2050 Net-Zero Roadmap") | Peak "just below 1.6 °C around 2040", "around 1.4 °C in 2100" (NZE23 p.63) [verified] |
| WEO24 NZE | Not named (list names WEO 2022) | Same NZE family. Annex has no transport fuel split by mode (section 4) |
| WEO25 NZE | Not named | "no longer a limited-overshoot scenario" (WEO25 p.106) [verified]; fails the Core p.87 criterion [ours] |
| GEVO24 / GEVO25 | Not named | GEVO24's NZE "is consistent with the 2023 update to the IEA Net Zero Roadmap" (GEVO24 p.102) [verified]. GEVO25 has STEPS only, to 2030 (GEVO25 p.82) [verified] |
| MPP-AV, MPP-TR, GtZ21 | Yes ("MPP – Sector transition Strategies") | MPP-AV and MPP-TR subtitles: "An industry-backed, 1.5°C-aligned transition strategy" (cover) [verified] |
| ICCT20 | Yes ("ICCT Vision 2050") | Targets "to keep global warming below 1.5°C" (ICCT20 preface, PDF p.3) [verified] |
| IMO23 | No (policy, not a pathway) | Usable as a policy floor, labelled as such [ours] |
| ReFuelEU, FuelEU | No (policy) | Policy floor for EU operations only [ours] |
| DNV19, ETC18, ETP17, FoT17 | No | ACT's original sources. ETP17 B2DS and FoT17 MTS predate 1.5 °C pathways |

---

## 3. Q1: what ACT's cited sources actually give

ACT TR 2.4 (TR pp.53–56) defines FLCV(t) = low-carbon vehicles / all vehicles in the plan year,
with ICE vehicles counted "proportionally to the share of low-carbon energy used in those
vehicles" (TR p.54). It sets rLCV(t) = FLCV(t)/SBLCV(t), averages it over the plan years and caps
it at 1 (TR p.55). SBLCV(t) "is represented in the graph" for road freight, maritime, aviation
and rail, 2020–2050, y-axis 0–80% (TR p.55). It has no data labels. [verified] The source table
(TR p.144, "Share of low carbon vehicles and energies required in a low-carbon scenario") names
the pages below. [verified]

| ACT citation (TR p.144) | What the cited page actually shows | Numbers by year? | Tag |
|---|---|---|---|
| Shipping: **DNV GL [34] p.93** | Figure 6.4: energy use by fuel, 2018–2050, EJ/yr, IMO-ambitions design-requirements (DR) pathway, **chart only**. Figure 6.5: 2050 fuel shares in the DR pathway as chart labels: LNG 41%, ammonia 25%, HFO + scrubber 10%, LSFO/MGO 9%, grid electricity 7%, advanced biodiesel 4%, bio/electro liquefied methane 2%, LPG 1%, hydrogen 1%. On p.92 (text): "Carbon-neutral fuels need to supply 30%–40% of the total energy for international shipping in mid-century if the IMO's ambitions for reducing GHGs are to be achieved." | 2050 only | [verified] |
| Shipping: **IEA ETP 2017 [4] p.260** | Box 5.5 ("Why LNG is not included in the B2DS?") and Figure 5.15 (WTW GHG emissions, RTS / high-LNG / B2DS, 2010–60), **chart only**. No fuel or vehicle shares. The nearest number is on p.261: in the B2DS, "5 EJ of second‐generation biofuels account for nearly half of the total final energy demand in international shipping in 2060." | No (one 2060 statement on p.261) | [verified] |
| Shipping: **ETC [8] p.110** ("illustrative") | Exhibit 6.1: "Final energy consumption by energy source in a net-zero-CO2-emissions economy, 2050, %", one bar per sector. The shipping bar's segments read 10% / 10% / 60% / 20%. The text layer does not show which segment is which fuel, so the split is not attributed here. The whole bar is zero-carbon energy by construction. | 2050 only | [verified] (segment-to-fuel mapping not verified) |
| Road freight: **IEA ETP 2017 [4] p.250** | Figure 5.10: "Global technology penetrations in truck stock by scenario, 2015-60", stacked areas for MFTs and HFTs in B2DS / 2DS / RTS, in million vehicles, **chart only**. Text describes the uptake qualitatively. | No | [verified] |
| Road freight: **IEA Future of Trucks [17] p.124** (PDF p.126) | Modern Truck Scenario (MTS) 2050 stock shares in text: "three-quarters of LCVs and 35% of MFTs are plug-in (or, in the case of MFTs, catenary-enabled) hybrid or battery electric by mid-century. In addition, 36% of HFTs are catenary-enabled electric trucks." The preceding page (p.123, PDF p.125) adds that by 2050 "7% of LCVs, 40% of MFTs and around 30% of HFTs use hybrid powertrains", and Figure 37 (stocks by technology, 2015–50) is chart only. | 2050 only | [verified] |
| Road freight: **IEA Future of Trucks [17] p.126** (PDF p.128) | Figure 39: GHG reductions by measure, MTS vs Reference, 2015–2050, Gt CO2-eq, **chart only**. Text: biofuels about one-quarter and low-carbon electricity 16% of cumulative reductions (p.125–126). | No | [verified] |
| Aviation: **IEA [35]** commentary, 2019 | Not opened (403). Search snippets quoting it say the Sustainable Development Scenario "anticipates biofuels reaching around 10% of aviation fuel demand by 2030, and close to 20% by 2040". | Two points, if correct | [unverified] |
| Rail: **IEA [23]** *Future of Rail* 2019 | Not checked (out of scope). | — | — |

**Answer to Q1.** No. The best any source does is a single 2050 (or 2060) number, and DNV19's
numbers are for an IMO-2018 pathway (50% GHG cut by 2050), not net zero. TR p.55's curve cannot
be traced value by value to these sources. Read it as ACT's interpolation. [ours] The values on
the TR p.55 chart were not read (chart only).

---

## 4. Q2: which current pathways print the four KPIs as numbers

### 4.1 (a) Zero-emission share of heavy-truck sales and/or stock

| Source | Metric | 2030 | 2035 | 2040 | 2050 | Page | Tag |
|---|---|---|---|---|---|---|---|
| **NZE23** milestone table, "Sales share of plug-in hybrid, battery and fuel cell electric vehicles", row "Heavy trucks" (2022: 1%) | Global sales share, incl. PHEV | 37% | 65% | — | 100% | p.93 | [verified] |
| NZE23 text | ICE truck sales end: "new fossil-fuelled ICE truck sales end in 2040 in advanced economies and China, and in 2045 in the rest of the world" | | | | | p.88 | [verified] |
| NZE23 text | EV sales share of heavy trucks: 55% in China and advanced economies, 7% in other emerging and developing economies | 55% / 7% | | | | p.124 | [verified] |
| NZE23 text | "electric heavy trucks increase from 1% to 33% share" of sales (differs from 37% on p.93; likely a narrower "electric" definition, not stated) | 33% | | | | p.125 | [verified] |
| NZE23 definition | "Heavy trucks: Include commercial vehicles: medium freight trucks (gross vehicle weight between 3.5 and 15 tonnes); and heavy freight trucks (>15 tonnes)" | | | | | p.207 | [verified] |
| GEVO24 | Truck EV sales share by scenario, 2030 and 2035 | chart only | chart only | | | p.106 | [verified] |
| GEVO24 text | "In the NZE Scenario, electric truck sales represent over 55% of total medium- and heavy-duty truck sales in 2035" | | > 55% | | | p.110 | [verified] |
| GEVO25 | STEPS only, projections "limited to 2030 in the STEPS"; no NZE | — | — | — | — | p.82 | [verified] |
| WEO24 annex (NZE, Table A.2c) | Heavy-duty truck energy (EJ) only: 29 / 27 / 25 / 23; no fuel split, no sales share | — | — | — | — | p.310 | [verified] |
| WEO25 ch.7 (NZE) | No heavy-truck sales or stock share found in the NZE chapter | — | — | — | — | pp.313–356 searched | [verified] |
| **MPP-TR** | Four regions (China, Europe, India, US). Text: "the majority of sales ZETs by 2030 and nearly 100% of sales ZETs by 2035, 95% of all trucks on the road by 2040 would be zero emissions" (in the carbon-pricing section 3.2.4). Exhibits 3.6–3.8 give regional, segment-level shares as chart labels | > 50% (sales) | ≈ 100% (sales) | 95% (stock) | | p.42 | [verified]; which scenario the sentence belongs to is unclear (section 8) |
| MPP-TR text, other policy scenario | "Sales of ZETs increase from less than 40% in 2035 to 100% by 2040, leading to a fully zero-emissions fleet by 2050" | | < 40% (sales) | 100% (sales) | 100% (stock) | p.40 | [verified] |
| ICCT20 | 2050 global stock (sales): heavy heavy-duty 29% (44%), medium heavy-duty 42% (60%), light heavy-duty 69% (87%) electric. BEV and FCEV not split | | | | stock 29–69% | p.14 (PDF p.16) | [verified] |

### 4.2 (b) Low- or zero-emission fuel share of shipping energy

| Source | Metric | 2030 | 2035 | 2040 | 2050 | Page | Tag |
|---|---|---|---|---|---|---|---|
| **NZE23** milestone table, "Shipping – Share in final energy consumption" | Biofuels | 8% | 13% | — | 19% | p.94 | [verified] |
| | Hydrogen | 4% | 7% | — | 19% | p.94 | [verified] |
| | Ammonia | 6% | 15% | — | 44% | p.94 | [verified] |
| | Methanol | 1% | 1% | — | 3% | p.94 | [verified] |
| | **Sum of the four rows** | **19%** | **36%** | — | **85%** | p.94 | [ours] (sum of verified values) |
| NZE23 text | "Bioenergy, hydrogen and hydrogen-based fuels ramp up from less than 1% of energy consumed today in shipping and aviation to almost 15% in 2030 and 80% by 2050" (shipping and aviation combined) | ≈ 15% | | | 80% | p.94 | [verified] |
| WEO25 (NZE) | "low-emissions ammonia, synthetic methanol and hydrogen … meet around 30% of the energy needs for shipping in the NZE Scenario by 2035" (excludes biofuels) | | ≈ 30% | | | p.342 | [verified] |
| WEO24 annex (NZE) | Shipping energy total only: 9 / 9 / 8 / 8 EJ | — | — | — | — | p.310 | [verified] |
| GtZ21 (MPP-funded) | Figure 5 S-curve of zero-emission fuel penetration, 2021–2051, **chart only**. Text: transition can "reasonably begin in 2030 if around 5% of shipping fuels globally had by then shifted to scalable zero-emission fuels" | ≈ 5% | | | | pp.29, 45 | [verified] |
| **IMO23** (policy) | "uptake of zero or near-zero GHG emission technologies, fuels and/or energy sources to represent at least 5%, striving for 10%, of the energy used by international shipping by 2030". Checkpoints: total GHG −20% (striving −30%) by 2030 and −70% (striving −80%) by 2040 vs 2008; net zero "by or around, i.e. close to, 2050" | ≥ 5% (10%) | | | | Annex 15, p.6 | [verified] |
| **FuelEU** (policy, EU) | Not a fuel share: GHG-intensity reduction of energy used on board vs a 2020 reference: −2% (2025), −6% (2030), −14.5% (2035), −31% (2040), −62% (2045), −80% (2050) | −6% | −14.5% | −31% | −80% | Art. 4(2) | [unverified] |
| DNV19 | See section 3: 2050 only, IMO-2018 ambition | | | | 30–40% | pp.92–93 | [verified] |

### 4.3 (c) SAF or low-emission fuel share of aviation fuel

| Source | Metric | 2030 | 2035 | 2040 | 2050 | Page | Tag |
|---|---|---|---|---|---|---|---|
| **NZE23** milestone table, "Aviation – Share in final energy consumption" | Biofuels | 10% | 22% | — | 33% | p.94 | [verified] |
| | Synthetic hydrogen-based fuels | 1% | 4% | — | 37% | p.94 | [verified] |
| | **Sum** | **11%** | **26%** | — | **70%** | p.94 | [ours] (sum of verified values) |
| NZE23 | "Avoided demand from behavioural measures": 9% / 14% / — / 20% (a demand reduction, not a fuel share) | | | | | p.94 | [verified] |
| WEO25 (NZE) | Synthetic kerosene "By 2035, it meets 3% of global aviation fuel demand"; "In 2035, around 80% of SAF are biofuels" | | 3% (synthetic) | | | pp.338, 342 | [verified] |
| **MPP-AV** Exhibit 2.8, "SAF blending rate, % of final jet fuel demand" (PRU and ORE scenarios), chart labels | SAF share | 13–15% | 28–32% | 62% | not labelled | p.51 | [verified] (chart labels) |
| MPP-AV text | "By 2030, about 42–51 Mt of SAFs — 13%–15% of total jet fuel demand — are required to achieve credible 1.5°C pathways" | 13–15% | | | | p.48 | [verified] |
| MPP-AV Exhibit G | Share of final energy demand in 2050: SAFs 65–85%, hydrogen 13–32%, battery-electric ≈ 2% | | | | SAF 65–85% | p.16 | [verified] |
| IEA-AVB19 (ACT's source) | SDS biofuel share of aviation fuel | ≈ 10% | | ≈ 20% | | n/a | [unverified] |
| **ReFuelEU** (policy, EU airports) | Minimum SAF share of fuel supplied: 2% (2025), 6% (2030), 20% (2035), 34% (2040), 42% (2045), 70% (2050); synthetic sub-minimum from 1.2% (2030) rising to 35% (2050) | 6% | 20% | 34% | 70% | Annex I | [unverified] |

### 4.4 (d) Zero-emission or low-carbon share of a road-freight operator's fleet

| Source | Metric | 2030 | 2035 | 2040 | 2050 | Page | Tag |
|---|---|---|---|---|---|---|---|
| NZE23 | No heavy-truck **stock** share printed. "EVs come to dominate the stock of not just cars and motorbikes but also trucks" (no number) | — | — | — | — | p.67 | [verified] |
| NZE23 road milestone, "Alternative fuel shares" of **all road** energy (biofuels + electricity + hydrogen) | 2022: 5% | 20% | 36% | — | 93% | p.93 | [verified] |
| NZE23 chart "Fuel shares of road energy consumption – Heavy trucks", 2010/2022/2030/2050 | **chart only** | | | | | p.93 | [verified] |
| **MPP-TR** text | "95% of all trucks on the road by 2040 would be zero emissions" (four regions; one policy scenario) | | | 95% | | p.42 | [verified] |
| MPP-TR text, Expected Adoption (market, not 1.5 °C) | "by 2050, 80% of trucks on the road will produce zero emissions" | | | | 80% | p.11 | [verified] |
| ICCT20 | 2050 electric share of global stock: HHDT 29%, MHDT 42%, LHDT 69% | | | | 29–69% | p.14 (PDF p.16) | [verified] |
| FoT17 (MTS, 2017, not 1.5 °C) | 2050 stock: 36% of HFTs catenary electric; 35% of MFTs plug-in/catenary hybrid or BEV | | | | 35–36% | p.124 (PDF p.126) | [verified] |

**Answer to Q2.** Numbers by year exist for (a), (b) and (c) in NZE23 (2030, 2035, 2050) and,
for aviation, in MPP-AV (2030, 2035, 2040). No current 1.5 °C source prints a global heavy-truck
**fleet** share as a yearly series. MPP-TR gives one stock point (2040). ICCT20 and FoT17 give
2050 stock points, but ICCT20's truck stock is far from 100% and FoT17 is a 2 °C-era scenario.
[verified for what the documents print; the assessment is ours]

---

## 5. Fit to ACT's definitions

- **TR 2.4 is a fleet-and-energy share.** Low-carbon vehicles include "Electric, plug-in hybrid,
  hydrogen-fuelled and ammonia-fuelled vehicles" and vehicles on biofuels or advanced fuels.
  ICE vehicles count in proportion to their contracted low-carbon fuel share (TR p.165 glossary;
  TR p.54). [verified] For ships and aircraft this is in effect an **energy share**, because
  fleets do not switch hull by hull the way trucks do. An energy-share benchmark therefore fits
  directly. [ours]
- **AU 4.4 is a sales share** of BEV + FCEV (PHEVs not counted for the company), against a
  benchmark that includes PHEVs "to stick to the conservativeness principle" (AU p.119). [verified]
  NZE23's heavy-truck row also includes PHEVs (p.93), so it keeps the same convention. [ours]
- **AU p.119 calls the NZE 67% a "global fleet" value.** It says PHEVs, BEVs and FCEVs "are
  expected to represent 67% of light-duty vehicles global fleet by 2030". AU p.10 and NZE23 p.93
  give 67% as a **sales** share ("Cars and vans 13% / 67% / 100% / 100%"). [verified] The AU
  wording is a slip, and AU Table 9 is used as a sales benchmark. [ours]
- **TR 2.4 averages the plan years.** Plans usually run to 2030 or 2035, so the missing 2040
  value matters only for long plans. Between published years, linear interpolation matches what
  ACT itself does in AU Table 9 ("a linear progression is assumed between 2022 and 2030 and
  between 2030 and 2035", AU p.119). [verified quote; using it here is ours]

---

## 6. Q3: recommended benchmark per KPI

### (a) Heavy-truck makers: ZE share of sales. Use NZE23 p.93, "Heavy trucks".

- Values: 2022 1%, **2030 37%, 2035 65%, 2050 100%**; no 2040. [verified]
- Fit: **direct** for a sales-share indicator (AU 4.4 dimension 1, and dimension 2's
  convergence). Same source family and convention as AU Table 9, but the heavy-truck row instead of
  the light-duty row. [ours]
- Required change: AU 4.4 dimension 2 converges to 100% in 2035 (AU p.56). For trucks, 2035 is
  65% and 100% comes in 2050. If 2040 is needed, the NZE text gives only end-of-ICE-sales dates
  (2040 in advanced economies and China, 2045 elsewhere; p.88). Linear interpolation between 2035
  and 2050 gives a value that is ours, not the IEA's. [ours]
- Flag: GEVO24 p.110 says "> 55%" electric truck sales in 2035, not 65%. The difference is
  probably definitional (PHEV/FCEV), but that is not stated. Cite p.93 for the table and note the
  difference. [verified values; the explanation is unverified]

### (b) Shipping: low-emission share of energy. Use NZE23 p.94.

- Values: **2030 19%, 2035 36%, 2050 85%** = biofuels + hydrogen + ammonia + methanol shares of
  shipping final energy consumption. No 2040. [verified rows; sum ours]
- Fit: **direct** to TR 2.4's "vehicles and energies" for a shipping company. The company's FLCV
  should be its low-carbon share of fuel energy, with ACT's contract-and-verification condition
  (TR p.54). [ours]
- Flags: (1) the table heading is "Shipping"; its activity row is "International shipping
  activity". The scope (international only, or all shipping) is not stated on the page.
  (2) The methanol row is assumed low-emission. The page does not say so. (3) A policy floor is the
  IMO23 level of at least 5%, striving for 10%, of international shipping energy by 2030 (Annex 15
  p.6). The NZE value is above it. [verified quotes; points ours]

### (c) Aviation: SAF / low-emission share of fuel. Use NZE23 p.94; MPP-AV for 2040.

- NZE23 values: **2030 11%, 2035 26%, 2050 70%** = biofuels + synthetic hydrogen-based fuels
  share of aviation final energy. [verified rows; sum ours]
- 2040, if needed: **MPP-AV p.51, 62%** (chart label; both MPP scenarios), with 2030 13–15% and
  2035 28–32%. [verified] MPP-AV runs slightly above NZE23 in 2030–2035. Do not mix the two series
  within one plan. [ours]
- Fit: **direct** (energy share). NZE23's 2050 value is below 100% because hydrogen and
  electricity aircraft and residual fossil fuel make up the rest (p.94 chart; MPP-AV p.16). [ours]
- Policy cross-check (EU flights only): ReFuelEU 6% (2030), 20% (2035), 34% (2040), 70% (2050).
  [unverified]

### (d) Road-freight operators: low-carbon share of fleet. No direct source; convert (a), and say so.

- No 1.5 °C pathway on the Core p.87 list prints a heavy-truck stock share for 2030, 2035, 2040
  and 2050. [verified for NZE23, WEO24, WEO25, GEVO24, MPP-TR, ICCT20]
- Recommended: build SB_LCV(t) for trucks from the NZE23 heavy-truck **sales** path (a), with a
  stated stock-turnover rule. ACT TR already uses an average vehicle lifetime L_f from "The
  Geography of Transport systems" for TR 1.2 (TR p.144). [verified] Apply that survival rule to
  the sales path and document the result as a derived benchmark. [ours] This note does not
  compute the derived values.
- Cross-check: MPP-TR p.42, **95% of trucks on the road by 2040** (four regions, policy
  scenario). Use it only as a sanity check on the derived 2040 value, because of its scope and the
  scenario-label issue (section 8). [verified quote; use ours]
- Rejected shortcut: using the (a) sales shares directly as the fleet benchmark. That puts a sales
  share against a fleet share and asks an operator for, e.g., 37% of its fleet in 2030, when only
  a fraction of the fleet is renewed by then. [ours]
- Alternative energy-share view: NZE23 p.93 "Alternative fuel shares" (20% / 36% / 93%) is an
  energy share, which fits TR 2.4's energy counting. But it covers **all road transport**, cars
  included, so it is not truck-specific. [verified values; mismatch ours]

---

## 7. Summary table

| KPI | Recommended source | 2030 | 2035 | 2040 | 2050 | Page | Fit to ACT definition | Verified |
|---|---|---|---|---|---|---|---|---|
| (a) ZE share of heavy-truck sales (PHEV + BEV + FCEV) | IEA Net Zero Roadmap 2023, milestone table, "Heavy trucks" | 37% | 65% | not published | 100% | p.93 | Direct for a sales indicator (AU 4.4-style). Replaces AU Table 9's light-duty values for truck makers | [verified] |
| (b) Low-emission share of shipping final energy (biofuels + H2 + NH3 + methanol) | IEA Net Zero Roadmap 2023, milestone table, "Shipping" | 19% | 36% | not published | 85% | p.94 | Direct (TR 2.4 counts low-carbon energy share). Scope intl/all not stated; methanol assumed low-emission | [verified] rows; sum [ours] |
| (c) SAF + synthetic share of aviation final energy | IEA Net Zero Roadmap 2023, milestone table, "Aviation" | 11% | 26% | not published (MPP-AV p.51: 62%) | 70% | p.94 (MPP-AV p.51) | Direct (energy share) | [verified] rows; sum [ours] |
| (d) ZE share of a road-freight operator's fleet | Derived from (a) with ACT's lifetime L_f (TR p.144); cross-check MPP-TR | needs conversion | needs conversion | needs conversion (MPP-TR: 95%) | needs conversion | NZE23 p.93; MPP-TR p.42 | Conversion required: (a) is a sales share and TR 2.4 is a fleet share. Unconverted use is a mismatch | Inputs [verified]; conversion [ours] |

Policy references, kept separate from scenario benchmarks:

| KPI | Policy | 2030 | 2035 | 2040 | 2050 | Reference | Verified |
|---|---|---|---|---|---|---|---|
| (b) | IMO 2023 Strategy, ZNZ fuel uptake (international shipping) | ≥ 5% (striving 10%) | — | — (GHG checkpoint −70%/−80% vs 2008) | net zero "by or around … 2050" | MEPC.377(80), Annex 15 p.6 | [verified] |
| (b) | FuelEU Maritime, GHG-intensity reduction (not a share) | −6% | −14.5% | −31% | −80% | Reg. (EU) 2023/1805 Art. 4(2) | [unverified] |
| (c) | ReFuelEU Aviation, minimum SAF share | 6% | 20% | 34% | 70% | Reg. (EU) 2023/2405 Annex I | [unverified] |

---

## 8. Could not access / not verified

- **IEA commentary "Are aviation biofuels ready for take off?" (2019)**, ACT's aviation source:
  iea.org returned HTTP 403, and archive and mirror copies were refused or reset. The ≈ 10%
  (2030) and ≈ 20% (2040) SDS values are from search snippets only.
- **ReFuelEU (2023/2405) and FuelEU (2023/1805)**: EUR-Lex returned an HTTP 202 bot challenge with
  an empty body for the HTML and PDF endpoints. All values are from secondary summaries (European
  Parliament legislative summary, trade press). The FuelEU 2020 reference value was not confirmed.
  Check them in the Official Journal before storing them.
- **MPP shipping, current edition**: MPP relaunched GtZ21 as "Making Zero-Emissions Shipping
  Possible". That PDF returned 403. Only the 2021 UMAS report was read.
- **MPP-TR scenario labels**: the p.42 sentence (95% stock by 2040) sits in section 3.2.4 "Fuel
  carbon pricing" (Accelerated Zero-Emissions — Carbon Cost), but the adjacent Exhibit 3.8 is
  titled "Zero-Emissions — ZET Mandate scenario". The p.40 text (sales 100% by 2040) matches the
  mandate scenario, while its Exhibit 3.6 is titled "Accelerated Zero-Emissions". Which scenario
  each number belongs to was not settled. MPP-TR also does not say which of its scenarios is
  1.5 °C-aligned. Only the cover claims that.
- **ETC18 Exhibit 6.1** segment-to-fuel mapping for shipping (10/10/60/20%) could not be read
  from the text layer.
- **NZE23 shipping scope** (international or all shipping) and whether its methanol row is all
  low-emission were not stated on p.94.
- **NZE23 p.93 (37%) vs p.125 (33%) vs GEVO24 p.110 (> 55% in 2035 vs 65%)**: the definitional
  reason for the differences is not given in the documents.
- **WEO25 annex tables**: the WEO25 PDF has no NZE annex table. Its scenario tables may be a
  separate download, which was not checked. WEO24's NZE annex (Table A.2c, p.310) has transport
  energy by mode but no fuel split within modes.
- **Not checked:** ATAG Waypoint 2050 (on the Core p.87 list); IEA *Future of Rail* (rail is out
  of scope); IRENA WETO 2023; ICCT papers after 2020 (e.g. HDV-specific 1.5 °C pathways); IEA ETP
  2023/2024; and the values on the TR p.55 SB_LCV chart (chart only, not read on purpose).
- **Licences.** IEA documents are CC BY 4.0 (NZE23, GEVO, WEO25) or CC BY-NC-SA 4.0 (WEO24 annex),
  as printed on their pages. ETP17 and FoT17 are "© OECD/IEA 2017". The IEA dataset terms for
  model use were not checked (ACT research §17 notes the same for other IEA data).

**Does `openwiki/` need an update?** No. This note changes no code or behaviour.
