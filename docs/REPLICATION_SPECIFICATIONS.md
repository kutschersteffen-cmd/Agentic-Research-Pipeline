# Replication specifications

Method extraction for the fifteen studies behind
[`CORPORATE_DECARBONISATION_REVIEW.md`](CORPORATE_DECARBONISATION_REVIEW.md).
One section per paper: data, sample construction, variable definitions,
estimator, inference, headline results to target, and what blocks replication.

Everything here is read from the papers. Where a detail is not recoverable from
the published text it says so rather than filling the gap. **Status** records
whether `arp.decarb` implements the method.

---

## 1. Dietz & Hastreiter (2026) — long-term net zero targets

*Corporate net zero targets: have they achieved anything?* Grantham Research
Institute Working Paper 446, 28 April 2026.

**Question.** Does adopting a long-term net zero (LTNZ) target change near-term
emissions or climate management?

**Universe.** The Transition Pathway Initiative company universe, ~2,000 listed
firms plus 27 large private companies, selected on a combined equal-weighted
ranking of absolute emissions and market capitalisation *within* sectors that
were themselves selected on absolute emissions and market cap (ICB sectors).
Chosen over index universes because indices miss the largest emitters, and over
CDP/SBTi samples because those are voluntary and self-selected. LTNZ data
available for 1,972 firms.

**Treatment.** Refinitiv ESG, extracted 4 February 2026. Refinitiv stores up to
six target sets per firm; they take the **earliest** LTNZ target. An LTNZ target
is a firm-level pledge to reach net zero, or an explicit equivalent (carbon
neutrality, climate neutrality), by around mid-century. All scopes included;
Refinitiv's "emissions scope" field flags Scope 3 inclusion for subgroup tests.
Non-adopters in sample period are never-adopters. Adoption rose 70 (2019) →
1,236 (2024), 63%.

**Outcomes.** Two emissions sources and four governance measures.

| Outcome | Source | Coverage |
|---|---|---|
| log absolute GHG (S1+2+upstream S3) | Trucost | ~1,600 firms, 2015–2023 |
| log GHG intensity (÷ revenue) | Trucost | same |
| Sector-specific physical intensity, z-scored to 2015 sector mean | TPI | ~200 firms, 2015–2022 |
| MQ indicator count (0–13) | TPI | 1,398 firms |
| MQ hierarchical level (0–5) | TPI | same |
| **MQ weighted score** (0–5.9), rarer/more demanding practices weighted higher | TPI | same |
| CDP score (numeric 1–8) | CDP | 1,377 firms |

**Stage 1, selection into treatment.** Linear probability model (not logit:
nonlinear FE estimators are biased in short panels, and conditional logit drops
never-adopters):

```
LTNZ_{i,t+1} = α + β1 log(MarketCap_it) + β2 log(AbsEmissions_it)
             + β3 log(EmissionsIntensity_it) + β4 MQ_it + γ_t + (μ_i or δ_s) + ε_it
```

One-year lead so regressors precede adoption. Adopter observations truncated at
one year pre-announcement to avoid post-treatment contamination. SEs clustered
on company. n = 3,115.

Results: market cap does not robustly predict adoption. Under **firm FE**,
absolute emissions are *negatively* and intensity *positively* associated; under
**sector FE** the absolute-emissions sign *reverses* (+0.0169**). MQ weighted
score is the strongest predictor (firm FE +0.0459***, sector FE +0.0646***).

**Stage 2, matching.** Propensity score matching, **not** CEM. Matched on log
market cap, log absolute emissions, log intensity, MQ weighted score, region,
sector cluster. Performed **per adoption cohort**, using pre-treatment covariate
averages from before the adoption year only. Logistic propensity model,
nearest-neighbour, **caliper 0.2**. Balance goes from Diff 0.64*** on MQ
weighted score to 0.018; 686 treated firm-cohorts → 645 matched pairs.
Robustness: alternative matching adding leverage, return on equity,
capex/assets.

**Stage 3, estimator.** **Callaway & Sant'Anna** group-time ATTs with
not-yet-adopters as controls, aggregated to event time. They note the estimator
assumes continuous outcomes, which MQ counts, levels and CDP scores are not.
TPI intensity sample too small to match, so reported unmatched.

