# Engagement & Voting Architecture

Architecture and implementation reference for the stewardship module: an
agentic system that manages company **engagement** (dialogue with investee
companies over ESG/governance issues) and **proxy voting** (AGM ballot
analysis and casting) on a shared record, with a human sign-off gate at
every point that touches an external party or casts a vote.

**Status: implemented (v1), backend only.** This started as a design-only
spec; the state machine, agents, storage, API, and CLI described below now
exist under `backend/arp/engagement/` and `backend/arp/voting/` (see the
per-section file references and §10). No frontend UI has been built yet —
everything is reachable via the CLI (`arp engagement ...` / `arp voting
...`) and the API (`/api/engagement/...` / `/api/voting/...`) described
below. It extends the existing Agentic Research Pipeline (theme building +
data-point extraction, see [`../README.md`](../README.md)) with a new
stewardship layer that reuses the same precision controls described in
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

Implemented as `EngagementRecord`/`EngagementIssue` in
`backend/arp/schemas/engagement.py`, persisted by
`backend/arp/storage/engagement_store.py`: a `record.json` per company
(current state) plus an append-only `events.jsonl` audit trail per company
(every mutation — contact added, issue opened, milestone/escalation
changed, correspondence/commitment logged — is a log entry, never
overwritten), the same "append, don't mutate, for anything audit-relevant"
philosophy `RunStore`'s review-decision log uses elsewhere in this
codebase. `VoteRecord` lives in `backend/arp/schemas/voting.py` — see §6.

**Milestone stage** and **escalation stage** are kept as configurable
enums rather than hardcoded, since houses run different frameworks. The
spec below assumes an illustrative 6-stage milestone framework and 7-step
escalation ladder (common in stewardship-code-aligned programs) purely to
make the state machine concrete — swap in the house's actual framework at
implementation time (edit `MilestoneStage`/`EscalationStage` in
`backend/arp/schemas/engagement.py`; nothing else hardcodes their names):

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

Implemented in `backend/arp/engagement/orchestrator.py` as a pure function,
`decide_next_action(issue, sla_days)`, rather than a long-running daemon: it
maps an issue's current milestone stage to the next dispatch action
(`DISPATCH_RESEARCH`, `AWAIT_RESPONSE`, `DISPATCH_DRAFTING_SUMMARY`,
`AWAIT_COMMITMENT_TARGET_DATE`, or, if the issue has had no recorded
activity for `engagement_sla_days` (`Settings.engagement_sla_days`,
default 45), `FLAG_FOR_ESCALATION_DECISION` — overriding whatever the
milestone stage would otherwise dispatch. Callable directly (`arp
engagement issue-next-action`, `GET
/api/engagement/records/{company_id}/issues/{issue_id}/next-action`) or
wired into a scheduler/worker loop that dispatches accordingly — no such
loop is included in v1, since which stages should run unattended vs. be
pulled by an analyst is a house workflow decision, not an architectural
one. Deciding is deliberately separate from *acting*: the function never
calls a sub-agent itself, so plugging a scheduler in later doesn't require
touching the state-machine logic.

Two queues feed it:
- **Engagement queue** — triggers from ESG/controversy screening (§5).
- **Proxy queue** — triggers from AGM calendar / new-filing detection
  (§6.3), each carrying a due-by-date driven by the meeting date, since
  voting deadlines (unlike engagement dialogue) are hard and unmovable.
  (v1 note: the proxy queue's *dispatch loop* isn't built — see §6.3 — a
  voting run is triggered explicitly today, `arp voting run` / `POST
  /api/voting/runs`, against a supplied company universe.)

## 3. Sub-agents (engagement side)

- **Research Agent** (`backend/arp/engagement/research_agent.py`) — fetches
  a company's available disclosures via the existing document registry
  (`backend/arp/ingestion/`, so EDGAR + local files + discovery-crawled
  documents all feed it identically), prefilters evidence chunks by the
  issue's theme, and drafts a `ResearchDossier` (summary, controversy
  context, peer-benchmark notes, engagement-history recap, recommended
  contacts) with grounded citations via the same `arp.grounding` check the
  rest of the codebase uses. Called via `arp engagement dossier-draft` or
  `POST .../issues/{issue_id}/dossier`. A real ESG/controversy-feed data
  provider isn't wired in (see §5/§8) — the dossier's own-disclosure
  research is real and grounded; controversy context beyond what's in the
  company's own documents currently comes from the trigger signal that
  opened the issue, not a live feed lookup inside this agent.
