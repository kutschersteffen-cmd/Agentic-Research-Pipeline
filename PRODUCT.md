# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: a stewardship and ESG team at an asset manager (confirmed). They run engagement with
companies, decide proxy votes, and assess climate transition plans and barriers. The research
functions (thematic universes, extraction, index construction, strategy replication) serve them
and adjacent investment analysts, but are secondary.

## Product Purpose

Agent pipelines for investment research at scale: build thematic company universes, extract
schema-defined data points from disclosures, assess transition plans, track engagement and votes,
and analyse portfolios, for up to ~4,000 companies per run. Success is a decision the team can
defend: every number traceable to a verified source and every automated suggestion reviewed by a
person before it counts.

## Positioning

Two rules no neighbouring tool truthfully claims together: **the LLM plans, deterministic code
computes**, and **every citation is re-verified programmatically** against the source document
rather than trusted from the model. Agents propose; people ratify. Nothing flagged enters an
export until a human approves it.

## Operating Context

- Mostly **presented to others** (confirmed): screen-shared in stewardship committees, investment
  committees and client meetings, as well as worked in directly.
- The work revolves around disclosures (annual, sustainability and proxy reports), cited evidence,
  review queues, escalation ladders, ballots, versioned taxonomies and effective-dated index
  calibrations.
- Runs are long batch jobs, checkpointed and resumable, polled while open.

## Capabilities and Constraints

- Sixteen functions (see README): Thematic Universe Builder, Taxonomy Library, Data-Point
  Extraction, Company Financials, Identity Resolution, Document Discovery, Indirect Exposure,
  Transition Plan Assessment (64 indicators, walk vs. talk), Transition Barrier Assessment
  (105-cell matrix), Portfolio Risk & Exposure Monitoring incl. Climate Analytics, Strategy
  Replication, Emerging Themes, Presentation & Reporting, Decision Studio, Equity Index
  Construction, standing agents.
- React + TypeScript (Vite) frontend over a FastAPI backend; file-based state, no database.
- Terminology to keep: run, review queue, grounded / ungrounded citation, ratify, calibration,
  escalation stage, walk / talk, tier.

## Brand Commitments

None (confirmed): no corporate brand; the product name is "Agentic Research Pipeline" (ARP).

## Evidence on Hand

- Real reference sources: 86 verified sources behind the transition barrier matrix; the
  Colesanti Senni et al. (2024) indicator set; taxonomies, portfolios and frameworks in the repo.
- No customers, testimonials, benchmarks or pricing exist; none may be invented.

## Product Principles

1. Provenance over polish: a figure without its source is unfinished.
2. Propose, never apply: automation suggests, a named person decides.
3. Show the uncertainty: guesses, gaps and rank ranges are surfaced, never smoothed away.
4. Legible in the room: the screen must read when shared, to people who did not drive it.
   (Inferred from "presented to others".)

## Accessibility & Inclusion

WCAG 2.1 AA as the working bar (inferred; no stated requirement). Presentation use adds
projector/screen-share legibility.
