# The mechanics of corporate abatement

A theory note underlying [`SECTOR_REGION_MECHANISMS.md`](SECTOR_REGION_MECHANISMS.md)
and [`CORPORATE_DECARBONISATION_REVIEW.md`](CORPORATE_DECARBONISATION_REVIEW.md).

The previous note established *that* regulation, technology and demand govern
where abatement happens. This one asks why, and works out what follows for
measurement. Everything below is elaboration on a single inequality.

---

## 1. One decision rule

A firm abates a marginal tonne when the value it captures covers what abatement
costs it:

```
    abate  iff   MAC(q)  ≤  p_c·κ  +  s  +  π   −  h
```

| Term | Meaning |
|---|---|
| `MAC(q)` | marginal abatement cost at abatement volume q |
| `p_c·κ` | carbon price times the share of the firm's marginal emissions actually priced |
| `s` | input cost savings the abatement measure itself delivers (energy, materials) |
| `π` | revenue premium per tonne abated, from customers paying more for the low-carbon product |
| `h` | the hurdle from irreversibility under uncertainty |

Define the **abatement gap**:

```
    G  =  MAC  −  (p_c·κ + s + π)  +  h
```

A firm abates when `G < 0`. The three "dimensions" are simply the three terms
that push `G` down; `MAC` and `h` push it up. Nothing in the corporate climate
literature escapes this inequality — targets, governance and disclosure operate
by shifting a firm's position relative to it, never by suspending it.

This immediately explains the corpus's central puzzle. Ruiz Manuel and Blok find
86% of member abatement in eight electricity and heavy-industry firms, not
because those firms are better managed, but because `G` was already negative in
their cell and positive almost everywhere else.

---

## 2. Regulation: the effective marginal price, not the headline one

### 2.1 Free allocation determines whether the price bites, and how

`κ` is doing more work than it looks. What matters is the carbon price on the
**marginal** tonne, and the design of free allocation decides whether that
equals the market price or something closer to zero.

**Lump-sum or grandfathered allocation** hands the firm a fixed quantity of
allowances independent of what it does afterwards. It is an infra-marginal
transfer: it changes the firm's wealth, not its marginal incentive. Abatement
incentive is fully preserved.

**Output-based or benchmarked allocation** ties allowances to production. Each
extra tonne of output brings extra allowances, so the scheme functions as an
output subsidy alongside a carbon price. The firm still has a full incentive to
cut emissions **per unit of output**, and a weakened incentive to cut **absolute**
emissions, because producing more is subsidised.

That distinction has a direct empirical signature, and it is one the review
documents at length: intensity falling while absolute emissions stay flat. LSEG
find FTSE All-World intensity down about a third since 2016 with absolute
emissions plateaued. Composition and revenue growth explain most of that gap,
but output-based allocation is a genuine second mechanism pushing the same way,
and it is policy-designed rather than accidental.

### 2.2 Why Phase I was zero

Colmer et al. find EU ETS Phase I effects indistinguishable from zero and Phase
II effects of −14 to −16%. Read through the inequality this is not a puzzle
requiring a behavioural explanation. Phase I over-allocated, the price collapsed
toward zero, so `p_c·κ ≈ 0` and `G` never turned negative. The policy did not
fail to change behaviour; it failed to create a price.

The lesson for measurement is concrete. A binary "covered by an ETS" indicator
encodes `κ > 0`, which is not the variable in the inequality. The variable is
`p_c·κ`, and a firm covered by a scheme with a collapsed price is, for
prediction purposes, unregulated.

### 2.3 Credibility: why the hurdle term is large

`h` is where most of the interesting policy economics lives.

Abatement capital is **irreversible** — an electric arc furnace cannot be
unbuilt — and it is long-lived, so what matters is the expected carbon price
over twenty to forty years, not today's. Under uncertainty, an irreversible
investment carries an option value of waiting: the firm can invest later with
better information, so it rationally requires the expected value to exceed cost
by a margin rather than merely to equal it. That margin is `h`, and standard
real-options results put it well above zero for volatile prices.

Three consequences follow, and they are not obvious from a static reading.

**Policy credibility matters through the variance, not only the mean.** A
legislated price floor, a long-dated trajectory, or a border adjustment reduces
the dispersion of the expected carbon price and therefore shrinks `h`. That can
trigger investment without the expected price rising at all.

**Announcements can move investment before prices move.** A credible future
constraint lowers `h` today. This is a mechanism by which a target or a
regulation can matter years before it binds.

**Volatility is a genuine cost of market-based instruments.** A price that
averages the right level but swings widely delivers less investment than a
stable price at the same mean. Carbon taxes and price floors have an advantage
here that headline-rate comparisons miss.