- **Drafting Agent** (`backend/arp/engagement/drafting_agent.py`) — three
  schema-first LLM calls (`draft_outreach_letter`, `draft_talking_points`,
  `draft_meeting_summary`), each reusing the dossier's already-grounded
  citations rather than re-deriving claims. Tools: the dossier, an
  optional house-style-notes string appended to the outreach-letter
  prompt.
- **Tracking Agent** (`backend/arp/engagement/tracking_agent.py`) —
  deliberately has no LLM calls: mechanical bookkeeping functions
  (`log_outreach_sent`, `log_meeting_summary_validated`,
  `log_commitment_verified`, ...) that write to the record store and
  advance `milestone_stage`, kept separate from Research/Drafting so a
  prompt bug can never silently corrupt milestone state. `tags`
  (theme-tagging) and SLA-stall flagging live in
  `backend/arp/engagement/triggers.py`'s `scan_for_stalled_issues` (§5),
  which calls the same `is_stalled` check the orchestrator uses.
- **Reporting Agent** (`backend/arp/engagement/reporting_agent.py`) — pure
  aggregation, no LLM calls, over `EngagementStore.list_all()` and a
  voting run's results: `compile_engagement_stats`, `compile_vote_stats`,
  and `escalation_linked_votes` (the explicit engagement↔vote narrative
  link, §6.6), composed into `compile_report`. Called via `arp engagement
  report` / `GET /api/engagement/report`.

## 4. Human checkpoints (engagement side, non-negotiable)

- **Dossier accuracy review before research → drafting handoff** — the
  dossier is written to disk/returned by the API, not auto-applied;
  nothing in this module hands a dossier straight to the Drafting Agent
  without a human passing it along explicitly.
- **Outreach send authorization (relationship owner signs off)** —
  `log_outreach_sent` (`tracking_agent.py`) only records that outreach
  went out and advances the milestone; it has no code path that sends
  anything itself, so "sending" is inherently whatever the human/relationship
  owner does outside this system, logged after the fact.
- **Meeting notes validation before they're logged as commitments** —
  enforced structurally: `log_meeting_summary_validated` is the only
  function that writes `Commitment`s from a drafted summary, and it takes
  a `validated_by` argument, i.e. it's only ever called after a human has
  looked at the draft.
- **Escalation lever decision** — enforced structurally:
  `EngagementStore.set_escalation_stage` is the *only* code path that can
  move `escalation_stage`, requires a `decided_by` argument, and is never
  called by the orchestrator itself (see `orchestrator.py`'s docstring on
  `decide_next_action`). Reachable via `arp engagement issue-escalate` /
  `POST .../issues/{issue_id}/escalate`.

## 5. Trigger & Detection Layer (engagement side)

