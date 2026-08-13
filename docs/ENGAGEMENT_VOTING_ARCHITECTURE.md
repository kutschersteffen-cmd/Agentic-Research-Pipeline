# Engagement & Voting Architecture

Design spec for a stewardship module: an agentic system that manages
company **engagement** (dialogue with investee companies over ESG/
governance issues) and **proxy voting** (AGM ballot analysis and casting)
on a shared record, with a human sign-off gate at every point that touches
an external party or casts a vote.

This is a design document, not yet implemented. It extends the existing
Agentic Research Pipeline (theme building + data-point extraction, see
[`../README.md`](../README.md)) with a new stewardship layer that reuses
the same precision controls described in
[`METHODOLOGY.md`](METHODOLOGY.md) — schema-first structured output,
programmatic grounding, confidence scoring + human review queue, resumable
batch execution — rather than inventing a parallel set for engagement and
voting.

## Core design principle

One shared state store, human gates at every send/decide/vote point —
nothing autonomous touches an external party or casts a vote without
sign-off. Two workflows (engagement, voting) share one orchestrator and one
record store rather than running as separate systems, because they are not
actually independent: how you voted on a company's say-on-pay resolution
and what you told its IR team in last quarter's engagement call are the
same conversation, and treating them as unrelated data is how stewardship
programs end up voting against a company they're mid-negotiation with, or
citing a commitment in a disclosure report that was never actually made.

## 1. Engagement Record Store (single source of truth)

A structured record per company: issue history, milestone status, contacts,
prior correspondence, escalation stage, and — new in this revision — linked
proposals and vote history for that company. Every agent reads/writes here;
this is what prevents agents working off different pictures of the same
company.

```
EngagementRecord
├── company_id, name, sector, holdings weight
├── contacts: [{ name, role (IR / Chair / Lead Independent Director / ...), email, last_contacted_at }]
├── issues: [{ theme, opened_at, status, severity, source (trigger / analyst-raised) }]
├── correspondence: [{ date, type (letter / call / meeting), summary, doc_ref }]
├── milestone_stage: enum, per-issue                      # see below
├── escalation_stage: enum, per-issue                      # see below
├── commitments: [{ text, made_at, target_date, status, validated_by }]
└── votes: [{ proposal_id, meeting_date, ... }]            # new — see §6

VoteRecord   (new)
├── proposal_id, company_id, meeting_id, meeting_date
├── proposal: { type, sponsor, resolution_text, management_recommendation, source_doc_ref }
├── policy_recommendation: { vote, rationale, policy_rule_id, confidence }
├── engagement_alignment_flag: bool, note                  # see §6.2
├── human_decision: { vote, decided_by, decided_at, override_note }
└── cast_confirmation: { platform, cast_at, confirmation_id }
```

**Milestone stage** and **escalation stage** are kept as configurable
enums rather than hardcoded, since houses run different frameworks. The
spec below assumes an illustrative 6-stage milestone framework and 7-step
escalation ladder (common in stewardship-code-aligned programs) purely to
make the state machine concrete — swap in the house's actual framework at
implementation time:

- **Milestone (illustrative 6-step):** Identified → Contacted → Dialogue
  Opened → Response Received → Commitment Made → Commitment Verified/Closed.
- **Escalation (illustrative 7-step):** (1) Private engagement → (2) Joint
  engagement with other investors → (3) Written escalation to the board →
  (4) Escalation to the Chair / lead independent director → (5) Vote
  against management (director election, say-on-pay, or the specific
  proposal) → (6) File or co-file a shareholder resolution → (7) Public
  statement.

## 2. Orchestrator (controller agent)

A state machine, not a chatbot. Watches the record store, decides which
stage each engagement (and now each proposal/ballot) is in, and dispatches
the right sub-agent. Owns all milestone/escalation/voting-cycle logic
centrally rather than scattering it across sub-agents, for the same reason
the existing pipeline centralizes run/review-queue state in
`backend/arp/orchestration/`: one place to audit, one place to fix a rule.

Two queues feed it:
- **Engagement queue** — triggers from ESG/controversy screening (§5).
- **Proxy queue** — triggers from AGM calendar / new-filing detection
  (§6.3), each carrying a due-by-date driven by the meeting date, since
  voting deadlines (unlike engagement dialogue) are hard and unmovable.

## 3. Sub-agents (engagement side, unchanged)

- **Research Agent** — pulls ESG/controversy feeds, prior engagement
  history, voting record, peer benchmarking, board/IR contact mapping.
  Tools: data provider API, internal CRM, web search. Reuses the existing
  document discovery crawler (`backend/arp/discovery/`) and EDGAR ingestion
  (`backend/arp/ingestion/edgar.py`) for public filings rather than a
  separate fetch path.
- **Drafting Agent** — writes the briefing dossier, outreach letter,
  meeting talking points, and post-meeting summary from notes/transcript.
  Tools: record store, house style templates.
