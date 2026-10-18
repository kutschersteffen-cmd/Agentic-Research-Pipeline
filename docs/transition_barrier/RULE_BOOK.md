# Transition barrier rule book

Rule book version 1.

# Power & Utilities

## PWR-T1 Levelised cost of renewable generation vs. new-build fossil

New solar PV and onshore wind (pwr.renewables) win new capacity on their own only where they are the cheapest new-build option without subsidies that can be withdrawn. Where their cost sits well above new-build gas or coal, build-out depends on support schemes, and retiring fossil plants (pwr.coal_exit) lacks a cheaper replacement.

**Actions**

- Utility-scale solar PV and onshore wind build-out
- Retirement of unabated coal and gas generation

**Facts**

- Renewable LCOE: Unsubsidised levelised cost of electricity of new utility-scale solar PV or onshore wind in the region, whichever is lower, for projects commissioned in the latest year reported (regional weighted average or central estimate), before tax credits, feed-in premiums or other support.
- New-build fossil LCOE: Levelised cost of electricity of a new-build gas combined-cycle or coal plant in the region, whichever is lower, for the same year and preferably from the same source as the renewable figure; includes a carbon price only where that source's estimate does.
- Subsidised renewable LCOE: The renewable LCOE above after the production or investment support available to new projects in the same year (for example US production tax credits or contract-for-difference support).
- Renewable-to-fossil LCOE ratio: Unsubsidised renewable LCOE divided by new-build fossil LCOE: 1 is parity, 1.3 means renewables cost 30% more.

**Rating**

- H: Renewable LCOE <= New-build fossil LCOE.
- M: Renewable-to-fossil LCOE ratio <= 1.3 or Subsidised renewable LCOE <= New-build fossil LCOE.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_within` Close cost gap | 1.3 |  |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), PWR-T1 rating_rubric.M: 'within 10-30% of new-build fossil LCOE'; L: 'more than 30% above' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric draws the M/L line at renewables costing 30% more than new-build fossil. No external benchmark for that line was found, so the framework value is carried over. M covers the whole range from parity up to 30% above; the rubric's '10-30%' left a gap from 0 to 10% that belonged to no level. |

## PWR-T2 Grid-scale storage / firming technology readiness

Solar and wind growth (pwr.renewables) stalls once output is regularly curtailed, because curtailed energy earns nothing and lowers the return on the next project. Grid-scale storage (pwr.storage) and grid reinforcement (pwr.grid) absorb variable output; where storage is negligible next to wind and solar capacity, further build-out runs into curtailment and congestion. The rule measures storage in power (GW), so storage duration (GWh) and the readiness of long-duration storage are not captured.

**Actions**

- Grid-scale battery and long-duration storage
- Transmission and grid-connection expansion
- Utility-scale solar PV and onshore wind build-out

**Facts**

- Grid-scale storage power capacity: Installed grid-scale battery storage power capacity in operation in the region at the end of the latest year reported (utility-scale; excludes behind-the-meter batteries and pumped hydro).
- Variable renewable capacity: Installed solar PV plus wind capacity in operation in the region at the end of the same year.
- Storage share of variable renewable capacity: Grid-scale storage power capacity as a percentage of solar plus wind capacity. Measured in power (GW over GW) rather than the metric's GWh per GW so both inputs share a unit.
- Wind and solar curtailment rate: Share of potential wind and solar generation in the region that was curtailed (dispatched down for grid constraints, congestion or oversupply, including redispatch) over the latest full year.

**Rating**

- H: Wind and solar curtailment rate <= 5% and Storage share of variable renewable capacity >= [open: Non-negligible storage share].
- M: Storage share of variable renewable capacity >= [open: Non-negligible storage share].
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_curtail` Material curtailment rate | 5 | % |  | NDRC and NEA, Clean Energy Consumption Action Plan (2018–2020) (发改能源规〔2018〕1575号), ESCAP Asia Pacific Energy Portal record, 2020 targets: solar utilisation above 95% (curtailment below 5%); wind about 95% (curtailment about 5%) <https://policy.asiapacificenergy.org/node/4123> | The rubric's H requires flexibility 'sufficient to avoid material curtailment' without a number. China's 2018–2020 action plan set 5% as the ceiling for acceptable wind and solar curtailment (95% utilisation), the only official numeric curtailment benchmark found. It is a Chinese policy target, applied here to the EU and the US as well because no EU or US benchmark was found; owner to confirm or add sourced overrides. |
| `p_storage_material` Non-negligible storage share | open |  |  |  | Open question: Above what storage share of solar plus wind capacity (%, measured in power: storage GW over solar plus wind GW) is grid-scale storage no longer 'negligible'? The rubric points to a region-specific benchmark informed by IEA grid-integration studies, but no such number was found (IEA pages could not be fetched). |

## PWR-R1 Effective carbon price on power generation

A carbon price on power emissions, or a binding clean-power mandate with a penalty, makes fossil plants pay for their emissions, which speeds coal and gas retirement (pwr.coal_exit) and raises the value of the renewables (pwr.renewables) and storage (pwr.storage) that replace them. Without either, fossil generation keeps its cost advantage at the margin. H also requires the price to cover the whole region: where only some states or provinces price carbon, the price fact averages over covered emissions only, so a high state price would otherwise rate the whole region H.

**Actions**

- Retirement of unabated coal and gas generation
- Utility-scale solar PV and onshore wind build-out
- Grid-scale battery and long-duration storage

**Facts**

- Effective carbon price on power: Average price per tonne CO2 over the latest full calendar year of the explicit carbon price (ETS allowance price or carbon tax rate) that covers the largest share of the region's power-sector emissions; where only state or provincial instruments apply, their average weighted by covered power emissions. Gross of free allocation; implicit prices from mandates are not included. Zero where none applies.
- Carbon price coverage: region_wide: the carbon price covers power generation across the whole region (EU-wide, federal or national); sub_regional: only in some states or provinces; none: no explicit carbon price on power.
- Clean generation mandate: binding_100pct_with_penalty: a region-wide legal requirement for 100% clean or renewable electricity by a set date, enforced by a financial penalty on non-compliant utilities or generators; other_target: any other clean or renewable generation target (below 100%, without a penalty, or only in some states or provinces); none: no such target.

**Rating**

- H: (Effective carbon price on power > 60 USD/tCO2 and Carbon price coverage = region_wide) or Clean generation mandate = binding_100pct_with_penalty.
- M: Effective carbon price on power >= 15 USD/tCO2 or Clean generation mandate = other_target.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_high` High carbon price level | 60 | USD/tCO2 |  | Report of the High-Level Commission on Carbon Prices (Carbon Pricing Leadership Coalition / World Bank, 2017), Executive Summary, PDF p. 10: 'at least US$40–80/tCO2 by 2020 and US$50–100/tCO2 by 2030' (midpoint of 40–80) <https://business.columbia.edu/sites/default/files-efs/imce-uploads/Joseph_Stiglitz/CarbonPricing_FullReport.pdf> | Today's rubric sets H at above USD 60/tCO2: the midpoint of the High-Level Commission's USD 40–80 range for 2020, and just under that range's 2030 lower bound in 2024 dollars (USD 63, World Bank State and Trends 2024, executive summary p. 5). |
| `p_material` Material carbon price level | 15 | USD/tCO2 |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), PWR-R1 rating_rubric.M: 'Effective carbon price USD 15-60/tCO2' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric starts M at USD 15/tCO2 and calls anything below 'no material carbon price'. No external benchmark for that line was found, so the framework value is carried over. Owner to confirm. |

## PWR-R2 Renewable deployment target and permitting regime

Renewable build-out (pwr.renewables) and the grid it needs (pwr.grid) depend on a legally binding target that underpins investment and on projects reaching grid connection in reasonable time. Long connection queues delay and kill projects even where targets exist.

**Actions**

- Utility-scale solar PV and onshore wind build-out
- Transmission and grid-connection expansion

**Facts**

- Renewable target status: binding: a region-wide, legally binding renewable capacity or generation target for a set year (for example the EU Renewable Energy Directive or a national five-year-plan target); aspirational_or_sub_regional: a non-binding region-wide target, or binding targets only in some states or provinces; none: neither.
- Grid connection time: Median time from grid-connection request to commercial operation for utility-scale wind and solar projects completed in the latest year with data, region-wide (or across the largest grid areas where no region-wide figure exists).

**Rating**

- H: Renewable target status = binding and Grid connection time < 3 years.
- M: Renewable target status in binding, aspirational_or_sub_regional and Grid connection time <= 7 years.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_fast` Fast grid connection | 3 | years |  | Lawrence Berkeley National Laboratory, Queued Up: 2024 Edition, p. 3: 'The typical project built in 2023 took nearly 5 years from the interconnection request to commercial operations, compared to 3 years in 2015 and <2 years in 2008' <https://emp.lbl.gov/sites/default/files/2024-04/Queued%20Up%202024%20Edition_R1.pdf> | Today's rubric treats a queue below 3 years as reformed. 3 years was the typical US time from connection request to operation in 2015, before queue backlogs built up (nearly 5 years for projects built in 2023). |
| `p_slow` Prohibitive grid connection | 7 | years |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), PWR-R2 rating_rubric.L: 'connection queue exceeds 7 years' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric rates a queue above 7 years L. No external benchmark for that line was found, so the framework value is carried over. Owner to confirm. |

## PWR-D1 Corporate and utility PPA market depth

Long-term power purchase agreements give new solar and wind (pwr.renewables) and storage (pwr.storage) projects a contracted revenue stream that lenders finance against. Where renewable output sells mainly on spot or merchant terms, projects carry price risk that raises their cost of capital.

**Actions**

- Utility-scale solar PV and onshore wind build-out
- Grid-scale battery and long-duration storage

**Facts**

- PPA volume signed: Renewable generation capacity contracted under corporate and utility long-term power purchase agreements signed in the region in the latest full calendar year (announced deals).
- PPA volume signed, prior year: The same measure for the calendar year before.
- Solar and wind additions: Solar PV and wind capacity added in the region in the same calendar year as the PPA volume.
- PPA volume as share of additions: PPA volume signed as a percentage of the year's solar and wind additions: how much new renewable capacity is matched by long-term contracts rather than sold on spot or merchant terms.

**Rating**

