# Phase B outline: revenue sizing, entities and live risk signals

Spec slug: `phase-b-exposure-outline`. **Outline, not for implementation.** Each workstream below gets its own

Status: outline approved by the owner, 2026-11-01 (scope and order).
detailed spec with an acceptance table once Phase A results are in. Parent: `2026-11-01-model-stack-design.md`.
Action plan: `docs/MARKET_EXPOSURE_APPROACHES_RESEARCH.md`, section 6.

## Why

Phase A builds the shared model layer, the funnel, golden sets, the risk view and open asset data. The gaps
that remain against the market are sizing exposure by revenue where companies don't disclose the split, linking
companies across text and data sources, a live controversy feed, checking stated plans against asset data, and
feeding all of it into engagement selection in place of the placeholder CLTI score.

## Workstreams

### B1 Revenue sizing

- **Goal:** a theme revenue share per company × activity, labelled by how it was obtained: `reported` (XBRL
  segments, #18), `extracted` (segment notes via the existing `research/revenue_exposure` resolver, with quotes),
  `modelled` (segments selected by the activity's keywords with a discount factor, the MSCI relevance-score
  pattern), always with a range for `modelled`.
- **Builds on:** `arp/research/revenue_exposure/` (already resolves revenue per activity from a catalogue and
  extraction), XBRL Facts, Financials (#4), A2 funnel passages.
- **Gate (becomes golden rows):** on A3 sets, the share is within ±10 pp for ≥ 80% of companies with disclosed
  segments; 100% of `modelled` values carry the label and a range.
- **Open questions:** discount factor per theme or global; whether `modelled` values may enter Decision Studio.

### B2 Entity linking

- **Goal:** link company mentions in text (news, reports, GEM owners, supply-chain sentences) to ARP company ids
  and LEIs.
- **Builds on:** GLiNER `spans`, `embed`, `rerank` (A1); Identity Resolution (#5); GLEIF as the reference list;
  the review queue for low-confidence links.
- **Gate:** precision ≥ 0.95 and recall ≥ 0.85 on a labelled set of 500 mentions (new golden set, A3 format).
- **Open questions:** keep a local GLEIF copy or call the API; how to treat subsidiaries (link to parent, to
  subsidiary, or both).

### B3 Controversy feed

- **Goal:** turn news and NGO/regulator sources into stewardship triggers with a source quote, replacing the
  static list in `engagement/triggers.py`; plus an NBIM-style LLM screen of each new holding within 24 hours.
- **Builds on:** B2 entity linking, `tag` (ESG topics) and `classify` (severity) from A1, the LLM for the
  holding screen, existing trigger lifecycle (`/stewardship/triggers`).
- **Gate:** on a labelled set of 200 incidents, recall ≥ 0.8 for high-severity events; every alert has a source
  quote and URL.
- **Open questions:** free sources first (GDELT, regulators, NGOs) vs licensed feed; languages in scope.

### B4 Say vs do

- **Goal:** compare stated emissions, targets and capex (transition-plan extraction, #8) with asset data (A5:
  GEM capacity, Climate TRACE emissions) and flag gaps with both numbers and sources.
- **Builds on:** A5, Transition Plan Assessment, Climate Analytics.
- **Gate:** gap flags for ≥ 50 high emitters, each showing the reported figure, the asset-based figure, both
  sources, and the share of the company's assets covered.
- **Open questions:** minimum asset coverage before a gap is shown; Scope 1 only or Scope 1+2.

### B5 Engagement selection on real data

- **Goal:** replace the placeholder CLTI in `stewardship/program.py` with transition-plan scores (#8), the risk
  view (A4), controversies (B3) and say-vs-do gaps (B4); add EOS-style milestones (raised → acknowledged →
  strategy → implemented) to engagement tracking; LGIM-style traffic lights per company.
- **Builds on:** stewardship program, tiers, escalation graph, Decision Studio.
- **Gate:** a backtest on 2024–2025 reproduces ≥ 70% of the house's actual engagement list, and every pick lists
  its reasons with sources.
- **Open questions:** availability of the house's historical engagement list; weights between inputs (Decision
  Studio framework or fixed).

## Order and dependencies

```
A1 ─┬─ B2 ── B3
    ├─ B1
A5 ─┴─ B4
A4, B3, B4, B1 ── B5
```

B1 and B2 can start in parallel after A1; B5 starts last.

## Rules for every B spec

Setting off by default; golden set in the A3 format with a `holdout` half; provenance (model, revision,
document, quote) on every value; owner approval before implementation; spec-critic pass.
