# ACT methodology for transition plan assessment: what to add beyond capex

Which parts of ACT (ACT Framework v2.1, ACT Core v1.0 and the ACT sector methodologies) would help
the platform judge whether a hard-to-abate company's transition plan is credible, beyond what is
already built. The doc reviews every ACT module and indicator, says what each needs and whether it
fits the platform's rules, and ends with a ranked shortlist.

Status: **research note, 2026-10-20.** It builds on `docs/CAPEX_ALIGNMENT_METHODOLOGY_RESEARCH.md`
(cited as "research §n") and the spec `docs/superpowers/specs/2026-10-19-transition-plan-alignment-design.md`
(cited as "spec §n"). It does not repeat research §13 (ACT detail) or §9 (owner decisions).

Evidence tags, as in the earlier research:

- **[verified]**: read in the ACT/WBA/ADEME document itself, on the page given.
- **[not verified]**: not traced to a primary document. See section 17.
- **[ours]**: a mapping, rule or proposal made in this note. No ACT document says it.

---

## 1. Summary

**Headline.** The platform already covers the parts of ACT that test *money* (D01.a capex share,
R&D tests, B02.d). The largest gap is the parts that test *delivery and consistency*: whether the
company has hit its own past targets, whether its listed actions add up to its target, whether it
has committed to phasing out its high-carbon business, and whether its plan contradicts itself.
ACT publishes formulas or bands for all four. Each can be computed in code from facts that
reports disclose with a quote and page.

**Ranked shortlist** (details in section 13):

| # | Addition | ACT source | Size | Usefulness |
|---|---|---|---|---|
| 1 | Target achievement and progress ratio | GE 1.4, Generic pp.31–36 | S | High |
| 2 | Abatement coverage: listed actions' savings vs the target gap | ACT Core B02.c p.37; Framework p.61 | S | High |
| 3 | Consistency flags taken from the narrative "Consistency and credibility" questions | Framework pp.22, 60–64 | M | High |
| 4 | Phase-out commitment for the high-carbon business: share and date | GE 9.2 dim. 3, Generic pp.139–140; ACT Core D02.a p.66 | S | High |
| 5 | Sector delivery KPIs with ACT bands (cement alternative fuels, chemical electrolytic H2, truck ZEV share, O&G CCS capex, fleet low-carbon share) | CEM 2.4a; CH 4.3; AU 4.4; OG 2.6; TR 2.4 | M | High (cement, chemicals, O&G); medium (others) |
| 6 | Plan-governance facts with computable ACT bands (plan horizon, review cycle, carbon-price use, climate pay level) | GE 5.3, 5.4, 5.5; EU 5.6; ACT Core C01.d | S–M | Medium |
| 7 | Carbon-price assumption vs a low-carbon-scenario price | GE 5.3 p.89, GE 5.5 p.96 | S | Medium |
| 8 | F01 realignment factor, a 1.5°C trajectory check on reported emissions | ACT Core F01, pp.80–82 | L | Medium-high, later phase |

**Out-of-scope items re-examined** (section 12): bring back **F01** later (rank 8) and **parts of
the narrative score** as code flags (rank 3). Keep **locked-in emissions**, **the trend score**,
**E01** and **patents** out, for the reasons given there.

**One small fix found on the way.** The benchmarks file maps `steel.h2_dri` and `steel.ccus` to
`null` because ACT Core has no steel lever wording (spec §2). ACT Iron & Steel has wording for
both: "Hydrogen DRI (using low- or zero-GHG hydrogen)" (IS p.117) and "Development of CCU/CCS
complete solutions" (IS p.120). [verified] Both appear as business-model activities (module 9),
not as ACT Core levers, so the owner should decide whether that wording counts (section 16).

---

## 2. Sources and method

All PDFs were downloaded from actinitiative.org on 2026-10-20 and converted to text page by page.
In every file the printed page number equals the PDF page number, so one number is given.