- H: PPA volume as share of additions >= [open: PPA share of an established market] and PPA volume signed >= PPA volume signed, prior year.
- M: PPA volume as share of additions >= [open: PPA share above negligible].
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_established` PPA share of an established market | open |  |  |  | Open question: What PPA volume, as a share of the region's annual solar and wind additions, marks an established market where multi-year contracting is standard practice? No citable benchmark was found (the registered BloombergNEF data is subscription-only). |
| `p_negligible` PPA share above negligible | open |  |  |  | Open question: Below what PPA share of annual solar and wind additions is the PPA market 'negligible', with renewables sold predominantly on spot or merchant terms? No citable benchmark was found. |

# Steel

## STL-T1 Green hydrogen cost vs. DRI-H2 breakeven

Hydrogen-based DRI (steel.h2_dri) replaces coal with hydrogen as the iron-ore reductant, so hydrogen is its largest variable cost. Unless renewable hydrogen reaches the plant at or below the cost at which H2-DRI matches blast-furnace steel at the prevailing carbon price, H2-DRI projects need lasting subsidy; without any renewable hydrogen supply in the region they cannot start at all.

**Actions**

- Hydrogen-based direct reduced iron with electric arc furnace

**Facts**

- Renewable hydrogen cost: Levelised cost of hydrogen from electrolysis powered by renewable electricity, delivered to steel production sites in the region (production plus transport and storage), latest year reported, before production subsidies such as US Section 45V credits; central estimate for the region's typical sites.
- DRI-H2 breakeven hydrogen cost: Hydrogen cost at which H2-DRI-EAF steel matches the cost of BF-BOF steel in the region at the region's prevailing carbon price, from the latest published techno-economic analysis for the region.
- Hydrogen cost to breakeven: Renewable hydrogen cost divided by the breakeven hydrogen cost: 1 is at breakeven, 2 is twice breakeven.
- Renewable hydrogen supply present: At least one electrolysis plant powered by renewable electricity is operating or under construction in the region to supply an industrial user (demonstration units below commercial operation do not count).

**Rating**

- H: Renewable hydrogen supply present is Yes and Renewable hydrogen cost <= DRI-H2 breakeven hydrogen cost.
- M: Renewable hydrogen supply present is Yes and Hydrogen cost to breakeven <= 2.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_within` Hydrogen cost gap still counted as close | 2 |  |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), STL-T1 rating_rubric.M: 'Green hydrogen cost within 2x of breakeven' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric rates hydrogen 'within 2x of breakeven' M. No external source was found for where the M/L line should sit, so the framework value is carried over. Owner to confirm or replace with a sourced 2030 cost-decline projection. |

## STL-T2 Scrap steel availability (EAF route feasibility)

Scrap-based EAF steelmaking (steel.scrap_eaf) is the low-carbon route available today without new technology, but its output is capped by how much scrap the region collects. Where domestic scrap covers only a small share of steelmaking capacity, most output must stay on the iron-ore route until H2-DRI (steel.h2_dri) or carbon capture (steel.ccus) matures.

**Actions**

- Scrap-based electric arc furnace

**Facts**

- Domestic scrap availability: Ferrous scrap available from the region's own sources in the latest year reported: scrap consumed by the region's steelmakers plus scrap exports minus scrap imports (Mt per year).
- Crude steelmaking capacity: Nameplate crude steelmaking capacity in the region in the same year (Mt per year).
- Scrap availability as share of capacity: Domestic scrap availability as a percentage of crude steelmaking capacity.

**Rating**

- H: Scrap availability as share of capacity > 50%.
- M: Scrap availability as share of capacity >= 25%.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_high` High scrap availability | 50 | % |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), STL-T2 rating_rubric.H: 'Scrap availability exceeds 50% of production capacity' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric rates scrap above 50% of capacity H. No external benchmark for this line was found, so the framework value is carried over. Owner to confirm. |
| `p_low` Low scrap availability | 25 | % |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), STL-T2 rating_rubric.L: 'Scrap availability below 25% of production capacity' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric rates scrap below 25% of capacity L. No external benchmark for this line was found, so the framework value is carried over. Owner to confirm. |

## STL-R1 Effective carbon price on steel production incl. border adjustment

Every low-carbon steel route, H2-DRI (steel.h2_dri), scrap-EAF (steel.scrap_eaf) and carbon capture (steel.ccus), costs more than BF-BOF steel unless BF-BOF pays for its CO2. A high carbon price closes that gap; a border levy and a legislated end to free allocation stop unpriced imports and free allowances from undoing it.

**Actions**

- Hydrogen-based direct reduced iron with electric arc furnace
- Scrap-based electric arc furnace
- Carbon capture on blast furnace or DRI plants

**Facts**

- Carbon price applies to steel: A compliance carbon price (emissions trading system or carbon tax) covers CO2 from steel production in the region in the latest compliance year, with an obligation to surrender allowances or pay the tax (monitoring and reporting alone does not count).
- Carbon price on steel: Average allowance price or tax rate per tonne CO2 applying to steel production in the region over the latest full calendar year, gross of free allocation (the marginal price a producer saves per tonne abated). Zero where no compliance price applies.
- Border carbon levy in force: A border carbon adjustment requires importers of steel into the region to pay for the embedded emissions (a financial obligation, not only reporting) for imports in the current or latest year.
- Free allocation phase-out legislated: Law in force sets an end date for free allocation of allowances to steel producers, with a schedule of reductions that has started to apply (for example the EU CBAM factor in Article 10a(1a) of Directive 2003/87/EC as amended by Directive (EU) 2023/959). Free allocation that is merely planned to be reviewed does not count.

**Rating**

- H: Carbon price applies to steel is Yes and Carbon price on steel > 50 USD/tCO2 and Border carbon levy in force is Yes and Free allocation phase-out legislated is Yes.
- M: Carbon price applies to steel is Yes and Carbon price on steel >= 33.92 USD/tCO2.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_high` High carbon price level | 50 | USD/tCO2 |  | Report of the High-Level Commission on Carbon Prices (Carbon Pricing Leadership Coalition / World Bank, 2017), Executive Summary, PDF p. 10: 'at least US$40–80/tCO2 by 2020 and US$50–100/tCO2 by 2030' <https://business.columbia.edu/sites/default/files-efs/imce-uploads/Joseph_Stiglitz/CarbonPricing_FullReport.pdf> | Today's rubric sets H at above USD 50/tCO2. That is the lower end of the High-Level Commission's 2030 range for a Paris-consistent explicit carbon price (USD 50–100, 2017 dollars), the level at which a carbon price starts to close the cost gap of low-carbon production routes. |
| `p_material` Material carbon price level | 33.92 | USD/tCO2 |  | OECD, Effective Carbon Rates 2021 (brochure), p. 4, Box 1 'Carbon pricing benchmarks': '1. EUR 30 per tonne of CO2, a historic low-end price benchmark of carbon costs in the early and mid-2010s.' <https://www.oecd.org/tax/tax-policy/effective-carbon-rates-2021-brochure.pdf> | The rubric's L reads 'no material carbon price' without a number. The OECD's lowest carbon price benchmark, EUR 30/tCO2 (a historic low-end estimate of carbon costs), is the line: a price below the low end of what emissions cost is not material. Converted at the 2025 Federal Reserve annual average of 1.1306 USD per EUR (this rule book's EUR to USD conversion for 2025): 30 x 1.1306 = USD 33.92/tCO2. |

## STL-R2 Green/low-carbon steel public procurement or building-code mandate

A binding requirement to buy low-carbon steel in public construction creates assured demand for steel from H2-DRI (steel.h2_dri) and scrap-EAF (steel.scrap_eaf) plants and lets them recover their cost premium. Voluntary criteria leave that demand to each buyer's discretion.

**Actions**

- Hydrogen-based direct reduced iron with electric arc furnace
- Scrap-based electric arc furnace

**Facts**

- Low-carbon steel procurement rule: binding: a law, regulation or building code in force in the region requires embodied-carbon limits or low-carbon steel in public procurement or construction; voluntary_or_pilot: voluntary criteria or standards, or requirements limited to pilot projects; none: neither exists. National or EU-wide rules count; rules of individual states, provinces or member states count as voluntary_or_pilot for the region.
- Share of steel demand covered: Share of the region's construction demand for steel (by tonnage, latest year with data) that falls under the binding rule.

**Rating**

- H: Low-carbon steel procurement rule = binding and Share of steel demand covered >= [open: Material share of construction demand].
- M: Low-carbon steel procurement rule in binding, voluntary_or_pilot.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_material_share` Material share of construction demand | open |  |  |  | Open question: What share of the region's construction demand for steel must a binding rule cover to count as 'a material share'? No sourced benchmark was found; a source for the coverage figure itself (e.g. the public-procurement share of construction steel use) is also needed. |

## STL-D1 Green steel price premium and recoverability

Low-carbon steel from H2-DRI (steel.h2_dri), scrap-EAF (steel.scrap_eaf) or carbon capture (steel.ccus) costs more to make than BF-BOF steel. Plants reach financing only when buyers sign offtake contracts that pay a premium on a large part of their output; without them the premium stays unrecovered.

**Actions**

- Hydrogen-based direct reduced iron with electric arc furnace
- Scrap-based electric arc furnace
- Carbon capture on blast furnace or DRI plants

**Facts**

- Green steel premium disclosed: A producer or buyer in the region has disclosed a price premium (per tonne or as a percentage) paid for certified low-carbon steel under contracts signed or in force in the latest year.
- Offtake agreements signed: At least one signed offtake agreement (binding or conditional, pilots included) exists for low-carbon steel from a producer in the region.
- Share of announced capacity under offtake: Annual volume contracted under signed offtake agreements as a percentage of the announced annual output of low-carbon steel capacity in the region (operating, under construction or at final investment decision), from the latest disclosures.

**Rating**

- H: Green steel premium disclosed is Yes and Share of announced capacity under offtake >= [open: Material offtake share].
- M: Green steel premium disclosed is Yes and Offtake agreements signed is Yes.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_material_offtake` Material offtake share | open |  |  |  | Open question: What share of announced low-carbon steel capacity must be covered by signed offtake contracts to count as 'a material share'? A benchmark could come from project-finance practice (the share of output lenders require under contract), but no citable source was found. |

# Cement

## CEM-T1 CCS capture technology deployment status

Carbon capture (cement.ccus) is the only way to remove the process CO2 released when limestone is calcined, which clinker substitution (cement.clinker_sub) and fuel switching (cement.alt_fuels) cannot reach. Until a full-scale cement capture plant has run in the region, cost, performance and storage-access risk keep investors from committing to further plants.

