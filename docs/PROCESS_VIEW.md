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

1. ~~**Decision Studio → Steward · Selection / Index Construction.**~~ **Closed.**
   A ratified framework's result can be *published*: frozen, signed by a named
   person, with each row matched to an issuer by its id column (`Company_Id`,
   `issuer_id`, …). Consumers read the latest publication per framework as
   ordinary company fields, `decision.<framework_id>.tier` / `.score` / `.rank`:
   - **Steward · Selection**: the fields reach the coverage rules as
     `issuer.decision.<framework_id>.*`. A person adds a column that uses them,
     and tier changes are confirmed at stage 5 as before. The studio lists each
     publication and how many issuers in scope it matched.
   - **Index Construction**: pick a publication under *Start from a preset*. Its
     fields join the universe by company id and become pickable in every rule.
     A candidate without a match lacks the field, so the rule's missing-value
     policy decides. A review dated before the publication is refused, and the
     review records which publications it read.
   Strategy research stays manual here: its rows are strategies, not companies.
2. ~~**Proxy Voting run → Steward · Voting / Checkpoint.**~~ **Closed.** The
   stewardship flow reads every Proxy Voting run (`arp/stewardship/voting_feed.py`):
   - **Steward · Voting** shows the decided ballots next to the policy's
     recommendation, plus live counts (items decided, votes against management).
   - **Steward · Checkpoint** lists every vote decided against the policy's
     recommendation, with the decider, co-signer and reason, for review.
   - Per issuer, the counts become company fields (`vote.decided`,
     `vote.against_management`, `vote.overrode_policy`, `vote.last_meeting_date`),
     so any stewardship rule can use them.
   The expected-vote metrics on the synthetic meeting sample stay as they were.
3. ~~**Document Discovery → Extraction / Transition Plan.**~~ **Closed.** Once a
   discovery run starts, Document Discovery offers "Extraction →" and
   "Transition Plan →" with the same universe, so nothing is uploaded twice.
4. ~~**Risk Monitoring → Transition Plan / Steward · Monitoring.**~~ **Closed.**
   - Under the portfolio selection, "Use the companies held in … in:" saves the
     companies held in the selected portfolios (as of the selected date) as a
     universe and opens Transition Plan, Extraction or Document Discovery with
     it. Holdings that don't resolve to a company are left out and counted.
   - Open Risk Monitoring alerts (open, acknowledged or escalated) become
     company fields, `alert.open_news_controversy` and
     `alert.open_threshold_breach`. Two new default house monitoring rules
     raise a stewardship trigger from them, and Steward · Monitoring opens the
     engagement. Alerts match stewardship issuers by company id.
5. ~~**Checkpoint → Engagement.**~~ **Closed with gap #2.** A new house monitoring
   rule (`vote_against_management`) raises a `vote_outcome` trigger when we voted
   against management; Steward · Monitoring opens the engagement from it. The
   trigger reads *our* vote, not the meeting result: vote results (support
   levels) have no feed yet. An installation that already saved its own
   monitoring rules needs the row added in the rule editor; the default applies
   only where no version was saved.
6. **Transition Barriers → Transition Plan.** Sector context is read, not joined.
   Fix: show the issuer's sector × jurisdiction barrier cells next to its
   walk-vs-talk verdict.

The universe handoff between screens is one piece of state in `App.tsx` that
records its sender and its destination, so only the addressed screen picks it
up and names where it came from.

## Deliberately not done

- **No process instances or process state.** A "run of the climate review for Q3"
  object would duplicate what runs, streams and calibrations already record. Add
  one if the team needs to see a process's history as one record.
- **No stepper that locks the order.** Steps are links, and real work loops back
  and skips steps.