**Target results.** Emissions: pre-trends near zero, post-adoption negative but
CIs always include zero. MQ count: no effect. **MQ level: negative, significant
at t+3.** MQ weighted score: positive, increasing, significant, preceded by a
significant t−1 coefficient concentrated in the 2021 cohort. By TCFD theme,
Governance negative, Strategy positive with the same t−1 anticipation.

**Explanation for the negative level effect:** non-adopters catching up on basic
practices.

**Blocks.** TPI MQ weighting scheme not published in the paper; Refinitiv and
Trucost both licensed.

**Status.** `research.did` implements the Callaway–Sant'Anna family; matching is
CEM not PSM, so the pipeline is not their design. Rarity weighting in
`saturation` is a reconstruction of the weighted-MQ idea, not their scheme.

---

## 2. Schüder & Zülch (2026) — SBTi across scopes

*Corporate carbon performance and the Science-Based Targets initiative.*
Journal of Industrial Ecology 30:799–813.

**Sample.** Design adopted from Romito et al. (2024). All listed firms
headquartered in Europe, North America, Asia (95% of SBTi participation) from
LSEG Data & Analytics, 2015–2024. Drop incomplete financial/ESG entries. SBTi
status from the SBTi website; "engaged" = active commitment **or** verified
targets. Merged on ISIN. Require ≥3 consecutive years of emissions reporting.
**4,104 firms before matching, 3,113 after.** 13.9% treated.

**Matching.** Coarsened exact matching. Covariates deliberately few: firm size
(total assets, **deciles**), region (Europe/NA/Asia), industry (carbon-intensive
vs not, per EU ETS), observation year, and the scope-specific log emissions
intensity. **Matching run separately per emissions scope.** Also run under both
three- and four-year minimum disclosure requirements.

**Dependent variables.** log(emissions ÷ sales), computed separately for Scope
1, location-based Scope 2, market-based Scope 2, Scope 3.

**Controls.** Return on assets; firm size as total assets relative to industry
average; debt-to-equity; LSEG governance score.

**Model.** OLS **weighted by CEM weights**, with **industry × year × region**
fixed effects, robust SEs, two-tailed tests. Estimated separately at t+1 … t+4.

**Target results.** Scope 1: −0.368*** (t+1), −0.387*** (t+2), −0.414*** (t+3),
−0.511*** (t+4). Market-based Scope 2: significant at t+2 and t+3 only.
Location-based Scope 2: consistently negative, above the 10% threshold in most
specifications. Scope 3: no effect. **Governance control is positive and
significant** (+0.007 to +0.008, p<0.01) in three of four Scope 1 models — i.e.
higher governance score, higher carbon intensity. Firm size negative throughout.

Diagnostics reported: pairwise correlations |<0.50|, VIF < 2.00, condition
numbers < 20. Robustness: alternative dependent variables and a stacked DiD.

**Blocks.** LSEG licensed. Romito et al. (2024) design details are in that paper.

**Status.** `research.matching` (CEM + weights) and `research.inference`
(weighted OLS, interacted FE, clustering) provide the components. Their exact
t+1..t+4 specification is not pre-built.

---

## 3. Brown, Hsu & Manya (2026) — greenwashing red flags

*Red flags in green promises.* npj Climate Action 5:19.

**Data.** Net Zero Tracker (via Green et al. 2024's reconstructed historical
records, aligned to **2022** to match CDP), CDP 2022 Climate Change
Questionnaire via the 2022 Global Climate Action report (13 major emitting
countries, 2,295 companies with quantifiable targets), and InfluenceMap
LobbyMap extracted October 2024. Matched with the **ClimActor** R package plus
manual review. **4,131 companies; 3,574 with a climate claim.**

**Claim gate.** Appears on NZT with any reduction pledge, **or** reports ≥1
emissions target for any scope.

**The seven rules** (1 = fails):

| Flag | Rule |
|---|---|
| No interim target | NZT reports none. If NZT missing, credited if CDP shows ≥2 targets with **different target years** |
| No implementation plan | NZT reports no plan |
| No Scope 3 coverage | Flag **unless** NZT shows full *or partial* Scope 3, **or** any CDP target references Scope 3 even partially |
| Questionable offsets | Fails to disclose whether offsets will be used, **or** confirms use without conditions (e.g. excluding avoided emissions, requiring safeguards) |
| Incomplete GHG coverage | Inventory unspecified or **CO₂ only**, *and* end target is one of: net zero, net negative, climate neutral, climate positive, zero emissions, GHG neutral |
| Negative lobbying | LobbyMap band **C or lower**. Only 600 firms rated |
| Not on track | PETA < 1 |