**Actions**

- Carbon capture and storage on cement kilns

**Facts**

- Largest operating cement CCS plant: Design capture capacity of the largest carbon capture facility at a cement plant in the region that is in commercial operation with CO2 sent to permanent storage or use, at the latest status; 0 if none.
- Operating track record: That facility has run in commercial operation for at least twelve consecutive months, with captured volumes reported by the operator, a regulator or the CO2RE database.
- Largest cement CCS plant at FID or in construction: Design capture capacity of the largest carbon capture facility at a cement plant in the region that has taken a final investment decision or is under construction but not yet operating, at the latest status; 0 if none.

**Rating**

- H: Largest operating cement CCS plant >= 0.4 Mtpa CO2 and Operating track record is Yes.
- M: Largest cement CCS plant at FID or in construction >= 0.4 Mtpa CO2 or Largest operating cement CCS plant >= 0.4 Mtpa CO2.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_full_scale` Full-scale capture capacity | 0.4 | Mtpa CO2 |  | POLITICO, 'Large-scale carbon capture sites in the U.S.' (Datawrapper map, source: Global CCS Institute), Chart intro: 'other industrial facilities capturing at least 400,000 metric tons of CO2 annually' <https://datawrapper.dwcdn.net/4Fi0R/2/> | Today's rubric calls a plant above 0.3 Mtpa full-scale but cites no source. The Global CCS Institute's large-scale threshold for industrial facilities other than coal power is at least 0.4 Mtpa (also stated as '> 0.4 Mt CO2/yr' in C. Petit, Imperial College, 2014 RCN deck, slide 2), so that sourced value replaces 0.3. Brevik CCS in Norway, the first full-scale cement plant, captures about 0.4 Mtpa. |

## CEM-T2 Clinker substitution rate (SCM availability)

Replacing clinker with supplementary cementitious materials such as slag, fly ash, calcined clay and limestone (cement.clinker_sub) is the cheapest cement abatement lever available now, cutting fuel and process CO2 per tonne of cement. A high regional clinker ratio means the lever is unused or the materials are scarce, leaving more of the abatement to carbon capture (cement.ccus).

**Actions**

- Clinker substitution with supplementary cementitious materials

**Facts**

- Clinker-to-cement ratio: Average tonnes of clinker per tonne of cement produced in the region in the latest year reported (GCCA Getting the Numbers Right or national statistics), all cement types.
- Active SCM substitution programme: A standard, building-code change or public or industry programme in force in the region promotes blended cements or the supply of supplementary cementitious materials (for example limestone calcined clay cement standards or slag and fly-ash supply schemes).

**Rating**

- H: Clinker-to-cement ratio < 0.65 t/t and Active SCM substitution programme is Yes.
- M: Clinker-to-cement ratio <= 0.8 t/t.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_low` Low clinker ratio | 0.65 | t/t |  | IEA, Net Zero Roadmap (2023 update): Cement, Milestones table, clinker-to-cement ratio (tonne per tonne): 0.71 (2022), 0.65 (2030), 0.61 (2035), 0.57 (2050) <https://www.iea.org/reports/cement-3> | Today's rubric rates a ratio below 0.65 H. 0.65 is the IEA Net Zero 2030 milestone for the global clinker-to-cement ratio (0.71 in 2022), and the lower clinker bound of EN 197-1 CEM II/B cements (65–79% clinker). IEA pages could not be fetched directly; the milestone was read from the search engine's copy of the page. |
| `p_high` High clinker ratio | 0.8 | t/t |  | Buzzi Unicem, Type II cements (composition under UNI EN 197-1), Type II/A: 'between 80-94% clinker'; Type II/B: 'between 65-79% clinker' <https://www.buzziunicem.it/en/type-ii> | Today's rubric rates a ratio above 0.80 L. Under EN 197-1 the least-blended Portland-composite cements (CEM II/A) contain at least 80% clinker, so a regional average above 0.80 means typical cement uses less substitution than the lightest blended cement type. |

## CEM-R1 Effective carbon price on cement production incl. border adjustment

Cement CCS (cement.ccus), deeper clinker substitution (cement.clinker_sub) and low-carbon fuels (cement.alt_fuels) all cost more than conventional clinker unless its CO2 is priced. A high carbon price closes the gap; a border levy and a legislated end to free allocation stop unpriced imports and free allowances from undoing it.

**Actions**

- Carbon capture and storage on cement kilns
- Clinker substitution with supplementary cementitious materials
- Alternative and low-carbon kiln fuels

**Facts**

- Carbon price applies to cement: A compliance carbon price (emissions trading system or carbon tax) covers CO2 from cement production in the region in the latest compliance year, with an obligation to surrender allowances or pay the tax (monitoring and reporting alone does not count).
- Carbon price on cement: Average allowance price or tax rate per tonne CO2 applying to cement production in the region over the latest full calendar year, gross of free allocation (the marginal price a producer saves per tonne abated). Zero where no compliance price applies.
- Border carbon levy in force: A border carbon adjustment requires importers of cement into the region to pay for the embedded emissions (a financial obligation, not only reporting) for imports in the current or latest year.
- Free allocation phase-out legislated: Law in force sets an end date for free allocation of allowances to cement producers, with a schedule of reductions that has started to apply (for example the EU CBAM factor in Article 10a(1a) of Directive 2003/87/EC as amended by Directive (EU) 2023/959). Free allocation that is merely planned to be reviewed does not count.

**Rating**

- H: Carbon price applies to cement is Yes and Carbon price on cement > 50 USD/tCO2 and Border carbon levy in force is Yes and Free allocation phase-out legislated is Yes.
- M: Carbon price applies to cement is Yes and Carbon price on cement >= 33.92 USD/tCO2.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_high` High carbon price level | 50 | USD/tCO2 |  | Report of the High-Level Commission on Carbon Prices (Carbon Pricing Leadership Coalition / World Bank, 2017), Executive Summary, PDF p. 10: 'at least US$40–80/tCO2 by 2020 and US$50–100/tCO2 by 2030' <https://business.columbia.edu/sites/default/files-efs/imce-uploads/Joseph_Stiglitz/CarbonPricing_FullReport.pdf> | Today's rubric sets H at above USD 50/tCO2. That is the lower end of the High-Level Commission's 2030 range for a Paris-consistent explicit carbon price (USD 50–100, 2017 dollars), the level at which a carbon price starts to close the cost gap of low-carbon production routes. |
| `p_material` Material carbon price level | 33.92 | USD/tCO2 |  | OECD, Effective Carbon Rates 2021 (brochure), p. 4, Box 1 'Carbon pricing benchmarks': '1. EUR 30 per tonne of CO2, a historic low-end price benchmark of carbon costs in the early and mid-2010s.' <https://www.oecd.org/tax/tax-policy/effective-carbon-rates-2021-brochure.pdf> | The rubric's L reads 'no material carbon price' without a number. The OECD's lowest carbon price benchmark, EUR 30/tCO2 (a historic low-end estimate of carbon costs), is the line: a price below the low end of what emissions cost is not material. Converted at the 2025 Federal Reserve annual average of 1.1306 USD per EUR (this rule book's EUR to USD conversion for 2025): 30 x 1.1306 = USD 33.92/tCO2. |

## CEM-R2 CCS infrastructure support scheme

Cement CCS (cement.ccus) needs capture, transport and storage infrastructure that a single plant cannot finance alone. Public grants that have actually been paid to cement projects show a working route to finance; a scheme that has paid nothing to cement yet, or is small and competitive, leaves projects exposed.

**Actions**

- Carbon capture and storage on cement kilns

**Facts**

- Public CCS funding scheme: A public funding mechanism (grant programme, carbon contract for difference, tax credit or state-funded CO2 transport and storage) is open or active in the region and applicable to carbon capture at cement plants.
- Funds disbursed to cement CCS: Such a scheme has paid out (not only awarded) funds to at least one cement CCS project in the region.

**Rating**

- H: Public CCS funding scheme is Yes and Funds disbursed to cement CCS is Yes.
- M: Public CCS funding scheme is Yes.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|

## CEM-D1 Low-carbon cement premium recoverability

Low-carbon cement, from deep clinker substitution (cement.clinker_sub) and especially from carbon capture (cement.ccus), costs more than conventional cement. Binding green procurement rules or embodied-carbon limits in building codes create demand that pays that premium; voluntary commitments cover only part of it.

**Actions**

- Carbon capture and storage on cement kilns
- Clinker substitution with supplementary cementitious materials

**Facts**

- Low-carbon cement procurement rule: binding: a law, regulation or building code in force in the region requires embodied-carbon limits or low-carbon cement in public procurement or construction; voluntary_or_pilot: voluntary criteria or standards, or requirements limited to pilot projects; none: neither exists. National or EU-wide rules count; rules of individual states, provinces or member states count as voluntary_or_pilot for the region.
- Binding demand as share of low-carbon capacity: Annual low-carbon cement volume that binding rules require buyers to use in the region (from the rules' scope and the construction they cover, latest year with data) as a percentage of the announced annual output of low-carbon cement capacity in the region (operating, under construction or at final investment decision).

**Rating**

- H: Low-carbon cement procurement rule = binding and Binding demand as share of low-carbon capacity >= [open: Material share of low-carbon capacity].
- M: Low-carbon cement procurement rule in binding, voluntary_or_pilot.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_material_share` Material share of low-carbon capacity | open |  |  |  | Open question: What share of the region's announced low-carbon cement capacity must demand created by binding procurement rules or embodied-carbon codes cover to count as 'a material share'? No sourced benchmark was found; a source for estimating the binding demand volume (tonnes of low-carbon cement the rules require per year) is also needed. |

# Chemicals

## CHM-T1 Green/blue hydrogen availability for ammonia and feedstock use

Low-carbon ammonia and methanol replace grey hydrogen from unabated natural gas reforming with hydrogen from renewable electrolysis (chem.low_carbon_h2) or from gas reforming with carbon capture (chem.ccus), and hydrogen is their main feedstock. Unless low-carbon hydrogen comes close to the cost of grey hydrogen, or the carbon price on grey hydrogen closes the gap, the switch needs lasting subsidy; without any low-carbon hydrogen supply in the region it cannot start at all.

**Actions**

