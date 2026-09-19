# `arp.decarb` — analyses for the corporate decarbonisation review

Companion code for [`docs/CORPORATE_DECARBONISATION_REVIEW.md`](../../../docs/CORPORATE_DECARBONISATION_REVIEW.md).
Every module implements a specific claim in that paper so a reader can check
the argument by running it rather than taking the prose on trust.

Two layers. The **core** (`arp/decarb/*.py`) is standard library only, Python
3.11+, and runs anywhere. The **research subpackage** (`arp/decarb/research/`)
holds the econometrics and figures and needs the scientific stack.

The split is deliberate: label construction, attribution and the saturation
analysis are the parts most likely to be lifted into another codebase, and they
should not drag numpy, statsmodels and matplotlib with them. The estimators that
genuinely need those libraries live behind the extra.

## Run it

```bash
cd backend
python -m arp.decarb.pipeline            # descriptive report, no dependencies
python -m pytest tests/test_decarb_stats.py tests/test_decarb_analysis.py -q

pip install -e ".[research]"             # econometrics and figures
python -m arp.decarb.research.figures    # regenerate the paper's figures
python -m pytest tests/test_decarb_research.py -q
```

To run against real data, build a `Panel` of `FirmYear` rows and pass it to
`pipeline.run(panel)`.

## What each module does

| Module | Implements | Review section |
|---|---|---|
| `schemas` | `Panel`/`FirmYear`; rejects mixed Scope 2 bases | 3.1 |
| `labels` | Chained (constant-perimeter) and forward-looking labels | 2.2, rule 1 |
| `attribution` | LMDI split into emissions / normalisation / allocation | 2.2 |
| `scope2` | Location- against market-based Scope 2 wedge | 2.3, 3.1 |
| `saturation` | Prevalence decay, rarity weighting, stratified AUC | 6.3, rule 3 |
| `redflags` | Seven-dimension profile and the orthogonality test | 7, rule 4 |
| `divergence` | Rank correlation across transition-risk metric families | 3.5, rule 5 |
| `predict` | Out-of-time increment over a persistence baseline | 6.5, rule 2 |
| `synthetic` | Calibrated simulated panel | — |

### Research subpackage (needs `arp[research]`)

| Module | Implements | Review section |
|---|---|---|
| `research.frames` | Panel to pandas, growth and lag columns | — |
| `research.matching` | Coarsened exact matching, balance table | 4 |
| `research.did` | Staggered DiD event study, group-time ATTs | 4, 6.3 |
| `research.inference` | Panel OLS, clustered SEs, sign-stability | 8 |
| `research.models` | Model comparison, level against change | 6.5 |
| `research.figures` | The paper's six figures, light and dark | all |

## What this reproduces, and what it does not

Worth being blunt, because "implements the method from paper X" can mean very
different things.

**Nothing here reproduces a published result.** No number in this repository is
a replication of any paper's finding. Every analysis runs on a synthetic panel
(see below). The empirical claims in the review are sourced to the studies
themselves, never to this code.

What is implemented is the *estimator family* each paper uses, validated
against ground truth in data where the right answer is known by construction.
That is a weaker claim than replication and a stronger one than "a chart that
looks like theirs".

| Paper | Its method | Here | Fidelity |
|---|---|---|---|
| LSEG (2026) App. IV | Log-change attribution of WACI | `attribution` | Close. Written from their prose; the equation is a raster image in the PDF. Their footnote 39 pins one case and `decompose_waci_proportional` matches it exactly |
| Dietz & Hastreiter (2026) | Staggered DiD + matching on TPI | `research.did`, `research.matching` | Same family. Group-time ATTs, not their exact covariate set or MQ weighting |
| Schüder & Zülch (2026) | CEM then OLS, sector×year×region FE | `research.matching`, `research.inference` | Components present; their t+1..t+4 specification is not pre-built |
| Xu, Wei & Ji (2026) | Six models, 60 features, XGBoost Gain | `research.models` | Five models, sklearn GBM not XGBoost, permutation importance. Design, not specification |
| Brown, Hsu & Manya (2026) | Seven flags from CDP/InfluenceMap/NZT | `flags`, `redflags` | Coding rules implemented from their Methods, including the CDP interim-target fallback, the PETA progress measure and the C-or-lower lobbying threshold. Their PETA equations do not reconcile as typeset; the documented reading is implemented |
| Fliegel (2026) | Rank correlation **plus** return sensitivity of brown/green portfolios to climate news | `divergence` | Only the correlation half. **His evaluation design is not implemented** |
| Colmer et al. (2025) | EU ETS DiD on administrative microdata | — | Not implemented |
| Jiang, Kim & Lu (2025) | Target outcome tracking, event study on failure | — | Not implemented |
| Bolton & Kacperczyk (2025) | Commitment selection models | — | Not implemented |
| Ruiz Manuel & Blok (2023) | Additionality assessment of RE sourcing | — | Not implemented |
| Bingler et al. (2024) | ClimateBertCTI cheap-talk index | — | Not implemented |
| Schimanski et al. (2023) | ClimateBERT-NetZero classifier | — | Not implemented |
| Silvia et al. (2026) | Transition-plan credibility index | — | Not implemented |
| Oyewo (2023) | Curvilinear governance terms | `research.inference` | Sign-stability check only; no quadratic specification |
| Frisch et al. (2025) | Qualitative core-business framework | — | Not code |

