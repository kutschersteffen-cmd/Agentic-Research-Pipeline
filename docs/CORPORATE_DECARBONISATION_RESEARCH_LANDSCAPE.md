# Corporate Decarbonisation: Measurement, Commitment Tracking, and Predictive Variables

A research landscape review, anchored on *Decarbonising portfolios 2026: Tracking the
transition across investment benchmarks* (LSEG / FTSE Russell with the UN-convened
Net-Zero Asset Owner Alliance, September 2026).

Two questions drive this memo:

1. **What approaches exist to analyse and track carbon emissions, targets and
   commitments at the company level?**
2. **What does the research say about the variables that predict — or classify —
   which companies actually decarbonise and which do not?**

---

## Part 0 — What the LSEG/NZAOA report actually does

Read first as a methodology, not as a set of findings. Five design choices matter,
because they are the ones a company-level analytics pipeline has to replicate or
deliberately depart from.

### 0.1 The metric taxonomy (report Table 1, Appendix II)

The report is explicit that **no single carbon metric is sufficient**, and classifies
metrics by what moves them:

| Family | Metric | Denominator | What contaminates it |
|---|---|---|---|
| Absolute | Aggregate emissions | none | index expansion, deletions, turnover |
| Absolute | **Chained emissions** | none (constant-constituent) | not comparable across benchmarks |
| Absolute | Financed emissions | attribution by EVIC | moves with EVIC as well as emissions |
| Intensity | WACI | revenue | revenue cycles, inflation, commodity prices |
| Intensity | CI-EVIC / CI-MktCap | enterprise value / market cap | valuation swings, asset-price inflation; EVIC rewards leverage |
| Intensity | Activity-based | physical output (MWh, t steel) | sector-specific, sparse disclosure |
| Sovereign | Production intensity | PPP-adjusted GDP | excludes imported emissions |
| Sovereign | Consumption intensity | population | denominator not comparable to economic intensities |

**Chained emissions** is the most transferable idea for company-level work: a
constant-constituent series that strips out entry/exit. The gap between the aggregate
and chained series *is* the compositional effect. In the report's high-yield universe,
aggregate emissions fell 9% p.a. while chained fell only 2% p.a. — i.e. essentially
all of the headline decline was issuer churn.

### 0.2 Log-ratio attribution (report Appendix IV)

The analytical spine. Every change in a portfolio carbon metric is decomposed into
three additive contributions using logarithmic changes of the individual factors
(index weight, emissions, revenue):

- **CE** — change in constituent emissions (further splittable by *reported vs estimated* data)
- **Norm** — normalisation (revenue or EVIC, plus the inflation adjustment)
- **Alloc** — allocation (constituent churn vs intra-portfolio weight shifts)

The headline result, and the report's central claim: **year-on-year movements are
dominated by normalisation and allocation, not by investee emissions**. For the FTSE
All-World 2020–2024, emissions *added* to WACI while normalisation and allocation
pulled it down. For high-yield bonds 2016–2019, allocation alone removed 66% of WACI.
These effects are transitory and wash out over multi-year horizons, which is why the
different intensity metrics converge in the long run (WACI −5% p.a., CI-EVIC −6% p.a.,
CI-MktCap −5% p.a. over 2016–2024) while diverging wildly year to year.

### 0.3 The decoupling framing

FTSE All-World absolute Scope 1+2 emissions have plateaued at ~12.5 GtCO2e (≈23.5% of
global emissions) while all intensity measures fell by roughly a third since 2016. The
report labels this **relative, not absolute, decoupling** — revenues and valuations grew
faster than emissions. Benchmark intensity declines (~5–6% p.a.) outpaced global
emissions per unit of GDP (~2% p.a.).

### 0.4 The company-level transition layer (report §2) — the part this memo extends

This is where the report moves from portfolio accounting to **company-level prediction**:

- **Disclosure**: 81% of FTSE All-World constituents reported Scope 1+2 in 2024 (55% in
  2016); EM up from 41% to 73%, but the EM gain is concentrated in China — *ex-China, EM
  disclosure is little changed*.
- **Targets**: 70% disclose a climate target (7% in 2018), 57% a net-zero commitment
  (1% in 2018).
- **The ambition/delivery gap**: 9.5 Gt of emissions sit under *some* disclosed target,
  but only 7 Gt under a quantifiable **absolute** reduction target, and only 5 Gt under
  targets covering 100% of in-scope emissions. Translated to trajectories, disclosed
  targets imply ~25% Scope 1+2 cuts by 2030 and ~50% by 2050 — materially weaker than a
  57% net-zero-commitment share would suggest.
- **Emissions are still rising for roughly half the index**: median annual change is
  0% to −1% outside the pandemic year; in 2023–24 the top quartile cut ≥7% while the
  bottom quartile grew ≥8%.

### 0.5 The report's own predictive finding: TPI Management Quality

The single most directly relevant result for question (2). Using **2019** TPI Management
Quality (MQ, v4) scores to predict **2019–2024** realised Scope 1+2 change:

| 2019 TPI MQ band | Mean annualised Scope 1+2 change, 2019–2024 |
|---|---|
| MQ 0 | +0.7% |
| MQ 1 | +1.4% |
| MQ 2 | +0.5% |
| MQ 3 | −1.1% |
| MQ 4 | −3.5% |
| MQ 5 | −5.6% |