- Low-carbon hydrogen as feedstock for ammonia and methanol
- Carbon capture and storage on ammonia, hydrogen and other chemical plants

**Facts**

- Low-carbon hydrogen cost: Levelised cost of low-carbon hydrogen delivered to chemical plants in the region (production plus transport and storage), latest year reported: the cheaper of hydrogen from electrolysis powered by renewable electricity and hydrogen from natural gas reforming with carbon capture and storage. Before production subsidies such as US Section 45V credits; central estimate for the region's typical sites.
- Grey hydrogen cost: Levelised cost of hydrogen from unabated natural gas steam methane reforming in the region at the region's prevailing natural gas price, for the same year as the low-carbon hydrogen cost, excluding any carbon price. The natural gas route is used as the metric states, also where coal gasification is the region's main route (as in China).
- Grey hydrogen cost with carbon price: Grey hydrogen cost as defined for this criterion plus the carbon price unabated hydrogen production pays in the region: the allowance price or tax rate of the same year times the CO2 emitted per kg of grey hydrogen, at the full price (the cost avoided per tonne abated, gross of free allocation). Equal to the grey hydrogen cost where no compliance carbon price covers hydrogen production.
- Low-carbon to grey hydrogen cost: Low-carbon hydrogen cost divided by grey hydrogen cost without carbon price: 1.2 is 20% above grey, 2 is twice grey.
- Low-carbon hydrogen supply present: At least one plant producing low-carbon hydrogen (electrolysis powered by renewable electricity, or natural gas reforming with carbon capture and storage) is operating or under construction in the region to supply an industrial or chemical user (demonstration units below commercial operation do not count).

**Rating**

- H: Low-carbon hydrogen supply present is Yes and (Low-carbon to grey hydrogen cost <= 1.2 or Low-carbon hydrogen cost <= Grey hydrogen cost with carbon price).
- M: Low-carbon hydrogen supply present is Yes and Low-carbon to grey hydrogen cost <= 2.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_within` Low-carbon hydrogen cost close to grey | 1.2 |  |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), CHM-T1 rating_rubric.H: 'Low-carbon hydrogen cost within 20% of grey hydrogen cost, or carbon price closes the gap' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric rates low-carbon hydrogen 'within 20% of grey hydrogen cost' H; within 20% is a cost ratio of at most 1.2. No external benchmark for this line was found, so the framework value is carried over. Owner to confirm. |
| `p_double` Low-carbon hydrogen cost gap still counted as moderate | 2 |  |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), CHM-T1 rating_rubric.M: 'Low-carbon hydrogen cost 20-100% above grey hydrogen cost'; rating_rubric.L: 'Low-carbon hydrogen more than 2x grey hydrogen cost, or no low-carbon hydrogen supply chain present' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric rates a low-carbon hydrogen cost 20-100% above grey M and 'more than 2x' grey L; 100% above grey is a cost ratio of 2. No external benchmark for this line was found, so the framework value is carried over. Owner to confirm. |

## CHM-T2 Electrification of process heat (steam cracking) readiness

Electric steam cracking (chem.e_cracker) replaces the fuel-fired furnaces of a steam cracker with electric heating. Producers can only plan it into a cracker revamp or new build once a production-size unit has run, or been committed, in the region; while the technology there is at demonstration or laboratory stage, no producer can commit capital to it.

**Actions**

- Electrically heated steam cracking

**Facts**

- Electric cracking readiness in the region: Technology readiness level on the EU Horizon 2020 scale (TRL 4 'technology validated in lab', TRL 5 'technology validated in relevant environment', TRL 6 'technology demonstrated in relevant environment', TRL 7 'system prototype demonstration in operational environment', TRL 8 'system complete and qualified') reached by the most advanced electrically heated steam cracking unit built in the region, latest status. Units in other regions do not count. 0 where no unit beyond laboratory scale has been built in the region.
- Commercial-scale electric cracker operating or at FID: An electrically heated cracking furnace sized as a production furnace of a commercial steam cracker (not a demonstration unit) is operating in the region, or a final investment decision on one has been announced.

**Rating**

- H: Electric cracking readiness in the region >= 7 TRL and Commercial-scale electric cracker operating or at FID is Yes.
- M: Electric cracking readiness in the region >= 5 TRL.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_trl_high` Readiness level for commercial use | 7 | TRL |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), CHM-T2 rating_rubric.H: 'TRL 7+ with commercial-scale pilot operating or announced FID' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric sets H at 'TRL 7+', on the scale where TRL 7 is a system prototype demonstrated in an operational environment (Horizon 2020 Work Programme 2014-2015, General Annexes, Annex G). No external benchmark for where H should start was found, so the framework value is carried over. Owner to confirm. |
| `p_trl_mid` Readiness level for demonstration | 5 | TRL |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), CHM-T2 rating_rubric.M: 'TRL 5-6, demonstration scale only'; rating_rubric.L: 'TRL below 5, lab/concept stage only' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric rates 'TRL 5-6, demonstration scale only' M and 'TRL below 5, lab/concept stage only' L; TRL 5 is the first level validated outside the laboratory (Horizon 2020 Annex G: 'technology validated in relevant environment'). Framework value carried over. Owner to confirm. |

## CHM-R1 Effective carbon price on chemicals production incl. border adjustment

Low-carbon ammonia and methanol (chem.low_carbon_h2), carbon capture (chem.ccus) and electric cracking (chem.e_cracker) all cost more than fossil production unless its CO2 is priced. A high carbon price closes that gap; a border levy and a legislated end to free allocation stop unpriced imports and free allowances from undoing it. In chemicals both must cover ammonia and the steam-cracker products, because those are the plants the actions change.

**Actions**

- Low-carbon hydrogen as feedstock for ammonia and methanol
- Carbon capture and storage on ammonia, hydrogen and other chemical plants
- Electrically heated steam cracking

**Facts**

- Carbon price applies to chemicals: A compliance carbon price (emissions trading system or carbon tax) covers CO2 from chemicals production (at least ammonia or steam cracking) in the region in the latest compliance year, with an obligation to surrender allowances or pay the tax (monitoring and reporting alone does not count).
- Carbon price on chemicals: Average allowance price or tax rate per tonne CO2 applying to chemicals production in the region over the latest full calendar year, gross of free allocation (the marginal price a producer saves per tonne abated). Zero where no compliance price applies.
- Border carbon levy in force for chemicals: A border carbon adjustment requires importers into the region to pay for the embedded emissions (a financial obligation, not only reporting) of both ammonia and steam-cracker products (high-value chemicals such as ethylene and propylene, or their polymers), for imports in the current or latest year. Coverage of ammonia or fertilisers alone does not count: the EU CBAM covers ammonia (Regulation (EU) 2023/956, Annex I, CN 2814) but leaves organic chemicals out of scope (recital 34).
- Free allocation phase-out legislated for chemicals: Law in force sets an end date for free allocation of allowances to both ammonia and steam-cracker producers, with a schedule of reductions that has started to apply (for example the EU CBAM factor in Article 10a(1a) of Directive 2003/87/EC as amended by Directive (EU) 2023/959, which applies to CBAM goods only). A phase-out for ammonia alone, or free allocation that is merely planned to be reviewed, does not count.

**Rating**

- H: Carbon price applies to chemicals is Yes and Carbon price on chemicals > 50 USD/tCO2 and Border carbon levy in force for chemicals is Yes and Free allocation phase-out legislated for chemicals is Yes.
- M: Carbon price applies to chemicals is Yes and Carbon price on chemicals >= 33.92 USD/tCO2.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_high` High carbon price level | 50 | USD/tCO2 |  | Report of the High-Level Commission on Carbon Prices (Carbon Pricing Leadership Coalition / World Bank, 2017), Executive Summary, PDF p. 10: 'at least US$40–80/tCO2 by 2020 and US$50–100/tCO2 by 2030' <https://business.columbia.edu/sites/default/files-efs/imce-uploads/Joseph_Stiglitz/CarbonPricing_FullReport.pdf> | Today's rubric sets H at above USD 50/tCO2. That is the lower end of the High-Level Commission's 2030 range for a Paris-consistent explicit carbon price (USD 50–100, 2017 dollars), the level at which a carbon price starts to close the cost gap of low-carbon production routes. |
| `p_material` Material carbon price level | 33.92 | USD/tCO2 |  | OECD, Effective Carbon Rates 2021 (brochure), p. 4, Box 1 'Carbon pricing benchmarks': '1. EUR 30 per tonne of CO2, a historic low-end price benchmark of carbon costs in the early and mid-2010s.' <https://www.oecd.org/tax/tax-policy/effective-carbon-rates-2021-brochure.pdf> | The rubric's L reads 'no material carbon price' without a number. The OECD's lowest carbon price benchmark, EUR 30/tCO2 (a historic low-end estimate of carbon costs), is the line: a price below the low end of what emissions cost is not material. Converted at the 2025 Federal Reserve annual average of 1.1306 USD per EUR (this rule book's EUR to USD conversion for 2025): 30 x 1.1306 = USD 33.92/tCO2. Same line as STL-R1 and CEM-R1. |

## CHM-D1 Green ammonia/methanol offtake market

Green ammonia and methanol plants (chem.low_carbon_h2) cost more to build and run than fossil plants and are financed against long-term offtake contracts. Signed volumes at a disclosed premium show that shipping lines and industrial buyers will pay the cost gap; without them projects do not reach a final investment decision.

**Actions**

- Low-carbon hydrogen as feedstock for ammonia and methanol

**Facts**

- Binding green ammonia or methanol offtake signed: At least one binding offtake or purchase agreement for green ammonia or green methanol has been signed by a shipping company or industrial user based in the region (the producer may be anywhere), latest status; pilot-scale volumes count. Term sheets, memoranda of understanding and letters of intent do not count. Green: made with hydrogen from electrolysis powered by renewable electricity (e-ammonia, e-methanol) or, for methanol, from sustainable biomass (bio-methanol); fossil-based product with carbon capture does not count.
- Signed green ammonia and methanol offtake: Sum of the annual volumes at full delivery (tonnes of product per year) under all binding agreements of the kind defined for this criterion, signed by buyers based in the region and not yet expired, latest status. Ammonia and methanol tonnes are added as reported.
- Offtake premium disclosed: At least one of these agreements discloses that the buyer pays a price premium over the fossil equivalent (the amount, or the existence of a premium, stated by a party to the agreement).

**Rating**

- H: Binding green ammonia or methanol offtake signed is Yes and Offtake premium disclosed is Yes and Signed green ammonia and methanol offtake >= [open: Material offtake volume].
- M: Binding green ammonia or methanol offtake signed is Yes.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_material` Material offtake volume | open | t/yr |  |  | Open question: Above what annual signed volume (t/yr) is green ammonia and methanol offtake 'material' for a region? No sourced line was found. Candidates for the owner: the annual output of one commercial-scale plant, or a share of the fuel needed for the IMO 2023 GHG Strategy's 2030 ambition (zero or near-zero GHG fuels at least 5%, striving for 10%, of the energy used by international shipping), converted to tonnes per region. |