---

## 3. Technology: learning is a property of manufacturing multiplicity

### 3.1 Wright's law and positive feedback

Technology costs follow cumulative **production**, not calendar time:

```
    C(x)  =  C₀ · x^(−b)
```

with cost falling a constant fraction per doubling of cumulative output.
Reported learning rates run around 24% per doubling for solar PV and 20% for
battery packs, giving declines of 89% and 86% respectively since 2010.

The structural point is that this is a **positive feedback loop**: deployment
lowers cost, which raises deployment. Systems with positive feedback do not
respond gradually to a forcing. They sit still and then tip. That is why
abatement looks binary by sector rather than proportional to effort, and why
extrapolating a sector's past rate of progress is a poor forecast on either
side of its tipping point.

### 3.2 Why cement does not get a learning curve

The learning denominator is *units manufactured*. Solar modules have been
produced billions of times; a cement kiln with carbon capture has been produced
a handful of times. The available doublings differ by orders of magnitude.

So steep learning is not a property of "clean technology". It is a property of
**modular, mass-manufactured goods**, and its absence is a property of bespoke
capital projects. Consistent with this, while clean modular goods fell 64–89%,
thermal plant EPC costs *inflated* by roughly 28% over a comparable period.
Same decade, opposite direction, because one rides manufacturing learning and
the other rides commodity and labour costs.

### 3.3 Electrification as a learning-transfer mechanism

This is the most useful reframing in this section. A sector that can electrify
**inherits someone else's learning curve for free**. It does not need to fund
the cost declines in solar and batteries; it buys the product of them.

So the decisive technology question for any sector is not "is there a green
option" but:

1. Can the process be electrified? If yes, the sector imports a 20–24% learning
   rate it did nothing to earn.
2. If not, why not — energy density (aviation), temperature (high-grade heat),
   or **process chemistry** (cement calcination releases CO₂ from limestone
   regardless of the energy source)?
3. Where electrification is impossible, abatement requires a bespoke capital
   project, which means no learning curve and a MAC that stays high.

This gives a clean prediction: sectors sort into those that inherit learning and
those that must generate it, and the observed bimodality of corporate abatement
follows. It also explains why Technology-sector emissions are *rising* while its
firms are among the most engaged: their emissions are overwhelmingly Scope 2,
their abatement is someone else's problem, and their demand growth outruns the
grid's improvement.

---

## 4. Demand: a missing market, not a missing preference

The premium term `π` is where the analysis most often stops at "customers don't
care". The mechanism is more specific, and more fixable.

### 4.1 The value-chain asymmetry

Abatement cost is concentrated **upstream** in materials and energy. Willingness
to pay is concentrated **downstream** with the final consumer. The quantities
are wildly mismatched at the two ends.

A €150 per tonne green steel premium is roughly €100–150 on a car containing
around a tonne of steel: immaterial against a €30,000 vehicle, perhaps 0.4% of
the price. The same premium against a steelmaker's margin is decisive.

So the premium is **negligible where the money is and decisive where the cost
is**. Position in the value chain, not preference intensity, determines who can
absorb it. This is why automotive offtake agreements at $30–80 a tonne exist at
all: the buyer is downstream enough that the premium disappears into its cost
base.

### 4.2 Three failures that stop the premium forming

**Credence good.** Low-carbon steel is physically identical to ordinary steel.
The buyer cannot verify the attribute by inspection or use. Markets for
unverifiable quality collapse to the low-quality price unless certification
exists, so **certification is a precondition for the market, not an accessory to
it**. This is the same structure that makes renewable energy certificates
attractive and, per Ruiz Manuel and Blok's 71% low-additionality finding, makes
them vulnerable to exactly the failure certification is supposed to prevent.

**Free-riding on learning.** The first buyer paying a premium funds the
deployment that moves the producer down its cost curve. Competitors then buy
cheaper. The private return to being first is below the social return, so first
movers are undersupplied. This is the standard argument for public procurement
as a demand-side instrument, and it explains why green public procurement
appears repeatedly in cement and steel policy.

**No spot market.** There is no liquid exchange for differentiated low-carbon
commodities, so price discovery happens bilaterally. Long-term offtake
agreements are the institutional substitute for a missing market, which is why
the observable evidence on `π` comes as contract disclosures rather than
published prices, and why the numbers are thin and dispersed.

### 4.3 Why the same product carries a different premium in different regions

The Chinese steel figure is the cleanest illustration in the whole analysis:
production cost gap around $140 a tonne, willingness to pay capped near $20.
Same technology, same physics, a seventh of the gap covered.

