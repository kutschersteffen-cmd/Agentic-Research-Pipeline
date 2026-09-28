# Process View

The app has 16 functions and 22 screens. The sidebar sorts them by *kind of tool*
(stewardship, research, portfolio, output), which suits someone who already knows
what to open. The team thinks in *processes*, though: "we're onboarding a mandate",
"it's proxy season", "the committee wants the climate review". This document maps
those processes onto the screens. The **Processes** screen (`#/processes/<id>`)
puts the map in the app.

## Principles

1. **A process is a path through existing screens, not a new screen.** Each step
   links into the screen that already does the work. The Processes view only holds
   the order, the handoffs and the live status of each step.
2. **Name the handoff.** Every arrow says what passes to the next step (a resolved
   universe, a ratified taxonomy, decided ballots). If you can't name it, it isn't a
   step.
3. **Show which handoffs are manual.** A dashed arrow means the person re-uploads
   or re-selects something by hand today. Those are the gaps; we show them instead
   of drawing a smooth line over them.
4. **"Done when" is an outcome a committee would accept**, not "the run finished".
5. **Status comes from the run store.** No new state is kept: each step shows the
   latest run of its type and the number of flagged items waiting.

## The processes

| Process | Cadence | Steps | Done when |
|---|---|---|---|
| **Onboard a portfolio** | When a fund or mandate is added | Identity Resolution → Document Discovery → Extraction → Review Queue → Data Library | Every holding resolves to one issuer, with current disclosures and reviewed figures |
| **Climate transition review** | Annual, plus ad hoc before committees | Risk Monitoring (WACI, financed emissions) → Transition Barriers → Transition Plan → Decision Studio → Steward · Selection → Reports | A tiered list of issuers to engage, each with a walk-vs-talk verdict and sector context |
| **Engage and escalate** | Continuous | Risk Monitoring · Alerts → Steward · Monitoring → Engagement → Steward · Drafting → Steward · Tracking (↺) | Every issue has an owner, a next step and a documented escalation path |
| **Proxy season** | Per meeting, peaks March–June | Proxy Voting → Steward · Voting → Steward · Checkpoint → Engagement | Intentions are published, votes cast are checked against policy, and outcomes feed engagement |
| **Client reporting** | Quarterly | Steward · Client program → Client policy → Reporting → Reports | A client report of house activity plus the points where the client's policy differed |
| **Launch a thematic product** | Per product idea | Emerging Themes → Taxonomy Library → Thematic Universe → Review Queue → Decision Studio → Index Construction → Reports | A ratified theme, a reviewed universe and an effective-dated index calibration |
| **Research a strategy** | Per paper or idea | Strategy Replication → Decision Studio → Index Construction → Reports | Tested out of sample, compared with alternatives, and built as an index if it holds |

The step definitions live in `frontend/src/pages/Processes.tsx`: one array to
edit when a process changes.

## Manual handoffs to close, most valuable first

Each of these is a place where a person carries data between screens by hand.
They are listed by how often a process crosses them.

1. **Decision Studio → Steward · Selection / Index Construction.** Tiers and
   scores don't reach coverage tiers or index screens. Two processes end here. Fix:
   export a scored table as an index score snapshot and as a tier proposal that
   Selection shows *proposed*, never applied.
2. **Proxy Voting run → Steward · Voting / Checkpoint.** The stewardship voting stage
   reads its own data, not the ballots decided in Proxy Voting. Fix: have the
   stewardship flow read decided ballots from voting runs.
3. **Document Discovery → Extraction / Transition Plan.** After discovery, the
   universe has to be uploaded again. Fix: a "Send to Extraction" button, the same
   pattern Identity Resolution already uses for Discovery.
4. **Risk Monitoring → Transition Plan / Steward · Monitoring.** Portfolio holdings
   and alerts don't become a universe or triggers. Fix: "Use these holdings as a
   universe" from the selection pane, and alerts as `manual` trigger events.
5. **Checkpoint → Engagement.** `vote_outcome` is already a monitoring trigger type,
   but real vote outcomes don't raise it yet.
6. **Transition Barriers → Transition Plan.** Sector context is read, not joined.
   Fix: show the issuer's sector × jurisdiction barrier cells next to its
   walk-vs-talk verdict.

Also: the Thematic Universe → Extraction handoff sets a single "pending universe"
that the Transition Plan screen picks up too, and it says "sent from another screen"
there. Tag the pending universe with its destination once a second sender exists.

## Deliberately not done

- **No process instances or process state.** A "run of the climate review for Q3"
  object would duplicate what runs, streams and calibrations already record. Add
  one if the team needs to see a process's history as one record.
- **No stepper that locks the order.** Steps are links, and real work loops back
  and skips steps.