**PETA.** achieved ÷ required, on a linear trajectory base year → target year.
Their equations (2) and (3) do not reconcile as typeset (achieved is negative
for a firm that cut emissions while required is positive, so the stated
on-track test could never hold); the working reading is
`achieved = E_base − E_report`, `required = (E_base − E_target) × elapsed
fraction`.

**Ambition,** their eq. (4):
`−100 × (1 / remaining maturity in years) × (E_target − E_base)/E_base`.

**No composite index**, explicitly: no agreed weighting exists, any weighting is
"inherently subjective", and binary indicators without an intensity dimension
"could dilute their meaning" when combined. Indicators analysed individually,
with co-occurrence counts and pairwise **phi** correlations.

**Target results.** 96% of pledging firms carry ≥1 flag. Scope 3 70%, offsets
40%, no interim 21%, off-track 20%, no plan 18%, GHG coverage 11%, lobbying 10%.
41% exactly one flag, 12% four or more. Net-zero-only subsample 95.8% overall
but offsets +29pp, no plan +10pp, Scope 3 −22pp. Ambition negatively correlated
with Scope 3 gaps (−0.19) and offsets (−0.18).

**Note.** Their results text describes the GHG-coverage dimension as failing "to
comprehensively address all emission scopes". The Methods are explicit it
concerns **gases**. Follow the Methods.

**Status. Implemented** in `arp.decarb.flags`, all seven rules plus PETA and
ambition. Not validated against their data.

---

## 4. Jiang, Kim & Lu (2025) — target accountability

*Limited accountability and awareness of corporate emissions target outcomes.*
Nature Climate Change 15:279–286.

**Sample.** CDP firms with emissions targets having **target year 2020**,
reporting years 2010–2021. CDP reporting year *n* covers fiscal *n−1*.

**Target filters,** applied in order: cover >80% of base-year emissions within
scope; horizon >3 years (target year − base year); cover Scope 1 or Scope 2
(Scope 3 excluded for measurement comparability); where a firm has multiple
targets per (type × scope), keep the one with highest base-year emissions,
highest coverage, longest horizon. Resulting targets cover 98.10% of sample
firms' emissions, mean reduction goal 23.81%.

**Outcome classification.**
- *Achieved*: self-reported progress reaches 100%, or status "achieved", in the
  most recent reporting year for that target.
- *Failed*: most recent reporting year **is 2021** and progress <100% / status
  not achieved.
- *Disappeared*: most recent reporting year is **before 2021** and progress
  <100% / status not achieved.
- Firms that stopped reporting to CDP entirely are **excluded** (likely external
  business events).
- Failed targets manually verified against sustainability reports and CDP
  comments.
- Firm-level: ≥1 failed target → failed firm; achieved and no failures →
  achieved; disappeared and neither → disappeared.

**Result: 1,041 firms → 633 achieved, 88 failed (9%), 320 disappeared (31%).**

**Media.** Ravenpack and TruValue Spotlight, three-stage keyword filter
(environment terms → target terms → achievement/failure terms), headline date
before 1 January 2022, future-tense headlines excluded, manual review. **Only 3
failed firms covered.**

**Consequences.** Difference-in-differences comparing failed to achieved firms,
2021 against prior years, on market reaction, media sentiment, environmental
scores, environment-related shareholder proposals. No significant negative
effect. Alternative explanations tested and rejected: prior information,
target ambition, COVID, industry materiality. One exception — significantly
lower MSCI environmental score for failed firms with unambitious targets.

**Blocks.** CDP, Ravenpack, TruValue all licensed.

**Status.** Not implemented.

---

## 5. Fliegel (2026) — transition-metric divergence and evaluation

*How you measure transition risk matters.* Journal of Corporate Finance 98:102939.