# Critical Minerals & Mining

## MIN-T1 Mine electrification and processing technology readiness

Battery-electric haulage, loading and drilling equipment (min.electric_fleet) replaces diesel-powered mobile machines at mines. Miners commit whole fleets only after the equipment has run in routine production at other operating mines; while it is still on trial, electrification stays a pilot. 'At scale' is tested as the metric's battery-electric share of new equipment orders; the readiness of electrified ore processing is not tested, because today's rubric rates on equipment deployment only.

**Actions**

- Battery-electric mining haulage, loading and drilling equipment

**Facts**

- Battery-electric equipment in production at more than one mine: Battery-electric haulage, loading or drilling equipment is in routine production use (bought or leased for operations, not a trial or pilot) at more than one operating mine in the region, latest status.
- Battery-electric equipment at an operating mine: Battery-electric haulage, loading or drilling equipment is in trial, pilot or production use at at least one operating mine in the region, latest status.
- Battery-electric share of equipment orders: Battery-electric units as a share of all haulage, loading and drilling equipment units ordered for mines in the region in the latest full year (orders placed, not deliveries), as reported by equipment makers or industry trackers.

**Rating**

- H: Battery-electric equipment in production at more than one mine is Yes and Battery-electric share of equipment orders >= [open: At-scale battery-electric order share].
- M: Battery-electric equipment at an operating mine is Yes.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_at_scale` At-scale battery-electric order share | open | % |  |  | Open question: What battery-electric share of new mining equipment orders marks deployment 'at scale' (rubric H, 'commercially deployed at scale (multiple operating mines)')? No sourced line was found; without it any two mines with production units would rate H. |

## MIN-R1 Fast-track permitting regime for strategic minerals projects

Long permitting delays new mines and processing plants for transition minerals (min.new_supply). A statutory fast-track with a maximum timeline lets a developer plan financing around a known decision date; a discretionary or open-ended process does not. Where no fast-track exists, standard permitting of five years or less still keeps a region out of L, as today's rubric reads.

**Actions**

- New domestic or allied mine and processing capacity for transition minerals

**Facts**

- Fast-track permitting for strategic minerals projects: statutory: law in force sets a fast-track permitting procedure with a binding maximum duration for projects designated as strategic minerals projects (for example Regulation (EU) 2024/1252, Article 11); discretionary: a fast-track, priority or coordination process exists for such projects (for example designation for expedited review by executive decision) but sets no binding maximum duration; none: neither exists. National or EU-wide procedures count; procedures of individual states, provinces or member states count as discretionary for the region.
- Statutory maximum permitting time: Maximum duration in months that the statutory fast-track allows for the permit-granting process of a strategic project involving extraction, as written in the law in force: the standard limit, without case-by-case extensions for exceptional cases and without periods the law itself leaves out of the count. Under Regulation (EU) 2024/1252 this is 27 months (Article 11(1)(a)); Article 11(3) leaves the environmental impact assessment report step out of the count and Article 11(4) allows up to six months' extension.
- Standard permitting time: Typical duration in months of the standard (not fast-track) permitting process for a new mining project in the region, from the first permit application to the last permit needed to start construction, from the latest government or independent review (the median where a distribution is given).

**Rating**

- H: Fast-track permitting for strategic minerals projects = statutory and Statutory maximum permitting time < 30 months.
- M: Fast-track permitting for strategic minerals projects in statutory, discretionary or Standard permitting time <= 60 months.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_fast` Fast permitting limit | 30 | months |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), MIN-R1 rating_rubric.H: 'Statutory fast-track permitting in force with maximum timeline below 30 months' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric sets H at a statutory maximum 'below 30 months'. No external benchmark for 30 months was found; it sits just above the EU Critical Raw Materials Act's 27-month limit for extraction projects (Regulation (EU) 2024/1252, Article 11(1)(a)), on which today's EU H rating rests. Framework value carried over. Owner to confirm. |
| `p_slow` Slow standard permitting | 60 | months |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), MIN-R1 rating_rubric.L: 'No fast-track permitting regime; standard permitting exceeds 5 years' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric L reads 'No fast-track permitting regime; standard permitting exceeds 5 years'; 5 years is 60 months. A region with no fast-track whose standard permitting takes 60 months or less is therefore not L and is rated M. No external benchmark for 5 years was found, so the framework value is carried over. Owner to confirm. |

## MIN-R2 Domestic sourcing / content requirement policy

A content requirement that makes a subsidy or a public contract depend on minerals from domestic or allied sources gives new mines, refineries and recycling plants in the region and its partners (min.new_supply, min.recycling) a protected market against cheaper incumbent supply. The effect scales with the money at stake and the share of content required; a requirement with no money attached, a low share or unclear enforcement moves little investment.

**Actions**

- New domestic or allied mine and processing capacity for transition minerals
- Recycling of critical minerals from end-of-life products and waste

**Facts**

- Domestic or allied content requirement: binding: law in force makes eligibility for a subsidy, tax credit or public-procurement award conditional on a minimum share of critical-mineral content extracted, processed or recycled domestically or in allied (for example free-trade-agreement) countries, checked before payment or award; other: a domestic or allied sourcing requirement, benchmark or target for critical minerals exists in law or policy but is not such a condition, or its enforcement is unclear (for example the 2030 capacity benchmarks of Regulation (EU) 2024/1252, Article 5); none: neither exists. Export controls on the region's own minerals are not a content requirement. National or EU-wide rules count; rules of individual states, provinces or member states count as other.
- Required domestic or allied content: Minimum share of critical-mineral content (by value or quantity, as the rule defines it) that must come from domestic or allied sources under the binding requirement in the current year.
- Subsidy tied to the requirement: Public money per year whose award depends on meeting the binding requirement: the annual budget or official cost estimate of the subsidy or tax credit, or the annual value of the public procurement covered, latest year.

**Rating**

- H: Domestic or allied content requirement = binding and Required domestic or allied content >= [open: Low content threshold] and Subsidy tied to the requirement >= [open: Material subsidy value].
- M: Domestic or allied content requirement in binding, other.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_low_share` Low content threshold | open | % |  |  | Open question: Below what required domestic or allied content share is a binding requirement's threshold 'low' (rubric M)? No sourced line was found. |
| `p_material_subsidy` Material subsidy value | open | USD million/yr |  |  | Open question: Above what annual subsidy or procurement value tied to the requirement (USD million per year) is the subsidy 'material' (rubric H)? No sourced line was found; a measure relative to the region's size (for example to its annual critical-mineral imports) may fit better than an absolute amount, which would change the fact. |

## MIN-D1 Committed offtake and supply agreements vs. identified demand gap

New mines and refineries for transition minerals (min.new_supply) are financed against long-term offtake contracts and committed capacity. Where signed offtakes and committed expansions cover a large share of the region's projected supply gap, the supply its clean-energy manufacturing needs is being built; where they cover little, the gap stays open. Tonnes of different minerals cannot be added, so lithium, named in today's evidence, is the reference mineral (owner to confirm).

**Actions**

- New domestic or allied mine and processing capacity for transition minerals

**Facts**

- Lithium supply secured for 2030: Annual lithium volume (kt lithium content per year) expected in 2030 under signed long-term offtake agreements of buyers based in the region with new or expanding mines or refineries anywhere, plus the 2030 output of new lithium extraction or refining capacity in the region with a final investment decision or under construction, counting a volume once where an offtake comes from such capacity. Latest status.
- Projected lithium supply gap for 2030: The region's projected 2030 lithium demand under the IEA Net Zero Emissions by 2050 Scenario minus the region's refined lithium production in the latest year (kt lithium content per year), from the latest IEA Global Critical Minerals Outlook or its data explorer. Zero or negative where latest production already meets projected 2030 demand.
- Share of lithium supply gap covered: Secured lithium supply as a share of the region's projected 2030 supply gap: 100% is fully covered. Only meaningful when the gap is positive.
- No projected lithium supply gap: The region's refined lithium production in the latest year already meets or exceeds its projected 2030 lithium demand under the IEA Net Zero Emissions by 2050 Scenario.

**Rating**

- H: No projected lithium supply gap is Yes or Share of lithium supply gap covered >= [open: Material share of the supply gap].
- M: Share of lithium supply gap covered >= [open: Minimal share of the supply gap].
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_material` Material share of the supply gap | open | % |  |  | Open question: What share of the region's projected 2030 lithium supply gap must signed offtakes and committed capacity cover to count as 'a material share' (rubric H)? No sourced line was found. Also: is lithium the right reference mineral, or should the owner name another or one criterion per mineral? |
| `p_minimal` Minimal share of the supply gap | open | % |  |  | Open question: Below what share of the projected 2030 lithium supply gap is offtake activity 'minimal' (rubric L) rather than 'some offtake agreements signed but gap remains largely uncovered' (rubric M)? No sourced line was found. |

# Aviation

## AVI-T1 SAF production capacity vs. jet fuel demand

HEFA, advanced biofuel and synthetic fuel plants (avi.hefa_saf, avi.advanced_bio_saf, avi.e_saf) cut aviation emissions only in the volumes they can produce. Where regional SAF capacity is a tiny share of jet fuel demand, blending mandates and airline targets cannot be met from regional supply at any price; plants at final investment decision or under construction show the share will keep growing. Volumes are compared in litres: US gallons and petroleum barrels convert by the NIST rows of the conversions table, but a figure in tonnes needs a jet fuel density (ASTM D1655 allows 775–840 kg/m3 at 15 °C), which is left open for the owner, so it does not count yet.

**Actions**

- HEFA sustainable aviation fuel from waste oils and fats
- Advanced biofuel SAF (alcohol-to-jet, gasification with Fischer-Tropsch)
- Power-to-liquid synthetic aviation fuel (e-SAF)

