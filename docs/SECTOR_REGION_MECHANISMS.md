# Sector × region, and the three mechanisms it stands for

A note extending [`CORPORATE_DECARBONISATION_REVIEW.md`](CORPORATE_DECARBONISATION_REVIEW.md).

Every design in the review controls for sector × region, and treats it as a
nuisance. That is the right thing to do for identification and the wrong way to
think about it. Sector × region is not noise. It is a compressed proxy for three
measurable forces — **regulation, technology, and demand for the low-carbon
product** — and whether a firm decarbonises depends first on whether those three
have cleared in the cell it occupies.

The practical consequence: a fixed effect absorbs the mechanism instead of
measuring it, which costs you interpretation and makes out-of-sample prediction
to an unobserved cell impossible.

---

## 1. Decarbonisation so far is concentrated to an extreme degree

Ruiz Manuel and Blok (2023) evaluated the 102 largest SBTi and RE100 members by
revenue. Their headline is a 35.6% collective Scope 1+2 reduction. The
disaggregation is the finding:

> 86% of total reductions were due to exclusive members in the Electricity
> Generation and Energy Intensive Industry sectors (n = 8), accounting for
> approximately 98.6% of all internal Scope 1 emission reductions. Other
> sectors, including all RE100 participants, only show evidence of emission
> mitigation occurring outside their operational control.

Eight firms in two sectors produced essentially all of the operational
abatement. Everyone else moved Scope 2 through procurement, 71% of it through
low-additionality instruments.

The LSEG (2026) sector data points the same way from a different angle:
Utilities alone are about a third of FTSE All-World Scope 1+2 and fell 25%
between 2019 and 2024, while Technology rose 28%. Telecoms and Energy fell
largely through index turnover rather than abatement.

So the corporate decarbonisation record to date is substantially an
**electricity** story: generators cutting their own emissions, and everyone else
benefiting passively as the grid they draw from cleans up. That second part is
precisely what `arp.decarb.kaya` strips out, and it is why the distinction
matters so much for measurement.

---

## 2. Why electricity and not cement

The three channels are **complements, not substitutes**. Abatement happens where
all three clear at once, which is why progress looks binary by sector rather
than gradual.

### 2.1 Regulation: coverage is narrow and sectorally skewed

The OECD's *Effective Carbon Rates 2025* puts the share of global emissions
subject to a carbon price at **34%**, rising with China's ETS extension to
aluminium, cement and steel. The composition matters more than the level:

| Instrument | Coverage 2023 | Sectors it reaches |
|---|---|---|
| Emissions trading | 22% (from 10% in 2018) | electricity and industry |
| Carbon taxes | ~5%, flat since 2018 | buildings and transport |

Electricity and heavy industry sit inside the instrument that expanded;
buildings and transport sit inside the one that did not. Roughly two thirds of
global emissions carry no explicit price at all.

Stringency matters as much as coverage, and Colmer, Martin, Muûls and Wagner
(2025) show why. Their EU ETS estimate of −14 to −16% is a Phase II and III
result; **Phase I point estimates are close to zero and statistically
insignificant.** A binary "covered by an ETS" indicator is therefore too coarse
to be useful. What predicts is the effective carbon rate actually faced, net of
free allocation.

The EU's Carbon Border Adjustment Mechanism changes the geography of this by
extending an EU price to imported embedded carbon, which converts a regional
regulation into a partially global one for traded goods.

### 2.2 Technology: two different cost worlds

Clean technology costs have fallen at rates that have no analogue in heavy
industry. Reported 2010–2025 declines: **solar PV modules −89%, battery packs
−86%, onshore wind −68%, electrolysers −64%**, with learning rates around
**24% for solar PV and 20% for battery packs** per doubling of cumulative
volume.

The reason is structural rather than incidental. These are mass-manufactured,
modular products, so they ride manufacturing learning curves. Cement kilns with
carbon capture and hydrogen-based steel furnaces are capital-intensive civil
projects, which do not. Thermal EPC costs have *inflated* by about 28% over a
comparable period.

The consequence for abatement cost: most primary steel decarbonisation options
cost over **$150/tCO₂**, sustainable aviation fuels over **$300/tCO₂** with a
blend wall capping them at roughly half the job, and cement has no scaled
substitute at all. Against an EU allowance price in the tens of euros, those
sectors face a cost gap that no plausible carbon price closes on its own.

### 2.3 Demand: the green premium exists, and it is regional

This is the channel most often omitted from corporate climate research, and the
evidence shows it varies by region for the *same* product, which is exactly what
a sector × region term is absorbing.

| Product | Premium | Note |
|---|---|---|
| Green steel, Europe | €120–180/t | stabilised through 2025 |
| Low-carbon steel, automotive offtakes | $30–80/t | multi-year contracts |
| Low-carbon steel, China | willingness to pay capped ≈ **$20/t** | against a cost gap of ≈ **$140/t** |
| Low-carbon cement | +10–25% | LC3 at +10–15%; CCS retrofit +20–25% |

The Chinese steel figure is the clearest single illustration in this note. Same
sector, same technology, a cost gap of roughly $140 a tonne, and buyers willing
to cover about a seventh of it. A European producer and a Chinese producer face
the same physics and entirely different economics, and no firm-level governance
indicator will bridge that difference.

