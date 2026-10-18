# Rule book v1: impact table

This table compares today's hand ratings with what the draft rule book v1 (35 criteria, signed as version 1 pending owner approval) would give for each of the 105 cells (35 criteria, 3 regions). The v1 column was worked out by hand from the figures in today's evidence text, not by the engine, which arrives in phase 2. Where the evidence has the needed figures the cell shows the rating the rules give. `not rated: missing <fact>` means the evidence text has no figure for that fact, so the rules cannot decide; the reason column gives the reading by hand where one exists. `not rated: open threshold <label>` means the result depends on one of the 17 thresholds that v1 leaves open for the owner (listed below), so the cell is not re-derived. A cell with both problems is shown under the one that blocks it first.

## Summary

| | Unchanged | Changed | Not rated (missing figure) | Not rated (open threshold) | Total |
|---|---|---|---|---|---|
| All regions | 29 | 4 | 54 | 18 | 105 |
| European Union | 11 | 1 | 16 | 7 | 35 |
| United States | 7 | 2 | 18 | 8 | 35 |
| China | 11 | 1 | 20 | 3 | 35 |

Changed cells: MIN-R2 EU (H to M), MIN-R2 CN (M to L), AVI-T1 US (L to M), OGU-R1 US (L to M). STL-R1 China, which the spec expected to differ, comes out unchanged at L: the price of USD 9.31-13.50 stays below the material line.

## Cells by sector

### Power & Utilities