The figures are outputs of these implementations on synthetic data. They show
what each method does and what its output looks like. They are not
reproductions of any paper's charts.

## What the estimators are for

The corpus this review draws on runs almost entirely on difference-in-differences
with matching, because adoption of a climate target is voluntary and heavily
selected. The research subpackage implements that machinery rather than gesturing
at it.

`research.did` estimates group-time average treatment effects in the style of
Callaway and Sant'Anna rather than two-way fixed effects. Under staggered
adoption with heterogeneous effects, TWFE uses already-treated firms as controls
for later-treated ones and can return the wrong sign; `twfe_event_study` is
included so the gap is visible. Standard errors come from a firm-level block
bootstrap, because resampling firm-years instead of firms would treat one firm's
nine observations as nine independent draws.

The synthetic generator makes this checkable. Target adoption has **no** causal
effect on emissions in it, but adopters are selected on an unobserved propensity
that does lower emissions. A naive adopter/non-adopter comparison therefore finds
about -0.8 percentage points a year that is not there, and the DiD returns
estimates indistinguishable from zero. Both are asserted in
`tests/test_decarb_research.py`.

## Four things the code refuses to let you do

These are the errors the review argues are doing most of the damage in
published work, so they are enforced rather than documented.

**Mixing Scope 2 bases.** `Panel.__post_init__` raises if a panel contains
both location-based and market-based Scope 2. Schüder and Zülch (2026) find
the SBTi effect in the market-based series and not the location-based one, so
a pooled series measures procurement policy as much as abatement.

**Letting composition masquerade as abatement.** `labels.chained_change`
returns the aggregate change, the constant-perimeter change and the gap. On
the synthetic panel the aggregate reads +0.4% while the chained series reads
+7.2%, meaning turnover is hiding real emissions growth. LSEG (2026) report
the mirror image in high-yield bonds, where aggregate emissions fell 9% a year
against 2% chained.

**Leaking the outcome into the features.** `labels.forward_labels` keys the
label by base year over a forward window, and `predict.Design` refuses
overlapping or look-ahead splits. `pipeline._persistence_test` additionally
embargoes `horizon` years between train and test so no training label window
reaches into the test period. An earlier version of this pipeline reported
R² = 1.000 because the numeric outcome was also a baseline feature.

**Reading a pooled AUC as a property of an indicator.**
`saturation.discriminatory_power` stratifies by sector by default. Sector
dominates emissions trajectories, so an unstratified AUC mostly ranks sectors,
and an indicator slightly more common in a fast-growing sector will score
below 0.5 even when it is associated with lower emissions inside every sector.

## Reading the output

Two results in the demo run are worth explaining because they look like bugs
and are not.

*Section 8 reports no gain over persistence.* This is correct. The synthetic
generator makes the demanding practices lower a firm's emissions drift, and
lagged emissions growth already contains that drift. Features acting through
the emissions trajectory add nothing once the trajectory is controlled for.
That is design rule 2 working, and it is why an incremental test is the only
interpretable one.

*The rarity-weighted score beats the raw count only on average.* Across 20
seeds it wins 15 times, with mean stratified AUC 0.547 against 0.540. The
effect is real but small relative to cross-firm dispersion in emissions
growth, so a single panel can invert it. The test asserts the mean over 12
seeds for that reason. The same fragility applies to the real data, which is
why the review treats Dietz and Hastreiter's result as one good study rather
than a settled fact.

## The synthetic panel

`synthetic.make_panel` is calibrated so the published magnitudes reproduce:
median annual Scope 1+2 change near zero with roughly half of firms still
growing, quartiles near LSEG's reported −5.6%/+7.0%, red-flag prevalences
matching Brown, Hsu and Manya (2026) within a few points, Technology carrying
much the widest Scope 2 wedge, and transition metrics correlating within
families but not across them.

Effect sizes for the causal links are set deliberately larger than the
literature's point estimates so the mechanisms are visible at test sample
sizes. Cross-firm dispersion is kept realistic, which means the effects are
still not reliably recoverable from any one panel.

This is simulated data. It exists to prove the code runs and to make the tests
deterministic. No number produced from it is evidence about any company.