**Metrics (8).** EU taxonomy alignment of capex; taxonomy alignment of revenue;
emission intensity; Scope 1–2 intensity; Refinitiv E-score (lagged one year);
MSCI E-score (portfolio returns from Pástor et al. 2022, raw scores
unavailable); Refinitiv Business Classification sector/technology; text-based
CC exposure and CC opportunity scores from Sautner et al. (2023a) earnings-call
keyword discovery. Exposure treated as backward-looking, opportunity as
forward-looking.

**Part 1, divergence.** Spearman rank correlations. Within-group: taxonomy 0.73,
emission intensity 0.60, text 0.58. Between-group ≈ 0. All taxonomy proxies
correlate **negatively** with inverted emission-intensity metrics.

**Part 2, evaluation.** Sort European firms into green/brown portfolios at the
**70th/30th percentiles** of each metric; equal-weighted monthly excess returns,
**February 2010 – July 2024** (179 months; 131 for MSCI). Regress on Fama–French
five factors plus a market-wide climate news shock index; the coefficient on the
shock index measures how well the metric proxies transition risk. Four shock
indices: Unexpected Media Climate Change Concern, Business Impact Innovation,
Transition Risk Innovation, and a standardised **aggregate** of them (his
recommendation, to smooth single-index measurement error). Value-weighted
returns in the appendix.

**Target results.** Green portfolios: taxonomy and TRBC react most strongly.
Brown: MSCI E-scores and TRBC strongest. Forward-looking metrics outperform
exposure measures.

**Note.** The author discloses using ChatGPT o3 for coding assistance.

**Status.** `divergence` implements Part 1 only. **Part 2, the evaluation that
makes the paper, is not implemented** — it needs monthly returns, FF5 factors
and the news indices.

---

## 6. Xu, Wei & Ji (2026) — ML prediction of carbon intensity

*Machine learning for predicting corporate carbon emissions: the role of
corporate governance.* Journal of Digital Economy 5:1–16.

**Target.** Carbon emission **intensity**, a level.

**Models (6).** Lasso, Ridge, Elastic Net, Random Forest, XGBoost, Neural
Network. Periods: full 2016–2023, pre-COVID 2016–2019, post-COVID 2020–2023.
Each run twice, with and without carbon-related predictors.

**Features.** 60 variables in a two-level hierarchy: four categories
(Carbon-Emission-Related, Governance, Financial, Firm-Specific) and 11
subcategories. Importance via XGBoost **Gain**, summed within category.

**Target results.** Linear models R² ≈ 0 or negative. XGBoost best throughout.
Pre-COVID R² 0.95 with all variables, **0.85 without carbon variables**;
post-COVID 0.88 / 0.85. Within governance, **Board Characteristics** the
strongest subcategory. With the carbon signal removed, weight shifts to
Liquidity, Profitability, Firm Value.

**Caveat for interpretation.** Predicting an intensity *level* without carbon
inputs largely recovers sector and size. `research.models.compare_targets`
demonstrates this: shuffling sector destroys the level R².

**Status.** `research.models` implements the comparison design with five models
(sklearn GBM for XGBoost) and permutation importance. Not their 60-feature
specification.

---

## 7. Bingler, Kraus, Leippold & Webersinke (2024) — cheap talk

*How cheap talk in climate disclosures relates to climate initiatives, corporate
emissions, and reputation risk.* Journal of Banking and Finance 164:107191.

**Model.** ClimateBertCTI, fine-tuned from ClimateBert on two tasks:
commitment/action classification and specificity classification.

**Index.** For each firm-year, drop non-climate paragraphs from the annual
report, classify the rest, then

```
CTI_it = |COMMIT ∩ NONSPEC|_it / |COMMIT|_it
```

the share of climate commitments that are non-specific.

**Sample.** MSCI World constituents, annual reports 2010–2020.

**Target results.** Targeted climate engagement → less cheap talk. Supporting
voluntary disclosure frameworks → **more** cheap talk. Cheap talk → higher
emissions growth and more negative news coverage. Utilities CTI up ~100% over
the period.

**Two caveats the authors state.** The emissions-growth relationship is
insignificant over the full sample and appears in later years only. It holds in
**third-party estimated data (Urgentem)** and **not** in self-reported data;
they deliberately avoid self-reported data because cheap talk and self-report
reliability are likely positively correlated, which would confound the estimate.

**Status.** Not implemented. Needs the fine-tuned model and an annual-report
corpus.

