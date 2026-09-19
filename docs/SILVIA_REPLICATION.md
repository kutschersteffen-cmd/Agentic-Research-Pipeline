# Replicating Silvia et al. (2026)

*Do credible climate transition plans matter for carbon performance? Evidence
from Fortune Global 500 firms.* Frontiers in Environmental Science 14:1907357.

Implementation: `backend/arp/decarb/research/silvia.py`,
instrument in `backend/arp/decarb/research/data/ctpci_items.json`.

```bash
cd backend
python -c "from arp.decarb.research.silvia import verify_against_published as v; print(v())"
python -m pytest tests/test_decarb_silvia.py -q
```

## What was and was not replicated

**Not replicated: their finding.** Reproducing it needs the CTPCI hand-coded
from 1,126 firm-year reports, plus Scope 1+2 emissions, financials, governance
and ownership data for 239 firms. None of that is reachable from this
environment: company websites, SEC EDGAR, Fortune and report aggregators are all
blocked by the network egress policy, and the authors' data is available "on
request" rather than by download.

**Replicated: their instrument and their specifications**, with the estimator
verified against data built to their published correlation structure.

The verification is a Monte Carlo, not a single fit. Firm fixed effects absorb
most of the between-firm variation in CTPCI, so one simulated panel puts a
correct estimator two standard errors from the truth often enough to prove
nothing either way. Over 40 panels built with β = −0.066:

| | |
|---|---|
| true β | −0.0660 |
| mean estimate | −0.0684 |
| Monte Carlo SE | 0.0030 |
| bias | −0.0024 (under 1 MC SE) |
| 95% interval coverage | 92% |

The estimator is unbiased and its intervals are close to nominal. That is a
claim about the implementation, not about corporate transition plans.

## Two gaps forced by the published text

**Appendix A is not in the PDF.** The paper cites it for "item definitions,
coding rules, and binary scoring criteria", but the published file ends at the
publisher's note; the checklist is separately hosted supplementary material on a
blocked domain. `ctpci_items.json` therefore carries their 24 item **labels**,
verbatim from their Table 2 with the same dimension assignments, and coding
rules written here. The instrument's content is theirs; the decision rules are a
reconstruction, and a different coder would score some items differently. This
is the single largest threat to any replication built on this file.

**Appendix B is not in the PDF either.** It holds the country-year regulatory
coding scheme, so `Regulatory` must be supplied by the caller.

## Their specification, as implemented

Dependent variable, aligned to base year *t*:

```
CarbonChange_{i,t+1} = (CO2e_{i,t+1} − CO2e_{i,t}) / Revenue_{i,t}
```

Scaling by **lagged** revenue is theirs and matters: the denominator is
predetermined, so a revenue shock in t+1 cannot mechanically move the outcome.
`carbon_change()` also returns NaN across year gaps, since a three-year jump is
not a one-year change.

Index:

```
CTPCI_{i,t} = disclosed items / total applicable items
```

Not-applicable items shrink the denominator rather than counting as failures.
External assurance is excluded from the index by design and enters as a
moderator. `equal_dimension_weight=True` gives their robustness variant.

Models, all with firm and year fixed effects and standard errors clustered on
the firm:

1. `CarbonChange ~ CTPCI + Controls`
2. `+ Assurance + CTPCI × Assurance`
3. `+ Regulatory + CTPCI × Regulatory`

Controls: Size (ln total assets), ROA (net income / total assets), Growth
(annual revenue growth), Leverage (total liabilities / total assets), BoardSize,
BoardIndependence, CEODuality, SOE, Big4. Continuous variables winsorised at the
1st and 99th percentiles.

**One implementation detail worth knowing.** Controls that never vary within a
firm are perfectly collinear with firm fixed effects; left in, statsmodels
returns a rank-deficient design and coefficients that are not uniquely
determined. `estimate()` drops them and reports which. In their data SOE, Big4
and CEODuality presumably change for enough firms to survive; whether they do is
a property of the sample rather than of the specification, so it is surfaced as
a warning rather than assumed either way.

## Targets to hit

From their Table 5:

| Model | CTPCI coefficient | SE |
|---|---|---|
| 1 | −0.066*** | 0.019 |
| 2 | −0.052** | 0.021 |
| 3 | −0.057*** | 0.020 |

From their Table 4: corr(CTPCI, CarbonChange) −0.183***, corr(CTPCI, Assurance)
+0.273***, corr(CTPCI, Regulatory) +0.428***, corr(CarbonChange, Big4)
−0.133***. `SilviaResult.compare_to_published()` reports each estimate against
these.

## Data required to run it for real

One row per firm-year, 2018–2023, for Fortune Global 500 **non-financial** firms
(financials excluded because their exposure is financed rather than operational).

| Column | Source | Notes |
|---|---|---|
| `firm_id`, `year`, `country` | — | |
| `co2e` | sustainability / ESG / integrated reports | Scope 1 + Scope 2. Pin the Scope 2 basis and keep it constant |
| `revenue`, total assets, net income, total liabilities | annual reports | Size = ln(assets), ROA = income/assets, Leverage = liabilities/assets |
| 24 CTPCI items | same reports, hand-coded | `score_ctpci()` turns the coded dict into the index |
| `Assurance` | assurance statement in the report | 1 if sustainability/ESG/climate report or GHG data assured in year t |
| `Regulatory` | their Appendix B, unavailable | country-year mandatory or quasi-mandatory disclosure dummy |
| `BoardSize`, `BoardIndependence`, `CEODuality` | annual report / proxy | |
| `SOE`, `Big4` | annual report | |

Then:

```python
from arp.decarb.research import silvia

frame["CarbonChange"] = silvia.carbon_change(frame)
frame["CTPCI"] = [silvia.score_ctpci(coded[i]) for i in frame.index]
for m in (1, 2, 3):
    print(silvia.estimate(frame, model=m).compare_to_published())
```

## The tractable route to real data

The 24 items are binary, grounded, report-level extractions, which is what this
repository's extraction engine already does: schema-defined fields, an
independent verifier on a different model, and a programmatic grounding check on
every citation. Wiring `ctpci_items.json` into that pipeline would code the index
from the same public reports the authors read by hand.

That is a real replication and it is worth being clear about the cost: 239 firms
× 6 years × 24 items is roughly 34,000 extractions, each needing a grounded
citation. The authors did it manually and resolved ambiguous cases by team
discussion. An automated coder should be validated against a hand-coded subset
before its output is treated as comparable, because the reconstructed coding
rules above are the weakest link in the chain.