- **Tracking Agent** — logs outcomes, updates milestone status, tags by
  theme, flags stalled/overdue engagements against SLA. Tools: CRM write
  access, calendar.
- **Reporting Agent** — compiles quarterly/annual stats and populates
  disclosure templates (e.g. PDCA-style stewardship reporting). Extended
  in this revision to also aggregate vote statistics (§6.4).

## 4. Human checkpoints (engagement side, unchanged, non-negotiable)

- Dossier accuracy review before research → drafting handoff
- Outreach send authorization (relationship owner signs off)
- Meeting notes validation before they're logged as commitments
- Escalation lever decision (co-file, vote against, public statement)

## 5. Trigger & Detection Layer (engagement side, unchanged)

Continuous background job: screens holdings against controversy/ESG data,
evaluates against the escalation ladder, and raises tasks into the
orchestrator's engagement queue.

---

## 6. Voting module (new)

Three new agents, one new trigger source, and one new checkpoint category.
Deliberately built as an extension of the same record store and
orchestrator rather than a parallel system — a vote decision that
contradicts an open engagement commitment should be *impossible to make
without the orchestrator seeing both records*, not something reconciled
after the fact in a spreadsheet.

### 6.1 Proposal Analysis Agent

Parses each AGM's ballot into structured, per-proposal records.

- **Input:** the proxy statement (DEF 14A in the US; equivalent filings
  elsewhere), sourced via the existing ingestion/discovery layer — the
  README already documents DEF-14A as a supported EDGAR filing type, so
  this agent is a new *consumer* of an existing pipeline, not a new fetch
  path.
- **Method:** reuses the extraction engine's schema-first approach
  (`backend/arp/extraction/`) rather than free-text parsing: a
  `Proposal` schema (type — director election / say-on-pay /
  auditor ratification / shareholder resolution / M&A / other; sponsor;
  resolution text; management's recommendation; relevant supporting data —
  e.g. CEO pay ratio for a say-on-pay item) is extracted per ballot item,
  with the same Extractor/Verifier adversarial pass and programmatic
  grounding check on every quoted figure or resolution clause used
  elsewhere in the system. A proposal whose extraction confidence is low,
  or whose supporting citation fails the grounding check, routes to the
  review queue instead of silently reaching the Policy Application Agent.
- **Output:** one `Proposal` record per ballot item, linked to
  `company_id` and `meeting_id`.

### 6.2 Policy Application Agent

Applies house voting policy to each extracted proposal and produces a
recommendation — not a vote. Casting a vote is a separate, explicitly
human-gated step (§6.5).

- **Method:** deterministic rule lookup first (policy documents encode
  most routine cases — e.g. "vote against auditor ratification if
  non-audit fees exceed 50% of audit fees" — as checkable rules, evaluated
  in code against extracted data, exactly the way the existing revenue/
  CapEx exposure cascade in `backend/arp/research/` prefers a hard
  disclosed number over an LLM judgment wherever one exists). Proposals
  that don't resolve deterministically (contested director elections,
  novel shareholder resolutions, judgment calls where policy language is
  ambiguous) go to an LLM judgment pass with mandatory cited rationale,
  same schema-first/grounded pattern as the rest of the system.
- **Engagement-alignment cross-check (the reason this lives next to
  engagement, not in a standalone proxy-voting tool):** before finalizing
  a recommendation, the agent queries the company's `EngagementRecord` for
  open issues/commitments matching the proposal's theme. A recommendation
  that would vote *for* management on a topic under active escalation
  (or *against* a resolution the fund itself co-filed) is flagged
  `engagement_alignment_flag: true` with a note, and is **never**
  auto-approved regardless of confidence — it always routes to a human,
  even if the underlying policy rule was deterministic.
- **Output:** `policy_recommendation` on the `VoteRecord`, plus the
  alignment flag.

### 6.3 Trigger source: AGM calendar / new-filing detection

Extends §5's detection layer rather than duplicating it: the same
document-discovery crawler that watches for new sustainability/annual
reports also watches for new DEF-14A-type filings per company, and an AGM
calendar feed (meeting dates, submission deadlines) raises proxy-queue
tasks with a due-by-date. Proxy season means thousands of these arrive in
a compressed window — the existing pipeline's resumable, per-company
checkpointed batch execution (`backend/arp/orchestration/batch_runner.py`)
is the same infrastructure this needs, not a new one, since the failure
mode ("partial completion at 4,000-item scale is normal") is identical to
what the research pipeline was already built for.

### 6.4 Ballot Casting Agent

Executes an authorized vote and closes the loop.

- **Input:** a `VoteRecord` with a human-approved `human_decision` (§6.5).
- **Method:** formats the vote instruction for the target platform
  (custodian ballot system / proxy voting platform, e.g. an ISS or Glass
  Lewis voting interface, or direct custodian instruction — the specific
  integration target is a house/infrastructure decision, not an
  architectural one) and transmits it. On confirmation, writes
  `cast_confirmation` back to the record; on failure/rejection, raises
  back into the orchestrator's proxy queue rather than silently retrying
  or dropping it.