---

## 8. Schimanski, Bingler, Hyslop, Kraus & Leippold (2023) — target detection

*ClimateBERT-NetZero.* arXiv 2310.08096.

Expert-annotated dataset of **3.5K** text samples. Classifier detects whether a
passage contains a net zero or reduction target. Accuracy **>96%**, beating
other BERT-family models and GPT-3.5. Hyperparameter grid over learning rate,
batch size, epochs reported as only marginally affecting accuracy. Demonstrated
combined with Q&A models to extract target ambition, and applied to quarterly
earnings call transcripts.

**Status.** Not implemented. Relevant as the tool that makes target-structure
features tractable at scale.

---

## 9. Colmer, Martin, Muûls & Wagner (2025) — EU ETS

*Does Pricing Carbon Mitigate Climate Change?* Review of Economic Studies
92:1625–1660.

Linked **administrative** data on French manufacturing plants' fuel use
(EACEI survey), giving consistent plant-level CO₂ construction. French ETS
installations matched to the manufacturing census via the official trading
registry. **Matched difference-in-differences** following Heckman et al.
(1997, 1998), with weights ω_jk from the matching step.

**Target results.** −14 to −16% CO₂, no detectable output contraction, no
outsourcing to unregulated firms or markets, targeted investment lowering the
emissions intensity of production. Phase I point estimates ≈ 0 and
insignificant; Phase II effects large. Mechanism: inattention — firms with low
initial productivity or high energy intensity underinvest in energy-saving
capital pre-regulation and show larger reductions *and* increases in activity
afterwards.

**Blocks.** French administrative microdata under restricted access. This is the
best-identified result in the corpus and the least replicable outside France.

**Status.** Not implemented.

---

## 10. Bolton & Kacperczyk (2025) — firm commitments

*Firm Commitments.* ECGI Finance Working Paper 990/2024, January 2025.

Trucost firm-level emissions (~99% of covered market cap; US 3,338, China 2,500,
Japan 2,467 firms; note Trucost expanded its universe between 2015 and 2016,
which creates a break). Commitment variables: `CDPTGT` (percentage reduction of
total Scope 1 implied by CDP targets), `CDPRED`, `SBTSIGN` (SBTi signatories,
including committed-but-not-yet-stated), `ABATE` (maximum percentage reduction
across stated commitments).

**Target results.** Committing firms subsequently reduce emissions, but
committers and the most ambitious committers already have **lower** emissions;
firms are **less** likely to commit ambitiously when Scope 1 emissions are
higher; commitments are less prevalent where national commitments exist; peer
pressure (industry commitment rates) predicts commitment; aggregate effect on
total emissions is small. Controls include emissions changes over the previous
one, three and five years.

**Status.** Not implemented.

---

## 11. Ruiz Manuel & Blok (2023) — initiative evaluation

*Quantitative evaluation of large corporate climate action initiatives.* Nature
Communications, doi:10.1038/s41467-023-38989-2.

**Design.** A Logical Framework evaluating SBTi and RE100 sequentially through
four indicators: **Ambition, Robustness, Implementation, Substantive Progress**.
Applied to the 102 largest members by revenue using publicly disclosed
environmental data, 2015–2019, disaggregated by sector and region.

**Target results.** Collective Scope 1+2 down **35.6%** from a baseline of 808.7
MtCO₂e. Concentrated in **eight** emission-intensive companies. Most members show
little operational reduction, progressing via renewable electricity purchases.
RE growth 31.2%/yr, reaching 45% of total electricity in 2019. **71% of
renewable energy purchased used low-additionality sourcing** (unbundled energy
attribute certificates, utility green premiums) against high-additionality PPAs.

**Status.** Not implemented. The additionality classification of sourcing models
is the transferable part and needs RE100 disclosure detail.

---

## 12. Silvia et al. (2026) — transition plan credibility

*Do credible climate transition plans matter for carbon performance?* Frontiers
in Environmental Science 14:1907357.

**Sample.** 239 Fortune Global 500 non-financial firms, **1,126 firm-years,
2018–2023**.

**CTPCI.** Binary coding of disclosure items, `CTPCI = disclosed items ÷ total
applicable items`. Six dimensions, 24 items:

| Dimension | Items | Coverage |
|---|---|---|
| Target credibility | 5 | net-zero/long-term target, interim target, baseline year, quantified target, target horizon |
| Emissions scope coverage | 3 | Scope 1, Scope 2, relevant Scope 3 consideration |
| Implementation strategy | 5 | renewables, energy efficiency, low-carbon technology, operational pathway, capital/investment alignment |
| Governance and accountability | 4 | board oversight, management responsibility, executive remuneration, internal monitoring |
| Risk and strategic integration | 4 | scenario analysis, transition risk, physical risk, strategy integration |
| Progress reporting | 3 | progress against targets, explanation of (non-)achievement, year-on-year emissions |

Items scored only on explicit, observable, verifiable disclosure; general
sustainability statements do not score. Ambiguities resolved by team discussion.
External assurance deliberately **excluded** from the index and used as a
moderator instead. Robustness uses a dimension-weighted variant giving each
dimension equal weight, so item-rich dimensions do not dominate.

**Moderators.** External Assurance (dummy, assured sustainability/ESG/climate
report or GHG data in year t). Regulatory Environment (country-year dummy for
mandatory or quasi-mandatory disclosure requirements).

**Models.**
```
CarbonChange_{i,t+1} = β0 + β1 CTPCI_it + β2 Controls_it + μ_i + λ_t + ε_it
CarbonChange_{i,t+1} = β0 + β1 CTPCI_it + β2 Assurance_it
                        + β3 (CTPCI_it × Assurance_it) + β4 Controls_it + μ_i + λ_t + ε_it
```
Firm and year fixed effects. H1 supported by a negative significant β1.

**Target results.** Higher credibility → lower subsequent emission changes.
Assurance strengthens it; mandatory disclosure environments moderate more
modestly. Scope 3 subsample weaker. Observational panel; authors interpret as
associational.

**Blocks.** The item-level coding checklist is in their Appendix A, which did not
extract from the PDF. Coding requires reading 1,126 firm-year reports.

**Status.** Not implemented. The closest fit for this repository's extraction
engine, since the 24 items are exactly the kind of grounded binary extraction it
does.

---

## 13. Oyewo (2023) — governance and carbon performance

*Corporate governance and carbon emissions performance: international evidence on
curvilinear relationships.* Journal of Environmental Management 334:117474.

**Sample.** Refinitiv/DataStream. Financial firms removed (160), then 4 firms
with no carbon data. **336 firms, 42 industries, 32 countries, 2006–2020, 4,550
firm-years.** Split into MDG (2006–2015) and SDG (2016–2020) eras.