| Code | Criterion | Region | Current | Under v1 rules | Reason |
|---|---|---|---|---|---|
| PWR-T1 | Levelised cost of renewable generation vs. new-build fossil | EU | H | not rated: missing New-build fossil LCOE | Evidence gives only renewables at EUR 40-60/MWh and says this is at or below new-build CCGT. By hand: H. |
| PWR-T1 | Levelised cost of renewable generation vs. new-build fossil | US | H | not rated: missing Renewable LCOE and New-build fossil LCOE | Evidence says unsubsidised wind and solar are below new-build CCGT in most regions, no figures. By hand: H. |
| PWR-T1 | Levelised cost of renewable generation vs. new-build fossil | CN | H | not rated: missing Renewable LCOE and New-build fossil LCOE | Evidence says renewables are cost-competitive, no figures. By hand: H. |
| PWR-T2 | Grid-scale storage / firming technology readiness | EU | M | not rated: open threshold Non-negligible storage share | Storage and curtailment figures are also missing. Evidence calls curtailment material, so H is false either way; M needs the open share. |
| PWR-T2 | Grid-scale storage / firming technology readiness | US | M | not rated: open threshold Non-negligible storage share | Storage and curtailment figures are also missing. |
| PWR-T2 | Grid-scale storage / firming technology readiness | CN | M | not rated: open threshold Non-negligible storage share | Storage and curtailment figures are also missing. Evidence calls curtailment material, so H is false either way; M needs the open share. |
| PWR-R1 | Effective carbon price on power generation | EU | H | H | EUR 60-90/t = USD 65-102 at 2024-25 rates, EU-wide, above the 60 line. |
| PWR-R1 | Effective carbon price on power generation | US | M | not rated: missing Effective carbon price on power and Clean generation mandate | Evidence names state programmes only (scope sub-regional), no figure. By hand, RGGI or California prices or state clean-energy targets would give M. |
| PWR-R1 | Effective carbon price on power generation | CN | M | not rated: missing Clean generation mandate | Price CNY 69-106 (2024) = USD 9.59-14.73 and CNY 66.9-97 (2025) = USD 9.31-13.50, below 15, so the price branch fails. M holds only if China's five-year-plan renewable targets count as other_target. On price alone: L. |
| PWR-R2 | Renewable deployment target and permitting regime | EU | H | not rated: missing Grid connection time | Renewable target is binding; connection time is not in the evidence. |
| PWR-R2 | Renewable deployment target and permitting regime | US | M | not rated: missing Grid connection time | Evidence says connection takes 'exceeding 3 years', so not H. Whether it is 7 years or less is unknown (LBNL's ~5 years, not in the evidence, would give M). |
| PWR-R2 | Renewable deployment target and permitting regime | CN | H | not rated: missing Grid connection time | Connection time is not in the evidence. |
| PWR-D1 | Corporate and utility PPA market depth | EU | H | not rated: open threshold PPA share of an established market | H needs the established-market share; PPA and additions figures (GW) are also missing. |
| PWR-D1 | Corporate and utility PPA market depth | US | H | not rated: open threshold PPA share of an established market | H needs the established-market share; PPA and additions figures (GW) are also missing. |
| PWR-D1 | Corporate and utility PPA market depth | CN | M | not rated: open threshold PPA share above negligible | M needs the negligible-share line; PPA and additions figures (GW) are also missing. |

### Steel

| Code | Criterion | Region | Current | Under v1 rules | Reason |
|---|---|---|---|---|---|
| STL-T1 | Green hydrogen cost vs. DRI-H2 breakeven | EU | M | not rated: missing Renewable hydrogen cost and DRI-H2 breakeven hydrogen cost | Evidence says cost is above breakeven, so H is false; M needs the cost ratio. |
| STL-T1 | Green hydrogen cost vs. DRI-H2 breakeven | US | M | not rated: missing Renewable hydrogen cost and DRI-H2 breakeven hydrogen cost | Evidence says cost is above breakeven, so H is false; M needs the cost ratio. |
| STL-T1 | Green hydrogen cost vs. DRI-H2 breakeven | CN | L | not rated: missing Renewable hydrogen cost and DRI-H2 breakeven hydrogen cost | No hydrogen cost figures in the evidence. |
| STL-T2 | Scrap steel availability (EAF route feasibility) | EU | M | not rated: missing Domestic scrap availability and Crude steelmaking capacity | No scrap or capacity figures in the evidence. |
| STL-T2 | Scrap steel availability (EAF route feasibility) | US | H | not rated: missing Domestic scrap availability and Crude steelmaking capacity | Evidence gives an EAF share of about 70%, which is not scrap divided by capacity. |
| STL-T2 | Scrap steel availability (EAF route feasibility) | CN | L | not rated: missing Domestic scrap availability and Crude steelmaking capacity | No scrap or capacity figures in the evidence. |
| STL-R1 | Effective carbon price on steel production incl. border adjustment | EU | H | not rated: missing Carbon price on steel | Evidence says 'in the effective range', no figure. Levy and free-allocation phase-out are both Yes. At PWR-R1's EUR 60-90 (USD 65-102) it would be H. |
| STL-R1 | Effective carbon price on steel production incl. border adjustment | US | L | L | Carbon price applies to steel is No (no federal price). |
| STL-R1 | Effective carbon price on steel production incl. border adjustment | CN | L | L | Expected by the spec to differ; it does not. Applies is Yes, but the price CNY 66.9-97 = USD 9.31-13.50 (2025 rate) is below the 33.92 material line and there is no levy, so L. M would need about CNY 244/t. L now rests on an explicit, sourced line. |
| STL-R2 | Green/low-carbon steel public procurement or building-code mandate | EU | M | M | Member-state rules read as voluntary_or_pilot. |
| STL-R2 | Green/low-carbon steel public procurement or building-code mandate | US | M | not rated: open threshold Material share of construction demand | Federal Buy Clean (EO 14057) was rescinded in January 2025; with current facts the US would be voluntary_or_pilot, giving M. |
| STL-R2 | Green/low-carbon steel public procurement or building-code mandate | CN | L | L |  |
| STL-D1 | Green steel price premium and recoverability | EU | H | not rated: open threshold Material offtake share | Premium and signed offtakes are both stated, so M holds at least; H needs the open share. |
| STL-D1 | Green steel price premium and recoverability | US | M | not rated: missing Green steel premium disclosed | Evidence names commitments, not a premium. |
| STL-D1 | Green steel price premium and recoverability | CN | L | L | No premium. |

### Cement

| Code | Criterion | Region | Current | Under v1 rules | Reason |
|---|---|---|---|---|---|
| CEM-T1 | CCS capture technology deployment status | EU | H | H | Brevik, about 0.4 Mtpa, operating with a track record, meets the 0.4 Mtpa line (>=). |
| CEM-T1 | CCS capture technology deployment status | US | M | not rated: missing Largest cement CCS plant at FID or in construction | Evidence says 'planning or FID', no capacity. Stale: DOE cancelled the Heidelberg Mitchell award in May 2025. |
| CEM-T1 | CCS capture technology deployment status | CN | L | L |  |
| CEM-T2 | Clinker substitution rate (SCM availability) | EU | M | not rated: missing Clinker-to-cement ratio | Evidence says 'above the H threshold', so H is false; M needs the ratio. |
| CEM-T2 | Clinker substitution rate (SCM availability) | US | M | not rated: missing Clinker-to-cement ratio | No ratio in the evidence. |
| CEM-T2 | Clinker substitution rate (SCM availability) | CN | M | not rated: missing Clinker-to-cement ratio | No ratio in the evidence. |
| CEM-R1 | Effective carbon price on cement production incl. border adjustment | EU | H | not rated: missing Carbon price on cement | Same as STL-R1 EU: no figure; levy and phase-out Yes; would be H at EUR 60-90. |
| CEM-R1 | Effective carbon price on cement production incl. border adjustment | US | L | L | Applies is No (no federal price). California cap-and-trade covers in-state cement; the region-level fact reads federal coverage. |
| CEM-R1 | Effective carbon price on cement production incl. border adjustment | CN | L | L | USD 9.31-13.50 is below 33.92 and there is no levy. |
| CEM-R2 | CCS infrastructure support scheme | EU | H | H |  |
| CEM-R2 | CCS infrastructure support scheme | US | M | M | Scheme active; disbursement 'earlier stage' reads as No. |
| CEM-R2 | CCS infrastructure support scheme | CN | L | L |  |
| CEM-D1 | Low-carbon cement premium recoverability | EU | M | M | Member-state green public procurement reads as voluntary_or_pilot. |
| CEM-D1 | Low-carbon cement premium recoverability | US | M | not rated: open threshold Material share of low-carbon capacity | Federal Buy Clean read as binding, but it was rescinded in January 2025; with current facts the US would be voluntary_or_pilot, giving M. |
| CEM-D1 | Low-carbon cement premium recoverability | CN | L | L |  |

### Chemicals

| Code | Criterion | Region | Current | Under v1 rules | Reason |
|---|---|---|---|---|---|
| CHM-T1 | Green/blue hydrogen availability for ammonia and feedstock use | EU | M | not rated: missing Low-carbon hydrogen cost and Grey hydrogen cost | Evidence says the gap 'remains material', no numbers. |
| CHM-T1 | Green/blue hydrogen availability for ammonia and feedstock use | US | M | not rated: missing Low-carbon hydrogen cost and Grey hydrogen cost | No cost figures in the evidence. |
| CHM-T1 | Green/blue hydrogen availability for ammonia and feedstock use | CN | L | not rated: missing Low-carbon hydrogen cost and Grey hydrogen cost | Evidence says the gap 'remains wide', no numbers. The grey reference is gas-based, but China's grey route is mostly coal, which makes China's gap look smaller than it is. |
| CHM-T2 | Electrification of process heat (steam cracking) readiness | EU | M | M | TRL 6-7 is at least 5; demonstration scale, so commercial is No. |
| CHM-T2 | Electrification of process heat (steam cracking) readiness | US | L | not rated: missing Electric cracking readiness in the region (TRL) | Evidence only says there is no commercial-scale pilot. If no unit exists at all, TRL is 0 and the result is L. |
| CHM-T2 | Electrification of process heat (steam cracking) readiness | CN | L | not rated: missing Electric cracking readiness in the region (TRL) | Same as US: if no unit exists, L. |
| CHM-R1 | Effective carbon price on chemicals production incl. border adjustment | EU | M | not rated: missing Carbon price on chemicals | No figure. H is false either way (levy No: CBAM covers ammonia but not organic chemicals). At EUR 60-90 the result would be M. |
| CHM-R1 | Effective carbon price on chemicals production incl. border adjustment | US | L | L | Applies is No. |
| CHM-R1 | Effective carbon price on chemicals production incl. border adjustment | CN | L | L | Applies is No (chemicals not covered by the national ETS). |
| CHM-D1 | Green ammonia/methanol offtake market | EU | M | not rated: open threshold Material offtake volume | Premium is also missing; H needs the open volume. |
| CHM-D1 | Green ammonia/methanol offtake market | US | L | not rated: missing Binding green ammonia or methanol offtake signed | Evidence describes 'offtake activity at a smaller scale', which suggests some binding agreements. If one exists the rules give M (today L). |
| CHM-D1 | Green ammonia/methanol offtake market | CN | L | not rated: missing Binding green ammonia or methanol offtake signed | 'No material market' does not say none exists. By hand: L if there are none. |

### Critical Minerals & Mining

| Code | Criterion | Region | Current | Under v1 rules | Reason |
|---|---|---|---|---|---|
| MIN-T1 | Mine electrification and processing technology readiness | EU | M | M | Pilots only. |
| MIN-T1 | Mine electrification and processing technology readiness | US | M | not rated: open threshold At-scale battery-electric order share | Evidence says 'a small number of operating mines ... at scale', so more than one mine reads Yes and H depends on the open order share. Low confidence: the same evidence also says 'similar pilot-stage' to the EU. |
| MIN-T1 | Mine electrification and processing technology readiness | CN | M | not rated: missing Battery-electric equipment in production at more than one mine | Deployment 'uneven', count unknown; deployed is Yes, so M at least. |
| MIN-R1 | Fast-track permitting regime for strategic minerals projects | EU | H | H | Statutory regime, 27 months, below 30 (counted without the Art. 11(4) six-month extension). |
| MIN-R1 | Fast-track permitting regime for strategic minerals projects | US | M | M | FAST-41 and executive prioritisation, no statutory maximum: discretionary. |
| MIN-R1 | Fast-track permitting regime for strategic minerals projects | CN | H | not rated: missing Standard permitting time | H is not possible: no statutory fast-track with a maximum timeline in the evidence. If the state-directed process counts as a priority process: M; if not, M depends on whether standard permitting takes 5 years or less. Low confidence. |
| MIN-R2 | Domestic sourcing / content requirement policy | EU | H | M (changed) | CRMA Art. 5 sets capacity benchmarks; nothing ties them to a subsidy or procurement award, so rule = other (M), not binding (H). The evidence's word 'binding' is not supported by the text. |
| MIN-R2 | Domestic sourcing / content requirement policy | US | M | M | 30D terminated; the residual 45X effect is not a content condition per the evidence, so other. If the OBBBA prohibited-foreign-entity rules for 45X count as binding, the cell becomes not re-derived (open thresholds). |
| MIN-R2 | Domestic sourcing / content requirement policy | CN | M | L (changed) | The evidence names only export controls, which are not a content requirement under the definition. The evidence itself calls them structurally different from an inbound content requirement. |
| MIN-D1 | Committed offtake and supply agreements vs. identified demand gap | EU | L | not rated: open threshold Material share of the supply gap / Minimal share of the supply gap | Figures also missing. |
| MIN-D1 | Committed offtake and supply agreements vs. identified demand gap | US | M | not rated: open threshold Material share of the supply gap / Minimal share of the supply gap | Figures also missing. |
| MIN-D1 | Committed offtake and supply agreements vs. identified demand gap | CN | H | not rated: missing No projected lithium supply gap, Share of lithium supply gap covered | 'Large share of its own demand' is not a 2030 NZE figure. By hand: H if no gap holds. |

### Aviation

| Code | Criterion | Region | Current | Under v1 rules | Reason |
|---|---|---|---|---|---|
| AVI-T1 | SAF production capacity vs. jet fuel demand | EU | L | not rated: missing SAF production capacity and Jet fuel demand | 'Well below 5%' rules out H; whether it is at least 1% is unknown. |
| AVI-T1 | SAF production capacity vs. jet fuel demand | US | L | M (changed) | Evidence says 'a small single-digit percentage', which is at least 1% and below 5%. Today's L (below 1%) contradicts its own rubric. |
| AVI-T1 | SAF production capacity vs. jet fuel demand | CN | L | not rated: missing SAF production capacity and Jet fuel demand | No figures in the evidence. |
| AVI-R1 | SAF blending mandate | EU | H | H |  |
| AVI-R1 | SAF blending mandate | US | M | not rated: missing SAF blending mandate (status) | Evidence names only the tax credit and 'no federal blending requirement'. By hand M through the SAF Grand Challenge volume goal; if that goal no longer stands, L. |
| AVI-R1 | SAF blending mandate | CN | L | L | No mandate; CORSIA is excluded. Flag: trade press reports a non-binding 14th Five-Year Plan SAF consumption target (cumulative 50,000 t by 2025), not checked against the CAAC text. If confirmed: M. |
| AVI-D1 | SAF price premium and corporate offtake coverage | EU | M | not rated: open threshold Substantial offset share / Material offtake share | M holds at least (offset mechanism in force); H needs the open shares. EU prices quoted in EUR/t do not count until the jet fuel density is settled. |
| AVI-D1 | SAF price premium and corporate offtake coverage | US | M | not rated: open threshold Substantial offset share / Material offtake share | M holds at least; H needs the open shares. USD/gallon prices convert through the NIST gallon row. |
| AVI-D1 | SAF price premium and corporate offtake coverage | CN | L | not rated: missing SAF price premium and SAF offtake signed | 'No material ... identified' does not mean none exists. By hand: L. |

### Shipping

| Code | Criterion | Region | Current | Under v1 rules | Reason |
|---|---|---|---|---|---|
| SHP-T1 | Dual-fuel/alternative-fuel vessel order book | EU | M | not rated: missing Alternative-fuel-capable share of new orders | Evidence gives the EU's share of the global order book, a different denominator. |
| SHP-T1 | Dual-fuel/alternative-fuel vessel order book | US | L | not rated: missing Alternative-fuel-capable share of new orders | Same denominator problem as EU. |
| SHP-T1 | Dual-fuel/alternative-fuel vessel order book | CN | M | not rated: missing Alternative-fuel-capable share of new orders | Evidence describes Chinese shipyards building for foreign owners, not orders by Chinese owners. |
| SHP-R1 | Effective carbon price / fuel intensity mandate on shipping | EU | H | H | ETS maritime in force; FuelEU applies from 1 January 2025. |
| SHP-R1 | Effective carbon price / fuel intensity mandate on shipping | US | L | L |  |
| SHP-R1 | Effective carbon price / fuel intensity mandate on shipping | CN | L | L | The Shanghai pilot ETS is sub-national and excluded; the IMO Net-Zero Framework is not in force. If the pilot counted: M. |
| SHP-D1 | Green shipping corridor and cargo owner offtake commitments | EU | M | not rated: missing Corridors with committed cargo and a premium mechanism | 'Committed but still limited cargo volumes' reads as a signed commitment, so M at least. |
| SHP-D1 | Green shipping corridor and cargo owner offtake commitments | US | M | not rated: missing Corridor with signed cargo commitment and Corridors with committed cargo and a premium mechanism | 'Committed cargo volume remains at an early stage' does not say whether a signed commitment exists, so L, M and H all remain possible. |
| SHP-D1 | Green shipping corridor and cargo owner offtake commitments | CN | M | not rated: missing Corridors with committed cargo and a premium mechanism | 'Binding cargo commitments remain limited' implies some exist, so M at least (low confidence). |

### Heavy-Duty Road Transport

| Code | Criterion | Region | Current | Under v1 rules | Reason |
|---|---|---|---|---|---|
| HDT-T1 | Battery-electric/fuel-cell truck TCO parity | EU | M | not rated: missing Zero-emission truck TCO and Diesel truck TCO | Words, no numbers: 'parity being reached for regional ... in several markets'. By hand: H or M. |
| HDT-T1 | Battery-electric/fuel-cell truck TCO parity | US | M | not rated: missing Zero-emission truck TCO and Diesel truck TCO | 'Approaching parity'. By hand: M. |
| HDT-T1 | Battery-electric/fuel-cell truck TCO parity | CN | H | not rated: missing Zero-emission truck TCO and Diesel truck TCO | 'Parity or better'. By hand: H. |
| HDT-R1 | Zero-emission heavy vehicle sales mandate or CO2 standard | EU | H | not rated: missing Required ZEV share of new heavy truck sales in 2030 | No implied ZEV share in the evidence; M at least. |
| HDT-R1 | Zero-emission heavy vehicle sales mandate or CO2 standard | US | M | not rated: missing Required ZEV share of new heavy truck sales in 2030 | M at least on today's evidence. Reversal outside the evidence: EPA repealed all heavy-duty GHG standards (91 FR 7686, effective 20 April 2026) and Congress disapproved the California ACT waiver (P.L. 119-15), so with current facts status is none and the result is L. |
| HDT-R1 | Zero-emission heavy vehicle sales mandate or CO2 standard | CN | M | not rated: missing Penalties for missing the standard and Required ZEV share of new heavy truck sales in 2030 | M at least. Low confidence: the evidence says the NEV credit system extends to commercial vehicles, which was not verified; heavy-duty fuel-consumption limits would count as a standard. |
| HDT-D1 | Charging/refuelling infrastructure density on freight corridors | EU | M | not rated: missing Heavy-duty charging and refuelling density on primary freight corridors | M is also blocked by the open 'Density above minimal'. |
| HDT-D1 | Charging/refuelling infrastructure density on freight corridors | US | L | not rated: missing Heavy-duty charging and refuelling density on primary freight corridors | M is also blocked by the open 'Density above minimal'. |
| HDT-D1 | Charging/refuelling infrastructure density on freight corridors | CN | M | not rated: missing Heavy-duty charging and refuelling density on primary freight corridors | M is also blocked by the open 'Density above minimal'. |

### Oil & Gas Upstream

| Code | Criterion | Region | Current | Under v1 rules | Reason |
|---|---|---|---|---|---|
| OGU-T1 | Methane abatement technology deployment | EU | H | not rated: missing Production covered by LDAR and flaring reduction | Evidence is about North Sea producers, many outside the EU-27. |
| OGU-T1 | Methane abatement technology deployment | US | M | not rated: missing Production covered by LDAR and flaring reduction | Deployed at major operators is unclear ('uneven across operators'). |
| OGU-T1 | Methane abatement technology deployment | CN | L | not rated: missing Production covered by LDAR and flaring reduction | No figures in the evidence. |
| OGU-R1 | Methane regulation and fee structure | EU | H | H | LDAR applies to existing sites from 2025, routine flaring is prohibited (Art. 15), penalties under Art. 33. |
| OGU-R1 | Methane regulation and fee structure | US | L | M (changed) | Under the rule as written: OOOOb/OOOOc standards count as limits, apply to new and modified sources, and their deadlines were extended in 2025, so phase-in (M). The Waste Emissions Charge does not count. By owner reading: (a) as written, M; (b) new-source limits count as in force, H; (c) fee-only, L (today's reading). See Decisions for the owner. |
| OGU-R1 | Methane regulation and fee structure | CN | L | L | A non-binding action plan counts as none. |
| OGU-D1 | Market demand trajectory / structural decline exposure | EU | L | not rated: open threshold Largest decline still stable / Decline short of structural | Figures also missing. By hand: L. |
| OGU-D1 | Market demand trajectory / structural decline exposure | US | M | not rated: open threshold Largest decline still stable / Decline short of structural | Figures also missing. By hand: M. |
| OGU-D1 | Market demand trajectory / structural decline exposure | CN | M | not rated: open threshold Largest decline still stable / Decline short of structural | Figures also missing. By hand: M or H. |

## Decisions for the owner

**Across criteria**

- Rubric-sourced thresholds: 17 numbers come from today's rubric with no external benchmark (cited to the framework at commit 2e97f40); confirm or replace each: PWR-T1 `p_within` (1.3); PWR-R1 `p_material` (15); PWR-R2 `p_slow` (7); STL-T1 `p_within` (2); STL-T2 `p_high` (50); STL-T2 `p_low` (25); CHM-T1 `p_within` (1.2); CHM-T1 `p_double` (2); CHM-T2 `p_trl_high` (7); CHM-T2 `p_trl_mid` (5); MIN-R1 `p_fast` (30); MIN-R1 `p_slow` (60); AVI-T1 `p_high` (5); AVI-T1 `p_low` (1); SHP-T1 `p_high` (30); SHP-T1 `p_low` (10); HDT-T1 `p_within` (1.2).
- Version 1 is signed with `approved_by` = `pending-owner-approval`; approving it in this PR needs one re-sign if any value above or any open threshold changes.
- Exchange rates: CNY and EUR to USD use Federal Reserve G.5A annual averages for 2023-2025. Volume and length rows (gallon, barrel, mile) carry year 1959, the year the units became exact, so they cover every as-of date.
- Source tiers (from task 6.0): IEA_CCUS_Projects_Database primary (its URL pointed at co2re.co until the registry clean-up and now points at the IEA's own CCUS Projects Database page); OGMP 2.0 reporting primary (UNEP-run, company-reported data); EU and China ETS price feeds secondary (exchange data, not regulator publications). Other judgement calls: ICC code register, First Movers Coalition, EVCIPA charging statistics, RE100, Mission Possible and IATA entries secondary; Congress.gov permitting tracker primary.

**PWR-T1**

- M spans parity to 30% above (the rubric's '10-30%' left 0-10% in no level), so the rubric's 10% is dropped. Affects no cell today.

**PWR-T2**

- `p_curtail` 5% is a Chinese policy target (NDRC/NEA 2018-2020) applied to the EU and US because no EU or US benchmark was found: confirm or add sourced overrides. Storage duration (GWh) and long-duration-storage readiness are not captured. Moves PWR-T2 EU, US, CN (all open anyway).

**PWR-R1**

- `p_material` 15 is PWR-R1's own rubric line; STL-R1, CEM-R1 and CHM-R1 use 33.92 (OECD Effective Carbon Rates 2021, EUR 30 at 1.1306). The two 'material' lines disagree and the OECD benchmark describes the 2010s at 2025 exchange rates: use one value everywhere, or keep both. Moves no cell today (China's price is USD 9-14 against either).
- H requires `scope` = region_wide because the price fact averages over covered emissions only; without it a high state price would rate the whole region H. Alternative: drop the condition. Moves PWR-R1 US if state prices were high.

**PWR-R2**

- The rubric's L says 'no binding target' but M says 'binding or aspirational'; M's wording is used, so an aspirational target can be M. Alternative: require binding for M. Moves PWR-R2 US if connection time is at most 7 years.

**STL-R1, CEM-R1, CHM-R1**

- 'Net of free allocation' is read as a free-allocation phase-out written into law plus the gross price, not price times paid share. Alternative: a literal net price, which would put the EU (free allocation about 97.5% of benchmark in 2026) at M or lower. Moves STL-R1 EU, CEM-R1 EU, CHM-R1 EU (current H, H, M; all three not rated under v1).
- CEM-R1 US: California cap-and-trade covers in-state cement, but the fact reads federal coverage. Alternative: a sub-national scope. Would move CEM-R1 US from L.
- CHM-R1: the levy and phase-out count only if they cover both ammonia and steam-cracker products; CBAM covers ammonia but not organic chemicals, so EU levy is No. Alternative: either product counts. Moves CHM-R1 EU (H becomes possible).

**STL-T1, STL-T2, CEM-T2**

- STL-T1 `p_within` 2 (framework-only; the rubric gives no source for where M and L sit). Moves STL-T1 EU, US, CN once figures exist.
- CEM-T2 `p_high` 0.80 cites a manufacturer page (Buzzi Unicem) for the EN 197-1 clinker bound; `p_low` 0.65 is from the IEA roadmap, read from a search-engine copy because iea.org returns 403. Moves CEM-T2 EU, US, CN once ratios exist.

**STL-R2, STL-D1, CEM-D1**

- STL-R2 US and CEM-D1 US: today's evidence treats federal Buy Clean as binding; it was rescinded in January 2025. With current facts both read voluntary_or_pilot, giving M; shown as open-threshold cells because of the stale reading.
- CEM-D1 `coverage` is binding demand as a share of announced low-carbon cement capacity (not of construction demand); alternative: a construction-demand denominator as in STL-R2. Moves CEM-D1 US.

**CEM-T1**

- `p_full_scale` changed from the rubric's 0.3 to 0.4 Mtpa (Global CCS Institute large-scale line for non-power industry), tested with >= so Brevik (about 0.4 Mtpa) counts; the cited copy is a POLITICO map (a news outlet), with an Imperial deck as backup. Alternative: keep 0.3. Moves CEM-T1 EU only if Brevik were just under 0.4.
- US evidence is stale: DOE cancelled the Heidelberg Mitchell award in May 2025.

**CHM-T1**

- Costs are before subsidies (as STL-T1), and the grey reference is gas-based SMR as the metric says; China's grey route is mostly coal, so China's gap looks smaller than it is. Alternatives: after-subsidy costs, or a coal grey reference for China. Moves CHM-T1 CN.

**CHM-T2**

- TRL is regional (the most advanced unit built in the region). Alternative: global TRL, which reads 6-7 for US and China and would rate both M. Moves CHM-T2 US, CN.

**CHM-D1**

- Open `p_material` (annual offtake volume). Candidates: one commercial plant's output, or a share of the fuel needed for the IMO 2030 ambition (5%, striving for 10%). Moves CHM-D1 EU.

**MIN-T1**

- 'Multiple mines' is read as more than one; H adds an open order-share threshold. The US reading (a small number of mines 'at scale') is low confidence because the same evidence says 'pilot-stage'. Moves MIN-T1 US between M and H.

**MIN-R1**

- The CRMA limit is counted at its standard 27 months, without the Art. 11(4) extension of up to six months (33 months would give EU M). Moves MIN-R1 EU H to M.
- The rubric's L clause (standard permitting over 5 years) is tested as `p_slow` = 60 months. China's cell depends on it.

**MIN-R2**

- CRMA Art. 5 benchmarks, targets and non-conditional rules map to `other` (M). Alternative: 'Requirement exists' means tied to subsidy or procurement, so they are L. Moves MIN-R2 EU from M to L.
- US: if OBBBA prohibited-foreign-entity rules for 45X count as binding, the cell becomes open-threshold. Moves MIN-R2 US.
- Export controls are not a content requirement (China L). Alternative: count them. Moves MIN-R2 CN L to M.

**MIN-D1**

- Lithium is the reference mineral (tonnes of different minerals cannot be added); alternative: one criterion per mineral or another mineral. Regional IEA NZE demand could not be confirmed, so `gap` may often not count. Moves MIN-D1 EU, US, CN.

**AVI-T1, AVI-D1**

- Jet fuel density (tonne to litre) is open: ASTM D1655 allows 775-840 kg/m3 at 15 C, verified only on a vendor sheet (Petrostar), not the paywalled standard. Without a density row, tonne figures do not count. Moves AVI-T1 EU and AVI-D1 EU prices quoted in EUR/t.
- AVI-D1: the offset excludes avoided mandate fines (counting them would make any mandate 'fully offset'); multi-year contracts are annualised as total divided by contract years. Moves AVI-D1 EU, US.

**AVI-R1**

- US: M rests on the SAF Grand Challenge volume goal; if it no longer stands, L. China: trade press reports a non-binding 14th Five-Year Plan SAF target (50,000 t cumulative by 2025), not checked against the CAAC text; if confirmed, AVI-R1 CN L becomes M. Sub-national rules count as announced_or_voluntary.

**SHP-T1**

- All vessel classes combined (alternative: the class with the most ordered GT); owners assigned by domicile (alternative: flag or yard, which would make China's yard evidence relevant); LNG included, hydrogen and battery excluded. Moves SHP-T1 CN, EU.

**SHP-R1**

- Sub-national schemes are excluded; if the Shanghai pilot ETS counted, SHP-R1 CN would be M. The IMO Net-Zero Framework is not adopted (vote adjourned October 2025); entry into force 1 March 2028 at the earliest per DNV.

**SHP-D1**

- H tests whether committed volume exists, not how large it is; an announced corridor without a signed commitment is L. 'Active' means GMF-listed. 'Main ports' is defined in words, with no top-N number. Alternative: open volume or port-count thresholds. Moves SHP-D1 EU, US, CN.
- Minor style gap: `p_multiple` is a numeric threshold of 1 while MIN-T1 uses a boolean 'more than one'.

**HDT-T1**

- TCO is net of purchase incentives (PWR-T1 uses unsubsidised costs); fuel-cell trucks count where cheaper, though the metric names battery-electric only. Moves HDT-T1 EU, US, CN.

**HDT-R1**

- 30% ZEV share by 2030 (Global MOU on ZE-MHDVs) is the single 'material' line for all regions; the MOU covers vehicles over 3.5 t including buses and is non-binding. Alternative: a regional value. Moves HDT-R1 EU between H and M once its required share is known.
- Fuel-consumption limits count as a CO2 standard; enforceable state rules are capped at announced (M); an unenforceable state rule counts as none. Alternative: let state rules reach H.
- China: the evidence says the NEV credit system extends to commercial vehicles; not verified (the dual-credit policy is believed to cover passenger cars).
- US evidence is out of date: EPA repealed all heavy-duty GHG standards (91 FR 7686, 18 February 2026, effective 20 April 2026) and Congress disapproved the California ACT waiver (P.L. 119-15, 12 June 2025). With current facts HDT-R1 US is L.

**HDT-D1**

- `p_sufficient` 3.33 points per 100 km per direction is derived from AFIR Art. 4(1)(c) (two 350 kW points per 60 km = 3.333, rounded down deliberately); alternative: a maximum-gap fact compared with 60 km. Hydrogen points share the density with charging points although the threshold comes from charging only. Open `p_minimal`. Moves HDT-D1 EU, US, CN.

**OGU-T1**

- Production is counted by site location, not operator domicile; 'major operators' is defined in words, not by a production-share number (alternative: an open threshold). Moves OGU-T1 EU, US.

**OGU-R1**

- US three-way reading. (a) Performance standards count as limits and 'in force' needs existing operations (as written): US M, EU H. (b) A limit on new and modified sources counts as in force: US H, EU H. (c) Fee or price only (today's reading): US L, and the EU's H, which rests on limits, would need re-justifying (EU L unless re-justified). The rubric's 'limit and/or fee' supports counting limits. Moves OGU-R1 US (L, M, H) and possibly EU.
- The Waste Emissions Charge does not count: P.L. 119-2 nullified the rule and P.L. 119-21 section 60012(b) moved the charge to calendar year 2034.

**OGU-D1**

- Both thresholds are open: the rubric's M ('flat') overlaps H ('stable'), and 'structural decline' has no number. Inverted reading kept (H = lower stranding risk). Moves OGU-D1 EU, US, CN.

**Evidence that is out of date (not a rule issue)**

- US Buy Clean (EO 14057) rescinded January 2025: STL-R2 US, CEM-D1 US.
- DOE cement CCS awards cancelled May 2025 (Heidelberg Mitchell): CEM-T1 US.
- EPA heavy-duty GHG repeal (91 FR 7686, effective 20 April 2026) and California ACT waiver revoked (P.L. 119-15): HDT-R1 US.
- Waste Emissions Charge: nullified (P.L. 119-2), charge delayed to 2034 (P.L. 119-21 section 60012(b)): OGU-R1 US.
- MIN-R2 US: 30D terminated by OBBBA, already reflected in the current rating.

## Open thresholds

17 parameters have no value in v1. Each stays open until the owner names a number and a source.

| Criterion | Label | Question |
|---|---|---|
| PWR-T2 | Non-negligible storage share | Above what storage share of solar plus wind capacity (%, measured in power: storage GW over solar plus wind GW) is grid-scale storage no longer 'negligible'? The rubric points to a region-specific benchmark informed by IEA grid-integration studies, but no such number was found (IEA pages could not be fetched). |
| PWR-D1 | PPA share of an established market | What PPA volume, as a share of the region's annual solar and wind additions, marks an established market where multi-year contracting is standard practice? No citable benchmark was found (the registered BloombergNEF data is subscription-only). |
| PWR-D1 | PPA share above negligible | Below what PPA share of annual solar and wind additions is the PPA market 'negligible', with renewables sold predominantly on spot or merchant terms? No citable benchmark was found. |
| STL-R2 | Material share of construction demand | What share of the region's construction demand for steel must a binding rule cover to count as 'a material share'? No sourced benchmark was found; a source for the coverage figure itself (e.g. the public-procurement share of construction steel use) is also needed. |
| STL-D1 | Material offtake share | What share of announced low-carbon steel capacity must be covered by signed offtake contracts to count as 'a material share'? A benchmark could come from project-finance practice (the share of output lenders require under contract), but no citable source was found. |
| CEM-D1 | Material share of low-carbon capacity | What share of the region's announced low-carbon cement capacity must demand created by binding procurement rules or embodied-carbon codes cover to count as 'a material share'? No sourced benchmark was found; a source for estimating the binding demand volume (tonnes of low-carbon cement the rules require per year) is also needed. |
| CHM-D1 | Material offtake volume | Above what annual signed volume (t/yr) is green ammonia and methanol offtake 'material' for a region? No sourced line was found. Candidates for the owner: the annual output of one commercial-scale plant, or a share of the fuel needed for the IMO 2023 GHG Strategy's 2030 ambition (zero or near-zero GHG fuels at least 5%, striving for 10%, of the energy used by international shipping), converted to tonnes per region. |
| MIN-T1 | At-scale battery-electric order share | What battery-electric share of new mining equipment orders marks deployment 'at scale' (rubric H, 'commercially deployed at scale (multiple operating mines)')? No sourced line was found; without it any two mines with production units would rate H. |
| MIN-R2 | Low content threshold | Below what required domestic or allied content share is a binding requirement's threshold 'low' (rubric M)? No sourced line was found. |
| MIN-R2 | Material subsidy value | Above what annual subsidy or procurement value tied to the requirement (USD million per year) is the subsidy 'material' (rubric H)? No sourced line was found; a measure relative to the region's size (for example to its annual critical-mineral imports) may fit better than an absolute amount, which would change the fact. |
| MIN-D1 | Material share of the supply gap | What share of the region's projected 2030 lithium supply gap must signed offtakes and committed capacity cover to count as 'a material share' (rubric H)? No sourced line was found. Also: is lithium the right reference mineral, or should the owner name another or one criterion per mineral? |
| MIN-D1 | Minimal share of the supply gap | Below what share of the projected 2030 lithium supply gap is offtake activity 'minimal' (rubric L) rather than 'some offtake agreements signed but gap remains largely uncovered' (rubric M)? No sourced line was found. |
| AVI-D1 | Substantial offset share | What share of the SAF price premium must offsets cover for the premium to be 'substantially offset' (rubric H)? No sourced line was found. |
| AVI-D1 | Material offtake share | What share of the region's jet fuel demand must signed SAF offtakes cover to be 'material offtake agreements' (rubric H)? No sourced line was found; one candidate is the region's mandated SAF share (ReFuelEU Aviation: 2% from 2025), which would need a by-region value. |
| HDT-D1 | Density above minimal | Below what density of public heavy-duty charging and hydrogen refuelling points per 100 km of primary freight corridor is the infrastructure 'minimal' (rubric L), restricting operation to depot-based captive fleets? No sourced line was found. AFIR's first milestone (Article 4(1)(a): by 31 December 2025, pools with at least one 350 kW point along at least 15% of the TEN-T network length in each direction) is a coverage share, not a density. |
| OGU-D1 | Largest decline still stable | What is the largest fall in combined oil and gas demand to 2035 under stated policies that still counts as 'stable' (rubric H: stable or growing)? The rubric's M ('flat to moderate decline') overlaps H ('stable'), so the line needs a number; no sourced line was found. A line at 0% would make H mean no decline. |
| OGU-D1 | Decline short of structural | What fall in combined oil and gas demand to 2035 under stated policies marks a 'structural decline' (rubric L) rather than a 'moderate decline' (rubric M)? No sourced line was found. |

## Registry errors found

Errors in source locators and URLs found while checking the primary texts. The registry clean-up in this PR fixed the first six; the list of fixes that touch sources these notes rely on follows the list.

- MIN-R1 and MIN-R2 (CRMA, Regulation (EU) 2024/1252): the locator says 'Article 12: 27-month target'. The limit is in Article 11 (11(1)(a) 27 months; 11(3) excludes the EIA step; 11(4) allows an extension of at most six months). The same locator puts the 2030 benchmarks in 'Article 3'; the verified text has them in Article 5(1).
- HDT-D1 (AFIR, Regulation (EU) 2023/1804): the locator says 'Article 3 for TEN-T road network charging'. The heavy-duty targets are in Article 4 (Article 3 is light-duty).
- OGU-R1 (US Waste Emissions Charge): the locator attributes 'EPA barred from collecting the charge until 2034' to the Congressional Review Act resolution. P.L. 119-2 only nullified the 2024 implementing rule; the 2034 delay is P.L. 119-21 section 60012(b), which replaces 'calendar year 2024' with 'calendar year 2034' in Clean Air Act section 136(g).
- CEM-T1: `IEA_CCUS_Projects_Database` pointed at co2re.co, the Global CCS Institute's site (copy-pasted from `Global_CCS_Institute_CO2RE_database`). Re-sourced to the IEA's CCUS Projects Database page; tiered primary on the publisher's name.
- `US_SAF_Grand_Challenge_IRA_40B_tax_credit` pointed at sustainability.gov/buyclean, the Buy Clean entry's URL, with the Buy Clean locator. Re-sourced to the SAF Grand Challenge Roadmap (DOE, September 2022).
- Two company-disclosure registry rows had url null where the criteria schema had a url (STL-D1 and CEM-D1 company investor disclosures). The schema now has null too, and both are marked manual.
- Could not be fetched, so not verified (not errors): iea.org returns 403 to every client (the IEA figure for CEM-T2 was read from a search-engine copy); the OECD Effective Carbon Rates 2021 component-6 page returns 403, so the brochure PDF is cited instead.

Registry clean-up fixes that touch sources these notes rely on:

- MIN-R1, MIN-R2: both CRMA locators now cite Article 5(1) for the benchmarks and Article 11 (11(1)(a), 11(3), 11(4)) for the permitting limit.
- HDT-D1: the AFIR locator now cites Article 4 for heavy-duty charging.
- OGU-R1 US: the Waste Emissions Charge locator now attributes the 2034 delay to P.L. 119-21 section 60012(b) and the nullified rule to P.L. 119-2 (EPA notice 90 FR 21225).
- STL-R1 CN, CEM-R1 CN, PWR-R1 CN: added the ICAP China National ETS factsheet (all three), the IEEFA ETS reforms report of 3 November 2025 (STL-R1, CEM-R1) and the Transition Asia brief (STL-R1); `China_national_ETS_sector_coverage_roadmap` now points at the MEE allocation plan of 18 November 2025 and also backs CEM-R1. The 890 yuan/t figure the STL-R1 CN reason relies on is in Transition Asia's March 2025 brief; the evidence text dates it September 2025.
- AVI-R1 US: the registry source is now the SAF Grand Challenge Roadmap, which states the 3 billion gallon (2030) volume goal the M reading rests on.
- HDT-R1 US: the EPA Phase 3 source now points at the final rule (89 FR 29440) and its locator records the repeal (91 FR 7686, effective 20 April 2026).
- HDT-R1 CN: the MIIT source now points at the 2020 amendment of the dual-credit measures, which cover passenger cars (乘用车) only; the evidence's claim that the NEV credit system extends to commercial vehicles is not in that text.
- STL-R2 US: the Buy Clean source now points at the Biden-era progress report, and its locator records that EO 14057 was rescinded in January 2025.
- PWR-R2 EU: the renewable-target source now points at Directive (EU) 2023/2413 (42.5% target), not the 2018 text.