Implemented in `backend/arp/engagement/triggers.py`:
- `run_trigger_screen(companies, source, store)` screens a company universe
  through a `ControversySource` (an abstract interface — `StaticControversySource`
  is the only implementation today, taking a caller-supplied signal list; a
  real MSCI/Sustainalytics/RepRisk-style feed integration is a house
  decision, not an architectural one, see §8) and opens a new
  `EngagementIssue` for every signal without an already-open issue on the
  same company/theme (deduped so a recurring feed can't spawn duplicates).
- `scan_for_stalled_issues(store, sla_days)` is the SLA half: no external
  feed needed, just a sweep over every open issue using the same
  `is_stalled` check the orchestrator uses, marking newly-stalled issues
  and raising a trigger event for each.

Both are triggered on demand today (`arp engagement trigger-scan`, `POST
/api/engagement/trigger-scan`) rather than by a continuous background job
— wiring either into a scheduler (the existing `DiscoveryScheduler` in
`backend/arp/discovery/scheduler.py` is a reasonable model to copy) is
future work, not a v1 architectural gap.

---

## 6. Voting module (new)

Three new agents, one new trigger source, and one new checkpoint category.
Deliberately built as an extension of the same record store and
orchestrator rather than a parallel system — a vote decision that
contradicts an open engagement commitment should be *impossible to make
without the orchestrator seeing both records*, not something reconciled
after the fact in a spreadsheet.

### 6.1 Proposal Analysis Agent

Parses each AGM's ballot into structured, per-proposal records. Implemented
in `backend/arp/voting/proposal_agent.py` + the per-company driver in
`backend/arp/voting/pipeline.py::_process_company`.

- **Input:** the proxy statement (DEF 14A in the US; equivalent filings
  elsewhere), sourced via the existing ingestion/discovery layer — EDGAR
  ingestion (`backend/arp/ingestion/edgar.py`) already fetches DEF-14A
  filings for the existing research pipeline, so this agent is a new
  *consumer* of an existing pipeline, not a new fetch path.
- **Method:** one schema-first `complete_structured` call
  (`extract_proposals`) returns every ballot item as a `ProposalDraft`
  (type, sponsor, resolution text, management's recommendation, and any
  explicitly disclosed `supporting_data` figures the Policy Application
  Agent's deterministic rules key off — e.g. `non_audit_fee_ratio`). Every
  citation is then checked with the same programmatic grounding function
  (`arp.grounding.ground_citations`) used everywhere else in this
  codebase. Note: this is schema-first + grounded, like the rest of the
  system, but it is a **single extraction pass**, not the extraction
  engine's two-pass Extractor/Verifier adversarial check — a ballot is
  inherently a *list*-extraction task (identify N proposals) rather than
  the single-value-per-field task the Verifier pattern was built for; a
  second adversarial pass here is a reasonable future hardening step, not
  something already built.
- **Output:** one `Proposal` per ballot item, linked to `company_id` and
  `meeting_id` (a `mtg_...` ID minted per pipeline run, since v1 has no AGM
  calendar to resolve a real meeting identity against — see §6.3).

### 6.2 Policy Application Agent

Applies house voting policy to each extracted proposal and produces a
recommendation — not a vote. Casting a vote is a separate, explicitly
human-gated step (§6.5). Implemented in `backend/arp/voting/policy_agent.py`.

- **Method:** deterministic rule lookup first — `DEFAULT_POLICY_RULES` is
  an ordered list of small Python predicates (`PolicyRule = Callable[[Proposal],
  VotePosition | None]`), e.g. `rule_auditor_independence` (against
  auditor ratification when `non_audit_fee_ratio > 0.5`) and
  `rule_egregious_pay_ratio` (against say-on-pay when a disclosed CEO pay
  ratio is clearly extreme) — evaluated in code against the proposal's
  extracted `supporting_data`, the same "a hard disclosed number is never
  second-guessed by a categorical LLM judgment" discipline the existing
  revenue/CapEx exposure cascade (`backend/arp/research/revenue_exposure/`)
  uses. These illustrative rules are a starting point, not house policy —
  see §8. The first rule to return non-`None` wins; everything else
  (contested director elections, novel shareholder resolutions, anything
  no rule resolves) falls through to one schema-first LLM judgment call
  (`PolicyJudgmentDraft`) with mandatory cited rationale.
- **Engagement-alignment cross-check (the reason this lives next to
  engagement, not in a standalone proxy-voting tool):** `check_engagement_alignment`
  looks up the company's `EngagementRecord` and flags a conflict in two
  cases — (1) the recommendation votes *for* management on a theme
  (director elections → `board_governance`, say-on-pay →
  `executive_compensation`, auditor ratification → `audit_independence`;
  this mapping is an illustrative default, easily extended) that has an
  issue escalated to `VOTE_AGAINST_MANAGEMENT` or beyond, or (2) the
  recommendation votes anything other than *for* on a shareholder
  resolution that appears to be the fund's own (`Settings.fund_name`
  matched against the proposal's sponsor). Either sets
  `engagement_alignment_flag: true` with a human-readable note.
- **Output:** `PolicyRecommendation` (`vote`, `rationale`, `policy_rule_id`
  — `None` means an LLM judgment call was made, `confidence`, the
  alignment flag/note) attached to the `VoteRecord`. In v1, *every*
  proposal is queued for mandatory human review regardless of confidence
  or whether the alignment flag fired (see §6.5) — a stricter guarantee
  than "flagged items always route to a human," since nothing here is
  auto-approved at all.

### 6.3 Trigger source: AGM calendar / new-filing detection

**Not yet implemented — the one real gap in v1.** The design intent still
stands: extend §5's detection layer so the same document-discovery
crawler that watches for new sustainability/annual reports also watches
for new DEF-14A-type filings per company, and an AGM calendar feed
(meeting dates, submission deadlines) raises proxy-queue tasks with a
due-by-date. What exists today instead: `arp voting run` / `POST
/api/voting/runs` takes an explicit company universe and fetches whatever
DEF-14A-type documents `DocumentSourceRegistry` currently has for each
company (same registry as everything else — EDGAR + local files +
discovery-crawled documents) — a company with no proxy statement available
yet simply produces an empty ballot (§6.1), the same "no evidence, plainly
reported, not an error" pattern `no_evidence_field` uses in the extraction
engine. Proxy season's thousands-in-a-compressed-window scale is already
handled, though: `execute_voting_run` (`backend/arp/voting/pipeline.py`)
runs through the same resumable, per-company checkpointed
`run_batch`/`JobManager` infrastructure
(`backend/arp/orchestration/batch_runner.py`) every other pipeline uses —
adding the calendar/new-filing trigger is a matter of what raises tasks
into that run, not new execution infrastructure.

### 6.4 Ballot Casting Agent

Executes an authorized vote and closes the loop. Implemented in
`backend/arp/voting/ballot_casting.py`.

- **Input:** a `VoteRecord` with a human-approved `human_decision` (§6.5).
- **Method:** `BallotPlatform` is an abstract interface (`cast(vote_record)
  -> CastConfirmation`); `ManualInstructionBallotPlatform` is the only
  implementation in v1 — no custodian/ISS/Glass-Lewis integration is wired
  up (a house infrastructure decision, see §8), so it writes a
  human-readable voting-instruction text file per vote instead of
  transmitting anywhere, exercising the real contract today against
  whatever real platform gets swapped in later. `cast_vote(platform,
  vote_record)` is idempotent (a vote_record that already has a
  `cast_confirmation` is returned unchanged) and resumable at the run
  level: `cast_approved_votes` tracks already-cast item keys in
  `cast_confirmations.jsonl` and skips them on rerun, the same
  checkpoint-and-skip pattern `read_done_keys` gives every other batch
  pipeline.
- **Never invoked directly from a Policy Application Agent
  recommendation** — only from an approved `human_decision`. `cast_vote`
  raises `CastVoteError` outright if `vote_record.human_decision` is
  `None`, so an unauthorized vote can't reach a platform integration
  regardless of what upstream code does, by construction rather than
  convention.

### 6.5 Human checkpoints (voting side, non-negotiable)

- **Vote decision authorization** — every recommendation is reviewed and
  either approved or overridden by the relationship owner before it becomes
  a `human_decision`. No confidence threshold skips this step; unlike the
  engagement side (where routine drafting can proceed to a review gate),
  every single ballot item requires an explicit decision, because casting
  is irreversible once submitted and deadline-bound. Implemented as
  `execute_voting_run` unconditionally calling `queue_for_review` for
  every `VoteRecord` it produces, regardless of confidence or the
  alignment flag — reusing the extraction engine's review-queue/decision
  machinery (`backend/arp/orchestration/review_queue.py`) unchanged, keyed
  `"{company_id}:{proposal_number}"`. `arp voting review` / `POST
  /api/voting/runs/{run_id}/review` records `approve` / `edit` (with the
  human's chosen `vote`) / `reject` (declines to cast this item at all).
- **Engagement-alignment conflicts** — any `engagement_alignment_flag`
  forces a named decision-maker (not just "the reviewer on duty") to either
  proceed and document why, or change the vote to match the engagement
  stance. Implemented as a required co-sign: `cast_vote` raises
  `CastVoteError` if `policy_recommendation.engagement_alignment_flag` is
  set and `human_decision.co_signed_by` is empty — the review endpoint/CLI
  accept a `co_signed_by` alongside the vote decision precisely so this
  can be supplied.
- **Escalation-triggered votes** — a vote against management that was
  itself the *chosen escalation lever* (step 5 of the ladder in §1) is,
  by design intent, meant to be cross-signed the same way: both the
  relationship owner and whoever made the original escalation-lever
  decision (§4's last bullet) confirm, since this is the point where
  engagement and voting are the same decision wearing two hats. **Not yet
  enforced in code as its own case**: `check_engagement_alignment` only
  flags a *conflict* (voting FOR despite an active escalation) — a vote
  that correctly votes AGAINST, consistent with an already-chosen
  escalation lever, doesn't currently set the alignment flag and so
  doesn't currently force a co-sign. Extending the check to flag
  escalation-*consistent* AGAINST votes too (not just escalation-
  *inconsistent* FOR votes) would close this gap; today it's a manual
  house process rather than a structural guarantee.

### 6.6 Reporting Agent (extended)

Adds vote-statistics aggregation to its existing quarterly/annual
compilation, implemented as `compile_vote_stats` and
`escalation_linked_votes` in `backend/arp/engagement/reporting_agent.py`
(§3): votes cast for/against/abstain by category, override rate (human
decision vs. policy recommendation), alignment-flag counts, and — where a
stewardship code requires it (e.g. GPIF-style PDCA reporting) — the
explicit narrative link between an engagement's escalation stage and any
vote cast for that company, since regulators and codes increasingly expect
that link to be shown, not just both figures reported separately. `arp
engagement report --run-id <voting_run_id>` / `GET
/api/engagement/report?run_id=...` compiles both halves together.

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
        │ (§5 -- implemented, on demand)│  │ (§6.3 -- NOT implemented; │
        │                               │  │  run explicitly instead) │
        └───────────────┬──────────────┘  └─────────┬────────────────┘
                        │                             │
              Research Agent                Proposal Analysis Agent
                        │                             │
              Human: dossier review          (grounded extraction,
                        │                      EVERY proposal ->
              Drafting Agent                   review queue, always)
                        │                             │
              Human: send authorization        Policy Application Agent
                        │                        (+ engagement-alignment
                    Outreach                      cross-check vs. record store)
                        │                             │
                    Meeting                    Human: vote decision
                        │                       (mandatory every item;
              Drafting Agent (summary)          co-sign required if
                        │                        engagement_alignment_flag)
              Human: notes validation                  │
                        │                    Ballot Casting Agent
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

Every box left of/including "Reporting Agent" is implemented (§10 has the
full file index); the proxy-queue trigger box is the one exception,
explicitly called out inline above and in §6.3.

## 8. What's deliberately left as an implementation/house decision

Kept out of this spec on purpose, since answering them now would bake in
assumptions this document shouldn't own. Where v1 ships a pluggable
interface with a stub implementation so the rest of the system can be
exercised for real today, that's noted.

- Exact milestone-stage and escalation-ladder taxonomy (the framework in
  §1 is illustrative; edit `MilestoneStage`/`EscalationStage` in
  `backend/arp/schemas/engagement.py` for the house's actual stewardship
  framework).
- Source of truth for voting policy (a maintained rules document vs. a
  third-party proxy advisor's policy vs. a blend) and how policy updates
  propagate to the deterministic rule set in §6.2. **Stubbed:**
  `DEFAULT_POLICY_RULES` in `backend/arp/voting/policy_agent.py` is a
  small illustrative rule set (auditor-fee-ratio, egregious-pay-ratio) —
  real house policy replaces or extends this list; `apply_policy` accepts
  any `rules: list[PolicyRule]`, so this doesn't require touching the
  pipeline.
- Real ESG/controversy data-provider integration (MSCI, Sustainalytics,
  RepRisk, or similar) for the engagement trigger layer. **Stubbed:**
  `ControversySource` (§5, `backend/arp/engagement/triggers.py`) is an
  abstract interface; `StaticControversySource` (caller-supplied signals)
  is the only implementation.
- Ballot-casting integration target (custodian API, ISS/Glass Lewis
  platform, or manual instruction with agent-prepared paperwork) — affects
  only the Ballot Casting Agent's tool integration, not the state machine
  around it. **Stubbed:** `BallotPlatform` (§6.4,
  `backend/arp/voting/ballot_casting.py`) is an abstract interface;
  `ManualInstructionBallotPlatform` (writes a text file per vote) is the
  only implementation.
- Non-US filing equivalents to DEF-14A for non-US holdings, and whatever
  document-discovery adjustments that requires per market.
- The AGM calendar / new-filing trigger loop itself (§6.3) — genuinely not
  built yet, not a stub with a swappable interface like the three items
  above.

## 9. Why this extends the existing pipeline instead of a new system

The research pipeline in this repo already solved the precision problems
this module runs into again: forced structured output instead of free-text
parsing, grounding checked in code rather than trusted from the model,
confidence-gated human review instead of a single-pass judgment, and
checkpointed batch execution for proxy-season-scale volume. Building the
voting module as new consumers of `backend/arp/ingestion/`,
`backend/arp/extraction/` (its grounding/chunking utilities specifically),
and `backend/arp/orchestration/` — rather than a second implementation of
the same controls — is the direct reason this document proposes an
extension rather than a standalone service. §10 shows exactly which files
reuse what.

## 10. Implementation index

```
backend/arp/schemas/engagement.py       EngagementRecord, EngagementIssue, MilestoneStage,
                                         EscalationStage, Contact, Commitment, dossier/drafting
                                         output schemas
backend/arp/schemas/voting.py           Proposal, VotePosition, PolicyRecommendation,
                                         HumanVoteDecision, CastConfirmation, VoteRecord
backend/arp/storage/engagement_store.py EngagementStore -- record.json + append-only events.jsonl
                                         per company

backend/arp/engagement/
  orchestrator.py     decide_next_action, is_stalled, milestone/escalation ordering (§2)
  triggers.py          ControversySource/StaticControversySource, run_trigger_screen,
                        scan_for_stalled_issues (§5)
  research_agent.py    Research Agent: research_company_issue, draft_dossier (§3)
  drafting_agent.py    Drafting Agent: draft_outreach_letter, draft_talking_points,
                        draft_meeting_summary (§3)
  tracking_agent.py    Tracking Agent: log_outreach_sent, log_meeting_summary_validated,
                        log_commitment_verified (§3)
  reporting_agent.py   Reporting Agent: compile_report and friends (§3, §6.6)

backend/arp/voting/
  proposal_agent.py    Proposal Analysis Agent: extract_proposals (§6.1)
  policy_agent.py       Policy Application Agent: apply_policy, DEFAULT_POLICY_RULES,
                         check_engagement_alignment (§6.2)
  ballot_casting.py     Ballot Casting Agent: BallotPlatform, ManualInstructionBallotPlatform,
                         cast_vote (§6.4)
  pipeline.py            run_voting / execute_voting_run (batch orchestration, §6.3),
                          cast_approved_votes (review-decision -> cast, §6.5)

backend/arp/api/routers/engagement.py   /api/engagement/... (records, issues, escalation,
                                         trigger-scan, dossier/outreach/talking-points/
                                         meeting-summary, tracking log endpoints, report)
backend/arp/api/routers/voting.py       /api/voting/... (runs, ballots, review-queue, review,
                                         cast)
backend/arp/cli.py                       `arp engagement ...` / `arp voting ...` (see --help)

backend/tests/test_engagement_store.py
backend/tests/test_engagement_orchestrator.py
backend/tests/test_engagement_triggers.py
backend/tests/test_engagement_tracking_agent.py
backend/tests/test_engagement_research_agent.py
backend/tests/test_policy_agent.py
backend/tests/test_voting_pipeline.py
```