Note also that electricity needs no demand channel at all. Electrons are
fungible, so a clean generator sells into the same market at the same price.
That is a third reason electricity moved first: it is the one sector where
decarbonising required no customer to pay more for a differentiated product.

### 2.4 The three together

| Sector | Regulation | Technology | Demand | Observed |
|---|---|---|---|---|
| Electricity | ETS from the start | solar/wind on steep learning curves | not needed, fungible | most abatement |
| Energy-intensive industry (EU) | ETS + CBAM | partial, expensive | some premium | some abatement |
| Steel (China) | ETS from 2024/25 | same as EU | premium capped at $20/t | little |
| Cement | mostly unpriced until recently | no scaled substitute | +10–25% premium, thin demand | little |
| Aviation, shipping | largely outside | >$300/t, blend wall | negligible | little |
| Technology, services | unpriced Scope 2 | n/a, buys power | n/a | emissions rising |

Read down the "observed" column against the other three. The pattern is not that
some sectors try harder. It is that abatement occurs where a priced externality,
an available technology and someone willing to pay all coincide.

---

## 3. What this means for measurement

### 3.1 A fixed effect hides the thing you want to know

Sector × region fixed effects are correct for identification and expensive in
three ways.

They **absorb the mechanism**, so the model cannot tell you *why* a cell
decarbonises, and you lose the ability to say what would happen if the carbon
price rose or the premium widened.

They **cannot extrapolate**. A model with a cell dummy has nothing to say about
a cell it never observed, which includes every cell created by a regulatory
change. CBAM effectively creates new cells.

They **absorb part of the firm response**. If two EU cement firms face the same
CBAM shock and one invests, the fixed effect removes the common shock, which is
what you want, but a cell-by-year effect also removes the average response, so
a firm that responds at the cell average scores zero.

### 3.2 Mechanism variables instead

Replace the dummy with three measured quantities, each available at
sector × region × year:

| Variable | Construction | Source |
|---|---|---|
| **Regulatory stringency** | effective carbon rate faced, net of free allocation, × share of the firm's emissions covered | OECD Carbon Pricing and Energy Taxation Database; ETS registries |
| **Abatement availability** | cost of the cheapest scaled option, $/tCO₂, for the sector's dominant process | sector MACC literature; IEA ETP |
| **Demand pull** | observed green premium × share of revenue in products that can carry it | commodity price assessments; offtake disclosures; public procurement rules |

Then the specification becomes interpretable and extrapolable: a firm's expected
abatement depends on its cell's mechanism values and on its own position given
those values. The firm-level residual after conditioning on mechanisms is the
quantity the review's design rules are trying to isolate, and it is the only
part a firm-level indicator can legitimately claim to predict.

A useful test falls out of this. Add the mechanism variables, then add the
cell dummies on top. **If the dummies still carry explanatory power, your
mechanism measures are incomplete**; if they do not, you have replaced 24 or
more dummies with three interpretable variables.

### 3.3 How much is at stake

Run a nested variance decomposition on the firm-level attributable rate before
choosing. On a panel of 800 simulated firms:

```
year only                  R2 = 0.029
+ sector                   R2 = 0.121
+ region                   R2 = 0.125
+ sector x region          R2 = 0.143
+ sector x region x year   R2 = 0.150
+ firm                     R2 = 0.851

firm-mean decomposition: 14% of variance between cells, 86% within
```

**Those numbers are a property of the generator, not an empirical result** — the
synthetic panel sets sector effects modestly, and the corpus evidence above
suggests the between-cell share is considerably higher in real data. The point
is the procedure. Run it first, because it tells you whether you are studying a
14% problem or an 86% one, and the answer changes what a firm-level indicator
can possibly be worth.

---

## 4. Implication for the predictor question

Two conclusions follow, and they pull in opposite directions.

**Against firm-level indicators.** If the mechanisms dominate, most of what
looks like firm-level predictive power in the literature is cell membership
poorly controlled. A model that appears to identify good managers may be
identifying European utilities. This is the sharper version of the sector
confound that `saturation.discriminatory_power` stratifies for.

**For committed capital specifically.** The case made earlier gets stronger
here rather than weaker. Capex is the firm's *response* to its cell: it is how a
firm converts a carbon price, an available technology and a willing buyer into
physical abatement. A firm that commits capital in a cell where the three
mechanisms have not cleared is making a bet; one that does so where they have is
executing. Conditioning on the mechanisms is what separates those two readings,
and neither is visible in a specification where the cell is a dummy.

That points at a specific and testable proposition: **capex alignment should
predict attributable abatement most strongly in cells where regulation,
technology and demand have all cleared, and weakly elsewhere.** An interaction
between capex and mechanism stringency is a sharper hypothesis than a capex main
effect, and nothing in the reviewed corpus tests it.

---

## Sources and confidence

Corpus papers (Ruiz Manuel & Blok, Colmer et al., LSEG) were read in full and
figures are quoted from them directly.

The regulation, technology and demand figures come from **web search summaries**
of OECD *Effective Carbon Rates 2025*, IEA material, commodity price assessments
and sector MACC literature. This environment's egress policy blocks the
underlying sources, so those numbers could not be verified against the primary
documents and should be checked before external use. The green steel and cement
premium figures in particular come from market commentary rather than
peer-reviewed work, and premium quotes move quickly.

The variance decomposition is simulated and is a demonstration of method only.