**Dependent.** Total Scope 1 + Scope 2 emissions in tonnes ("carbon emissions
rate", negative polarity: lower is better). Robustness with Scope 1 and Scope 2
separately.

**Independent (6).** Board meetings, board independence, board gender diversity,
CEO duality, ESG-based compensation, ESG committee.

**Controls.** Firm size, market presence, leverage, liquidity, profitability;
country economic development and World Governance Indicators; Hofstede
individualism/collectivism, long-term orientation, indulgence.

**Estimator.** **Panel quantile regression** across q0.1 … q0.95 — this is what
"curvilinear" means in the title, not a quadratic term. Chosen because carbon
emissions are skewed and outlier-heavy, so OLS on the mean is inappropriate.
Robustness: 2SLS/IV with Anderson canonical correlation LM (under-identification)
and Stock–Yogo weak-identification tests.

**Target results.** Board gender diversity, CEO duality and ESG committee
negatively associated with carbon emissions rate (better). **Board independence
and ESG-based compensation significantly positive** (worse). Relationships vary
across quantiles.

**Status.** Not implemented. `research.inference.sign_stability` addresses the
instability this paper surfaces but is not quantile regression.

---

## 14. LSEG / FTSE Russell with NZAOA (2026) — portfolio attribution

*Decarbonising portfolios 2026.* Fifth annual edition, September 2026.

**Metrics.** Aggregate emissions; **chained emissions** (constant-perimeter,
constituents present in consecutive years); financed emissions (EVIC-attributed);
WACI (÷ revenue); CI-EVIC; CI-market cap; activity-based intensity. Sovereign:
production intensity ÷ PPP-adjusted GDP, consumption intensity per capita.

**Attribution (Appendix IV).** Contributions to WACI change from the logarithmic
change of index weight, carbon emissions and revenue, split into emissions (CE),
normalisation (Norm) and allocation (Alloc). CE further splits by reported vs
estimated data source; Alloc splits into constituent churn vs weight changes.
Inflation factors, or portfolio size for financed emissions, enter as additional
explicit factors.

**The equation is a raster image in the PDF and does not extract.** Footnote 39
is the one place the estimator is pinned down: "in the unlikely event that
changes in individual factors exactly cancel … the relative contributions of
individual factors will also be 0."

LMDI and proportional apportionment are algebraically identical here, since
`L(m₁,m₀) = (m₁−m₀)/ln(m₁/m₀)` and the three log changes sum to `ln(m₁/m₀)`.
They differ **only** where that sum is zero — exactly the footnote's case, where
LMDI gives equal and opposite non-zero contributions and the footnote requires
zero.

**Data.** Emissions from LSEG Climate MAP / LSEG Data & Analytics Climate
(reported plus Hierarchical Multi-model estimates), FY2024 latest. Financials
from WorldScope (EVIC, revenue, segment revenue), FY2024 revenue estimates from
I/B/E/S, market cap from FTSE Russell. Revenue deflated by the US GDP deflator
(IMF WEO); EVIC adjusted by the ratio of universe-average EVIC to 2024 average,
per the EU Paris-Aligned Benchmarks handbook. TPI MQ **v4** (not v5, chosen for
history length).

**Target results.** FTSE All-World Scope 1+2 ≈12.5 GtCO₂e, 23.5% of global.
WACI −5%/yr, CI-EVIC −6%, CI-MktCap −5%, 2016–2024, against global emissions per
GDP −2%. High-yield aggregate −9%/yr vs chained −2%/yr; allocation alone removed
66% of HY WACI 2016–2019. Technology location-based Scope 2 +60% vs market-based
+22%, 2020–2024. TPI MQ 2019 → 2019–24 annualised change: MQ5 −5.6%, MQ4 −3.5%,
MQ3 −1.1%, MQ2 +0.5%, MQ1 +1.4%, MQ0 +0.7%; 76% of MQ4–5 cut emissions vs 53% of
MQ0–2. ITR 3.1°C without targets, 1.9°C with, 2.3°C credibility-weighted;
1.5°C-aligned share 27% → 8%.

**Status. Implemented** in `attribution` (both readings) and `labels` (chained).
Not validated against their data.

---

## 15. Frisch, Engels, Rötzel, Johnson, Frank, Commelin & Busch (2025)

*That's none of my business.* Energy Research & Social Science.

Conceptual, not statistical. Core business modelled through three
industry-independent dimensions — **management, value chain, investments** — each
with three categories, nine in total, assessed with qualitative indicators
positioning a company on a spectrum between opposing poles. Built iteratively
from three years of a panel study with high-emitting companies: semi-structured
interviews with sustainability managers, review of CDP questionnaires, company
reports and websites, plus ongoing exchanges. Applied to three example
companies; proposes four types of interrelation between dimensions as future
research.

**Status.** Not code. Relevant as the argument that decarbonisation should be
assessed by integration into core business rather than by counting climate
management activities.

---

## Cross-cutting notes for anyone replicating

**Licensed data is the binding constraint.** Trucost, Refinitiv/LSEG, CDP,
WorldScope, I/B/E/S, Ravenpack, MSCI and TPI's full indicator set are all
needed across these papers. Net Zero Tracker, LobbyMap and the Sautner et al.
text measures are the most accessible.

**Three specifications are under-determined by their published text**: LSEG's
attribution equation (image), Silvia et al.'s item checklist (Appendix A did not
extract), and Brown, Hsu & Manya's PETA equations (do not reconcile as typeset).
Each is flagged above with the reading used.

**Emissions source matters and the papers disagree deliberately.** Dietz &
Hastreiter run Trucost *and* TPI physical intensities to test whether findings
are a measurement artefact. Bingler et al. use estimated rather than self-
reported data on purpose. Jiang, Kim & Lu use self-reported CDP progress because
self-report *is* the object of study. Any replication should state which and why.

**Scope 2 basis must be pinned.** Schüder & Zülch's split result is the
clearest demonstration that pooling the two bases measures procurement.