**Facts**

- SAF production capacity: Combined nameplate capacity to produce neat sustainable aviation fuel (from biomass, waste or renewable electricity, meeting ASTM D7566 or an equivalent standard) of plants operating in the region at the end of the latest year, in million litres per year. Plants that can switch between renewable diesel and SAF count at their stated maximum SAF output; co-processing in fossil refineries counts at its stated renewable jet output.
- Jet fuel demand: Total jet fuel (kerosene-type aviation fuel) consumed in the region in the latest full calendar year, including fuel uplifted for international flights departing the region, in million litres per year.
- SAF capacity share of jet fuel demand: SAF production capacity as a share of the region's jet fuel demand: 5% means capacity could supply one twentieth of the fuel used.
- SAF expansion at FID or under construction: At least one new SAF plant or SAF capacity expansion in the region has taken a final investment decision or is under construction, latest status. Announcements without a final investment decision do not count.

**Rating**

- H: SAF capacity share of jet fuel demand > 5% and SAF expansion at FID or under construction is Yes.
- M: SAF capacity share of jet fuel demand >= 1%.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_high` High SAF capacity share | 5 | % |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), AVI-T1 rating_rubric.H: 'SAF capacity exceeds 5% of regional jet fuel demand with credible near-term expansion pipeline' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric sets H at SAF capacity that 'exceeds 5% of regional jet fuel demand'. No external benchmark for this line was found; for scale, ReFuelEU Aviation requires a minimum 2% SAF share from 2025 and 6% from 2030 (Regulation (EU) 2023/2405, Annex I). Framework value carried over. Owner to confirm. |
| `p_low` Low SAF capacity share | 1 | % |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), AVI-T1 rating_rubric.M: 'SAF capacity between 1-5% of demand'; rating_rubric.L: 'SAF capacity below 1% of regional jet fuel demand' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric rates SAF capacity 'between 1-5% of demand' M and 'below 1%' L. No external benchmark for this line was found, so the framework value is carried over. Owner to confirm. |

## AVI-R1 SAF blending mandate

A binding blending mandate creates assured demand for SAF (avi.hefa_saf, avi.advanced_bio_saf, avi.e_saf) that rises on a known schedule, which is what lets producers finance new plants; penalties make that demand real. An announced mandate or a voluntary target signals direction but assures no demand.

**Actions**

- HEFA sustainable aviation fuel from waste oils and fats
- Advanced biofuel SAF (alcohol-to-jet, gasification with Fischer-Tropsch)
- Power-to-liquid synthetic aviation fuel (e-SAF)

**Facts**

- SAF blending mandate: in_force: a law or regulation in force in the region requires fuel suppliers or airlines to supply or use a minimum share of SAF in the current year; announced_or_voluntary: such a mandate is adopted or announced but its first obligation year has not started, or the region has only a voluntary or non-binding SAF target; none: neither exists. National or EU-wide rules count; rules of individual states, provinces or member states count as announced_or_voluntary. Tax credits without a minimum share are not mandates, and offsetting schemes such as CORSIA are not SAF targets.
- Mandated share rises by law: The law sets minimum SAF shares for later years that are higher than the current year's (for example Regulation (EU) 2023/2405, Annex I: 2% from 2025, 6% from 2030, rising to 70% from 2050).
- Penalties for missing the mandate: The law requires fines or other financial penalties on fuel suppliers or airlines that miss the mandated share (for example Regulation (EU) 2023/2405, Article 12(4): a fine not less than twice the SAF price difference times the quantity not complying).

**Rating**

- H: SAF blending mandate = in_force and Mandated share rises by law is Yes and Penalties for missing the mandate is Yes.
- M: SAF blending mandate in in_force, announced_or_voluntary.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|

## AVI-D1 SAF price premium and corporate offtake coverage

SAF (avi.hefa_saf, avi.advanced_bio_saf, avi.e_saf) costs more than fossil jet fuel, and producers finance plants against offtake contracts. Where tax credits, tradable credits or emissions-trading value cover most of the premium and airlines and corporate buyers have signed large offtakes, plants get built; where the airline or passenger bears the full premium with no offset and no contracts, SAF stays a niche. Prices per gallon convert by the gallon row applied to the unit's denominator (USD/gallon ÷ 3.785411784 = USD/litre); prices or volumes in tonnes need a jet fuel density, left open for the owner as in AVI-T1.

**Actions**

- HEFA sustainable aviation fuel from waste oils and fats
- Advanced biofuel SAF (alcohol-to-jet, gasification with Fischer-Tropsch)
- Power-to-liquid synthetic aviation fuel (e-SAF)

**Facts**

- SAF price premium: Price of neat SAF minus the price of fossil jet fuel in the region, average of the latest year, before any tax credit, tradable credit or other offset, per litre. A premium stated as a price multiple is converted with the fossil jet fuel price of the same year and region.
- Premium offset per litre: Value per litre of SAF, in the same year, of the mechanisms in force in the region that pay or credit SAF: production or blender tax credits (for example US Section 45Z), tradable credits that SAF generates (for example US RINs or state low-carbon fuel standard credits), and allowances or carbon costs avoided under an emissions trading system (for example the EU ETS allowances reserved to cover part of the SAF price difference under Directive (EU) 2023/958, and the carbon cost avoided because SAF emissions count as zero). Fines a mandate imposes for not supplying SAF are not counted: they are why the premium is paid, not an offset of it. Zero where no mechanism applies.
- Share of SAF premium offset: Premium offset per litre as a share of the SAF price premium: 100% means fully offset.
- Premium offset mechanism in force: At least one mechanism of the kinds listed for the premium offset is in force in the region and available for SAF supplied in the current year.
- SAF volume under signed offtakes: Annual SAF volume under signed offtake or purchase agreements, book-and-claim certificate purchases included, of airlines and corporate buyers based in the region, for the current or latest delivery year, in million litres per year. A multi-year contract counts at its total volume divided by its number of contract years.
- Jet fuel demand: Total jet fuel (kerosene-type aviation fuel) consumed in the region in the latest full calendar year, including fuel uplifted for international flights departing the region, in million litres per year.
- SAF offtake share of jet fuel demand: SAF volume under signed offtakes as a share of the region's jet fuel demand.
- SAF offtake signed: At least one signed SAF offtake or purchase agreement of the kind defined for this criterion exists for an airline or corporate buyer based in the region.

**Rating**

- H: Premium offset mechanism in force is Yes and SAF offtake signed is Yes and Share of SAF premium offset >= [open: Substantial offset share] and SAF offtake share of jet fuel demand >= [open: Material offtake share].
- M: Premium offset mechanism in force is Yes or SAF offtake signed is Yes.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_substantial` Substantial offset share | open | % |  |  | Open question: What share of the SAF price premium must offsets cover for the premium to be 'substantially offset' (rubric H)? No sourced line was found. |
| `p_material` Material offtake share | open | % |  |  | Open question: What share of the region's jet fuel demand must signed SAF offtakes cover to be 'material offtake agreements' (rubric H)? No sourced line was found; one candidate is the region's mandated SAF share (ReFuelEU Aviation: 2% from 2025), which would need a by-region value. |

# Shipping

## SHP-T1 Dual-fuel/alternative-fuel vessel order book

A ship ordered today runs for decades on the fuels its engines can burn, so the share of new orders able to use methanol, ammonia or LNG (shp.alt_fuel_vessels) sets how fast the fleet can switch fuel, and it is the demand signal against which producers of low- and zero-GHG marine fuels (shp.green_fuels) finance plants. LNG counts because the metric names it, although fossil LNG cuts emissions far less than methanol or ammonia made from renewable or biogenic sources. The rubric's 'relevant vessel class' is read as all vessel classes ordered by the region's owners combined, because no class is named per region; owner to confirm.

**Actions**

- Newbuild vessels able to run on methanol, ammonia or LNG (dual-fuel)
- Production and bunkering of low- and zero-GHG marine fuels (bio- and e-methanol, green ammonia, bio-LNG)

**Facts**

- Alternative-fuel-capable share of new orders: Share of the new ocean-going merchant vessels (all vessel classes combined) contracted in the latest full calendar year by shipowners based in the region that are specified to run on methanol, ammonia or LNG (dual-fuel or single-fuel engines for that fuel installed at delivery), by gross tonnage; by vessel count only where the source gives no gross-tonnage share. 'Ready' notations (a ship prepared for a later conversion) do not count. Owners are assigned by the domicile of the ordering owner, not by flag state or building yard. Denominator: all new vessels contracted by the same owners in the same year.

**Rating**

