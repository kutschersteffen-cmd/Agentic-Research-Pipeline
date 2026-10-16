# Themes lane add-on: 3-layer exposure framework and research replications

Date: 2026-10-15
Status: add-on supplied by the owner; **not yet reconciled into a build plan**. No code is built from this file.
Parent: Themes lane in `docs/superpowers/specs/2026-10-14-rd-lab-overview-design.md`. There is no
separate thematic implementation plan yet; this file is the add-on that plan will absorb when the
Themes lane gaps (market test, topic entry, verified exposure) are planned. Until then it is the
reference for that planning.

## 1. What the add-on proposes (summary)

- **3-layer exposure hierarchy:** Layer 1 direct pure-plays (segment revenue share above 30 to 50
  percent), Layer 2 value-chain and supply bottlenecks (customer disclosures, 1 and 2 hops),
  Layer 3 macro infrastructure and downstream adopters (capex, interconnection queues, segment
  margins). One consolidated score `S_i` per company with layer weights `w1=0.45, w2=0.35,
  w3=0.20`, graph decay `gamma=0.85`, and a Thematic Bubble Indicator (TBI) penalty.
- **Four research replications:** THEME (contrastive semantic-temporal embeddings,
  arXiv:2508.16936), FinDKG (temporal knowledge graph, arXiv:2407.10909), FundaPod
  (analyst/skeptic/auditor debate, arXiv:2605.27864), LLM-enhanced Black-Litterman
  (arXiv:2504.14345; view vector `q` and uncertainty `Omega` from N=100 stochastic queries).
- **Pipeline:** three-agent LangGraph scoring (analyst, skeptic, auditor reconciling against XBRL),
  Neo4j supply-chain graph, CVXPY optimizer (long-only, 10 percent cap, tracking-error limit, TBI
  penalty), 12-week roadmap with Qdrant, Elasticsearch, Neo4j, Next.js and a broker sandbox.

The full text as supplied is kept in the appendix, unedited except for the missing equations (see 2).

## 2. Gaps in the add-on as supplied

1. **Equations are missing.** The formulas for `S_i`, the THEME loss, and the Black-Litterman
   `q` and `Omega` parameterisation did not arrive (only their symbols). They must be re-supplied
   or taken from the papers before anything is built. This file does not reconstruct them.
2. **Layer weights disagree.** The text says `w = 0.45 / 0.35 / 0.20`; the auditor code uses
   `0.50 * revenue_share + 0.35 * density * sentiment + 0.15 * 0.85`. One set must be chosen.
3. **The auditor stub contains invented numbers** (`n_density = 0.92`, `sentiment = 1.0`, a
   hard-coded thesis and critique). It is an illustration, not a method.
4. **Paper references are unverified.** The four arXiv IDs have not been checked against the
   papers; FundaPod's ID (2605.27864) in particular must be confirmed before it is cited.

## 3. Reconciliation with this repo (my calls; the planner confirms each)

| Add-on item | Repo today | Call |
|---|---|---|
| Layer 1 direct pure-play, revenue share | `emerging_themes/company_exposure.py`, `company_role.py`, revenue-exposure cascade, XBRL loader (`ingestion/xbrl.py`) | Extend, do not rebuild. Layer 1 is the existing verified-exposure standard with a numeric share threshold. |
| Layer 2 supply chain (ASC 280 major customers) | No supply-chain graph. | New. Start as a Postgres edge table (supplier issuer, customer issuer, revenue dependency, source filing, effective date); decide Neo4j only if multi-hop queries outgrow SQL. |
| Layer 3 macro and adopters | No equivalent. | New, lowest priority within the add-on; needs data not yet identified (interconnection queues). |
| `S_i` consolidated score | Scoring rules engine in the shared build stage. | Implement as a versioned scoring rule once the formula is supplied. |
| Hybrid search, re-ranker | Hybrid retrieval exists but is off; no re-ranking (see `docs/THEMATIC_INTELLIGENCE_ARCHITECTURE_REVIEW.md` 3.2). | Reuse; enable per that review. Qdrant and Elasticsearch are not adopted: the repo's decision is Postgres with pgvector (same review, section 4). |
| Analyst/skeptic/auditor agents | Verifier model separation and self-consistency exist or are planned; the Analysts lane sketch covers analyst agents. | Fold into the Analysts lane (lowest priority); LangGraph is a new dependency and needs a decision. |
| THEME embeddings | Library choice already made: sentence-transformers, ChronoBERT, BERTopic. | Treat THEME as a research candidate in the Signals notebooks, not a platform dependency. |
| FinDKG / temporal graph | None. | Research candidate after Layer 2 exists as a table. |
| Black-Litterman with LLM views | `docs/OPTIMIZATION_TOOLING.md` already picks cvxpy with Clarabel behind `apply_constraints`. | Shared build stage upgrade. LLM views are signals and must pass the Signals evidence core (registry, trial counting, training-cutoff rule) before they feed `q`; N=100 queries per view is a cost to price first. |
| TBI penalty | None. | Needs a definition; a bubble indicator built from price and valuation is a signal and goes through the same evidence gate. |
| CVXPY optimizer sketch | Index and portfolio construction exists. | Use the existing construction stage; the sketch's constraints are examples. |
| Tickers as keys (Neo4j `Company.ticker` unique) | Issuer key and `company_id` are the single identity. | **Conflict. Use the issuer key.** Tickers are attributes only. |
| Broker execution, direct indexing, tax-loss harvesting, conversational front end | Out of scope: internal use only, nothing is sold or traded. | Not adopted. |
| Phase costs and 12-week roadmap | n/a | Not adopted as a schedule; the lab's order of work in the overview governs. |

## 4. Constraints this add-on must honour when planned

- **Evidence before ranking:** theme and exposure rankings that the data cannot separate are
  reported as "insufficient data", not ordered.
- **Point in time:** supply-chain edges and segment revenue carry an effective date and the time
  they became public; backtests use event time only.
- **Grounding rule:** every LLM-derived exposure claim cites its source passage; "not found"
  rather than a guess.
- **Training cutoff:** any LLM-derived view or score is contaminated for periods inside the model's
  training window and cannot count as evidence there.

## 5. Open questions for the owner

1. The missing equations (`S_i`, THEME loss, Black-Litterman `q` and `Omega`).
2. Which layer weights are intended (0.45/0.35/0.20 or 0.50/0.35/0.15).
3. Where Layer 3 data comes from.
4. Whether LangGraph is acceptable as a dependency, or the debate runs on the repo's existing
   agent tooling.

## Appendix: add-on text as supplied

The blueprint is reproduced in the owner's message of 2026-10-15 (`thematic_ai_platform_architecture.md`).
Its sections: Executive summary; 1. four-layer topology (ingestion and storage, intelligence and
semantic graph, quantitative optimisation and risk, presentation and execution); 2. the 3-layer
exposure hierarchy with layer definitions and the consolidated score; 3. research replications A to D;
4. the three-agent LangGraph scoring pipeline; 5. Neo4j schema (unique Company ticker and Theme name,
CIK index) and the two-hop `SUPPLIES_TO` traversal returning anchor, tier 1 and tier 2 suppliers with
revenue dependency; 6. the CVXPY optimiser (maximise adjusted exposure plus Black-Litterman return minus
`gamma` times variance; fully invested, long-only, 10 percent cap, tracking-error limit); 7. the three-phase
roadmap (weeks 1 to 4 engine, 5 to 8 graph and risk engine, 9 to 12 web and direct indexing).
