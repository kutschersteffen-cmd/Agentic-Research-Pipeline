# Golden set draft: electrolyser manufacturers

Theme for the first exposure golden set (see `docs/COMPANY_EXPOSURE_MODEL_FUNNEL.md`, sections 2 and 5).
Status: **labels checked 2026-11-01** against company pages, filings and news (sources in
`electrolyser_funnel_results.md`). Two changes from the first draft: Cummins → `not` (halted new electrolyser
sales Feb 2026), Chart Industries removed (acquired by Baker Hughes, July 2026).

## Activity definitions (step 0)

| Key | Description used by the models |
|---|---|
| `make_electrolysers` | Manufactures and sells electrolysers or electrolyser stacks (alkaline, PEM, solid oxide or AEM) |
| `supply_components` | Supplies components or materials for electrolysers or hydrogen systems (membranes, catalysts, compressors, tanks) |
| `produce_hydrogen` | Produces or sells hydrogen, or operates electrolysis plants, without making the electrolysers |
| `fuel_cells` | Makes fuel cells (the reverse device: hydrogen to power), not electrolysers |

## Labels

`core`: making electrolysers is a main business. `peripheral`: makes electrolysers, but as a small part of a
larger business. `not`: does not make electrolysers (hard negatives are deliberate).

| # | Company | Country | Label | Activity | Why it is in the set | Check |
|---|---|---|---|---|---|---|
| 1 | Nel ASA | NO | core | make_electrolysers | Pure player (alkaline, PEM) | |
| 2 | ITM Power | GB | core | make_electrolysers | Pure player (PEM) | |
| 3 | thyssenkrupp nucera | DE | core | make_electrolysers | Alkaline; also chlor-alkali (shared technology) | |
| 4 | HydrogenPro | NO | core | make_electrolysers | Small pure player (alkaline) | |
| 5 | Enapter | DE/IT | core | make_electrolysers | AEM modules; since Aug 2026 stacks made by a partner in China | |
| 6 | Plug Power | US | core | make_electrolysers | PEM electrolysers next to fuel cells and hydrogen supply; mixed business | |
| 7 | McPhy Energy | FR | core (historic) | make_electrolysers | Hard case: judicial liquidation July 2025; assets sold to John Cockerill | checked |
| 8 | Green Hydrogen Systems | DK | core (historic) | make_electrolysers | Hard case: bankruptcy order June 2025 | checked |
| 9 | Siemens Energy | DE | peripheral | make_electrolysers | Electrolyser business is a small share of revenue | |
| 10 | Cummins (Accelera) | US | not (was peripheral) | – | Hard case: halted new electrolyser sales Feb 2026, fulfils existing orders | checked |
| 11 | LONGi Green Energy | CN | peripheral | make_electrolysers | Hydrogen subsidiary inside a solar group | |
| 12 | Sungrow Power | CN | peripheral | make_electrolysers | Hydrogen unit inside an inverter maker | |
| 13 | Bloom Energy | US | peripheral | make_electrolysers + fuel_cells | Solid oxide electrolysers next to fuel cells | |
| 14 | Ceres Power | GB | peripheral | make_electrolysers + fuel_cells | Hard case: licenses SOEC/SOFC technology; licensees build the stacks | checked |
| 15 | GTT (Elogen) | FR | peripheral | make_electrolysers | PEM subsidiary inside an LNG containment group | |
| 16 | Johnson Matthey | GB | not | supply_components | Supplier: catalyst-coated membranes (kept after selling Catalyst Technologies) | |
| ~~17~~ | ~~Chart Industries~~ | US | removed | – | Acquired by Baker Hughes, July 2026 | |
| 18 | Burckhardt Compression | CH | not | supply_components | Supplier: hydrogen compressors | |
| 19 | Hexagon Purus | NO | not | supply_components | Supplier: hydrogen tanks | |
| 20 | Linde | IE/US | not | produce_hydrogen | Producer and plant builder; partners with ITM | |
| 21 | Air Liquide | FR | not | produce_hydrogen | Producer; buys electrolysers | |
| 22 | Air Products | US | not | produce_hydrogen | Producer of large green-hydrogen projects | |
| 23 | RWE | DE | not | produce_hydrogen | Operates electrolysis plants (buyer) | |
| 24 | Shell | GB | not | produce_hydrogen | Operates electrolysis plants (buyer) | |
| 25 | Ballard Power | CA | not | fuel_cells | Hard negative: fuel cells, not electrolysers | |
| 26 | Daimler Truck | DE | not | fuel_cells | Hard negative: fuel-cell trucks | |
| 27 | Heidelberg Materials | DE | not | – | Easy negative; mentions hydrogen as a fuel | |
| 28 | Martin Marietta | US | not | – | Easy negative | |

Not listed on purpose: private makers (Sunfire, John Cockerill, Electric Hydrogen, Ohmium, Topsoe), because ARP
works on listed universes. Add them if private companies matter.

## Next steps

1. Owner confirms or changes the labels (the `verify` rows first).
2. Collect one business description per company: 10-K Item 1 for US filers (EDGAR), the "business model"
   section of the annual report for the others.
3. Run funnel steps 1–3 on CPU and report, per company, the step at which it drops out, compared with its label.
