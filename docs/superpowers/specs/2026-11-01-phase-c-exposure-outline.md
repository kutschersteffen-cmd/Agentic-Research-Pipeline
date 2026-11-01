# Phase C outline: asset-level risk, buy decisions, supply chain, research front end

Spec slug: `phase-c-exposure-outline`. **Outline, not for implementation.** Each workstream gets its own detailed

Status: outline approved by the owner, 2026-11-01 (scope and order).
spec after Phase B. Parent: `2026-11-01-model-stack-design.md`. Action plan:
`docs/MARKET_EXPOSURE_APPROACHES_RESEARCH.md`, section 6.

## Why

After Phase B, ARP has revenue sizing, entity linking, controversies and asset ownership. Remaining gaps
against the market: asset-level physical risk (MSCI Climate VaR, S&P Trucost, Moody's), a supply chain built
from text rather than only input-output tables, and a decision on which data to license rather than build.

## Workstreams

### C1 Physical risk, first cut

- **Goal:** per-company exposure scores from asset locations (A5) × open hazard layers (river and coastal flood,
  extreme heat, water stress), weighted by ownership share and capacity, flagged `indicative`.
- **Builds on:** A5 asset graph; open hazard data (candidates: WRI Aqueduct water risk and floods, Copernicus
  climate indicators; licences to be checked in the detailed spec).
- **Gate:** rank correlation ≥ 0.6 with a licensed vendor sample if C2 licenses one; otherwise agreement with
  the asset-level examples published in vendor methodology documents.
- **Open questions:** scenarios (current climate only, or SSP pathways); hazards in scope; treatment of assets
  without coordinates.

### C2 Buy-vs-build review

- **Goal:** a written decision, per data type, on licensing versus ARP's own results: revenue classification
  (e.g. FactSet RBICS vs B1), physical risk (Trucost / Moody's / MSCI vs C1), controversies (RepRisk / Truvalue
  vs B3), asset ownership (Asset Impact vs A5).
- **Method:** run both on the A3 golden sets (vendor trial data), compare quality, coverage, refresh speed and
  cost per company; include licence terms for redistribution in client reports.
- **Output:** `docs/BUY_VS_BUILD_EXPOSURE_DATA.md` with a recommendation per data type, approved by the owner.
- **Open questions:** budget; which vendors offer trials on a sample universe.

### C3 Supply chain from text

- **Goal:** supplier and customer edges extracted from disclosures (relation extraction or LLM, with quotes)
  into the company graph, next to input-output propagation (#7).
- **Builds on:** B2 entity linking, `company_graph.py` (edge versions with `source_doc` and `source_passage`
  already exist), review queue.
- **Gate:** edge precision ≥ 0.9 on a labelled sample of 300 sentences; every edge has a source passage.
- **Open questions:** keep only disclosed edges, or also estimate revenue shares as Bloomberg SPLC does.

### C4 Research front end over the new evidence

- **Goal:** Ask and Smart Search answer questions over risk views, controversies, assets and funnel evidence,
  citing stored evidence only.
- **Builds on:** `arp/ask.py`, `smart_search.py`, the stores from A–B.
- **Gate:** a golden question set (≥ 50 questions); every answer cites stored evidence; ≥ 90% judged correct.
- **Open questions:** which questions analysts actually ask (collect from the stewardship team first).

## Order and dependencies

```
A5 ── C1
B1, B3, C1 ── C2
B2 ── C3
A4, B3, A5 ── C4
```

C2 can start as soon as B1 and B3 have golden results; its outcome may cancel or shrink C1 or C3.

## Rules for every C spec

As for Phase B: setting off by default, golden set with `holdout`, provenance on every value, owner approval,
spec-critic pass.
