# Stewardship Agentic Workflow — Plan

How the *Stewardship operating model* (house truth + client overlay, eight
stages) lands on the v1 engagement/voting module described in
[`ENGAGEMENT_VOTING_ARCHITECTURE.md`](ENGAGEMENT_VOTING_ARCHITECTURE.md).
Stages 1–6 are mostly built; stages 7–8 (client overlay) are new.

## Decisions

| # | Question | Decision |
|---|---|---|
| 1 | Escalation keyed to resolution (operating model) or issue (v1)? | **Per issue.** Ladder steps 1–4 happen before any resolution exists. A vote against management is ladder step 5 and links *to* the issue. |
| 2 | Where are Client Vote Instructions generated? | **Stage 7 only.** The operating model's stage 4 bullet that generates them is dropped. Stages 1–6 never read a client entity, so onboarding a client touches stages 7–8 only. |
| 3 | Is proxy pass-through (PTV) in scope? | **Yes.** See §4. |
| 4 | What is CLTI? | The transition plan assessment already in `backend/arp/transition_plan/` (64 indicators, Colesanti Senni et al. 2024). See §3. |

## 1. Entity mapping (operating model → code)

| Operating model | Code today | Change |
|---|---|---|
| Issuer | `company_id` (+ `EngagementRecord.name/sector`) | none |
| Issuer.clti_score / nature_score | `TransitionPlanAssessmentRecord`, TNFD pipeline | read the latest by `company_id` (§3) |
| Engagement Record | `EngagementIssue` (inside the per-company `EngagementRecord`) | none (naming only) |
| House Voting Decision | `VoteRecord` (proposal + recommendation + `human_decision`) | add `issue_id: str \| None` (stage 4 link) |
| Escalation Log | `EngagementIssue.escalation_stage/escalation_history` | none (decision 1) |
| Client / Asset Owner | — | **new** `Client` |
| Client Policy Profile | — | **new** `ClientPolicyProfile` |
| Client Engagement View | — | computed at read time, **not stored** |
| Client Vote Instruction | — | **new**, sparse rows |
| Portfolio / Mandate | `Portfolio` (client only as a free-text tag) | add `client_id`, `vehicle_type` |
| Holding | `Holding` (→ `SecurityRef.company_id`) | none |
| Disclosure / Report | `reporting_agent.compile_report` (house-level) | per-client render + `delivery_log` |

## 2. New schemas (client overlay)

```
Client                  client_id, name
ClientPolicyProfile     client_id (1:1), priority_weights {region/sector/theme -> float},
                        voting_policy_deltas: list[rule ref], voting_delegation_mode
                        (house_voted | ptv_pass_through), reporting_template_ref,
                        approved_by, approved_at
ClientVoteInstruction   client_id + vote_record_id, vote, source (policy_delta | client_ptv),
                        rationale, rule_id
Portfolio (+)           client_id, vehicle_type (SMA | CCF | ETF)
BallotLine              vote_record_id + portfolio_id, vote, source (house | client_delta | client_ptv),
                        cast_confirmation
DeliveryLogEntry        client_id, period, report hash, approved_by (compliance), sent_at
```

`BallotLine` is the one structural change v1 needs. Today `cast_vote` casts
once per `VoteRecord`, but a ballot is cast per **resolution × account**.
Stage 7 expands each approved `VoteRecord` into one line per holding
portfolio. `cast_vote` then moves to lines, with the same guards: no human
decision means no cast, and an alignment flag without a co-sign means no cast.

Client policy deltas reuse v1's `PolicyRule` type
(`Callable[[Proposal], VotePosition | None]`), so a client profile is
simply an extra rule list evaluated after the house decision.

## 3. CLTI and nature scores

- **CLTI** = latest `TransitionPlanAssessmentRecord` for the company:
  `disclosed_count / 64`, plus the walk/talk split and `by_category`.
  Versioned by `run_id` / `generated_at` (the record already carries both).