- H: Alternative-fuel-capable share of new orders > 30%.
- M: Alternative-fuel-capable share of new orders >= 10%.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_high` High alternative-fuel order share | 30 | % |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), SHP-T1 rating_rubric.H: 'Alternative-fuel-capable vessels exceed 30% of new orders in the relevant vessel class' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric sets H at alternative-fuel-capable vessels exceeding 30% of new orders. No external benchmark for 30% was found, so the framework value is carried over. Owner to confirm. |
| `p_low` Low alternative-fuel order share | 10 | % |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), SHP-T1 rating_rubric.M: 'Alternative-fuel-capable vessels 10-30% of new orders'; L: 'Alternative-fuel-capable vessels below 10% of new orders' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric sets M at 10-30% of new orders and L below 10%, so 10% itself is M. No external benchmark for 10% was found, so the framework value is carried over. Owner to confirm. |

## SHP-R1 Effective carbon price / fuel intensity mandate on shipping

Zero- and low-GHG marine fuels (shp.green_fuels) and the ships that burn them (shp.alt_fuel_vessels) cost more than fossil bunker fuel and conventional ships, and efficiency retrofits (shp.efficiency) pay back faster when fuel and emissions cost more. A carbon price makes every tonne emitted cost money; a binding fuel GHG intensity limit forces fuel switching whatever the price. Both together close the gap from two sides; neither leaves decarbonisation voluntary. The rubric names no price level, so any compliance price counts.

**Actions**

- Newbuild vessels able to run on methanol, ammonia or LNG (dual-fuel)
- Production and bunkering of low- and zero-GHG marine fuels (bio- and e-methanol, green ammonia, bio-LNG)
- Energy-efficiency retrofits and wind-assisted propulsion

**Facts**

- Carbon price applies to shipping: A compliance carbon price (emissions trading system or carbon tax) in force covers greenhouse gas emissions from ships on voyages within, to or from the region in the current or latest compliance year, with an obligation to surrender allowances or pay (monitoring and reporting alone does not count). A scheme in phase-in counts, for example the EU ETS, under which shipping companies surrender allowances for 40% of verified emissions reported for 2024, 70% for 2025 and 100% from 2026 (Article 3gb of Directive 2003/87/EC as amended by Directive (EU) 2023/959). National, EU-wide or global (IMO) measures count once in force; an IMO measure approved or adopted but not yet in force does not count. Schemes of individual provinces, states or cities do not count for the region (for example the Shanghai pilot ETS, which added local shipping in 2016).
- Binding fuel GHG intensity mandate applies: A law or regulation in force requires ships on voyages within, to or from the region to keep the greenhouse gas intensity of the energy used on board below a limit that tightens over time, with penalties for exceeding it, in the current or latest reporting period (for example Regulation (EU) 2023/1805, Article 4(2): the reference value of 91.16 gCO2e/MJ reduced by 2% from 1 January 2025, rising to 80% from 1 January 2050, and Article 23 FuelEU penalties). The same scope rules apply as for the carbon price. Ship design or operational efficiency ratings (for example IMO EEXI and CII) are not fuel intensity mandates.

**Rating**

- H: Carbon price applies to shipping is Yes and Binding fuel GHG intensity mandate applies is Yes.
- M: Carbon price applies to shipping is Yes or Binding fuel GHG intensity mandate applies is Yes.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|

## SHP-D1 Green shipping corridor and cargo owner offtake commitments

The first ships able to burn zero- and near-zero-emission fuels (shp.alt_fuel_vessels) and the plants that make those fuels (shp.green_fuels) need buyers who commit cargo volume and pay the fuel premium; green corridors concentrate that demand on one route. The Global Maritime Forum's 2025 progress report names cargo owners' willingness to pay a higher fuel premium as a key obstacle, which is why H needs committed cargo and a disclosed premium mechanism on more than one corridor. M needs at least one corridor on the region's main trade routes with a signed cargo commitment; an announced corridor without one is L, as the rubric's L ('no active green corridor commitments') reads. The rubric's 'limited committed volume' is not tested as a number.

**Actions**

- Newbuild vessels able to run on methanol, ammonia or LNG (dual-fuel)
- Production and bunkering of low- and zero-GHG marine fuels (bio- and e-methanol, green ammonia, bio-LNG)

**Facts**

- Corridor with signed cargo commitment: At least one green shipping corridor initiative on the region's main trade routes (at least one end is one of the region's main container or bulk ports by cargo throughput, as named by the source), listed as an active initiative in the Global Maritime Forum's latest Annual Progress Report on Green Shipping Corridors (any stage: Initiation, Exploration, Preparation or Realisation) or announced by its participants since that report, for which one or more cargo owners have signed a commitment to ship a stated cargo volume on zero- or near-zero-emission vessels or fuels on that corridor (memoranda of understanding and letters of intent do not count), as of the latest report or announcement. Must be Yes whenever Corridors with committed cargo and a premium mechanism is at least one.
- Corridors with committed cargo and a premium mechanism: Number of green shipping corridor initiatives on the region's main trade routes (at least one end is one of the region's main container or bulk ports by cargo throughput, as named by the source), active, as defined for the fact Corridor with signed cargo commitment, for which (a) one or more cargo owners have signed a commitment to ship a stated cargo volume on zero- or near-zero-emission vessels or fuels on that corridor (memoranda of understanding and letters of intent do not count), and (b) the participants have disclosed how the fuel cost premium is paid (for example a green freight surcharge, a book-and-claim purchase, a cost-pooling mechanism or a cargo owners' alliance tender such as ZEMBA's), as of the latest report or announcement.

**Rating**

- H: Corridors with committed cargo and a premium mechanism > 1 corridors.
- M: Corridor with signed cargo commitment is Yes.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_multiple` Multiple corridors threshold | 1 | corridors |  | Merriam-Webster Dictionary, 'multiple' (adjective), Adjective, sense 1: 'consisting of, including, or involving more than one' <https://www.merriam-webster.com/dictionary/multiple> | Today's rubric H asks for 'multiple' active corridors. 'Multiple' means more than one, so H needs more than one qualifying corridor; this is the word's definition, not a judgement. |

# Heavy-Duty Road Transport

## HDT-T1 Battery-electric/fuel-cell truck TCO parity

Fleet operators buy battery-electric (hdt.bev_trucks) or fuel-cell (hdt.fcev_trucks) trucks at scale only once they cost no more over their life than diesel. Parity usually comes first in regional, depot-based work, where trucks charge at their own base, and last in long-haul. Costs include the purchase incentives a buyer can get today, as today's evidence does. Studies that quote USD per mile convert through the mile row (USD/mile ÷ 1.609344 = USD/km); EUR and CNY use the currency rows.

**Actions**

- Battery-electric heavy trucks
- Hydrogen fuel-cell heavy trucks

**Facts**

- Zero-emission truck TCO, regional: Total cost of ownership per kilometre of a new zero-emission heavy truck (battery-electric, or fuel-cell electric where its cost of ownership is lower) of the region's heaviest truck class (EU and China category N3, US Class 8) in regional or depot-based operation (the truck returns to its base each day and charges or refuels there), bought in the latest year: purchase price net of the purchase incentives available to the buyer, energy, maintenance, tolls and road charges and other operating costs over the source's ownership period, divided by the kilometres driven in that period. Central estimate of the latest regional study (for example ICCT); the zero-emission and diesel figures come from the same study, year and duty cycle.
- Diesel truck TCO, regional: Total cost of ownership per kilometre of a new diesel heavy truck doing the same work of the region's heaviest truck class (EU and China category N3, US Class 8) in regional or depot-based operation (the truck returns to its base each day and charges or refuels there), bought in the latest year: purchase price net of the purchase incentives available to the buyer, energy, maintenance, tolls and road charges and other operating costs over the source's ownership period, divided by the kilometres driven in that period. Central estimate of the latest regional study (for example ICCT); the zero-emission and diesel figures come from the same study, year and duty cycle.
- Zero-emission truck TCO, long-haul: Total cost of ownership per kilometre of a new zero-emission heavy truck (battery-electric, or fuel-cell electric where its cost of ownership is lower) of the region's heaviest truck class (EU and China category N3, US Class 8) in long-haul operation (multi-day or long-distance trips that depend on charging or refuelling away from the base), bought in the latest year: purchase price net of the purchase incentives available to the buyer, energy, maintenance, tolls and road charges and other operating costs over the source's ownership period, divided by the kilometres driven in that period. Central estimate of the latest regional study (for example ICCT); the zero-emission and diesel figures come from the same study, year and duty cycle.
- Diesel truck TCO, long-haul: Total cost of ownership per kilometre of a new diesel heavy truck doing the same work of the region's heaviest truck class (EU and China category N3, US Class 8) in long-haul operation (multi-day or long-distance trips that depend on charging or refuelling away from the base), bought in the latest year: purchase price net of the purchase incentives available to the buyer, energy, maintenance, tolls and road charges and other operating costs over the source's ownership period, divided by the kilometres driven in that period. Central estimate of the latest regional study (for example ICCT); the zero-emission and diesel figures come from the same study, year and duty cycle.
- TCO ratio, regional: Zero-emission truck TCO divided by diesel truck TCO in regional or depot-based operation: 1 is parity, 1.2 means 20% above diesel.
- TCO ratio, long-haul: Zero-emission truck TCO divided by diesel truck TCO in long-haul operation: 1 is parity.

**Rating**

- H: Zero-emission truck TCO, regional <= Diesel truck TCO, regional.
- M: TCO ratio, regional <= 1.2 or TCO ratio, long-haul <= 1.2.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_within` Close to TCO parity | 1.2 |  |  | Transition Barrier Assessment framework, rating rubric before the rule book (verified 2026-08-14), HDT-T1 rating_rubric.M: 'TCO within 20% of parity for depot-based cycles; long-haul not yet competitive'; L: 'TCO more than 20% above diesel for all duty cycles' <https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline/blob/2e97f40523d2e6d397e9b9ccf3a37faefe90bddf/backend/arp/transition_barrier/data/criteria_schema.json> | Today's rubric sets M at a TCO within 20% of parity and L at more than 20% above diesel for all duty cycles, so a ratio of 1.2 or less in any duty cycle keeps a region out of L. No external benchmark for 20% was found, so the framework value is carried over. Owner to confirm. |

## HDT-R1 Zero-emission heavy vehicle sales mandate or CO2 standard

Truck makers build battery-electric (hdt.bev_trucks) and fuel-cell (hdt.fcev_trucks) models in volume, and price them to sell, when a binding standard with penalties requires a rising zero-emission share of their sales. An announced standard, or one that is binding but weak in the near term, signals direction but forces little production. 'Material ZEV share within the assessment horizon' is read as the share the Global MOU on zero-emission medium- and heavy-duty vehicles sets for 2030, applied to all regions.

**Actions**

- Battery-electric heavy trucks
- Hydrogen fuel-cell heavy trucks

**Facts**

- Heavy truck CO2 standard or ZEV mandate: in_force: a national or EU-wide law or regulation applies to makers of new heavy trucks in the current model or reporting year and sets either a CO2 emission (or fuel-consumption) limit or a minimum zero-emission share of sales; announced: such a standard or mandate is adopted or formally proposed by the government but its first compliance year has not started; none: neither exists, or it has been repealed. Rules of individual states or provinces count as announced for the region where they can legally be enforced; a state rule whose federal waiver Congress has disapproved counts as none (for example California's Advanced Clean Trucks waiver, disapproved by H.J.Res.87, P.L. 119-15, approved 12 June 2025).
- Penalties for missing the standard: The law requires fines or other financial penalties on manufacturers that miss the standard or mandate (for example the excess CO2 emissions premium in Article 8(1) of Regulation (EU) 2019/1242, as amended by Regulation (EU) 2024/1610).
- Required ZEV share of new heavy truck sales in 2030: Share of new heavy truck sales in 2030 that must be zero-emission for manufacturers to comply with the standard or mandate in force: the share the law sets (ZEV mandate) or, for a CO2 standard, the share that the regulator's impact assessment or an independent analysis (for example ICCT) estimates is needed to meet the 2030 target. Zero where no requirement applies in 2030.

**Rating**

- H: Heavy truck CO2 standard or ZEV mandate = in_force and Penalties for missing the standard is Yes and Required ZEV share of new heavy truck sales in 2030 >= 30%.
- M: Heavy truck CO2 standard or ZEV mandate in in_force, announced.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_material` Material ZEV share by 2030 | 30 | % |  | Global Memorandum of Understanding on Zero-Emission Medium- and Heavy-Duty Vehicles (Global Drive to Zero / CALSTART and the Netherlands, 2021), Section 1 'Overall ambition': 'enable ZE-MHDVs to reach 30% of sales of new MHDVs by 2030, as well as enable a full transition to ZE-MHDVs in new fleets by 2040'; footnote 1: MHDVs are vehicles 'with gross vehicle weight above 3,500 kilograms' <https://globaldrivetozero.org/site/wp-content/uploads/2021/11/Global-MOU-ZE-MHDVs.pdf> | The rubric's 'material ZEV share within the assessment horizon' has no number. The Global MOU on zero-emission medium- and heavy-duty vehicles, signed by governments since COP26, sets 30% of new sales by 2030 as its interim goal on the way to a full transition by 2040; a standard that requires at least that share matches what its signatories regard as on track. One benchmark is applied to all regions. The 2030 horizon and the scope are imported from the MOU: its 30% covers all medium- and heavy-duty vehicles above 3.5 tonnes, buses included, while the fact here is heavy-truck sales; the MOU is non-binding and serves only as the line. Owner to confirm both. |

