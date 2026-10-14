# R&D Lab overview (lab-level design)

Date: 2026-10-14
Status: approved by the owner, 2026-10-14

## Intent

The R&D Lab is the internal workspace where research ideas are tested with honest evidence and
then graduated into production scoring, or shelved. Today it is a workspace page (`#/rdLab`)
that links six screens and defines two processes (see `frontend/src/lib/processes.ts` and
`docs/PROCESS_VIEW.md`). This design grows it into a lab with several lanes, a shared contract
between them, and a new landing page in front of the existing screens.

This document holds only the shared contract. Each lane and the shared build stage gets its own
design, in the order below. The first, the Signals workbench, is already written:
`docs/superpowers/specs/2026-10-14-signals-workbench-design.md`.

## The lanes

| Lane | Question it answers | Steps | Status of the work |
|---|---|---|---|
| **Themes / topics** | What is the world talking about and doing? | Detect, Define, Identify, Universe | Most steps exist today; gaps listed below |
| **Signals** | Can text and market data predict returns, honestly? | Design, Generate, Evidence, Decide | New. First to be built (Signals workbench) |
| **Analysts** | What does a sector-aware analyst agent conclude about a company, and what changed today? | Define rule pack, Analyse, Evidence, Decide; plus a daily watch of a large universe | New. Lower priority, designed last |
| **Shared build stage** | Given a universe and inputs, what is the score and the portfolio? | Score, Construct, Backtest | Exists; upgrades listed below |

Themes and signals are different kinds of things and are not merged. Analysts are a third kind. Picture of the first two lanes and the shared stage: `docs/superpowers/specs/assets/lab-two-kinds.html`.

### Themes lane (as the owner described it)

1. **Detect:** emerging themes, issues and risks across a large portfolio. For each, three
   checks: what companies *say* (management comments, earnings calls), what they *do* (capex,
   revenue growth in the field), and the *market test* (is it showing in stock performance).
   The market test is a Themes-lane step.
2. **Define:** a taxonomy of business activities exposed to the theme, direct and indirect along
   the value chain, each backed by an authoritative source, with sectors and industries. A user
   can start here from any topic they type in.
3. **Identify:** a JSON extraction theme that finds companies systematically by their specific
   activities, with cited evidence.
4. **Universe:** companies with verified exposure, reviewed and effective-dated.

Known gaps against today's code: the market test in Detect, entry from a user-defined topic,
and the "verified exposure" standard in Identify. These get their own design.

### Analysts lane (summary; own design later; sketch at `docs/superpowers/specs/assets/analysts-lane-sketch.html`)

Equity analyst agents that follow a **sector rule pack** (user-written or agent-derived from
authoritative sources, versioned and ratified before use). Output per company is a **scorecard**
(one row per rule: evidence, quote, score, confidence; "not found" rather than a guess) and a
**note written only from scorecard lines**. Two jobs: analyse a company on demand, and a
**daily watch** of a universe too large for people: a cheap screen over every name, triage
under a cost cap, and an analyst agent only for names that tripped a screen or are stale,
producing alerts into a review queue.

### Shared build stage

Scoring rules engine, index and portfolio construction, backtest. Exists. Planned upgrades:
neutralisation, value-weighting, costs and cross-signal correlation. Inputs: a verified-exposure
universe from Themes, graduated signals from Signals, accepted scorecards from Analysts.

## Shared contract

**Research item.** Every lane's work is a research item with a kind (theme, signal, analyst
pack), a title, an owner, a stage (lane-specific steps above), a status, and an outcome:
in research, graduated, or shelved. Shelving never deletes.

**Registry.**
- Themes and analysts follow the repo's existing rule that no new state is kept: stage and
  status are read from the run store and the existing review and ratification flows.
- Signals add a registry because trial counting needs it (see the Signals design). The registry
  also records decisions.
- The landing page reads one aggregated view over both; it has no state of its own.