- **Never invoked directly from a Policy Application Agent
  recommendation** — only from an approved `human_decision`. This agent
  has no read access to "recommendation," only to "decision," so a bug
  upstream cannot result in an unauthorized vote by construction, not just
  by convention.

### 6.5 Human checkpoints (voting side, non-negotiable)

- **Vote decision authorization** — every recommendation is reviewed and
  either approved or overridden by the relationship owner before it becomes
  a `human_decision`. No confidence threshold skips this step; unlike the
  engagement side (where routine drafting can proceed to a review gate),
  every single ballot item requires an explicit decision, because casting
  is irreversible once submitted and deadline-bound.
- **Engagement-alignment conflicts** — any `engagement_alignment_flag`
  forces a named decision-maker (not just "the reviewer on duty") to either
  proceed and document why, or change the vote to match the engagement
  stance.
- **Escalation-triggered votes** — a vote against management that was
  itself the *chosen escalation lever* (step 5 of the ladder in §1) is
  cross-signed: both the relationship owner and whoever made the original
  escalation-lever decision (§4's last bullet) confirm, since this is the
  point where engagement and voting are the same decision wearing two
  hats.

### 6.6 Reporting Agent (extended)

Adds vote-statistics aggregation to its existing quarterly/annual
compilation: votes cast for/against/abstain by category, override rate
(human decision vs. policy recommendation), alignment-flag resolution
outcomes, and — where a stewardship code requires it (e.g. GPIF-style PDCA
reporting) — the explicit narrative link between an engagement's
escalation stage and any vote cast as a result of it, since regulators and
codes increasingly expect that link to be shown, not just both figures
reported separately.

---

## 7. Combined data flow

```
                    ┌─────────────────────────────────────────────┐
                    │         Engagement Record Store              │
                    │   (per-company: issues, milestones,          │
                    │    escalation stage, commitments, votes)      │
                    └───────────────┬───────────────────────────────┘
                                     │  read/write, all agents
                    ┌────────────────▼────────────────┐
                    │           Orchestrator            │
                    │  (state machine; owns milestone/  │
                    │   escalation/voting-cycle logic)  │
                    └──┬──────────────────────────┬──────┘
                        │ engagement queue          │ proxy queue
        ┌───────────────▼──────────────┐  ┌─────────▼────────────────┐
        │ Trigger: ESG/controversy      │  │ Trigger: AGM calendar /   │
        │ screen vs. escalation ladder  │  │ new DEF-14A-type filing   │
        └───────────────┬──────────────┘  └─────────┬────────────────┘
                        │                             │
              Research Agent                Proposal Analysis Agent
                        │                             │
              Human: dossier review          (grounded extraction,
                        │                      low-confidence → review queue)
              Drafting Agent                          │
                        │                    Policy Application Agent
              Human: send authorization        (+ engagement-alignment
                        │                        cross-check vs. record store)
                    Outreach                            │
                        │                    Human: vote decision
                    Meeting                    (mandatory every item;
                        │                       cross-signed if
              Drafting Agent (summary)          escalation-linked)
                        │                             │
              Human: notes validation          Ballot Casting Agent
                        │                             │
              Tracking Agent (log) ──────────► writes VoteRecord back to
                        │                        Engagement Record Store
              Orchestrator (milestone/
               escalation check)
                        │
                  [loop or escalate] ◄──────── engagement_alignment_flag
                        │                        can re-open an engagement
              Reporting Agent (periodic: engagement stats + vote stats,
                                linked narrative where required)
```

## 8. What's deliberately left as an implementation/house decision

Kept out of this spec on purpose, since answering them now would bake in
assumptions this document shouldn't own:

- Exact milestone-stage and escalation-ladder taxonomy (the framework in
  §1 is illustrative; use the house's actual stewardship framework).
- Source of truth for voting policy (a maintained rules document vs. a
  third-party proxy advisor's policy vs. a blend) and how policy updates
  propagate to the deterministic rule set in §6.2.
- Ballot-casting integration target (custodian API, ISS/Glass Lewis
  platform, or manual instruction with agent-prepared paperwork) — affects
  only the Ballot Casting Agent's tool integration, not the state machine
  around it.
- Non-US filing equivalents to DEF-14A for non-US holdings, and whatever
  document-discovery adjustments that requires per market.

## 9. Why this extends the existing pipeline instead of a new system

The research pipeline in this repo already solved the precision problems
this module runs into again: forced structured output instead of free-text
parsing, grounding checked in code rather than trusted from the model,
confidence-gated human review instead of a single-pass judgment, and
checkpointed batch execution for proxy-season-scale volume. Building the
voting module as new consumers of `backend/arp/ingestion/`,
`backend/arp/extraction/`, and `backend/arp/orchestration/` — rather than
a second implementation of the same controls — is the direct reason this
document proposes an extension rather than a standalone service.