## HDT-D1 Charging/refuelling infrastructure density on freight corridors

Battery-electric (hdt.bev_trucks) and fuel-cell (hdt.fcev_trucks) trucks can leave depot work for long-haul only where public high-power charging (hdt.public_charging) or hydrogen refuelling (hdt.h2_refuelling) lines the main freight corridors. H uses the density the EU requires on its core network by 2030 so that heavy trucks can travel throughout the Union, applied to all regions. A corridor average can hide gaps: the EU rule also sets a maximum distance between charging pools, which this density does not test.

**Actions**

- Public high-power charging for heavy trucks on freight corridors
- Public hydrogen refuelling for heavy trucks
- Battery-electric heavy trucks
- Hydrogen fuel-cell heavy trucks

**Facts**

- Heavy-duty charging and refuelling density on primary freight corridors: Publicly accessible recharging points dedicated to heavy-duty electric vehicles with an individual power output of at least 350 kW, plus publicly accessible hydrogen refuelling points suitable for heavy-duty vehicles, located along the region's primary freight corridors, per 100 km of corridor in each direction of travel (a site serving both directions counts for each direction). Primary freight corridors: the TEN-T core road network in the EU; in the US and China, the national highway or expressway network the source uses for freight. Latest count.

**Rating**

- H: Heavy-duty charging and refuelling density on primary freight corridors >= 3.33 points per 100 km.
- M: Heavy-duty charging and refuelling density on primary freight corridors >= [open: Density above minimal].
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_sufficient` Density for unconstrained long-haul | 3.33 | points per 100 km |  | Regulation (EU) 2023/1804 on the deployment of alternative fuels infrastructure (AFIR), Article 4(1)(c): 'by 31 December 2030, along the TEN-T core road network, publicly accessible recharging pools dedicated to heavy-duty electric vehicles are deployed in each direction of travel with a maximum distance of 60 km between them and that each recharging pool offers a power output of at least 3 600 kW and includes at least two recharging points with an individual power output of at least 350 kW'; recital 19 <https://eur-lex.europa.eu/eli/reg/2023/1804/oj/eng> | By 31 December 2030 the EU requires heavy-duty recharging pools on the TEN-T core network in each direction at most 60 km apart, each with at least two recharging points of at least 350 kW: at least 2 points per 60 km, or 3.33 points per 100 km per direction (200 ÷ 60 = 3.333; rounding down to 3.33 is deliberately lenient, so a network that just meets the 60 km rule is not missed by rounding). Recital 19 gives the purpose: enough fast recharging points for heavy-duty vehicles 'to ensure full connectivity throughout the Union'. That is the rubric's 'unconstrained long-haul operation'. One benchmark is applied to all regions. |
| `p_minimal` Density above minimal | open | points per 100 km |  |  | Open question: Below what density of public heavy-duty charging and hydrogen refuelling points per 100 km of primary freight corridor is the infrastructure 'minimal' (rubric L), restricting operation to depot-based captive fleets? No sourced line was found. AFIR's first milestone (Article 4(1)(a): by 31 December 2025, pools with at least one 350 kW point along at least 15% of the TEN-T network length in each direction) is a coverage share, not a density. |

# Oil & Gas Upstream

## OGU-T1 Methane abatement technology deployment

Leak detection and repair (ogu.ldar) and ending routine flaring (ogu.flaring) are the core upstream methane abatement measures, and they cut methane only where operators actually run them. H needs them across a majority of the region's production; M needs them at the region's largest operators, defined in words rather than by a production share; owner to confirm. Production counts where it is located: for the EU, sites in the EU, not North Sea fields outside it run by EU-based companies.

**Actions**

- Methane leak detection and repair (LDAR)
- Ending routine flaring and venting (flare gas recovery or re-injection)

**Facts**

- Production covered by LDAR and flaring reduction: Share of the region's upstream oil and gas production in the latest full year (energy-equivalent volume produced at sites located in the region) that comes from sites that both run a leak detection and repair programme (periodic surveys of components for methane leaks with repair deadlines, whether required by regulation or run voluntarily) and use flaring reduction (no routine flaring, or associated gas recovered, used or re-injected). Denominator: all upstream oil and gas production in the region in the same year.
- Deployed at the region's major operators: The largest upstream producers in the region (the national oil companies, and the companies with the largest shares of the region's production as named by the source) run LDAR programmes and flaring reduction across their operations in the region, as they report or as a regulator or the IEA reports.

**Rating**

- H: Production covered by LDAR and flaring reduction > 50%.
- M: Deployed at the region's major operators is Yes.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_majority` Majority of production | 50 | % |  | Merriam-Webster Dictionary, 'majority' (noun), Noun, sense 1a: 'a number or percentage equaling more than half of a total' <https://www.merriam-webster.com/dictionary/majority> | Today's rubric H asks for deployment 'across a majority of regional production'. A majority is more than half, so H needs coverage above 50%; this is the word's definition, not a judgement. |

## OGU-R1 Methane regulation and fee structure

Without a binding limit or a fee, leak repair (ogu.ldar) and ending routine flaring and venting (ogu.flaring) stay voluntary, and operators that skip them produce more cheaply. A limit or fee in force on existing operations, with penalties, is H; one that covers only new or modified sources, or whose deadlines lie ahead, is phase-in (M). A fee counts only where it can be collected now, so the US Waste Emissions Charge does not count. Three readings are open for the owner, with these US outcomes: (1) limits count and a limit on new or modified sources only is phase-in, as written here: US M. (2) A limit on new or modified sources only counts as in force: US H. (3) Fee-only, where performance standards do not count (today's US L): US L, and the EU's H, which rests on limits, would then need to be re-justified. The rubric's 'limit and/or fee' supports counting limits.

**Actions**

- Methane leak detection and repair (LDAR)
- Ending routine flaring and venting (flare gas recovery or re-injection)

**Facts**

- Binding methane limit or fee: in_force: a national or EU-wide law or regulation in force sets, for existing upstream oil and gas operations in the current year, a binding methane limit (a cap on methane emissions or intensity, a ban on routine venting or flaring, or mandatory leak detection and repair with repair deadlines) or a methane fee that the authority collects for the current year; phase_in: such a limit or fee is adopted or formally proposed but applies so far only to new or modified sources, or its compliance deadlines for existing operations have not arrived or have been extended into the future; none: neither, or only monitoring, reporting or non-binding action plans and targets. A fee counts only where the authority can collect it for the current year: the US Waste Emissions Charge does not count, because Congress nullified its implementing rule (H.J.Res.35, P.L. 119-2, approved 14 March 2025) and P.L. 119-21, section 60012(b), replaced 'calendar year 2024' with 'calendar year 2034' in Clean Air Act section 136(g).
- Enforcement mechanism: The law requires penalties for non-compliance (fines or periodic penalty payments) and gives an authority power to inspect or verify (for example Regulation (EU) 2024/1787, Article 33).

**Rating**

- H: Binding methane limit or fee = in_force and Enforcement mechanism is Yes.
- M: Binding methane limit or fee in in_force, phase_in.
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|

## OGU-D1 Market demand trajectory / structural decline exposure

Here H means lower stranding risk, as today's rubric says: stable demand keeps the cash flow and field life over which upstream operators recover what they spend cutting their own emissions, such as electrifying operations (ogu.electrification) or recovering flare gas (ogu.flaring). Under structural decline fields close earlier and that spending pays back over fewer years. The rubric reads only the stated-policies trajectory, so the announced-pledges scenario named in the metric is not a fact here. Its lines between stable, moderate and structural decline have no numbers and are open.

**Actions**

- Electrification of upstream operations (power from shore or renewables)
- Ending routine flaring and venting (flare gas recovery or re-injection)

**Facts**

- Oil and gas demand change to 2035 (stated policies): Percentage change in the region's combined oil and natural gas demand (in energy units, oil and gas added together) from the base year of the latest IEA World Energy Outlook (2024 where available) to 2035 under the IEA Stated Policies Scenario (STEPS), for the WEO's European Union, United States or China region. Negative for a decline.

**Rating**

- H: Oil and gas demand change to 2035 (stated policies) >= [open: Largest decline still stable].
- M: Oil and gas demand change to 2035 (stated policies) >= [open: Decline short of structural].
- L: Otherwise (neither H nor M holds).

**Parameters**

| Parameter | Value | Unit | Overrides | Source | Rationale |
|---|---|---|---|---|---|
| `p_stable` Largest decline still stable | open | % |  |  | Open question: What is the largest fall in combined oil and gas demand to 2035 under stated policies that still counts as 'stable' (rubric H: stable or growing)? The rubric's M ('flat to moderate decline') overlaps H ('stable'), so the line needs a number; no sourced line was found. A line at 0% would make H mean no decline. |
| `p_structural` Decline short of structural | open | % |  |  | Open question: What fall in combined oil and gas demand to 2035 under stated policies marks a 'structural decline' (rubric L) rather than a 'moderate decline' (rubric M)? No sourced line was found. |