A monotone gradient across the top four bands, and it holds *within* subsamples
(report Table 9): developed vs emerging markets, high-emitting vs other sectors,
large vs medium cap. Distributionally, **76% of MQ 4–5 firms cut emissions** over the
period against **53% of MQ 0–2 firms**. The report is careful — "while not predictive
on their own" — and flags that the MQ 0–2 band is the most dispersed, over-represented
at both tails, much of which reflects small caps with *estimated* emissions and largely
disappears when filtering to disclosed emitters. The gradient itself is robust to
window and disclosure filters.

The report then operationalises this as a **credibility weighting**: applying TPI MQ as
the blend weight between target-based and trend-based Implied Temperature Rise moves the
FTSE All-World from 3.1°C (no targets) / 1.9°C (all targets taken at face value) to
**2.3°C (credibility-weighted)**. Distributionally the effect is severe: the share of
constituents classed 1.5°C-aligned falls from **27% to 8%** once credibility is applied.

### 0.6 Two blind spots the report flags

- **Scope 2 method choice.** Among FTSE All-World constituents dual-reporting 2020–2024,
  Technology's **location-based** Scope 2 rose **60%** vs **22%** market-based. Market-based
  accounting absorbs the AI/data-centre demand shock into renewable procurement claims.
  Tech Scope 1+2 rose 28% 2019–2024, more than any other sector; Scope 2 is ~84% of that
  sector total, and Scope 2 CAGR for Technology was 3.3% 2019–2024.
- **Scope 3.** 61% disclose ≥1 category (35% in 2016) but only **40% disclose a *material*
  category**. Disclosure is inversely related to materiality: Category 6 (Business Travel)
  is the most-disclosed at 44% of firms yet <1% of reported Scope 3 volume, while Cat 11
  (Use of Sold Products) — 21.4% of volume — and Cat 10 (Processing of Sold Products) are
  underreported.

---

## Part 1 — Approaches to tracking emissions and commitments at company level

Six distinguishable layers. A pipeline needs a position on each.

### Layer A — Emissions measurement and estimation