`π` is not a technological parameter. It is set by who the buyers are, what they
are regulated to buy, and whether a certification regime exists that lets them
verify what they bought. That makes it the most regionally variable of the three
terms, and the one most directly manufactured by policy. CBAM is best understood
in exactly these terms: it converts `π` from a voluntary premium a buyer may
choose to pay into a regulatory cost an importer must pay, which is why it
changes the sector's economics more than its technology.

---

## 5. Why the three behave as complements

At the margin the three terms are **substitutes**: any of them closing the gap
is enough, and they enter the inequality additively.

Empirically they behave as **complements**, and the reason is `h` combined with
lumpiness. Abatement investment is not continuous. A firm does not buy 3% of an
electric arc furnace. It faces a discrete, irreversible, long-lived commitment
that must clear `MAC ≤ value + margin`, where the margin is the option value of
waiting. For hard-to-abate sectors, no single channel is large enough to clear
a `MAC` of $150–300 a tonne on its own: a $60 carbon price does not do it, a
10–25% premium on a thin slice of demand does not do it, and the technology has
no learning curve to ride. All three must move together, so they look
multiplicative in the data even though the underlying model is additive.

There is also a genuine **dynamic complementarity**. Deployment funded by any
channel today lowers `MAC` tomorrow through learning, which lowers the carbon
price and premium needed thereafter. Policy that subsidises early deployment is
buying down the future cost of every other instrument. This is the formal
argument for deployment support alongside pricing, and it has no static
counterpart.

---

## 6. What this implies for measuring predictors

### 6.1 Firm-level indicators can only matter near the margin

The inequality has a sharp implication for the question that started this work.
Where `G` is large and negative, every firm abates and no indicator predicts
anything, because there is no variation left to explain. Where `G` is large and
positive, no firm abates, and again there is nothing to predict. Firm-level
factors — capital access, management quality, planning horizon — tip the
decision only where the cell's economics leave it close to balanced.

Simulating a firm-quality indicator across the gap distribution:

```
 cell gap $/t  share abating     AUC   risk diff
         -120          100%   0.500       0.000
          -60           98%   0.646       0.025
          -30           85%   0.630       0.151
           +0           50%   0.634       0.301   <-- peak
          +30           15%   0.660       0.184
          +60            2%   0.715       0.038
         +120            0%   0.500       0.000
```

Decision relevance is an **inverted U in the abatement gap**, peaking where the
cell is balanced and collapsing at both extremes.

This is a candidate explanation for why the literature disagrees with itself
about firm-level predictors. Studies sampling different sectors and periods are
sampling different parts of the gap distribution, and will find different
answers from correct analyses of the same underlying process.

### 6.2 A trap in the statistic, including in my own earlier advice

Read the two columns above against each other. The **risk difference** traces
the inverted U. The **AUC does not** — it stays near 0.63 through the middle and
*rises* to 0.715 at a gap of +60, where the indicator changes almost no
outcomes (risk difference 0.038).

AUC is rank-based and base-rate invariant. In a cell where 2% of firms abate,
those few are strongly selected on quality, so the ranking looks excellent while
the indicator flips essentially nothing. A study reporting AUC alone would
conclude the indicator works best in hard-to-abate sectors, which is the precise
opposite of its decision relevance.

Earlier in this work I recommended sector-stratified AUC as the evaluation
metric, and `saturation.discriminatory_power` implements it. That recommendation
is incomplete. **Report a risk difference or marginal effect alongside any AUC**,
because the two diverge systematically across exactly the dimension that matters
here, and the one that looks most favourable is the misleading one.

### 6.3 The measurement that follows

`G` is estimable at sector × region × year from published sources: effective
carbon rates net of free allocation, sector MACC literature, and observed
premiums. Doing so turns the analysis from a fixed effect into a variable with
a sign and a magnitude, and yields a sharper hypothesis than any main effect:

> Firm-level indicators should predict abatement most strongly where `G ≈ 0`,
> and negligibly where the cell's economics already determine the outcome.

That is testable with the machinery already built, it explains the existing
disagreement in the literature, and nothing in the reviewed corpus tests it.

---

## Sources

Mechanisms are derived, not cited: the real-options treatment of irreversible
investment, Wright's law, credence goods and free-riding are standard results
applied here to this setting. Empirical magnitudes come from the corpus
(Colmer et al., Ruiz Manuel & Blok, LSEG) where marked, and from the web-search
summaries flagged as unverified in `SECTOR_REGION_MECHANISMS.md` otherwise. The
simulation is illustrative and demonstrates a property of the estimator, not a
fact about firms.