- **Nature** = latest TNFD assessment for the company.
- **Used in:**
  - **Stage 1 trigger:** a CLTI below a house threshold, or one that falls
    between runs, opens a `climate_transition` issue through the existing
    `run_trigger_screen` dedupe path. This is a `ControversySource`
    implementation fed by assessments rather than news.
  - **Stage 2 research:** the dossier includes the score and the specific
    `NO` indicators. Those become the engagement's concrete asks.
  - **Stage 6 tracking:** a verified commitment can be checked against the
    indicator flipping to `YES` in the next assessment run.

## 4. PTV pass-through

- `voting_delegation_mode` sits on the client profile, so it applies to all
  of that client's portfolios.
- **`house_voted`:** the line gets the house decision, overridden by the
  first client delta rule that fires (`source=client_delta`). The client
  approved its rules at onboarding, so these lines need no per-item review.
- **`ptv_pass_through`:**
  - The house never votes these shares.
  - Stage 7 publishes the house recommendation and rationale to the client.
  - The client's instruction is recorded as a `ClientVoteInstruction` with
    `source=client_ptv`, and the line casts that vote.
  - If no instruction arrives by the cutoff, those shares are not voted.
    They never fall back to the house vote.
- Stage 8 reports lines where a client vote differs from an open
  escalation, as information only. It is the client's right to vote that way,
  so this raises no alert.

## 5. Workflow shape

A deterministic state machine dispatches to LLM leaf agents. LLMs read
unstructured text and write drafts. Only code writes state.

| Stage | Worker | LLM | State |
|---|---|---|---|
| 1 Trigger | controversy source, **CLTI source**, **AGM calendar / DEF 14A watcher** | no | calendar + CLTI new |
| 2 Research | Research Agent + CLTI/nature scores | yes | built; scores new |
| 3 Drafting | Drafting Agent, Proposal Analysis Agent | yes | built |
| 4 Link | set `VoteRecord.issue_id` (theme map already in `check_engagement_alignment`) | no | new, small |
| 5 Human | unified review inbox over existing review queues | — | new |
| 6 Tracking | Tracking Agent | no | built |
| 7 Overlay | expand to `BallotLine`s, apply deltas / PTV | no | new |
| 8 Reporting | per-client aggregation + LLM narrative → compliance gate → delivery log | narrative | new |

Two extra agents:
- **Client Policy Onboarding agent:** reads a client's voting guidelines
  and proposes `voting_policy_deltas` with cited clauses. A human approves
  them before the profile goes live.
- **Scheduler tick:** each tick sweeps open issues (`decide_next_action`),
  new assessments, and the AGM calendar. It orders work by vote deadline
  and routes each task either to an agent or to the review inbox. Modelled
  on `DiscoveryScheduler`.

### Human checkpoints (consolidated)

1. Dossier review before drafting (v1)
2. Outreach send authorization (v1)
3. Meeting notes validation before commitments (v1)
4. Escalation lever decision (v1)
5. Every house vote decision; co-sign on alignment conflicts (v1)
6. **Co-sign on votes against management that are the chosen escalation lever** (v1 gap, md §6.5)
7. **Client policy profile approval at onboarding** (new)
8. **Compliance/legal review before a client report is sent** (new)

## 6. Phases

| Phase | Scope | Size |
|---|---|---|
| 1 | Stage 1–6 gaps: `VoteRecord.issue_id`, co-sign for escalation-lever votes, CLTI/nature in dossier, CLTI trigger source | ~1–2 days |
| 2 | Overlay schemas + storage: `Client`, `ClientPolicyProfile`, `ClientVoteInstruction`, `Portfolio.client_id/vehicle_type` | ~1 day |
| 3 | Stage 7: `BallotLine` expansion, client deltas, PTV routing, `cast_vote` on lines | ~2–3 days |
| 4 | Stage 8: per-client report, relevance weighting, compliance gate, delivery log | ~2 days |
| 5 | AGM calendar / new-filing trigger + scheduler tick + review inbox | ~3 days |
| 6 | Client Policy Onboarding agent | ~1–2 days |

Out of scope for now: CCF/ETF look-through (holdings stay flat, as the
operating model assumes), real custodian or proxy-platform casting
integration (`ManualInstructionBallotPlatform` remains), and a UI.
