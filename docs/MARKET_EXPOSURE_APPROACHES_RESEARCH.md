# Market-leading approaches to theme and risk exposure, and how ARP closes the gap

Status: research note and action plan, 2026-11-01. Companion to `COMPANY_EXPOSURE_MODEL_FUNNEL.md` (the two
pipelines) and the approved umbrella spec `superpowers/specs/2026-11-01-model-stack-design.md`.

**How this was researched.** Web search on 2026-11-01 by two research agents, using vendor methodology pages,
product pages, press releases, asset-manager publications and papers. Full methodology PDFs were mostly **not**
opened, so formulas and thresholds come from search summaries of those documents and must be checked before
being cited externally. Items marked *unconfirmed* had no primary source. Coverage numbers are vendor figures
and vary by date.

## 1. Summary

1. **"How much" is revenue; "whether and why" is text.** Every leading thematic product scores exposure on
   revenue (FactSet RBICS, MSCI relevance score, Bloomberg revenue exposure, ISS/Clarity Taxonomy data). Text
   models are used to *find* candidates and segments (MSCI keyword lists, Kensho, Solactive ARTIS), not to
   size the exposure.
2. **Risk exposure is asset-level.** Physical and transition risk products (MSCI Climate VaR, S&P Trucost,
   Moody's) put hazards and policy scenarios on geolocated assets and roll them up through ownership trees.
   Controversies come from outside-in news NLP checked by analysts (RepRisk, Truvalue).
3. **Entity resolution is the backbone.** Kensho NERD/Link, LEI links in GEM and ownership trees in Asset
   Impact are what make text and assets attach to the right company.
4. **GenAI sits mostly at the front end, not the core.** 2024–2026 launches are research assistants and agents
   (AlphaSense Deep Research, Clarity AI assistant, RepRisk agents, MSCI AI Portfolio Insights, Kensho
   LLM-ready API). Little public evidence shows the core classifications are now LLM-generated. The notable
   exception is NBIM, which uses Claude to screen every new holding within 24 hours.
5. **ARP's edge** is quote-level evidence that is verified in code, fast new themes, and an audit trail. Its
   gaps are revenue sizing for undisclosed segments, asset-level data, a live controversy feed and entity
   linking at scale. Section 6 is the plan to close them.

## 2. Thematic exposure: "which companies are active in field X?"

### 2.1 Vendors

| Vendor | Method | Text vs revenue | Human role | GenAI (2024–26) | Source |
|---|---|---|---|---|---|
| **FactSet RBICS** | 6-level taxonomy, 1,700+ sector groups, 49k+ companies. "RBICS with Revenue" maps reported segment revenue onto the taxonomy and normalises non-standard segments using management commentary. Separate Focus (primary business) and Tradenames (product level) feeds | Revenue | Analyst-driven, full review at least yearly | none RBICS-specific | [1], [2], [3] |
| **Bloomberg BICS / BI thematic** | BICS operating-segment data (~1,200 KPIs). Bloomberg Intelligence thematic scores on two axes: *revenue exposure* (share of current and future business) and *thematic relevance* (positioning, informed by NLP over filings and transcripts). Bloomberg AI index weighted by market cap × revenue exposure | Hybrid | Analyst | none found | [4], [5], [6] |
| **MSCI thematic indexes** | Relevance score = (revenue from selected segments + discount × revenue from SIC-matched segments) / total revenue. NLP only builds yearly keyword lists that pick segments. Typical cut at ≥ 25% (50% for some environmental indexes); 5% issuer cap | Hybrid, revenue scores | Committee | AI Portfolio Insights (risk analytics, not thematic). An LLM "opposing agents" thematic method is *unconfirmed* | [7], [8], [9], [10] |
| **S&P Kensho New Economies** | Expert-curated themes, then topic modelling and NLP on SEC filings to find "core" and "ecosystem" companies | Text | Experts define themes | Kensho LLM-ready API (2026) | [11] |
| **Kensho NERD / Link** | NERD links company, person and place mentions in text to Capital IQ or Wikidata IDs. Link matches messy names to 26M+ entities and adds parent and cross-reference IDs | Entity resolution | – | "next evolution of Link" (2026) | [12], [13], [14], [15] |
| **Solactive ARTIS** | Proprietary NLP on reports, news and business descriptions gives an ARTIS score per theme. Combined with classification screens; weights blend market cap and score. Used in 100+ indices | Text | Index committee | none published | [16] |
| **ISS ESG (EU Taxonomy, SDG Solutions)** | Reported Taxonomy data preferred and flagged; otherwise modelled from its SDG Solutions Assessment and FactSet RBICS revenue, with 400+ screening factors. Validated against ~1,845 reporters | Revenue | Rules + analysts | none found | [17], [18], [19] |
| **Clarity AI** | ML and NLP plus expert rules, source-traceable data points; EU Taxonomy metrics; 65k+ companies | Hybrid | Expert validation | Research assistant over 200k+ company reports (2025) | [20], [21], [22] |

### 2.2 Asset managers and asset owners

| Manager | Approach | Link to engagement | Source |
|---|---|---|---|
| **BlackRock (iShares IRBO)** | Thematic fund on the NYSE FactSet Global Robotics & AI Index: RBICS revenue in 22 sub-industries; eligible with ≥ 50% revenue, ≥ 20% market share or ≥ $1bn revenue. A 2024 filing moves an AI fund to a Morningstar index scoring expected 5-year revenue by subtheme | – (index) | [23], [24] |
| **Robeco SDG Framework** | Three steps (what the company does, how it does it, controversies) score −3 to +3 per SDG; NLP on business descriptions plus sector-to-SDG mappings; 15k+ companies; analyst review; open IP | Defines SFDR "sustainable investment"; feeds engagement | [25], [26] |
| **APG / PGGM (SDI Asset Owner Platform, Entis)** | NLP on annual reports and websites gives an SDI status, a confidence score, % of revenue SDI-eligible and the main SDGs; 8–10k companies; governance body and human review | Portfolio targets | [27], [28], [29] |
| **Schroders SustainEx** | Net social and environmental externalities in $ (% of sales) from unit social costs; 400+ studies; ~9k companies | Prioritisation (engagement link *unconfirmed*) | [30], [31] |

### 2.3 Research

| Paper | Finding | Source |
|---|---|---|
| Hoberg & Phillips, *Text-Based Network Industries…*, JPE 2016 | Cosine similarity of 10-K product descriptions gives firm-specific peer sets that beat SIC and NAICS | [32] |
| *Company Similarity using Large Language Models*, 2023 | LLM embeddings of business descriptions reproduce GICS and give continuous similarity | [33] |
| Buchner et al., *Prompt Tuned Embedding Classification for Industry Sector Allocation*, 2023 | Embedding-based classification into sectors | [34] |
| Sautner, van Lent, Vilkov & Zhang, *Firm-Level Climate Change Exposure*, J. Finance 2023 | ML-built bigrams in earnings calls measure climate opportunity, physical and regulatory exposure for 10k+ firms; the measures are priced | [35] |
| Kim, Muhn & Nikolaev, *From Transcripts to Insights…Generative AI*, 2023 | GPT summaries of calls give firm-level political, climate and AI risk; beat dictionaries | [36] |
| Basu et al., *Firm-level AI exposure*, 2026 | AI exposure from 13.7k firms' calls, with 10 sub-measures | [37] |

## 3. Risk exposure: "which companies are exposed to risk Y?"

### 3.1 Asset-level climate risk

| Vendor | Method | Coverage | Source |
|---|---|---|---|
| **MSCI Climate VaR** | Policy risk, technology opportunities, and physical risk and opportunities as scenario costs/profits in % of value. Physical = hazard × asset value × vulnerability on 600k+ geolocated assets; transition = Scope 1–3 emissions against pathways at carbon prices; patents and low-carbon revenue for opportunities | listed universe | [38], [39] |
| **S&P Trucost physical risk** | Hazard models on asset locations mapped to parents via ownership data; exposure scores 0–100 (> 75 high) and financial impact; 10 hazards, 4 scenarios, decades to the 2090s | 73k+ companies, 7M+ assets | [40], [41] |
| **Moody's Climate on Demand** (RMS, Four Twenty Seven) | Hazard × exposure × vulnerability per facility; company scores aggregate facilities; flood at 30 m | 3.5M+ facilities, 23k+ companies | [42], [43], [44] |
| **BlackRock Aladdin Climate** | Asset-level physical risk down to 25 m grids and transition risk via the Baringa scenario model; climate-adjusted valuations | portfolio platform | [45], [46] |

### 3.2 Open asset data

| Source | Method | Licence | Source |
|---|---|---|---|
| **Climate TRACE** | ML on satellite and remote-sensing data trained against ground truth; ~2.77M emission sources; monthly; assets linked to owners | open | [47], [48] |
| **Global Energy Monitor** | Researcher-built trackers (coal, gas, steel, …), every fact cited; Ownership Tracker links assets to owners; LEI links (2025) | CC BY 4.0 mostly | [49], [50], [51] |
| **TransitionZero** | ML on Sentinel-2 for solar assets (TZ-SAM), ~1 TW mapped | CC BY-NC 4.0 | [52], [53] |
| **Asset Impact** (formerly Asset Resolution, GRESB) | Asset-based company data for power, steel, cement, vehicles, oil and gas, linked through the ownership tree; data behind RMI PACTA | licensed | [54], [55] |

### 3.3 Controversies and events

| Vendor / manager | Method | Source |
|---|---|---|
| **RepRisk** | Outside-in only (no self-disclosure): AI/ML screen 150k+ sources in 30 languages daily, analysts curate and score against 100+ risk factors; 300k+ entities, mostly private; agentic delivery team (2025) | [56], [57] |
| **FactSet Truvalue Labs** | NLP over 150k+ external sources mapped to 26 SASB issues; Insight, Pulse, Momentum and Volume scores | [58], [59] |
| **RavenPack / Bigdata.com** | Entity and event detection from ~100k human-written templates; relevance, sentiment and novelty per mention; GenAI platform on top | [60], [61] |
| **NBIM** | Risk assessment when a company enters the benchmark; daily monitoring for severe incidents; since 2025 an LLM (Claude) screens each new holding within 24 hours for forced labour, corruption and fraud, especially where vendors cover poorly; analysts review every flag; results feed divestment, engagement and Council on Ethics referrals | [62], [63], [64] |
| Research | Hanley & Hoberg (RFS 2019): topic models plus embeddings on 10-K risk factors detect emerging risks early. LLM extraction of 10.7k risk factors from S&P 500 10-Ks (2026). ESG reputation events → about −0.29% abnormal returns (UCL) | [65], [66], [67] |

### 3.4 Supply chain

| Vendor | Method | Source |
|---|---|---|
| **FactSet Revere** | Analysts collect customer, supplier, partner and competitor links from disclosures; 2nd–4th degree; history since 2003 | [68], [69] |
| **Bloomberg SPLC** | Disclosed relationships plus algorithmically *quantified* ones (revenue and cost shares) where disclosure is missing | [70], [71] |
| **Interos** | ML knowledge graph that infers Tier 2+ suppliers; 0–100 i-Score over six risk domains | [72], [73] |
| Critique | Culot et al. (J. Supply Chain Mgmt 2023) on the validity of SPLC, FactSet and Mergent data | [74] |

## 4. Engagement selection in practice

| Manager | How companies are selected and escalated | Source |
|---|---|---|
| **LGIM / L&G (Climate Impact Pledge)** | ~5,000 companies in 20 climate-critical sectors scored on governance, strategy, policies, metrics and targets; traffic-light ratings; votes against (usually the chair) for misses; ~100 in-depth engagements; persistent laggards divested from Future World funds and named | [75], [76], [77] |
| **Federated Hermes EOS** | Four-stage milestones: concern raised → acknowledged → credible strategy → implemented; selection from client engagement plans and holdings; escalation through voting | [78], [79] |
| **NBIM** | Risk-based monitoring (section 3.3) feeds engagement and exclusion | [62] |
| **Amundi** | ESG rating (38 criteria, A–G, monthly) on ALTO Sustainability; thematic and collaborative engagement; AI role *unconfirmed* | [80], [81] |
| **Man Group** | Agentic LLM system (AlphaGPT) for signal research with human committees; partnership with Anthropic; alpha research, not stewardship | [82], [83] |

## 5. Where ARP stands

| Capability | Market standard | ARP today | Gap |
|---|---|---|---|
| Evidence from text, with quotes | NLP + analysts, quotes rarely shown | LLM debate (Universe Builder), `grounding.py`, review queue; funnel tested (section 7) | **ahead** on auditability |
| New themes quickly | Kensho, ARTIS (text); revenue taxonomies are slow | Taxonomy Library + funnel: a new theme in days | **ahead** |
| Revenue sizing (disclosed) | RBICS, MSCI relevance score | XBRL Facts (#18), Financials segments (#4) | small |
| Revenue sizing (undisclosed splits) | analyst normalisation, Bloomberg quantified estimates | none | **large** |
| Entity resolution and linking | Kensho NERD/Link, LEI, ownership trees | Identity Resolution (#5), company graph | **medium** |
| Asset-level physical and transition risk | MSCI CVaR, Trucost, Moody's | none | **large** |
| Asset ownership data | GEM, Asset Impact, Climate TRACE | none | **large** (open data exists) |
| Controversy and event feed | RepRisk, Truvalue, NBIM's LLM screening | static controversy list | **large** |
| Supply chain | Revere, SPLC, Interos | input-output propagation (#7), Neo4j graph from CSV | medium |
| Engagement selection and escalation | LGIM pledge scoring, EOS milestones | stewardship program, tiers, escalation graph; CLTI is a placeholder | **medium** (data, not logic) |
| Research front end (GenAI) | AlphaSense, Clarity AI assistant | Ask, Smart Search, LLM agents | small |

## 6. Action plan

Principle: **buy or connect the data, build the evidence and decisions.** ARP's code already follows the
market's architecture (models propose, code computes, people decide); what it lacks is data. Every workstream
below is a child spec of the umbrella spec, behind a setting that is off by default, with a golden-set gate.

### Phase A, next 6 weeks: make the funnel production-grade and close the cheapest gaps

| # | Workstream | Deliverable | Uses | Done when (gate) | Effort |
|---|---|---|---|---|---|
| A1 | Shared model layer | `arp/models/` per the approved umbrella spec | embeddings, cross-encoder, NLI, GLiNER | its 19 acceptance rows pass | 1–2 weeks |
| A2 | Thematic funnel in front of the Universe Builder | Steps 1–3 as a pre-filter; operator-vs-maker and supplier hypotheses; shortlist goes to the debate | A1, `research/match_graph.py` | Golden set (A3): recall ≥ 0.95 of core + peripheral at the shortlist; LLM calls −50% with no loss in final precision | 2 weeks |
| A3 | Golden sets | Electrolyser set grown to ~60 companies (held-out half) plus two more themes (one fuzzy, e.g. "AI data centres"; one risk, e.g. "water scarcity") | annual reports, EDGAR | labels checked against filings, with sources | 1 week, ongoing |
| A4 | Company risk view | Child spec `company-risk-view` (risks, mitigations, year-on-year) | A1, LLM | its acceptance rows; golden on Heidelberg and Martin Marietta | 2 weeks |
| A5 | Open asset data | GEM trackers (steel, cement, coal, gas plants) and Climate TRACE sources loaded with owner links into the company graph | GEM CC BY, Climate TRACE | ≥ 80% of GEM listed owners in the universe matched to ARP company ids | 1–2 weeks |

### Phase B, months 2–4: revenue sizing, entities and live risk signals

| # | Workstream | Deliverable | Uses | Done when (gate) | Effort |
|---|---|---|---|---|---|
| B1 | Revenue sizing | Theme revenue share per company: (1) XBRL segments, (2) LLM-extracted segment notes with quotes, (3) an estimate flagged `modelled` where nothing is disclosed (keyword-selected segments with a discount, as MSCI does) | #4, #18, A1 | On the golden set: revenue share within ±10 pp for ≥ 80% of companies with disclosed segments; every modelled value flagged | 3–4 weeks |
| B2 | Entity linking | Company mentions in text (news, reports, GEM) linked to ARP ids and LEIs using GLiNER spans + embeddings + cross-encoder, with GLEIF as the reference | A1, #5, GLEIF | precision ≥ 0.95, recall ≥ 0.85 on a 500-mention labelled set | 3 weeks |
| B3 | Controversy feed | News and NGO sources → entity linking (B2) → ESG topic tags + NLI severity → stewardship triggers, replacing the static list; NBIM-style LLM screen of each new holding | A1, B2, LLM | On a labelled set of 200 incidents: recall ≥ 0.8 of high-severity events; every alert has a source quote | 4 weeks |
| B4 | "Say vs do" | Compare stated emissions and plans (transition-plan extraction) with Climate TRACE / GEM asset data; flag gaps | A5, #8 | Gap flags on ≥ 50 high emitters, each with both numbers and sources | 2 weeks |
| B5 | Engagement selection uses real data | Replace the placeholder CLTI with transition-plan scores (#8), risk view (A4), controversies (B3) and say-vs-do (B4); LGIM-style traffic lights and EOS-style milestones in stewardship tracking | stewardship, Decision Studio | A backtest on 2024–2025 shows the selection reproduces ≥ 70% of the house's actual engagement list, and every pick lists its reasons | 3 weeks |

### Phase C, months 4–9: asset-level risk and buy decisions

| # | Workstream | Deliverable | Done when (gate) |
|---|---|---|---|
| C1 | Physical risk, first cut | Asset locations (A5) × open hazard layers (flood, heat, water stress) → per-company exposure scores, flagged `indicative` | Rank correlation with a vendor sample (if licensed) or with published case studies |
| C2 | Buy-vs-build review | Decide on licensing revenue classification (FactSet RBICS), physical risk (Trucost / Moody's / MSCI) and controversies (RepRisk) versus A–B results | A written comparison on the golden sets, with cost per company |
| C3 | Supply chain | Supplier edges from text (REBEL / LLM on disclosures) into the company graph; compare with input-output propagation (#7) | Edge precision ≥ 0.9 on a labelled sample |
| C4 | Research front end | Ask/Smart Search over the new evidence (risk views, controversies, assets) with citations | Every answer cites stored evidence; golden questions pass |

### Gates and governance

- **One golden set per capability**, kept in `backend/tests/golden/`, labels checked against sources, refreshed yearly.
- **Default-off settings**: a capability is switched on by default only after its gate passes (umbrella-spec rule).
- **Provenance**: every value records model, revision, source document and quote.
- **Owner approval** of each child spec before implementation (`docs/superpowers/ACCEPTANCE_TEMPLATE.md`).

### Risks

| Risk | Mitigation |
|---|---|
| Revenue estimates look precise but are not | Always flag `modelled`; show the range; never mix with reported values without a label |
| Open asset data has ownership gaps (GEM: 7.6% of entities listed) | Report coverage per sector; fall back to vendor data in C2 |
| News feed volume and licensing | Start with free sources (GDELT, regulators, NGOs); buy only if B3's gate fails |
| Model drift between years | Pinned registry revisions; yearly re-run of golden sets |

## 7. Evidence from ARP's own test (electrolyser manufacturers)

See `golden_drafts/electrolyser_funnel_results.md`. The first run on "about" pages found 6/6 core makers but
0/6 peripheral ones. The rerun on full annual reports and 10-Ks with an operator-vs-maker hypothesis is
summarised there. In short: full reports fix the peripheral misses, but they also raise false positives from
companies that discuss electrolysers at length without making them. The revenue-sizing step (B1) and the LLM
debate (A2) exist to settle those.

## 8. Sources

- [1] https://insight.factset.com/resources/factset-revere-business-industry-classifications-datafeed
- [2] https://insight.factset.com/resources/at-a-glance-factset-rbics-with-tradenames-datafeed
- [3] https://go.factset.com/hubfs/Website/Resources%20Section/Case%20Studies/major-institutional-asset-manager-enhances-multiple-esg-processes-with-factset-company-revenue-exposure-per-industry-data-case-study%20.pdf
- [4] https://www.bloomberg.com/company/press/quants-increase-focus-on-sector-specific-data-as-ai-adoption-evolves-bloomberg-research
- [5] https://www.bloomberg.com/professional/?p=131918
- [6] https://microsites.databricks.com/sites/default/files/dais/2024/D241255B_Bloomberg_THEMATIC%20INVESTING_%20Data%20+%20AI%20Summit_June%202024_1718387684904001MpiA.pdf
- [7] https://www.msci.com/indexes/documents/methodology/2_MSCI_Thematic_Relevance_Score_Methodology_20220519.pdf
- [8] https://www.msci.com/eqb/methodology/meth_docs/MSCI_Relevance_Score_Calculation_Methodology.pdf
- [9] https://www.msci.com/documents/1296102/43829639/How+MSCI+Builds+Thematic+Indexes.pdf/2e437bbd-05a1-ac8f-5146-b8f3bff0d6f2
- [10] https://www.businesswire.com/news/home/20240610715107/en
- [11] https://spglobal.com/spdji/en/documents/additional-material/brochure-sp-kensho-new-economies-indices.pdf
- [12] https://docs.kensho.com/nerd/overview
- [13] https://press.spglobal.com/2023-10-02-Kensho-Technologies-Streamlines-Client-Data-Management-by-Integrating-its-Link-AI-Solution-with-S-P-Global-Market-Intelligences-Cross-Reference-Service-Dataset,-BECRS
- [14] https://www.spglobal.com/market-intelligence/en/news-insights/research/2026/04/next-evolution-kensho-link
- [15] https://www.marketplace.spglobal.com/en/solutions/kensho-llm-ready-api-(a156fe9f-5564-4f60-a624-95d8645dc98f)
- [16] https://solactive.com/artis/
- [17] https://www.issgovernance.com/esg/eu-taxonomy-solution/
- [18] https://insights.issgovernance.com/posts/bridging-the-gap-how-iss-esg-eu-taxonomy-modelled-data-compares-with-reported-data
- [19] https://insights.issgovernance.com/posts/iss-esg-enhances-eu-taxonomy-alignment-solution
- [20] https://clarity.ai/regulatory-compliance/eu-taxonomy/
- [21] https://clarity.ai/research-and-insights/regulatory-compliance/eu-taxonomy-leveraging-technology-to-analyze-controversies/
- [22] https://www.businesswire.com/news/home/20250311570178/en
- [23] https://www.blackrock.com/us/individual/literature/product-brief/ishares-robotics-and-artificial-intelligence-irbo-etf-product-brief-en-us.pdf
- [24] https://www.sec.gov/Archives/edgar/data/1100663/000119312524159938/d420147d497.htm
- [25] https://www.robeco.com/files/docm/docu-robeco-sdg-framework.pdf
- [26] https://www.robeco.com/en-int/insights/2022/10/robecos-sdg-framework-from-niche-to-mainstream
- [27] https://apg.nl/en/publication/apg-co-launches-platform-for-investments-in-sustainable-development/
- [28] https://apg.nl/en/publication/we-discovered-1320-new-teslas/
- [29] https://stoxx.com/wp-content/uploads/2020/12/2020-Qontigo-Summit_Session-1-The-New-Asset-Owner-Platform-for-Identifying-SDG-Investments.pdf
- [30] https://mybrand.schroders.com/m/317c7fc89b751d5a/original/SustainEx-High-Level-Methodology-Final.pdf
- [31] https://www.schroders.com/en/global/individual/sustainability/sustainable-investing/measure-sustainability/
- [32] https://www.nber.org/papers/w15991
- [33] https://arxiv.org/abs/2308.08031
- [34] https://arxiv.org/abs/2309.12075
- [35] https://papers.ssrn.com/abstract=3642508
- [36] https://arxiv.org/abs/2310.17721
- [37] https://strathprints.strath.ac.uk/97605/
- [38] https://www.msci.com/documents/1296102/39141520/Updated_PUBLIC_CVaR_Meth+doc_EEC.pdf/719282fb-3775-c978-bfe1-01be17d1a4c4
- [39] https://www.msci.com/documents/1296102/19288350/ClimateVaR_RealEstate_Methodology.pdf
- [40] https://marketplace.spglobal.com/en/datasets/trucost-physical-risk-(148)
- [41] https://press.spglobal.com/2022-09-15-S-P-Global-Sustainable1-Launches-Physical-Risk-Exposure-Scores-and-Financial-Impact
- [42] https://developer.rms.com/climate-on-demand/reference/cod-v1-score-facilities-job
- [43] https://developer.rms.com/climate-on-demand/docs/company-level-scoring
- [44] https://climate.moodys.com/climate-blog/understand-physical-climate-risk-introducing-moodys-climate-on-demand-version-2
- [45] https://www.businesswire.com/news/home/20201201005395/en/
- [46] https://www.esgtoday.com/blackrock-launches-solution-for-financials-and-investors-to-quantify-climate-risk-in-portfolios/
- [47] https://climatetrace.org/news/what-are-artificial-intelligence-ai-and-machine-learning-ml
- [48] https://watttime.org/about-us/climate-trace/
- [49] https://globalenergymonitor.org/projects/global-energy-ownership-tracker
- [50] https://globalenergymonitor.org/about-gems-trackers/
- [51] https://www.gem.wiki/Global_Coal_Plant_Tracker_Ownership_Review
- [52] https://globalenergymonitor.org/press-release/transitionzero-launches-global-ai-generated-solar-plant-dataset-discovering-3x-additional-gw-capacity-for-smaller-facilities-than-alternatives/
- [53] https://zenodo.org/records/11368204
- [54] https://asset-impact.gresb.com/frequently-asked-questions
- [55] https://pacta.rmi.org/pacta-for-investors/software-downloads-data/
- [56] https://www.reprisk.com/insights/resources/methodology
- [57] https://www.reprisk.com/insights/news-and-media-coverage/reprisk-boosts-agentic-ai-delivery-to-power-data-integration
- [58] https://insight.factset.com/resources/at-a-glance-factset-truvalue-sasb-scores-datafeed
- [59] https://advantage.factset.com/hubfs/Website/Resources%20Section/Brochures/esg-data-and-analytics-from-truvalue-labs-brochure.pdf
- [60] https://www.finextra.com/pressarticle/56610/ravenpack-upgrades-rpna
- [61] https://european-lisp-symposium.org/static/2018/cornez.pdf
- [62] https://www.nbim.no/contentassets/7cdcc51cdb954e67ad933008866b874d/european-commissions-consultation-on-corporate-sustainability-due-diligence-directive-implementation-guidelines.pdf
- [63] https://nordsip.com/2026/03/20/norways-oil-fund-turns-to-ai-for-esg-risk-screening/
- [64] https://www.claude.com/customers/nbim (vendor case study)
- [65] https://sfs.org/editors-choice-3212/
- [66] https://arxiv.org/abs/2601.15247
- [67] https://discovery.ucl.ac.uk/10184974/1/ESGReputationRiskMatters.pdf
- [68] https://www.library.hbs.edu/databases-cases-and-more/datasets/factset-revere-supply-chain-relationships
- [69] https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/factset/
- [70] https://www.bloomberg.com/professional/insights/markets/researching-supply-chain-exposures-how-to-analyse-coronavirus-related-risks
- [71] https://prod.libraries.emory.edu/sites/default/files/migrated-documents/db-pages/bloomberg-splc.pdf
- [72] https://aws.amazon.com/marketplace/pp/prodview-h3m3irdg7bika
- [73] https://www.businesswire.com/news/home/20260428661670/en/interos.ai-Launches-iQ-to-Elevate-Supply-Chain-Risks-to-the-C-Level
- [74] https://ideas.repec.org/a/bla/jscmgt/v59y2023i1p3-25.html
- [75] https://climatepledge.lgim.com
- [76] https://lgim.com/landg-assets/lgim/_document-library/adviser/climate-pledge-report-lgim-investor-audience.pdf
- [77] https://cms.lgim.com/globalassets/lgim/responsible-investing/q2-2024-engagement-report.pdf
- [78] https://www.hermes-investment.com/uploads/2025/04/c03ad3a773b60da42c9b7cf57f982bcb/eos-stewardship-brochure-2025.pdf
- [79] https://www.hermes-investment.com/uploads/2026/05/91cd9aebec5aa39fe01ed91cc5b6304e/eos-corporate-activities-outcomes-report-2025.pdf
- [80] https://www.amunditechnology.com/alto-sustainability
- [81] https://about.amundi.com/files/nuxeo/dl/15c30503-5d76-4860-be03-6e994025886e
- [82] https://www.bloomberg.com/news/articles/2025-07-10/man-group-says-agentic-ai-is-now-devising-quant-trading-signals
- [83] https://www.hedgeweek.com/man-group-partners-with-anthropic-to-embed-ai-across-investment-processes/

## 9. Not confirmed

FactSet's estimation of undisclosed revenue splits; a Bloomberg GenAI thematic product; MSCI's LLM thematic
method; BlackRock's and Amundi's use of AI for engagement selection; Robeco's NLP model details; LGIM's current
pledge red lines; Interos domain weights; Asset Impact coverage; coverage figures for Revere, SPLC and Interos
(conflicting across sources). Several manager descriptions rest on press coverage or vendor case studies rather
than the managers' own reports (NBIM, Man Group, APG/Entis).