**Guardrails shown at lab level** (enforced inside each lane, listed in each lane's design):
unregistered notebook runs, periods labelled contaminated, the trial count.

**Graduation.** Moving to shared scoring is an explicit approval that records who and when,
freezes the version, and hands the shared stage a defined input (a universe, a characteristic
panel, or a scorecard set).

**Evidence before ranking.** No lane may rank two items above each other if the data cannot
separate them. "Insufficient data" is an accepted answer.

## What gets built from this document

Only the **landing page and its aggregated read model** (version 1), built after the Signals
registry exists, because it reads from it. The rest of this document is the contract the lane
designs must honour; it builds nothing else. The landing page builds no approval flows: it
displays what each lane exposes (graduations awaiting approval, contested exposures, missing
training cutoffs, guardrail numbers). Open questions carried from the Signals design do not
block it.

How a theme's state is read in version 1 (my calls; the builder confirms each against the
existing run store and flows, which I have not read in detail):

- **Stage:** the latest run per run type, using the step-to-run-type mapping already in
  `frontend/src/lib/processes.ts`.
- **Title:** the theme's own name. No owner field for themes or analyst packs in version 1,
  because runs do not carry one as far as I know.
- **Graduated:** a ratified taxonomy with a published universe. **Shelved:** an Emerging Themes
  candidate that was rejected or disconfirmed (those actions exist today).
- **Tile counts:** in research, graduated and shelved are counted separately; the tile headline
  is "in research".
- **Guardrail status:** shown for Signals only, as values the Signals work exposes. Themes and
  analysts show none in version 1.
- **Graduation input to the shared stage:** defined by the shared-stage design. Until then a
  graduated item is a recorded decision with a frozen artifact, and the shared stage does not
  read it automatically. I have not verified which input types the stage accepts today.

## Landing page

A new page at the front of the existing R&D Lab workspace. The existing six screens and the two
existing processes stay and remain reachable from it.

It shows:
- one tile per lane with counts and a link in (Themes, Signals, Analysts when built, Shared
  build stage);
- ideas in flight: item, kind, stage, status;
- a "needs you" list (approve a graduation, review contested exposures, set a missing training
  cutoff). The app already has a "needs you" component and a workspace hub; reuse them.
- guardrail status.

A mockup with invented data is at `docs/superpowers/specs/assets/rd-lab-home-mockup.html`. It shows layout only; the numbers are invented.

## Order of work

1. Signals workbench, with the foundation (point-in-time text store, training-cutoff map,
   evidence checks, experiment registry) inside it.
2. Themes lane gaps.
3. Shared build stage upgrades.
4. Landing page. It can be built as a thin first version earlier, once the registry exists.
5. Analysts lane.

## Goals

- One place to see everything in research and what needs a person.
- Each lane usable on its own.
- The same lifecycle and outcomes across lanes, so a graduated thing means the same everywhere.

## Non-goals

- Merging themes and signals into one object.
- Selling or distributing anything. Internal use only.
- Rebuilding the existing screens, runs or ratification flows.
- Real-time monitoring. The Analysts watch is a daily batch.

## Constraints

- Internal use only.
- Precision first.
- Repo conventions: backend checks `ruff` and `pytest`; frontend `npm run lint`, `npx tsc -b`,
  `npm test`; never delete or weaken a test; PRs target `main`.
- The grounding rule holds for every LLM output.

## Decisions made by the owner

- Themes and signals are different kinds of things.
- Detect's market test lives in the Themes lane.
- A fourth lane, Analysts, with a note backed by a scorecard, rule packs both user-written and
  agent-derived, and a daily watch for coverage and event detection. Lower priority.
- The landing page is new and sits in front of the existing R&D Lab.
- Signals workbench first.

## My calls

- Item kinds share one lifecycle and the three outcomes above.
- The landing page is a read-only aggregation; it holds no state.
- Analysts is designed last because it depends on the shared stage and on data volume decisions.
- A theme can feed a signal (for example theme attention); not in scope until the Signals
  design needs it.

## Left to the builder

How the landing page sits in the app's navigation, tile layout, and how the aggregated view is
queried. I have not checked how `#/rdLab` renders today; the builder should read
`frontend/src/pages/ProcessHub.tsx` and `frontend/src/lib/processes.ts` first.

## Open questions

Carried from the Signals design: search tool and spend ceiling, who owns the training-cutoff
dates, vendor names for analyst revisions, fundamentals and transcripts.