| Short | Document | PDF creation date | Licence line |
|---|---|---|---|
| **Framework** | [ACT Framework v2.1](https://actinitiative.org/wp-content/uploads/framework-2.1.pdf) | 2025-12-11 | © WBA and ADEME 2025 |
| **Core** | [ACT Core v1.0, 24 Feb 2025](https://actinitiative.org/wp-content/uploads/pdf/act-core-methodology.pdf) | 2025-02-26 | © WBA, ADEME 2025 |
| **GE** | [ACT Generic v2.0](https://actinitiative.org/wp-content/uploads/act-generic-v2.0.pdf) | 2026-09-29 | © WBA, ADEME, CDP 2023 |
| **EU** | [ACT Electricity v2.0](https://actinitiative.org/wp-content/uploads/act-electricity-v2.0.pdf) | 2026-08-31 | © WBA, ADEME, CDP |
| **OG** | [ACT Oil & Gas](https://actinitiative.org/wp-content/uploads/act-og-methodology_vf.pdf) | 2026-08-31 | © CDP, ADEME 2021 |
| **IS** | [ACT Iron & Steel v2.0](https://actinitiative.org/wp-content/uploads/act-iron-steel-methodo_v2.0.pdf) | 2026-08-31 | © CDP, ADEME 2022 |
| **CEM** | [ACT Cement v2.0](https://actinitiative.org/wp-content/uploads/act-cement-v2.0.pdf) | 2026-08-31 | © CDP, ADEME 2021 |
| **CH** | [ACT Chemicals](https://actinitiative.org/wp-content/uploads/act-chemicals-final.pdf) | 2026-08-31 | © CDP, ADEME 2024 |
| **TR** | [ACT Transport v2.1, March 2022](https://actinitiative.org/wp-content/uploads/act-transport-v2.1.pdf) | 2026-08-31 | © CDP, ADEME 2021 |
| **AU** | [ACT Automotive v2.0](https://actinitiative.org/wp-content/uploads/act-auto-v2.0.pdf) | 2026-08-31 | © WBA, ADEME, CDP 2024 |

- **Sector coverage.** ACT has sector methods for power, oil and gas, steel, cement, chemicals,
  transport (airlines, shipping and road freight operators) and automotive (vehicle makers). It
  has none for mining; mining falls back to Generic and ACT Core. [verified, method list on the
  [ACT methodologies page](https://actinitiative.org/act-methodologies/)]
- **Indicator numbering.** Framework Table 4 (p.17) numbers Generic targets 1.1–1.5, with scope 3
  split into upstream (1.2) and downstream (1.3). The Generic v2.0 PDF itself numbers them GE 1.1
  scope 1+2, GE 1.2 scope 3, GE 1.3 time horizon, GE 1.4 achievement (GE pp.3, 19–36). This note
  uses the Generic PDF numbers. [verified]
- **Fixed module weights.** The Framework fixes the weights of modules 1, 5, 8 and 9 for all
  methods and lets 2, 3, 4, 6 and 7 vary by sector (Framework p.19). [verified] Weights matter
  here only as a signal of what ACT thinks is informative, because the platform does not
  reproduce the performance score.
- **What fits the platform.** Owner rules: the model never outputs a score; code computes scores
  from extracted facts; precision first. An ACT indicator therefore fits only if (a) its inputs
  are facts a report states, with a quote and page, and (b) its scoring rule is a formula or a
  band on those facts. A maturity matrix fits only for the rows whose levels are counts, shares,
  years or yes/no facts. Rows whose levels are words like "comprehensive" or "credible" need an
  assessor and are marked "judgement". ACT Core's own principles back this: "Conservativeness –
  Any assumptions … should not overestimate progress or improvements if supporting evidence is
  not available" (Core p.8). [verified]

---

## 3. How to read the module tables

Each module (sections 4–11) has one table. Columns:

1. **What it measures / how ACT scores it**, with page.
2. **Data** the company must disclose.
3. **Extract**: can it be extracted with quote and page from reports or plans? *Yes*; *partly*
   (often missing or only in CDP); *no* (needs external data).
4. **Code**: *yes* (formula or band on facts); *partly* (some rows); *no* (assessor judgement).
5. **Use**: usefulness for judging plan credibility here: **H**igh, **M**edium, **L**ow.
6. **Link** to what exists: benchmarks file (`transition_alignment/data/benchmarks.json`), barrier
   criteria (`transition_barrier/data/criteria_schema.json`), B02 (spec §5), the 64-indicator set
   (`transition_plan/data/indicators.json`, cited as "#n") and its helper fields
   (`tp_h_target_pct`, `tp_h_target_year`, `tp_h_scope{1,2,3}_emissions`,
   `tp_h_scope{1,2,3}_intensity` in `presets/transition_plan.py`).

Built items (D01.a, R&D tests, redlines, B02.a–d, barrier matching) are not repeated as new. Where
an indicator could extend one of them, the Link column says so.

---

## 4. Module 1: Targets (fixed 15%; Framework p.19)

| Indicator | What / how scored | Data | Extract | Code | Use | Link |
|---|---|---|---|---|---|---|
| **GE 1.1** S1+2 target alignment | Trend ratio of the company's target pathway vs its benchmark pathway; score = ratio, capped at 100%, 0 if the target trend rises. If coverage < 95% of S1+2, score × coverage. Two dimensions, 50/50 (GE pp.19–24) | Target year, base year, reduction, coverage %, share of emission sources | Yes | Yes, once a sector pathway is chosen | M | Needs a pathway per sector (none in the benchmarks file); `tp_h_target_*`. Overlaps E01. |
| **GE 1.2** S3 target alignment | Same calculation for scope 3 (GE pp.25–28) | S3 target by category | Yes | Yes, with a pathway | L | O&G and autos only, where S3 cat 11 dominates |
| **GE 1.3** time horizon | LT = 2050 − RY; Te = longest target year − RY. Dim. 1: Te > LT → 50%; 33%·LT < Te < LT → 75%·Te/LT − 25%; Te ≤ 33%·LT → 0%. Dim. 2: gaps between target years ≤ 5 years over all of Te → 50%, falling by 10 points per 20% of Te not covered. Coverage < 95% scales the score (GE pp.28–31) | Every target year and its scopes | Yes | **Yes** | M | #4, #9 ask yes/no only; code can give the ACT band from target years |
| **GE 1.4** achievement of past and current targets | Dim. 1 (25%): for targets with a target year in the past 10 years, a = (E_base − E_horizon)/(E_base − T_horizon); a ≥ 1 → 100%, 0.5 < a < 1 → 100%·(2a − 1), a ≤ 0.5 → 0%. Dim. 2 (75%): running targets, p = a / %time, %time = (t_ref − t_RY)/(t_ref − t_horizon); p ≥ 1 → 100%, else p (GE pp.31–34) | Per target: base year, start year, target year, reduction %, % achieved, coverage | Yes | **Yes** | **H** | **Shortlist #1.** Uses `tp_h_target_*` and `tp_h_scope*_emissions`; needs base year and base-year emissions |
| **Core A01.a** GHG reporting | Matrix: S1+2 only → separate S1/S2 → material S3 categories → all S3 categories with method → plus independent verification (Core pp.19–21). Table 9 sets the minimum S3 categories per industry (Core pp.100–102) | Inventory by scope and category, method, assurance | Yes | **Yes** | M | #46–49 are yes/no; Table 9 gives the per-sector "material category" list (section 11) |
| **Core A01.b** targets | Near term ≤ 2030 and long term net zero ≤ 2050; ≥ 95% S1+2 and ≥ 90% S3 coverage; absolute or physical intensity only, "financial intensity … not accepted"; % targets need a baseline with the same coverage (Core pp.21–23) | Target year, unit, coverage, baseline | Yes | **Yes** | M | #1–9 cover parts; the coverage and unit tests are new and cheap |
| **Core A01.c** 1.5°C pathway used | Met if SBTi-validated, or a listed pathway is cited, or, without a pathway, S1+2 ≥ 50% by 2030 from a base ≥ 2019 (4.2% × (target year − 2019) if earlier), net zero ≤ 2050, **≤ 2040 for electric utilities and maritime**; S3 ≥ 30% near term (Core pp.24–25) | Target %, year, base year, pathway cited | Yes | **Yes** | M | #5 and #10; the rule `tp_r_ambition_5` already flags a YES on #5 against the numbers. The 2040 rule for power and shipping is new |
| **Core A01.d** no offsets or avoided emissions | Met if targets exclude avoided emissions and credits; residual emissions ≤ 10% of baseline; credits only for residuals after net zero (Core pp.25–27) | Credits planned, residual % | Yes | Yes | M | #11, #12. A residual > 10% is a numeric flag |
| **Core E01.a–d** current target alignment | Company target ÷ company-specific 1.5°C target (c1.5C, built from 2019 with budget recovery); met if ≤ 1.10; intensity targets converted with activity, 1.5%/yr growth assumed if none (Core pp.70–79) | Annual S1+2, S3 from 2019 (≥ 4 years), target, activity forecast | Partly | Yes, with a pathway | M | Same machinery as F01 (section 10). Not shortlisted: F01 tests what happened, E01 what is promised |

---

## 5. Module 2: Material investment (0–35%)

| Indicator | What / how scored | Data | Extract | Code | Use | Link |
|---|---|---|---|---|---|---|
| **GE 2.1** past S1+2 trend | Gradient of RY−5…RY intensity vs benchmark gradient RY…RY+5: rising → 0; ratio r if 0 < r < 1; 100% if r ≥ 1 or already below the 2050 benchmark (GE pp.37–41) | S1+2 and activity, RY and RY−5 | Yes | Yes, with a pathway | M | `tp_h_scope*_intensity` series; the rules `tp_r_progress_*` test direction only |
| **GE 2.2** future S1+2 trend | A_future = (EI(RY) − EI(RY+5)) / (EI_B(RY) − EI_B(RY+5)), same cases. Future emissions come from assets, **"or … by using company's short-term plans to decrease scope 1+2 emissions"**, else score 0 (GE pp.42–45) | RY and RY+5 emissions or intensity | Partly | Yes, with a pathway | M | The "short-term plans" route can use B02.c savings (shortlist #2) |
| GE 2.3 / D01.a capex share | **Built** (spec §3) | | | | | Extension: OG 2.6 CCS share (below) |
| **GE 2.4** locked-in emissions (own fleet/buildings) and the sector versions EU 2.2, IS 2.3, CEM 2.2a, CH 2.3, TR 2.3 | rLB = locked-in ÷ budget over RY…RY+15; score 100% if rLB ≤ rSA, linear to 0% at rLB = 1.5 (EU pp.39–46; IS pp.55–63). **Transport uses 1.1, not 1.5**: "a leeway of 10% … score drops to 0% when rLB ≥ 1.1" (TR p.53) | Every existing and planned asset: type, route, capacity, production, emission factor, commissioning year, lifetime, ownership; projected activity Y+5, Y+15 (IS p.55; CEM p.47) | No (asset registers are rarely in reports) | Yes, once data exist | M | Out of scope; re-examined in section 12 |
| **EU 2.3** future intensity of generation | As GE 2.2, from planned capacity; if not estimable, extrapolate the last 5 years (EU pp.46–49) | Generation intensity RY, RY+5 | Partly | Yes | M | Power only |
| **OG 2.4** unsanctioned projects in budget | Score = 100% − SUP, Carbon Tracker's share of STEPS capex outside the SDS budget (OG pp.49–51) | Carbon Tracker data | No | Yes | L | Licence-bound third-party data (research §10.2); the NZE redline covers the same risk |
| **OG 2.6** CCS/CCUS/CDR capex share | average(S(Y)/CB; S(Y+5)/CB), capped at 100%; a plan shorter than 5 years is multiplied by years/5; EOR excluded; benchmark from McCollum et al. 2018 (OG pp.56–59; 5% per research §4) | Planned CCS/CDR capex share, Y and Y+5 | Partly | **Yes** | M | **Shortlist #5.** A second capex test in the benchmarks file for Oil & Gas Upstream |
| **IS 2.2 / 2.5** past and future intensity per route | As GE 2.1/2.2, per technical route (BF-BOF, DRI, EAF) (IS pp.52–55, 67–70) | Production and intensity per route | Partly | Yes | M | Route split makes the EAF claim (`steel.scrap_eaf`) checkable |
| **IS 2.6** scrap reduction strategy | Matrix on commitments, method, monitoring, each 1/3 (IS pp.70–72) | Strategy description | Yes | No (judgement) | L | Pre-consumer scrap; a minor lever |
| **IS 2.7** co-products | Dim. 1 = 1 − % solid co-products landfilled; dim. 2 = 1 − % off-gases flared; 50/50 (IS p.73) | Two percentages | Partly | **Yes** | L | Cheap, but weakly linked to the main levers |
| **CEM 2.4a** alternative fuels | Share of alternative fuels (biomass included, CCS excluded): < 5% Basic; 5–10% Standard; 11–20% Advanced; 21–30% Next practice; > 30% Low-carbon aligned. ETP 2017 B2DS reference: world 5% (2014), 11% (2030), 23% (2050); OECD 19/24/30%; non-OECD 2/10/22% (CEM pp.49–50) | Thermal substitution rate | **Yes** (widely reported) | **Yes** | **H** for cement | **Shortlist #5.** Delivery evidence for `cement.alt_fuels` |
| **CH 2.5** energy management | Matrix (CH pp.57–66) | Energy efficiency and low-carbon electricity facts | Partly | Partly | L | |
| **TR 2.4** low-carbon vehicles and energies | F_LCV(t) = low-carbon vehicles ÷ all vehicles per plan year; ICE vehicles count pro rata to contracted low-carbon fuel, only with "contractual agreements with energy suppliers and … a verification process"; r = F_LCV / SB_LCV(t), averaged over plan years, capped at 1 (TR pp.53–56) | Fleet size and low-carbon count per plan year; fuel contracts | Partly | Yes, once a benchmark curve is chosen | M | **Shortlist #5.** ACT prints SB_LCV(t) only as a chart (TR p.55), so its values cannot be read; use an IEA NZE milestone instead [ours] |

---

## 6. Module 3: Intangible investment (0–10%)

| Indicator | What / how scored | Data | Extract | Code | Use | Link |
|---|---|---|---|---|---|---|
| GE 3.1 and sector R&D | **Built** (steel 80%/65%, cement 5% of capex, aviation and shipping 80%) | | | | | Extension: OG 3.2 below; consistency flag (shortlist #3) |
| **GE 3.2** low-carbon patents | Share of CPC Y02/Y04S patents in all patents over 5 years; > 80% gets full score (GE pp.59–61) | Patent counts (external) | No | Yes | L | Stays out (section 12) |
| **OG 3.2** CDR R&D share | Share of R&D in carbon removal (OG pp.65–68) | R&D split | Partly | Yes | L | Rarely disclosed |
| **TR 3.2** digital solutions; **TR 3.3** training | Investment in digital optimisation; employee training (TR pp.59–62) | Spend, training hours | Partly | Partly | L | Weak signal for plan credibility |

---

## 7. Module 4: Sold product performance (0–35%)

| Indicator | What / how scored | Data | Extract | Code | Use | Link |
|---|---|---|---|---|---|---|
| **GE 4.1** product interventions | Matrix scored by the analyst on hotspot coverage, maturity, ambition (GE pp.62–66) | Interventions per product | Yes | No (judgement) | L | |
| **GE 4.2** past product trend | As GE 2.1 for S3 (GE pp.66–69) | S3 per product, RY−5 | Partly | Yes | L | |
| **GE 4.3 / AU 4.3** locked-in sold products | Cumulative use-phase emissions of sales RY…RY+5 vs budget; only for long-lived products (≥ 10 years) (GE pp.69–74; AU pp.52–54) | Sales forecast, use-phase factors | Partly | Yes | L | Truck makers only |
| **GE 4.4** subcontracted transport | Matrix; × 100/80/60/40% by spot-contract share (GE pp.74–79) | Subcontractor knowledge | Partly | Partly | L | |
| **AU 4.4** low-carbon vehicle share | Dim. 1 (50%): mean over RY−5…RY of min(company share / benchmark share, 1); dim. 2 (50%): gradient of planned share RY…RY+3 vs an SDA path converging to 100% in 2035, ratio capped at 1; benchmark: IEA NZE 2023 EV sales share (AU pp.55–56) | ZEV share of sales, past and planned | **Yes** | **Yes** | M for HDT makers (ISIC 2910) | **Shortlist #5.** Delivery evidence for `hdt.bev_trucks`, `hdt.fcev_trucks`; barrier HDT-R1. The NZE benchmark is for light vehicles; trucks need the NZE heavy-truck milestone [ours] |
| **CH 4.3** low-carbon H2 feedstock | Ammonia from electrolytic H2: < 5 / < 15 / < 30 / < 50 / > 50% of tonnage; methanol < 10 / < 25 / < 45 / < 75 / > 75%; each weighted by its tonnage share, 50% together; plus share of electrolysis power that is low-carbon < 25 / 25–49 / 50–70 / 71–90 / > 90%, 50% (CH pp.76–78) | Tonnes of ammonia and methanol, electrolytic share, power source | Partly | **Yes** | **H** for chemicals | **Shortlist #5.** Delivery evidence for `chem.low_carbon_h2`; barrier CHM-T1; the `h2_cost` assumption |
| **CH 4.4** alternative feedstocks | Bio-based share < 1 / < 2 / < 3 / < 4 / > 4% by weight plus certified-sourcing share; MTO/MTA share (CH pp.78–83) | Bio-based %, certification % | Partly | Yes | M | |
| **EU 4.3** low-carbon retail sourcing | Sum of shares × weight: unbundled market 0%, EAC 50%, corporate PPA 100%; certified power only if ≤ 100 gCO2e/kWh life-cycle (EU pp.65–66) | % of retailed power by source | Partly | **Yes** | L (retailers only) | Barrier PWR-D1 (PPA depth) |
| **EU 4.4 / OG 4.4** energy-efficiency services share | Revenue share (EU pp.67–69; OG pp.79–81) | Revenue split | Partly | Yes | L | |
| **OG 4.3** future low-carbon products share | average(S(Y)/CB; S(Y+5)/CB), corrective ratio for short plans (OG pp.76–78) | Planned low-carbon revenue Y+5 | Partly | Yes | M | Extends the D02/green revenue fields with a Y+5 value |
| **CEM 4.2b / 4.3b**, **IS 4.2** | Blenders' electricity and purchased clinker; purchased steel interventions (CEM pp.58–62; IS pp.83–87) | | Partly | Partly | L | Grinding-only and re-rolling companies |

---

## 8. Module 5: Management (fixed 10%)

| Indicator | What / how scored | Data | Extract | Code | Use | Link |
|---|---|---|---|---|---|---|
| **GE 5.1** oversight | Level of the person or committee in charge: none / Level 4 … Level 1 (board, CEO) (GE pp.80–82) | Who is responsible | Yes | **Yes** (level is a fact) | L | #13, #17; Core C01.a |
| **GE 5.2** oversight capability | Board expertise matrix (GE pp.82–85) | Board skills | Yes | Partly | L | #14; Core C01.c "at least 2 instances" (Core pp.52–53) is a count |
| **GE 5.3** transition plan | 10 sub-dimensions, 10% each (GE pp.85–90). **Computable rows**: *timescale* (plan end ≤ RY+3 / RY+4–10 / RY+11–20 / RY+21–2049 / 2050 or later, and net zero before 2050 counts as top); *scope* (not defined / < 50% / > 50% of GHG / all operations / plus value chain); *review* (none / commitment without cycle or process / cycle or process / both, but less often than every 5 years / at least every 5 years with a process); *progress reporting* (none / commitment without cycle or feedback / cycle or feedback / less than annual with feedback / annual with stakeholder feedback); *carbon price* (none / studied / qualitative / embedded in cost calculations / aligned with a low-carbon scenario, e.g. IEA WEO 2019 Annex B). **Judgement rows**: measure of success (SMART), financial content, short-term actions, long-term actions, use of scenario results | Plan document | Yes | Partly (5 of 10 rows) | M | **Shortlist #6, #7.** Short- and long-term action rows overlap B02.b |
| **GE 5.4** incentives | Who benefits (50%): any other answer (Basic), Level 4 … Level 1 (Low-carbon aligned); type (50%): no incentives (Basic) / GHG metrics in annual bonus (Standard) / GHG metrics in LTIP (Advanced) / LTIP aligned with the plan's timescale and targets (top printed cell) (GE pp.90–93) | Pay plans, metric types, who | **Yes** | **Yes** | M | **Shortlist #6.** `presets/remuneration.py` already extracts climate metric types per CEO/exco and STI/LTI |
| **GE 5.5** scenario testing | Scope 25%, timescale 20%, risk categories assessed (0–4 of market/technology, reputation, policy/legal, physical) 10%, number of scenarios (0 / 1 / 2 / ≥ 3 incl. low-carbon) 10%, parameters (1–2 / 3–4 / ≥ 5) 15%, results (qualitative … value at risk) 10%, carbon price aligned with a low-carbon scenario 10% (GE pp.93–97) | Scenario analysis disclosure | Yes | Mostly (counts and bands) | M | #24, #25. Core B02.e asks the same in words (Core pp.38–39) |
| **EU 5.6** fossil power incentives | Basic if any pay component rewards growth in fossil generation capacity, or it is unclear; Low-carbon aligned if none (EU pp.90–91) | Pay plan metrics | Yes | **Yes** | M for power | **Shortlist #6.** A "production growth" metric in pay is a remuneration-preset fact |
| **Core B01.a** transition plan | Met if a standalone plan exists, or 4 of 5 TPT fundamentals (ambition, metrics/targets, strategy, engagement, governance) are evidenced (Core pp.27–30) | Plan or fundamentals | Yes | Yes (count of 5 yes/no facts) | M | #13–25 cover parts. "Which plan counts" (spec §4) already needs the plan document |
| **Core B01.b** plan coverage | All business units; exclusions not material (Core p.31) | Plan scope | Yes | Partly | M | Same fact as GE 5.3 scope row |
| **Core B01.c** periodic review | Plan reviewed periodically (Core p.31) | Review statement | Yes | Yes | L | GE 5.3 review row gives a band |
| **Core B02.e** risks and uncertainties | "Compelling evidence" that levers were checked against assumptions, policy changes, macro trends, technology, demand, physical risk, locked-in emissions (Core pp.38–39) | | Yes | No (judgement) | M | The barrier matrix fills this gap with region evidence (research §13.4) |
| **Core C01.a–d** governance | Highest-body responsibility; named functions; ≥ 2 expertise instances on the board; LTIP linked to GHG metrics (Core pp.50–54) | | Yes | **Yes** for C01.c (count) and C01.d (fact) | M | C01.d = GE 5.4 type row |

---

## 9. Modules 6 and 7: Supplier and client engagement (0–20% each)

| Indicator | What / how scored | Data | Extract | Code | Use | Link |
|---|---|---|---|---|---|---|
| **GE 6.1** supplier strategy | Scope 30%: strategy covers ≤ 30 / 31–60 / 61–90 / > 90% of procurement spend or supplier-related S3; emissions requirements in procurement templates 20%; other rows judgement (GE pp.98–104) | % spend or S3 covered | Partly (often CDP only) | Partly | L–M | Steel: iron ore and coal are S3 cat 1 |
| **GE 6.2** supplier activities | Action types (information, engagement, innovation) 30%; scope ≤ 30 … > 90% 40%; measured impact 30% (GE pp.104–107) | | Partly | Partly | L | |
| **Core B03.a / B03.b** | ≥ 2 action types; engagement covers ≥ 60% of procurement spend or supplier S3 (Core pp.39–45) | Same | Partly | **Yes** | L–M | |
| **Core B03.e** value-chain requirements | Met if quantified GHG requirements in procurement templates or required supplier targets; reporting requirements alone do not count (Core pp.48–49) | Procurement policy | Yes | Yes (fact) | M | Steel's offtake contracts with green-steel specs are such a requirement |
| **GE 7.1 / 7.2** client strategy and activities | Scope ≤ 30 / 31–60 / 61–90 / > 90% of revenue or client S3; action types; impact (GE pp.108–114) | | Partly | Partly | L | |
| **Core B03.c / B03.d** | ≥ 2 action types; ≥ 60% of revenue or client S3 (Core pp.45–47) | | Partly | Yes | L | |
| **TR 6.1–6.3** | Engagement with subcontractors, vehicle makers, infrastructure operators (TR pp.92–96) | | Partly | Partly | M for airlines and shipping | TR 6.3 matches barrier HDT-D1, SHP-D1 (infrastructure, corridors) |

Engagement is low value here: the nine sectors' plans stand or fall on their own assets, and the
inputs are mostly in CDP rather than in reports. B03.e is the exception; it is one yes/no fact.

---

## 10. Module 8: Policy engagement (fixed 5%)

| Indicator | What / how scored | Data | Extract | Code | Use | Link |
|---|---|---|---|---|---|---|
| **GE 8.1** policy on associations | Transparency and scope 40%, review process 40%, action plan 20% (GE pp.115–119) | Policy text | Yes | Partly | L | #63 |
| **GE 8.2 / Core C02.b** associations not climate-negative | Membership list checked against InfluenceMap; not met if a member association scores D–F (Core pp.55–56; GE pp.119–121) | Membership list (extractable) + InfluenceMap band (external) | Partly | Yes, given the band | M | Licence of InfluenceMap data not checked (section 17) |
| **GE 8.3 / Core C02.a** position on climate policies | Opposition (incl. third-party claims) 0 → … → Paris commitment and leadership; review process 40% (GE pp.121–124; Core pp.54–55) | Statements; InfluenceMap | Partly | Partly | M | **Link to barrier "Regulation" criteria** [ours]: a company that opposes the very policy its plan depends on (for example STL-R1 carbon price incl. border adjustment, AVI-R1 SAF mandate, HDT-R1 ZEV standard) has an inconsistent plan. A candidate flag for shortlist #3 once a source is chosen |
| **GE 8.4** local authorities | Matrix (GE pp.124–127) | | Partly | No | L | |

---

## 11. Module 9: Business model (fixed 10%)

| Indicator | What / how scored | Data | Extract | Code | Use | Link |
|---|---|---|---|---|---|---|
| **GE 9.1** low-carbon revenue | Share in RY: ≤ 25 / 26–50 / 51–75 / 76–95 / > 95%, 70%; trend RY−3…RY: falling ≥ 1%/yr / flat / rising ≥ 1%/yr, 30%; a qualitative "rising" statement earns "Advanced" (GE pp.132–133) | Low-carbon and total revenue, RY and RY−3 | Yes | **Yes** | M | `green.py` revenue fields and `eut_turnover_*` exist; only RY−3 and the bands are new |
| **GE 9.2 dim. 1** new low-carbon business models (50%) | Size (new: < 1 / 1–5 / > 5%; existing: < 5 / 5–20 / > 20% of FTE, revenue or activity), 40%; scheduled growth (none / grows / at least doubles by RY+5), 30%; importance via the IEA ETP Clean Energy Technology Guide ("Low" Basic, "Moderate" Advanced, "High"/"Very high" Low-carbon aligned), 30% (GE pp.134–136) | Per business model: size, start year, growth plan | Partly | Yes, with a curated importance table | M | Importance could be stored per rule-book action id in the benchmarks file [ours] |
| **GE 9.2 dim. 2** decarbonising existing activities (10%) | Share of activity covered ≤ 25 … > 95%; scheduled growth; relevance; importance (GE pp.136–139) | | Partly | Partly | M | Same object as a B02 plan action, plus "share of activity covered" |
| **GE 9.2 dim. 3** phase-out of high-carbon business (40%) | Share committed to phase-out: none or ≤ 25 / 26–50 / 51–75 / 76–95 / > 95% or already done, 70%; phase-out date: ≥ RY+21 or none / RY+16–20 / RY+11–15 / RY+6–10 / ≤ RY+5 or done, 30%. Selling assets instead of closing them is to be "reflected negatively in the Narrative" (GE pp.139–140) | Share and date of committed phase-out | **Yes** | **Yes** | **H** | **Shortlist #4.** Research §9.1 gap 2; #38, #39 are yes/no only; links to the redlines |
| **GE 9.3** sales into low-carbon products | Share > 80% → full score, else proportional (GE pp.140–141) | | Partly | Yes | L | Mining (battery metals) only |
| **Core D02.a** business model matrix | Low-carbon revenue band (< industry average / < 50 / 51–70 / 71–90 / > 90%) × plans (none with B02.a unmet / none with B02.a met / creation in 5 yr / growth / doubling). A company with "a clear commitment, backed by concrete planning/actions to completely phase out its most high-emitting business model over a timeline relevant to the sector (e.g. 2035 for automotive sector; 2030/40 for electricity, 2040 for shipping)" is Low-carbon aligned (Core pp.64–66) | Revenue split; plans; phase-out | Yes | Partly: "industry average" is not defined in ACT Core | M | The phase-out clause feeds shortlist #4 |
| **Sector module 9**: IS 9.1–9.3, CEM 9.1–9.3, OG 9.1–9.3, CH 9.1 | Most mature business model scored on maturity, profitability, size, expansion plan and timescale; deployment ≤ 2 years vs later (IS pp.116–120; CEM pp.91–95; OG pp.112–120; CH pp.124–130) | | Partly | Partly | M | IS p.117 and p.120 give the missing steel lever wording (section 1) |

---

## 12. ACT Core: what it adds or changes, and the out-of-scope items re-examined

### 12.1 What ACT Core changes compared with the sector methods

- **No score, two axes.** Transition-plan quality (A–C) and contribution to the transition
  (D–F), classed by element thresholds (Core pp.10, 18). WBA's 2026 grading overrides the
  default classes (research §12.2.2). [verified]
- **Only absolute-emission pathways.** "ACT Core only considers global and sectoral pathways
  based on absolute emissions" (Core p.87); no intensity pathways, no locked-in, no sold-product
  module (research §12.2.2). [verified]
- **Hard thresholds where sector methods use curves.** 95%/90% target coverage, ≤ 2030 near
  term, ≤ 2050 net zero (≤ 2040 for power and shipping), residuals ≤ 10%, ≥ 3 + 1 levers, ≥ 60%
  engagement, ≥ 2 board expertise instances, InfluenceMap D–F (Core pp.22–56). These are all
  code-checkable once the facts are extracted.
- **Plan-level B02 tests the spec does not yet run** [verified, Core pp.34–37]:
  - **B02.b at plan level**: "The element is not met if the company discloses levers/actions for
    only one of the timeframes" (p.35). The spec tests timeframe per action only (spec §5).
    Adding "both near and long term present" is a few lines on facts already counted.
  - **B02.c's top checkbox**: "quantifies expected GHG emissions reductions from its actions and
    contextualises them against the targets it has set" (p.37). This is shortlist #2.
  - **Edge year.** ACT says near term is "between the reporting year and the year 2030" and long
    term "beyond 2031" (p.34). The spec counts 2031 as long term; ACT leaves 2031 itself in
    neither. A one-line note for the owner, not a change.
- **Table 9, minimum S3 categories per industry** (Core pp.100–102). For the nine sectors:
  Chemicals: location-based S2, cat 1 and cat 11; Metals & Mining: cat 1 for processors, cat 10
  for miners (aluminium location-based S2); Oil & Gas: cat 11; Utilities: location-based S2, cat 3
  and cat 11; Motor Vehicles: cat 11; Freight & logistics: cat 4 and cat 1 or 3; Passenger
  transport: cat 4; Construction Materials: cat 1, cat 3 and cat 4. [verified] Useful as a fixed
  per-sector list for an A01.a "material categories reported" check.
- **F01 alternative for climate-solution providers**: compare the company's 3-year output growth
  with the 1.5°C deployment growth RY…RY+3, banded < 50 / 50–70 / 70–80 / 80–95 / ≥ 95% (Core
  p.82). Not relevant to the nine sectors. [verified]

### 12.2 Out-of-scope items: should any come back?

| Item | Verdict | Why |
|---|---|---|
| **Locked-in emissions** (GE 2.4, EU 2.2, IS 2.3, CEM 2.2a, CH 2.3, TR 2.3) | **Stay out** | Needs a full asset register (capacity, factor, commissioning year, lifetime, ownership) and projected activity to RY+15 (IS p.55; CEM p.47). Reports rarely give it; ACT fills gaps with IPCC defaults and median lifetimes (IS p.70; CEM p.49), which runs against precision first. The redlines already catch the worst new-build cases. Revisit only with an asset database (for example the Global Energy Monitor trackers, whose licence was not checked). |
| **Narrative score** | **Stay out as a score; bring parts back as flags** | The score is an assessor's 0–4 judgement on five criteria using media and RepRisk (Framework pp.21–25). But several "Consistency and credibility" questions are mechanical once facts exist (Framework pp.61–64). These become shortlist #3. |
| **Trend score** | **Stay out** | Assessor sets +, = or − after a ±1 average; and "The ACT Initiative has started working on a new trend score set-up … can therefore not be used as yet" (Framework p.27). [verified] |
| **E01** target alignment | **Stay out for now** | Same pathway machinery as F01 plus activity forecasts for intensity targets and a 1.5%/yr growth assumption (Core pp.73–74). F01 gives more for less: it tests delivered emissions, not promises. |
| **F01** realignment factor | **Bring back in a later phase** (shortlist #8) | Inputs are reported emissions (already extracted as `tp_h_scope*_emissions`) plus one owner-signed sector pathway; the formula and bands are published (Core pp.80–82). The pathway choice is the open question. |
| **Patents** (GE 3.2) | **Stay out** | Not in reports; needs a patent database query on CPC Y02/Y04S (GE pp.59–61). Low weight (module 3 is 0–10%). |

---

## 13. Ranked shortlist

Ranking weighs: credibility signal, extraction precision, code-only scoring, reuse of existing
facts, and cost. Fields named `tp_…`, `ta_…`, `tc_…` follow the existing presets; new names are
proposals [ours]. Every band below is an ACT band; nothing invents a threshold (spec anti-goals).

### 13.1 Target achievement and progress ratio (GE 1.4) — size S, usefulness High

**Why first.** A company that met its last targets and is on track for the current one is the
strongest evidence that its plan is credible; ACT says the indicator gives "information on the
organizational capability to set and meet emission reduction targets" (GE p.35). [verified]
**Fields.** Per target, keyed by `basis` like plan actions: `tp_h_target_base_year`,
`tp_h_target_base_emissions` (tCO2e, same scope as the target), `tp_h_target_set_year`, plus the
existing `tp_h_target_pct`, `tp_h_target_year` and the `tp_h_scope*_emissions` series; a scope
enum (S1+2, S1+2+3). **Rule.** Dim. 1 for targets whose year is in the past 10 years:
a = (E_base − E_year) / (E_base − T); score 100% if a ≥ 1, 100%·(2a − 1) if 0.5 < a < 1, else 0.
Dim. 2 for running targets (start ≥ 1 year before RY, end ≥ 1 year after): p = a_RY / %time,
%time = (t_RY − t_set)/(t_year − t_set) [the PDF prints the reverse order of both differences,
which gives the same quotient]; score min(p, 1). Weights 25/75 (GE pp.32–34). Show a and p even
when only one dimension applies. A missing base-year value means "not scored", never 0.
**Data source.** Sustainability report target tables and emissions tables. **Link.** Feeds
shortlist #2 (the target gap) and #8.

### 13.2 Abatement coverage: do the listed actions add up to the target? — size S, usefulness High

**Fields.** None new for actions (`ta_action_ghg_saving`, `ta_action_year`, status); the target
and base-year fields from 13.1. **Rule** [ours, from ACT's checkbox]: target gap = E_base ×
`tp_h_target_pct` / 100; coverage = Σ savings in tCO2e/yr of counted actions whose year ≤ target
year ÷ target gap, shown as a percentage with the list of actions used. Savings in % are counted
only when the plan states their base; otherwise listed but not summed. No band: ACT gives none,
so the number is shown, not scored. **ACT basis.** B02.c's top checkbox, "contextualises them
against the targets it has set" (Core p.37); Framework p.61, "Are the GHG emissions reduction
targets set by the company consistent with its transition plan?". [verified] **Data source.**
The plan's action table, already extracted. **Link.** Uses the B02 machinery; a low coverage next
to a high barrier rating on the same actions is the clearest "weak plan" signal on the page.

### 13.3 Consistency flags from the narrative criterion — size M, usefulness High

**Rule.** Each flag is a code test on counted facts, shown with the ACT question it comes from
and the facts behind it; flags never combine into a score. Candidates [ours, each from a
Framework question, verified on the page given]:

| Flag | Test | ACT question |
|---|---|---|
| Non-mature levers without R&D | A planned action uses an id the benchmarks file marks non-mature (e.g. `steel.h2_dri`, `*.ccus`, `avi.e_saf`) and `tc_lowcarbon_rnd_early` is 0 or not disclosed | "net-zero target is heavily reliant on as-yet-unproven or non-mature technologies, yet the company is not investing in low-carbon R&D" (p.61) |
| Falling emissions claimed, no low-carbon capex | A near-term absolute target or a positive B02.c sum, and `tc_lowcarbon_capex` is 0 or not disclosed | "does not report any low-carbon CapEx, but claims future emissions will significantly decrease" (p.64) |
| Net zero without phase-out | #3 = yes and no phase-out commitment (13.4) | "net-zero targets … but it doesn't have any plan to decommission or phase out its fossil fuel or emissions-intensive assets" (pp.61–62) |
| Expansion against net zero | A redline fact true (`tc_new_unabated_coal`, `tc_new_oil_gas_project`, `tc_new_blast_furnace`) and #3 = yes | "announced net-zero … however, it plans to expand its emissions-intensive assets" (p.62) |
| Regions left out | An operating region (`ta_operates_*`) with no action matched to it while others have actions | "reports emissions reduction targets for one region, but announces business as usual for others" (p.61) |
| Pay rewards growth | Remuneration facts show a production or capacity-growth metric (power: EU 5.6) | "incentives that relate to financial metrics only, incentivising growing production" (p.61) |
| Offsets emphasised | #11/#12 facts show credits counted towards targets, or residuals > 10% (Core p.26) | "emphasising carbon credits at the cost of its direct and indirect emissions" (p.62) |

**Data source.** Facts already extracted, plus 13.4. **Link.** Needs a "maturity" tag per action
id in the benchmarks file (owner-signed), which could take TRLs from the IEA ETP Clean Energy
Technology Guide that GE 9.2 cites (GE p.136; licence not checked).

### 13.4 Phase-out commitment for the high-carbon business (GE 9.2 dim. 3) — size S, usefulness High

**Fields.** `ta_phaseout_activity` (string: which high-carbon activity), `ta_phaseout_share_pct`
(share of that activity committed, by capacity, production or revenue, with its basis),
`ta_phaseout_year`, `ta_phaseout_method` (enum closure, conversion, sale). **Rule.** Share bands
≤ 25 / 26–50 / 51–75 / 76–95 / > 95% (70%) and date bands ≥ RY+21 / RY+16–20 / RY+11–15 /
RY+6–10 / ≤ RY+5 (30%) (GE pp.139–140); show `sale` with ACT's note that selling assets "should
be reflected negatively" (GE p.139). Also show whether the year meets the ACT Core sector
timeline for D02.a: 2030/2040 electricity, 2040 shipping, 2035 automotive (Core p.66). Coal
phase-out dates from IEA NZE (spec §2 left them out of redlines) can sit next to it as
milestones. **Data source.** Transition plans; CA100+ asks the same (research §9.1 gap 2).
**Link.** Redlines (new build) and phase-out (existing assets) are two halves of one question.

### 13.5 Sector delivery KPIs with ACT bands — size M, usefulness High/Medium

**Fields and rules** (one or two per sector; bands and benchmarks into the benchmarks file,
each cited like the R&D tests):

| Sector | Field | ACT rule | Barrier / action link |
|---|---|---|---|
| Cement | `tc_alt_fuel_share_pct` (thermal substitution, CCS excluded) | Bands < 5 / 5–10 / 11–20 / 21–30 / > 30% (CEM pp.49–50) | `cement.alt_fuels` |
| Chemicals | `tc_nh3_electrolytic_pct`, `tc_meoh_electrolytic_pct`, tonnes of each, `tc_electrolysis_lc_power_pct` | CH 4.3 bands and weights (CH pp.76–78) | `chem.low_carbon_h2`; CHM-T1; `h2_cost` assumption |
| Oil & Gas | `tc_ccs_capex_share_pct`, `…_planned` (Y+5) | average(S(Y)/5%, S(Y+5)/5%), × years/5 if the plan is shorter, capped at 1; EOR excluded (OG pp.56–59) | `ogu.*`; complements the 77% capex test |
| Heavy-duty trucks (makers, ISIC 2910) | `ta_zev_sales_share_pct` (RY−5…RY) and planned (RY…RY+3) | AU 4.4 two dimensions (AU pp.55–56) | `hdt.bev_trucks`, `hdt.fcev_trucks`; HDT-R1 |
| Airlines, shipping, road freight operators | `ta_fleet_lc_share_pct` per plan year (low-carbon vehicles plus contracted low-carbon fuel share) | TR 2.4 ratio (TR pp.53–56); benchmark curve must come from another source, since ACT gives only a chart | `avi.*_saf`, `shp.green_fuels`; AVI-R1, SHP-R1 |

Steel and power get none here: steel's route split (IS 2.2/2.5) needs route-level data rarely
disclosed, and power's ACT KPIs either need asset data (EU 2.2/2.3) or concern retail only (EU
4.3). Mining has no ACT method.

### 13.6 Plan-governance facts with computable ACT bands — size S–M, usefulness Medium

**Fields.** `tp_h_plan_end_year`, `tp_h_plan_review_years`, `tp_h_progress_report_cycle`,
`tp_h_plan_scope_pct`, `tp_h_carbon_price_use` (enum: none, studied, qualitative, embedded,
scenario-aligned), `tp_h_scenarios_n`, `tp_h_risk_categories_n`. **Rule.** The GE 5.3 rows for
timescale, scope, review, reporting and carbon price, and the GE 5.5 rows for scenarios and risk
categories, each banded as ACT prints them (GE pp.87–90, 94–96); GE 5.4 from the remuneration
preset: CEO = Level 1, executive committee = Level 2; GHG metric in STI → Standard, in LTI →
Advanced, LTI aligned with the plan → the top printed cell (GE pp.91–92); EU 5.6 for power. Show per-row levels; do not add them up. **Link.**
The judgement rows of GE 5.3 stay with the 64-indicator yes/no answers.

### 13.7 Carbon-price assumption vs a low-carbon-scenario price — size S, usefulness Medium

**Fields.** Existing `ta_assumed_carbon_price`; `tp_h_carbon_price_use` from 13.6. **Rule.**
Next to today's barrier-evidence comparison (spec §4), add the scenario price for the same region
and year, with the gap in the same format. ACT points to "IEA World Energy Outlook 2019, Annex B,
p 758 … predicted values in 2030 and 2050" by region (GE p.90; GE p.97; EU p.90). [verified]
Use a newer IEA table, owner-signed in the benchmarks file `assumptions` block [ours]. **Link.**
Turns one assumption into two comparisons: against what policy delivers today (barrier) and what
1.5°C needs (scenario).

### 13.8 F01 realignment factor — size L, usefulness Medium-high (later phase)

**Fields.** Annual S1+2 and S3 from 2019 to RY (the existing series, extended; ACT needs at least
four years including RY, Core p.70). **Rule.** s1.5C = 2019 emissions × the sector pathway's
annual percentages; c1.5C steepens it to recover any excess since 2019 within the 2050 budget;
realignment = required trend / observed trend, weighted by the S1+2 and S3 shares (EQ4);
bands > 3 Basic, 1.5–3 Standard, 1.2–1.5 Advanced, 1–1.2 Next practice, ≤ 1 Low-carbon aligned
(Core pp.71–72, 80–82). [verified] **Data source.** Reported emissions; one absolute-emissions
pathway per sector chosen from Core's list (IEA NZE, TPI, OECM, MPP …; Core p.87), owner-signed.
**Risk.** Base-year restatements, M&A and boundary changes; the c1.5C recovery step is ACT's own
construction (after Rekker et al. 2022) and needs careful tests.

---

## 14. Sector specifics for the nine sectors

| Sector | ACT method | Most useful ACT items beyond what is built | Notes |
|---|---|---|---|
| Power & Utilities | Electricity v2.0 | Phase-out (13.4, timeline 2030/2040, Core p.66); long-term target ≤ 2040 (Core p.25); EU 5.6 fossil incentives (EU pp.90–91); EU 4.3 for retailers | EU 2.2/2.3 need plant data. Table 9: location-based S2, cat 3 and cat 11 (Core p.102) |
| Oil & Gas Upstream | O&G 2021 | OG 2.6 CCS/CDR capex share (OG pp.56–59); OG 4.3 low-carbon products share at Y+5 (OG pp.76–78); phase-out | OG 2.4 needs Carbon Tracker data. Cat 11 is the material S3 (Core p.101) |
| Chemicals | Chemicals | CH 4.3 electrolytic H2 (CH pp.76–78); CH 4.4 bio-based and MTO/MTA (CH pp.78–83) | Matches CHM-T1, CHM-D1 and the `h2_cost` assumption |
| Steel | Iron & Steel v2.0 | Route-level intensity (IS 2.2/2.5) if disclosed; IS 2.7 co-products (IS p.73); lever wording for `steel.h2_dri` (p.117) and `steel.ccus` (p.120) | Defaults from IPCC medians for missing plant data (IS p.70) are not precision-first |
| Cement | Cement v2.0 | CEM 2.4a alternative fuels (CEM pp.49–50) | CEM 2.4a reference values are ETP 2017 B2DS, dated. Clinker ratio has no CEM indicator for integrated producers; barrier CEM-T2 covers SCM availability |
| Aviation | Transport v2.1 | TR 2.4 (SAF counted only with supply contracts and verification, TR p.54); TR 6.3 infrastructure engagement | SB_LCV curve is a chart only (TR p.55) |
| Shipping | Transport v2.1 | TR 2.4; long-term target ≤ 2040 (Core p.25); phase-out by 2040 (Core p.66) | As aviation |
| Heavy-Duty Road Transport | Automotive v2.0 (makers, ISIC 2910); Transport v2.1 (operators, ISIC 4923) | AU 4.4 ZEV sales share; TR 2.4 fleet share | AU 4.4's benchmark is the NZE EV sales share, a light-vehicle figure |
| Critical Minerals & Mining | none | Generic and Core only; GE 9.3 for battery-metal sales | Table 9: miners cat 10, processors cat 1 (Core p.101) |

---

## 15. Extensions to what exists

- **Benchmarks file.** New per-sector blocks: `delivery_kpis` (13.5, each with bands and
  source), `phaseout_timeline` (Core p.66 years), `action_maturity` per action id (13.3) and a
  `scenario_price` per region and year under `assumptions` (13.7). Fill `act_levers` for
  `steel.h2_dri` and `steel.ccus` from IS pp.117, 120 if the owner accepts sector-method wording.
- **B02.** Add plan-level B02.b (both timeframes) and abatement coverage (13.2). Both reuse
  counted action facts.
- **Barrier matching.** Delivery KPIs (13.5) sit next to the barrier rating of the same action:
  for example a high CHM-T1 barrier rating next to an electrolytic-H2 share of 0% and no
  allocated funding.
- **64-indicator set.** #4, #9 (horizon), #38–39 (phase-out), #59 (capex), #19 (pay) get ACT
  bands from facts; the yes/no answers stay as they are (spec non-goal: do not change that set).

## 16. Owner decisions needed

1. Which shortlist items to take, and in which order. Suggested: 13.1 and 13.2 together (shared
   fields), then 13.4, 13.3, 13.5.
2. Whether ACT sector-method wording (IS pp.117, 120) may fill `act_levers` where ACT Core has
   none.
3. For 13.3: who signs the per-action maturity tags, and from which source.
4. For 13.5: the benchmark curves ACT does not print (TR 2.4, AU 4.4 for trucks); NZE milestones
   would be the default.
5. For 13.7 and 13.8: which IEA (or other) table to use for scenario carbon prices and
   absolute-emission pathways, and its licence.
6. Whether a policy-position flag (section 10) is wanted, and from which source (InfluenceMap
   or company statements only).

**Does `openwiki/` need an update?** No. This note changes no code behaviour.

---

## 17. Could not access / not verified

- **TR 2.4 benchmark** SB_LCV(t) for road freight, maritime, aviation and rail is printed only as
  a chart (TR p.55); its values were not read.
- **Transport version label.** The cover says "VERSION 2.1 | March 2022"; page footers say
  "Version 2.0". Page cites refer to the file linked.
- **Re-issued PDFs.** The sector PDFs linked from the methodology page carry creation dates of
  2026-08-31 (Generic 2026-09-29). Older copies exist (`pdf/act-chemicals-v2.0.pdf`, 172 pages, and
  `pdf/act-electricity-2.0-1.pdf`, 179 pages, both 2024-10-30) with different page counts. Page
  numbers here refer to the linked files; the older copies were not compared section by section.
- **GE 1.3 scoring scale.** The dimension tables print maxima of 50% each and also say "Dimension
  1: 50%, Dimension 2: 50%" (GE pp.29–30). Read as two halves summing to 100%; not confirmed.
- **GE 5.4 type row.** In the text extraction the "LTIP aligned with the plan" cell sits between
  the Next practice and Low-carbon aligned columns (GE p.92); which level it is was not settled.
- **GE 1.4 %time.** Printed as (t_ref − t_reporting)/(t_ref − t_horizon) with t_ref the year
  the target was set (GE p.33); dimension 1 uses E(t_ref) as base-year emissions (p.32). The two
  uses of t_ref differ; 13.1 reads dimension 2 with the set year.
- **Core D02.a "industry average"** for low-carbon revenue is not defined in ACT Core; Appendix
  10.3 gives typical *expenditure*, not revenue.
- **InfluenceMap** data terms, **IEA ETP Clean Energy Technology Guide** terms, **Global Energy
  Monitor** tracker terms and the **IEA WEO** scenario-price tables were not checked.
- **ACT Core web page** (`actinitiative.org/en/act-core/`) redirected to a French article; it
  repeats the seven principles of Core p.8 and adds nothing used here. WBA's 2026 grading note was
  not re-read (verified in research §12.2.2).
- **Not read in this round:** ACT Aluminium, Agriculture, Buildings, Glass, Pulp & Paper,
  Retail, Fashion, Finance; ACT Core Appendix 10.4 (framework mapping) in detail; the narrative
  "Risk" and "Reputation" matrices beyond the questions quoted.
- **Licence.** Every ACT document carries "Reproduction of all or part of work without licence
  of use permission … is prohibited" (research §13.2.4). Under the owner's internal-use decision,
  the bands above may be stored with citation; ask WBA/ADEME (and CDP for the older sector
  methods) before sharing outputs outside the organisation.