**The core problem: estimated data is not the same object as reported data.** The report's
own attribution splits the emissions contribution by data source for exactly this reason,
and its TPI caveat (dispersion in the low band "largely disappears among disclosed
emitters") is the same problem surfacing.

Key findings from the data-quality literature:

- **Provider divergence is scope-dependent.** Reported Scope 1 correlates ~0.97 across
  providers; *estimated* Scope 1 ~0.85. Scope 3 is far worse — the correlation between
  aggregated Scope 3 from ISS and Trucost has been measured as low as **16%**. ISS's
  divergence is largest because it substitutes EEIO/LCA model estimates for reported
  figures. See Busch et al., *Corporate carbon emissions data for equity and bond
  portfolios*, Managerial Finance 50(1) (2024);
  https://www.emerald.com/mf/article/50/1/118/1224623/Corporate-carbon-emissions-data-for-equity-and
- **ML estimation of Scope 3 has a low ceiling.** Machine learning improves aggregate
  Scope 3 prediction accuracy by up to 6% (up to 25% when categories are estimated
  individually), but *absolute* prediction performance remains poor even for best models,
  limited by thin observation counts per category. Nguyen et al., PLOS Climate;
  https://journals.plos.org/climate/article?id=10.1371%2Fjournal.pclm.0000208
- **Interpretable ML for non-reported emissions**: Heurtebize et al., *Greenhouse gases
  emissions: estimating corporate non-reported emissions using interpretable machine
  learning* (arXiv 2212.10844); and Nguyen et al., *Estimation of Corporate Greenhouse Gas
  Emissions via Machine Learning* (arXiv 2109.04318). Both are relevant less as estimators
  than as documentation of which features carry signal.
- **Supervisory/central-bank work**: Banque de France, *Estimating corporate carbon
  emissions using artificial intelligence*;
  https://www.banque-france.fr/en/publications-and-statistics/publications/estimating-corporate-carbon-emissions-using-artificial-intelligence
- **Governance variables as estimator features**: *Machine learning for predicting corporate
  carbon emissions: the role of corporate governance* (ScienceDirect, 2025) compares Lasso /
  Ridge / Elastic Net against Random Forest / XGBoost / Neural Net on listed firms. XGBoost
  is the most robust across periods, and **governance variables carry significant predictive
  power specifically when historical emissions data is unavailable** — the cold-start case.
  https://www.sciencedirect.com/science/article/pii/S2773067025000512
- **Benchmarking**: *GHGbench: A Unified Multi-Entity, Multi-Task Benchmark for Carbon
  Emission Prediction* (arXiv 2605.13743) — useful if the pipeline ever needs a
  standardised evaluation harness rather than bespoke backtests.

**Practical implication.** Any company-level decarbonisation classifier must carry a
`disclosed | estimated` flag as a first-class feature and report performance separately on
each. Otherwise the model is partly learning the vendor's estimation model, and the
"emissions trend" it predicts is partly a revenue trend pushed through an EEIO regression.

### Layer B — Commitment and target tracking

- **Coverage/structured target databases**: SBTi (validated targets, near-term and net-zero),
  CDP, the report's own LSEG Climate MAP target fields. SBTi's own progress reporting claims
  a typical approved company reduced Scope 1+2 at ~8.8% p.a. since target-setting against a
  4.2% required rate, and 29% combined Scope 1+2 reduction 2015–2020 across approved-target
  companies; https://sciencebasedtargets.org/reports/sbti-progress-report-2021/science-based-targets-result-in-biggest-emissions-reduction-to-date
  Treat self-reported initiative figures as an upper bound — they are subject to survivorship
  and selection.
- **Independent replication is more nuanced.** A 2026 study of 3,113 listed firms
  (*Corporate carbon performance and the Science-Based Targets initiative: disentangling the
  effects across Scope 1, 2, and 3*, Journal of Industrial Ecology) finds consistent
  improvement in **Scope 1 and market-based Scope 2**, but **no measurable effect for
  location-based Scope 2 or Scope 3**. That asymmetry is exactly the Scope 2 accounting
  artefact the LSEG report's Box 1 warns about: the apparent effect may partly be
  procurement accounting rather than abatement.
  https://link.springer.com/article/10.1007/s44498-026-00058-4
- **Target *outcome* tracking — the accountability gap.** Bolton, Kacperczyk et al.,
  *Limited accountability and awareness of corporate emissions target outcomes*, Nature
  Climate Change (2024): of 1,041 firms with targets ending in 2020, **88 (9%) failed and
  320 (31%) simply disappeared** (target quietly dropped). After a failure there is *no*
  significant market reaction, no change in media sentiment, environmental scores, or
  environment-related shareholder proposals — in sharp contrast to the announcement, which
  *is* rewarded. Only three failures received media coverage. Achievement rates are higher
  in common-law countries and where media accountability is stronger.
  https://www.nature.com/articles/s41558-024-02236-3
  **This is the single most important paper for justifying credibility adjustment.** It says
  the target-setting signal is not merely noisy — it is unpoliced, and target *disappearance*
  is three times more common than target *failure*.
- **Target integrity**: Bjørn et al., *Renewable energy certificates threaten the integrity of
  corporate science-based targets*, Nature Climate Change (2022) — RECs let firms claim
  progress without real reductions; https://www.nature.com/articles/s41558-022-01379-5
- **Initiative-level evaluation**: *Quantitative evaluation of large corporate climate action
  initiatives shows mixed progress in their first half-decade*, Nature Communications (2023);
  https://www.nature.com/articles/s41467-023-38989-2
- **Ambition auditing**: *An audit of corporate decarbonisation ambition against low carbon
  futures*, Scientific Reports (2025) — aggregates disclosed corporate ambition and tests it
  against scenario-consistent pathways, the company-level analogue of the report's "25% by
  2030 / 50% by 2050" implied-trajectory exercise;
  https://www.nature.com/articles/s41598-025-20203-6
- **Greenwashing-risk screening at scale**: *Red flags in green promises: a framework for
  identifying greenwashing risk in corporate climate pledges*, npj Climate Action (2026) —
  applied to >4,000 companies combining disclosures, implementation plans, performance data
  and **lobbying activity**; reports that **96% of pledging companies show at least one
  greenwashing risk indicator**. The lobbying dimension is a feature class absent from both
  the LSEG report and most academic models.
  https://www.nature.com/articles/s44168-026-00346-6

### Layer C — Governance / transition-readiness assessment frameworks

- **TPI Management Quality & Carbon Performance** (TPI Global Climate Transition Centre, LSE;
  MQ data powered by LSEG). MQ = 19 Yes/No indicators on policy, reporting, target-setting,
  and responsibilities/accountability, scored into bands 0–5 (v4) — *processes*. CP = alignment
  of the emissions pathway to sector-specific 1.5°C / below-2°C benchmarks — *outcomes*.
  Native coverage is ~600 companies in 16 high-carbon sectors; the LSEG report applies the
  LSEG-powered MQ extension across the full FTSE All-World (n≈2,808 in the banded analysis).
  Methodology: https://www.transitionpathwayinitiative.org/methodology ;
  factsheet: https://www.lseg.com/content/dam/data-analytics/en_us/documents/fact-sheets/lseg-tpi-mq-scores-factsheet.pdf
  **Note the version issue**: the report deliberately uses MQ **v4** rather than v5 for history
  length. Any replication must pin the methodology version — score levels are not comparable
  across versions.
- **Climate Action 100+ Net Zero Company Benchmark** — ten indicators across emissions
  reduction, governance, and transition-plan disclosure/implementation; company research
  conducted by TPI with Grantham/LSE and FTSE Russell. The 2026 framework was streamlined and
  adds a World Benchmarking Alliance partnership for climate governance and absolute emissions
  metrics. IIGCC's own read of the benchmark: commitment progress is **not** matched by credible
  decarbonisation strategies — the same ambition/delivery gap.
  https://www.climateaction100.org/net-zero-company-benchmark/methodology/
- **ASCOR** — the sovereign analogue (Assessing Sovereign Climate-related Opportunities and
  Risks), relevant to the report's Box 3 WGBI analysis.
- **Transition-plan credibility frameworks**: GFANZ Net-zero Transition Plan framework
  (https://www.gfanzero.com/our-work/financial-institution-net-zero-transition-plans/);
  IIGCC *Investor Expectations of Corporate Transition Plans: From A to Zero*
  (https://www.iigcc.org/resources/investor-expectations-of-corporate-transition-plans-from-a-to-zero)
  and the Net Zero Investment Framework (https://www.iigcc.org/net-zero-investment-framework);
  NZAOA *A Tool for Developing Credible Transition Plans*
  (https://www.unepfi.org/wordpress/wp-content/uploads/2023/12/NZAOA_A-Tool-for-Developing-Credible-Transition-Plans.pdf).
  These are normative checklists, not scored datasets — but they define the feature space a
  credibility model should populate.
- **Holistic evaluation critique**: *That's none of my business: A holistic framework for
  evaluating corporate decarbonization at the core of business* (Energy Research & Social
  Science, 2025) — argues most frameworks score peripheral action rather than core business
  model change; https://www.sciencedirect.com/science/article/pii/S2214629625001756

### Layer D — Forward-looking alignment metrics (ITR and relatives)

- TCFD *Measuring Portfolio Alignment: Technical Supplement* (2021) is the canonical taxonomy
  of binary alignment / benchmark divergence / implied temperature rise methods;
  https://ccli.ubc.ca/wp-content/uploads/2021/09/2021-TCFD-Portfolio_Alignment_Technical_Supplement.pdf
- WWF *Alignment Cookbook*;
  https://wwfint.awsassets.panda.org/downloads/rapport_0207_mis_a_jours.pdf
- **Metric divergence is the main empirical finding.** Bingler, Colesanti Senni & Monnin,
  *Understand what you measure: Where climate transition risk metrics converge and why they
  diverge*, Finance Research Letters 50 (2022) — transition-risk metrics agree on the
  least- and most-exposed firms and disagree substantially in the middle, and the authors
  call for a supervisory baseline to ensure comparability.
  https://ideas.repec.org/a/eee/finlet/v50y2022ics1544612322004561.html
  Extended in *How you measure transition risk matters: comparing and evaluating climate
  transition risk metrics* (Ecological Economics, 2025);
  https://www.sciencedirect.com/science/article/pii/S092911992500207X
- **ITR is extremely assumption-sensitive.** A sensitivity-analysis framework for equity-portfolio
  ITR is at
  https://cdn.prod.website-files.com/672cea0ae7889396005b1e87/67e9af362e7bb34d604550f1_implied-temperature-rise-of-equity-portfolios-2205-1.pdf ;
  uncertainty quantification in portfolio temperature alignment at arXiv 2412.14182. The LSEG
  report's 3.1 / 2.3 / 1.9°C spread from a *single* assumption change (target treatment) is a
  clean illustration: **the target-credibility assumption dominates the temperature output.**
- SBTi Temperature Alignment tool (open source) —
  https://sciencebasedtargets.github.io/SBTi-finance-tool/intro.html

### Layer E — Portfolio-level attribution (the report's own layer)

- **NZAOA / UNEP-FI, *Understanding the Drivers of Investment Portfolio Decarbonisation***
  (discussion paper, 2023) — the reference attribution model, and the direct methodological
  sibling of the LSEG report's Appendix IV;
  https://www.unepfi.org/wordpress/wp-content/uploads/2023/12/Emission-Attribution-Analysis-Discussion-Paper_FINAL.pdf
- **EDHEC Climate Institute**, attribution analysis of GHG emissions for an equity portfolio —
  decomposes into **five** drivers: sector allocation, intra-sectoral allocation, emissions
  intensity, sales, and market capitalisation (a finer split than the report's three-way
  CE/Norm/Alloc);
  https://climateinstitute.edhec.edu/news/attribution-analysis-greenhouse-gas-emissions-associated-equity-portfolio
- **IIGCC NZIF Portfolio Decarbonisation Reference Objective** with attribution —
  https://www.iigcc.org/insights/nzifs-portfolio-decarbonisation-reference-objective-and-attribution-analysis-its-how-you-get-there-that-counts
- FactSet's practitioner implementation of the NZAOA model;
  https://insight.factset.com/measuring-portfolio-decarbonization-applying-the-nzaoa-attribution-model-in-practice
- MSCI *Carbon Footprinting Demystified* — the older metric-choice reference.

Published attribution results are consistent with the LSEG report: in one NZAOA-style
analysis, reductions in constituent weights in high-carbon industries accounted for **64%**
of WACI reduction 2016–2021. Composition, not abatement.

### Layer F — NLP / LLM extraction from disclosure

Most relevant to this repo, since the Extraction Engine already does grounded document
extraction.

- **ClimateBERT** (Webersinke et al., arXiv 2110.12010) — DistilRoBERTa pretrained on >2M
  climate paragraphs; 3.6–35.7% error reduction across climate downstream tasks.
- **ClimateBERT-NetZero** (arXiv 2310.08096) — detects and classifies net-zero vs general
  reduction targets in text at scale. Directly relevant to building the report's
  "quantifiable absolute target vs vague target" split (the 9.5 Gt → 7 Gt → 5 Gt funnel)
  from raw disclosure.
- **ClimateBERT-CTI / cheap-talk index** — Bingler, Kraus, Leippold & Webersinke, *How cheap
  talk in climate disclosures relates to climate initiatives, corporate emissions, and
  reputation risk*, Journal of Banking & Finance (2024). See Layer G below for the finding.
  https://www.sciencedirect.com/science/article/pii/S0378426624001080
- **ChatReport** (Ni et al.) — LLM evaluation of sustainability reports against the 11 TCFD
  recommendations.
- **Colesanti Senni et al.** — expert-in-the-loop LLM assessment of company transition plans
  and disclosure quality. This is the closest published analogue to an Advocate/Opposing/
  Adjudicator adjudication pipeline applied to transition plans.
- *Judging It, Washing It: Scoring and Greenwashing Corporate Climate Disclosures using Large
  Language Models* (arXiv 2502.15094).
- *Climate AI for Corporate Decarbonization Metrics Extraction* (arXiv 2411.03402).
- *Glitter or Gold? Deriving Structured Insights from Sustainability Reports via LLMs*
  (arXiv 2310.05628).
- WWF, *Combining AI and Domain Expertise to Assess Corporate Climate Transition Plans*
  (working paper, 2024);
  https://wwfint.awsassets.panda.org/downloads/working-paper-ai-greenwashing-may-2024_1.pdf

---

## Part 2 — Predictive variables: what actually separates decarbonisers from non-decarbonisers

### 2.1 The baseline nobody should skip: persistence

*The Anatomy of Decarbonizing Firms* — global panel combining financial characteristics,
balance-sheet indicators, ESG metrics, macro variables and firm GHG emissions — finds that
**emission trajectories exhibit strong persistence, with past emissions the dominant
predictor of future performance**. It also finds that firms with larger footprints display
greater abatement potential, that SBT adoption is a significant catalyst (with a causal
identification claim), and that ML models beat heuristic benchmarks at forecasting
one-year-ahead abatement, *especially in hard-to-abate sectors*.

**Design consequence:** an autoregressive baseline (lagged emissions level and lagged growth,
sector × region fixed effects) is the benchmark every governance/target feature must beat.
The LSEG report's TPI gradient is reported as an unconditional mean by band — it is *not*
shown to survive conditioning on lagged emissions growth. Replicating it with that control
is the first experiment worth running.

### 2.2 Evidence table

Direction is signed toward *more* decarbonisation. Strength reflects identification quality
and sample breadth, not effect size.

| # | Variable | Direction | Evidence | Strength |
|---|---|---|---|---|
| 1 | **Lagged emissions level / growth** | persistence (past trend continues) | dominant predictor in *Anatomy of Decarbonizing Firms* | **High** |
| 2 | **Climate governance quality (TPI MQ band)** | + strongly | MQ5 −5.6% vs MQ1 +1.4% p.a. 2019–24; 76% vs 53% of firms cutting; holds within DM/EM, high-emitting/other, large/medium | **High** (unconditional) |
| 3 | **SBTi-validated target** | + | 8.8% vs 4.2% required p.a. (SBTi self-reported); independent 3,113-firm study confirms **Scope 1 + market-based Scope 2 only**, null for location-based S2 and S3 | **Medium-High**, scope-dependent |
| 4 | **Target *structure*: absolute vs intensity, full vs partial scope coverage, quantifiable vs vague** | + | LSEG 9.5→7→5 Gt funnel; Bolton & Kacperczyk note intensity targets let totals rise while the firm "looks" to be reducing | **High** (mechanical, easy to encode) |
| 5 | **Any net-zero pledge (headline)** | ≈ 0 near-term | CEPR: net-zero targets "neither greenwashing nor a gamechanger" — weak near-term emissions evidence; they formalise processes already underway in firms with strong climate governance | **Medium** — *headline pledge alone is near-useless as a near-term predictor* |
| 6 | **Cheap-talk index (NLP vagueness of disclosure)** | **−** | ClimateBERT-CTI: higher cheap talk **predicts faster emissions growth** and more negative environmental news coverage (JBF 2024) | **Medium-High** — rare example of a *negative* signal with direct emissions-growth prediction |
| 7 | **Green capex / EU-taxonomy capex alignment** | + | capex is the most tangible committed-resource signal; taxonomy-capex portfolios show the most robust response among transition metrics. **But <50% of top emitters disclose green capex, ~30% outside Europe** | **Medium**, severe coverage bias |
| 8 | **Green revenue share** | + (slow-moving) | LSEG report Fig. 7: every sector raised green revenue share and cut intensity 2016–2024; benchmark 8% in 2024. Utilities show the trap — ~25% green revenue yet still >5× benchmark intensity | **Medium** — measures *what a firm sells*, not how cleanly it operates; the two must be modelled jointly |
| 9 | **Green patents / R&D orientation** | + | R&D-oriented and smaller firms better positioned to pair digital and low-carbon innovation; not all patents convert to revenue | **Low-Medium** |
| 10 | **Carbon-price / ETS regulatory exposure** | **+ strongly, causal** | Colmer, Martin, Muûls & Wagner, *Does Pricing Carbon Mitigate Climate Change?*, Review of Economic Studies 92(3) (2025): EU ETS caused **−14 to −16%** CO2 with no detectable output contraction; Phase II effect 25–28pp vs controls, Phase I ≈ 0. Meta-evidence: 483 effect sizes / 80 evaluations / 21 schemes — immediate substantial reductions for ≥17 | **High** — best causal identification in the literature |
| 11 | **Green/climate-motivated institutional ownership (engagement)** | + | Azar/Duro/Kadach/Ormazabal and NBER w31791: emissions fall when *green fund* ownership rises, unchanged for non-green; effect strongest for actively engaging pensions rather than passive funds | **High** |
| 12 | **Divestment pressure** | ≈ 0 / possibly **−** | divestment likely counterproductive vs holding; engagement, not exit, moves emissions | **Medium-High** |
| 13 | **Climate-linked executive compensation** | + *if emission-specific* | emission-specific KPIs show a significant negative relation to emissions, strongest in regulated industries; **generic ESG-linked pay does not** — vague/weakly monitored KPIs are adopted symbolically | **Medium** — the *specificity* of the KPI is the feature, not its presence |
| 14 | **Board networks / interlocks with regulated peers** | + | 1,952 firms / 48 countries / 2003–2020, stacked DiD on exogenous carbon-regulation shocks: focal firms cut absolute emissions ~**9%**; concentrated in high emitters under strict regulation, *with* targets and policies, and with low financial constraints | **Medium-High** |
| 15 | **Financial constraints / leverage** | − (constraint) | abatement is capex; constrained firms cannot fund it. Interaction effect in #14; dedicated literature on decarbonisation under financial constraints | **Medium** |
| 16 | **Digital transformation** | + | 1 s.d. increase ≈ **−3.2% carbon intensity**, staggered-rollout DiD; channel is R&D → green innovation bias → TFP | **Medium** |
| 17 | **Jurisdiction: common-law + media accountability** | + | target achievement rates materially higher (Nature Climate Change 2024) | **Medium** |
| 18 | **Assurance / verification of reported data** | + | "particularly when targets are externally validated and data is assured" | **Medium** |
| 19 | **Lobbying activity inconsistent with stated pledge** | − | core red-flag dimension in npj Climate Action (2026) greenwashing framework | **Low-Medium**, hard to source |
| 20 | **Disclosure status (reported vs estimated)** | confounder, not predictor | LSEG: MQ 0–2 tail dispersion "largely disappears among disclosed emitters" | **Control variable — must be in every model** |
| 21 | **Sector** | dominant confounder | Tech +28% vs Utilities −25% (2019–24); Utilities alone ≈ ⅓ of index Scope 1+2 | **Control** |
| 22 | **Scope 2 accounting method (location vs market)** | measurement artefact | Tech: +60% location vs +22% market, 2020–24 | **Control — pin the method or the "decarboniser" label is an artefact** |

### 2.3 Modelling approaches used in this literature

- **Panel / causal designs** dominate the credible end: staggered DiD on regulation shocks
  and board interlocks; regression discontinuity and matched DiD on ETS coverage;
  event studies around target announcement and around target failure.
- **Supervised ML**: Lasso/Ridge/Elastic Net vs RF/XGBoost/NN — non-linear models win, XGBoost
  most robust; governance features matter most in the cold-start (no emissions history) case.
- **Sequence/state models**: *Modelling Corporate Transition Dynamics Using Markov Chains,
  Hidden Markov Models and CatBoost: Evidence from High-Emission Sectors* (Sustainability, MDPI)
  — models transition *states* rather than a continuous emissions target;
  https://www.mdpi.com/2071-1050/18/5/2351
- **Regime-dependence warning**: *Dynamic Evolution of Corporate Emissions Determinants*
  (arXiv 2605.22994), a US facility panel 1992–2023, finds determinants are **time-dependent** —
  variables strongly associated with emissions in one regulatory phase lose relevance, reverse
  sign, or re-emerge later. A model fitted on 2016–2024 should not be assumed stable through
  2030.
- **Classification framing**: threshold-based high-emitter classification (e.g. >125,000 tCO2e
  under Korea's ETS) benchmarking RF/SVM/XGBoost/LightGBM/CatBoost; and LLM-extracted
  qualitative indicators from sustainability reports used to enrich the feature space for a
  downstream ML classifier — the hybrid pattern that maps most directly onto this repo.

---

## Part 3 — Synthesis: a defensible company-level decarbonisation classifier

Combining the report's method with the literature, five design rules:

1. **Define the label carefully.** "Decarbonising" must be a chained, constant-perimeter,
   multi-year (≥3y, ideally 5y) Scope 1+2 change with a fixed Scope 2 accounting method,
   restricted to *disclosed* emitters for training. Every shortcut here (single-year change,
   mixed location/market Scope 2, estimated emissions in the label) injects the exact
   compositional and measurement noise the report spends its whole attribution section
   removing. M&A and divestment restatements are the label's biggest practical hazard.

2. **Persistence is the benchmark, not a feature to celebrate.** Report every feature's
   contribution *net of* lagged emissions growth and sector × region fixed effects.

3. **Structure beats presence, everywhere.** Not "has a target" but absolute-vs-intensity ×
   scope coverage × quantifiability × assurance. Not "has ESG-linked pay" but
   emission-specific KPI vs generic. Not "has a transition plan" but capex-backed vs narrative.
   This is the consistent shape of the findings: #4, #5, #6, #13.

4. **The strongest signals are external pressure and committed resources, not stated ambition.**
   Carbon pricing exposure (#10, the cleanest causal evidence in the field), green-investor
   engagement (#11), and green capex (#7) beat pledges (#5). Governance quality (#2) and
   cheap talk (#6) work because they proxy for whether a firm has built the machinery to
   deliver — they are credibility measures, not ambition measures.

5. **Credibility weighting is the report's real contribution, and it is where a pipeline adds
   most.** TPI MQ is a coarse proxy — 19 binary indicators, natively ~600 high-carbon
   companies, extended by model beyond that. The 27% → 8% collapse in 1.5°C-aligned share
   once credibility is applied shows how much rides on that proxy. A grounded, document-level
   credibility score — target structure, capex backing, governance mechanics, assurance,
   lobbying consistency, cheap-talk score — built with verified citations, is a direct
   improvement on using an MQ band as the blend weight.

### Where the gaps are

- **Scope 3 is unmodellable at present** for cross-sectional classification: 40% material-category
  disclosure, provider correlations as low as 16%, ML estimation accuracy poor. Material-category
  filters are a mitigation, not a fix.
- **Green capex coverage** (<50% of top emitters, ~30% ex-Europe) makes it a strong-but-biased
  feature; missingness is itself informative and should be modelled, not imputed away.
- **Scope 2 method divergence** will widen with AI electricity demand. Any model trained on
  mixed-method Scope 2 across 2020–2026 Technology names is learning procurement accounting.
- **Regime instability** (arXiv 2605.22994) argues against a single static model and for
  period-aware validation.
- **Lobbying consistency** is the least-covered high-value feature class — document-extraction
  territory rather than a licensable dataset.

---

## Bibliography

**The anchor report**
- LSEG / FTSE Russell with UN-convened NZAOA (September 2026). *Decarbonising portfolios 2026:
  Tracking the transition across investment benchmarks.* 5th annual edition.
- LSEG (2026). *From promise to plausibility: Credibility-adjusted ITR scores.*
- LSEG (2025). *Scope 3 conundrum: How materiality filters can sharpen the focus.*
- LSEG (2023). *Are corporates walking the walk on climate pledges?*
- FTSE Russell. *Decarbonisation equity benchmarks.*
  https://www.lseg.com/content/dam/ftse-russell/en_us/documents/research/decarbonisation-equity-benchmarks.pdf

**Targets, commitments and accountability**
- Bolton, P. & Kacperczyk, M. *Firm Commitments.* NBER WP 31244 / SSRN 3840813.
  https://www.nber.org/system/files/working_papers/w31244/w31244.pdf
- *Limited accountability and awareness of corporate emissions target outcomes.* Nature Climate
  Change (2024). https://www.nature.com/articles/s41558-024-02236-3
- *Renewable energy certificates threaten the integrity of corporate science-based targets.*
  Nature Climate Change (2022). https://www.nature.com/articles/s41558-022-01379-5
- *Quantitative evaluation of large corporate climate action initiatives shows mixed progress in
  their first half-decade.* Nature Communications (2023).
  https://www.nature.com/articles/s41467-023-38989-2
- *Corporate carbon performance and the Science-Based Targets initiative: disentangling the effects
  across Scope 1, 2, and 3 emissions.* Journal of Industrial Ecology (2026).
  https://link.springer.com/article/10.1007/s44498-026-00058-4
- *Corporate net zero targets: Neither greenwashing nor a gamechanger.* CEPR VoxEU.
  https://cepr.org/voxeu/columns/corporate-net-zero-targets-neither-greenwashing-nor-gamechanger
- *Red flags in green promises: a framework for identifying greenwashing risk in corporate climate
  pledges.* npj Climate Action (2026). https://www.nature.com/articles/s44168-026-00346-6
- *An audit of corporate decarbonisation ambition against low carbon futures.* Scientific Reports
  (2025). https://www.nature.com/articles/s41598-025-20203-6
- *Evaluating net-zero targets' impact on corporate emissions.* Environmental Research Letters.
  https://iopscience.iop.org/article/10.1088/1748-9326/adeff8/pdf
- *The Mediating Role of Climate Targets in Corporate Emission Reductions.* Business Strategy and
  the Environment (2026). https://onlinelibrary.wiley.com/doi/full/10.1002/bse.70364
- *Do credible climate transition plans matter for carbon performance? Evidence from Fortune Global
  500 firms.* Frontiers in Environmental Science (2026).
  https://www.frontiersin.org/journals/environmental-science/articles/10.3389/fenvs.2026.1907357/full

**Predictive variables and firm-level drivers**
- *The Anatomy of Decarbonizing Firms.* (persistence; SBT catalyst; ML beats heuristics for
  one-year-ahead abatement)
- Colmer, Martin, Muûls & Wagner. *Does Pricing Carbon Mitigate Climate Change? Firm-Level Evidence
  from the European Union Emissions Trading System.* Review of Economic Studies 92(3), 2025.
  https://academic.oup.com/restud/article/92/3/1625/7681739 ;
  working paper: https://cep.lse.ac.uk/pubs/download/dp1728.pdf
- *Divestment and Engagement: The Effect of Green Investors on Corporate Carbon Emissions.*
  NBER WP 31791. https://www.nber.org/system/files/working_papers/w31791/w31791.pdf
- Azar, Duro, Kadach & Ormazabal. *Institutional investors, climate disclosure, and carbon emissions.*
  Journal of Accounting and Economics (2023).
  https://www.sciencedirect.com/science/article/pii/S0165410123000642
- Bingler, Kraus, Leippold & Webersinke. *How cheap talk in climate disclosures relates to climate
  initiatives, corporate emissions, and reputation risk.* Journal of Banking & Finance (2024).
  https://www.sciencedirect.com/science/article/pii/S0378426624001080
- *Board Networks and Corporate Carbon Emissions: A Cross-Country Analysis of Causal Effects.*
  Business Strategy and the Environment. https://onlinelibrary.wiley.com/doi/10.1002/bse.70878
- *Climate Contracting and Carbon Performance: Does Climate Governance Matter?* Corporate Governance:
  An International Review (2026). https://onlinelibrary.wiley.com/doi/10.1111/corg.70045
- *Corporate digital transformation, carbon emissions, and ESG performance.* Empirical Economics
  (2026). https://link.springer.com/article/10.1007/s00181-026-02918-1
- *Corporate governance and carbon emissions performance: International evidence on curvilinear
  relationships.* Journal of Environmental Management (2023).
  https://www.sciencedirect.com/science/article/pii/S0301479723002621
- *Corporate Decarbonization under Financial Constraints.* ECGI working paper.
- *Dynamic Evolution of Corporate Emissions Determinants.* arXiv 2605.22994.
- *Modelling Corporate Transition Dynamics Using Markov Chains, Hidden Markov Models and CatBoost:
  Evidence from High-Emission Sectors.* Sustainability (MDPI). https://www.mdpi.com/2071-1050/18/5/2351

**Emissions data quality and estimation**
- Busch et al. *Corporate carbon emissions data for equity and bond portfolios.* Managerial Finance
  50(1), 2024. https://www.emerald.com/mf/article/50/1/118/1224623/Corporate-carbon-emissions-data-for-equity-and
- *Scope 3 emissions: Data quality and machine learning prediction accuracy.* PLOS Climate.
  https://journals.plos.org/climate/article?id=10.1371%2Fjournal.pclm.0000208
- *Greenhouse gases emissions: estimating corporate non-reported emissions using interpretable machine
  learning.* arXiv 2212.10844.
- *Estimation of Corporate Greenhouse Gas Emissions via Machine Learning.* arXiv 2109.04318.
- *Machine learning for predicting corporate carbon emissions: The role of corporate governance.*
  https://www.sciencedirect.com/science/article/pii/S2773067025000512
- Banque de France. *Estimating corporate carbon emissions using artificial intelligence.*
- *GHGbench: A Unified Multi-Entity, Multi-Task Benchmark for Carbon Emission Prediction.*
  arXiv 2605.13743.
- LSEG. *ESG carbon data and estimate models* (factsheet).
  https://www.lseg.com/content/dam/data-analytics/en_us/documents/fact-sheets/lseg-esg-carbon-data-and-estimate-models.pdf

**Frameworks and assessment**
- Transition Pathway Initiative. *Methodology and Indicators, Management Quality and Carbon
  Performance, v4.0* (Nov 2021). https://www.transitionpathwayinitiative.org/methodology
- LSEG. *TPI Management Quality Scores, powered by LSEG* (factsheet).
  https://www.lseg.com/content/dam/data-analytics/en_us/documents/fact-sheets/lseg-tpi-mq-scores-factsheet.pdf
- Climate Action 100+. *Net Zero Company Benchmark — methodology* (2026 framework).
  https://www.climateaction100.org/net-zero-company-benchmark/methodology/
- GFANZ. *Net-zero Transition Plan framework.*
  https://www.gfanzero.com/our-work/financial-institution-net-zero-transition-plans/
- IIGCC. *Investor Expectations of Corporate Transition Plans: From A to Zero*; *Net Zero Investment
  Framework.* https://www.iigcc.org/net-zero-investment-framework
- NZAOA / UNEP-FI. *A Tool for Developing Credible Transition Plans* (2023).
- *That's none of my business: A holistic framework for evaluating corporate decarbonization at the
  core of business.* Energy Research & Social Science (2025).
  https://www.sciencedirect.com/science/article/pii/S2214629625001756

**Portfolio attribution and alignment metrics**
- UNEP-FI / NZAOA. *Understanding the Drivers of Investment Portfolio Decarbonisation* (2023).
  https://www.unepfi.org/wordpress/wp-content/uploads/2023/12/Emission-Attribution-Analysis-Discussion-Paper_FINAL.pdf
- EDHEC Climate Institute. *Attribution analysis of greenhouse gas emissions associated with an equity
  portfolio.* https://climateinstitute.edhec.edu/news/attribution-analysis-greenhouse-gas-emissions-associated-equity-portfolio
- IIGCC. *NZIF's Portfolio Decarbonisation Reference Objective and attribution analysis.*
- TCFD. *Measuring Portfolio Alignment: Technical Supplement* (2021).
  https://ccli.ubc.ca/wp-content/uploads/2021/09/2021-TCFD-Portfolio_Alignment_Technical_Supplement.pdf
- Bingler, Colesanti Senni & Monnin. *Understand what you measure: Where climate transition risk metrics
  converge and why they diverge.* Finance Research Letters 50 (2022).
  https://ideas.repec.org/a/eee/finlet/v50y2022ics1544612322004561.html
- *How you measure transition risk matters: comparing and evaluating climate transition risk metrics.*
  Ecological Economics (2025). https://www.sciencedirect.com/science/article/pii/S092911992500207X
- WWF. *The Alignment Cookbook.*
- *Uncertainty Quantification in Portfolio Temperature Alignment.* arXiv 2412.14182.
- SBTi Finance Tool (temperature scoring). https://sciencebasedtargets.github.io/SBTi-finance-tool/intro.html

**NLP / LLM approaches**
- Webersinke et al. *ClimateBert: A Pretrained Language Model for Climate-Related Text.* arXiv 2110.12010.
- *ClimateBERT-NetZero: Detecting and Assessing Net Zero and Reduction Targets.* arXiv 2310.08096.
- Ni et al. *ChatReport* (TCFD-based LLM evaluation of sustainability reports).
- *Judging It, Washing It: Scoring and Greenwashing Corporate Climate Disclosures using LLMs.*
  arXiv 2502.15094.
- *Climate AI for Corporate Decarbonization Metrics Extraction.* arXiv 2411.03402.
- *Glitter or Gold? Deriving Structured Insights from Sustainability Reports via LLMs.* arXiv 2310.05628.
- WWF. *Combining AI and Domain Expertise to Assess Corporate Climate Transition Plans* (2024).

---

## Sourcing caveats

**Read this before citing anything below the Part 0 line.**

Findings attributed to the LSEG/NZAOA report (Part 0, and every figure elsewhere marked as
the report's) are read directly from the source PDF and are reliable.

**Every claim about the external literature in Parts 1–3 and the bibliography rests on web
search-result summaries, not on the papers themselves.** No external full text was retrieved:
this environment's network egress proxy denies all the relevant domains — nber.org,
nature.com, academic.oup.com, sciencedirect.com, link.springer.com, emerald.com,
cep.lse.ac.uk, arxiv.org, ecgi.global, unepfi.org, journals.plos.org and
transitionpathwayinitiative.org all return a policy denial. Titles, venues and URLs were
resolved from search indexes; quantitative details, effect sizes and characterisations of
method were paraphrased by the search tool from page content it retrieved.

Practical consequences:

- Treat every number in the Part 2 evidence table as **unverified against source**. The
  direction of each finding is more trustworthy than its magnitude.
- Publication years — particularly for 2025–2026 items — are as reported by the search index
  and may refer to online-first versions, preprints, or in some cases may be wrong.
- *The Anatomy of Decarbonizing Firms* is cited without authors or a venue because the search
  results did not supply them. It carries substantial weight in §2.1 and design rule 2, and is
  the single highest-priority item to verify.
- Where a search summary attributed a finding to a named journal, that attribution has not been
  independently checked.

Verify against primary sources before any external use.
