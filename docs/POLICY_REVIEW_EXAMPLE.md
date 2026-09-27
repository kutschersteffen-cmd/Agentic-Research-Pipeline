# Policy Review — Worked Example

Output of the policy review (section 5.7 of
[`STEWARDSHIP_OPERATING_MODEL.md`](STEWARDSHIP_OPERATING_MODEL.md)) for a
**fictional** client, compared with the **draft** house voting policy. Both
policies, and the decisions, are illustrative. Regenerate with:

```
cd backend
python -m arp.stewardship.policy_review arp/stewardship/data/examples/client_policy_example.json \
  --sample arp/stewardship/data/examples/sample_meetings.json \
  --decisions arp/stewardship/data/examples/client_policy_example_decisions.json \
  --build arp/stewardship/data/examples/client_policy_example_built.json
```

Inputs:
[client policy](../backend/arp/stewardship/data/examples/client_policy_example.json),
[decisions](../backend/arp/stewardship/data/examples/client_policy_example_decisions.json),
[house policy draft](../backend/arp/stewardship/data/house_voting_policy_draft.json),
[issue catalogue](../backend/arp/stewardship/data/policy_issue_catalogue.json).
[synthetic meetings](../backend/arp/stewardship/data/examples/sample_meetings.json) for the back-test
(12 fictional companies, about 170 resolutions; about 10% of company values deliberately missing).
Output: [built custom policy](../backend/arp/stewardship/data/examples/client_policy_example_built.json).

The flow has three steps:

1. **Review.** The client policy is captured as a questionnaire: each position
   states only what differs, and everything else inherits the house value. The
   review aligns it with the house policy issue by issue and suggests a
   recommendation per difference. With `--sample`, it also back-tests the
   envisioned policy (every difference adopted) against the house policy on the
   meeting data, and counts per difference how many expected votes it changes.
   **The meeting data here is synthetic, so these counts show the mechanism,
   not a real estimate.**
2. **Decide.** A person records a decision on every difference: `adopt`,
   `adopt_with_modification`, `decline`, `defer` (wait for a condition, e.g. a
   score scale) or `clarify` (ask the client).
3. **Build.** The custom policy is the house policy with every adopted difference
   applied. The build refuses to run while any difference is undecided. Deferred
   and clarified items stay on the house position and are listed as open items.

## 1–2. Review and decisions

**Client:** Example Client A (fictional public pension fund) · **Client policy:** `example_client_a_voting_draft` · **House policy:** `house_voting 0.1-draft` · **Catalogue:** `0.3-draft` · **Mandate:** vehicle_type: SMA, benchmark: MSCI World, voting_mode: house_voted

Differences that change how the client's shares are voted: **15** need a separate vote of the client's shares, **0** cannot be delivered in a pooled vehicle.

**Back-test on synthetic sample data:** 170 resolutions; the envisioned policy (every difference adopted) changes the expected vote on **25**. House: for: 131, against: 36, case_by_case: 3. Client: for: 108, against: 59, case_by_case: 3. *Votes changed* counts resolutions whose expected vote changes because of that issue; *masked* counts resolutions where its rule fires differently but another rule already decides the vote.

| Kind | Count |
|---|---|
| house_only | 28 |
| stricter | 12 |
| different_action | 2 |
| unmapped | 2 |
| unclear | 1 |
| looser | 1 |
| identical | 1 |
| changed | 1 |

| Recommendation | Count |
|---|---|
| adopt | 11 |
| review_with_house | 2 |
| adopt_when_scale_defined | 2 |
| clarify_or_add_issue | 2 |
| clarify | 1 |
| adopt_with_modification | 1 |

### Difference register

| Issue | Kind | Changes (house → client) | Direction | Votes changed | Flags | Recommendation | Decision |
|---|---|---|---|---|---|---|---|
| `board.independence` | stricter | `min_independent_pct`: 50 → 66<br>`controlled_company_min_pct`: 33 → 50 | more_against_management | 2 (+1 masked) | — | **adopt** | **adopt** (Stewardship committee (example)) |
| `board.chair_ceo_separation` | stricter | `require_separation`: no → yes<br>`accept_lead_independent_director`: yes → no | more_against_management | 0 | — | **adopt** | **adopt** (Stewardship committee (example)) |
| `board.overboarding` | stricter | `max_mandates_non_executive`: 5 → 4 | more_against_management | 5 (+3 masked) | — | **adopt** | **adopt** (Stewardship committee (example)) |
| `board.gender_diversity` | stricter | `min_underrepresented_gender_pct`: 30 → 40 | more_against_management | 2 (+1 masked) | — | **adopt** | **adopt** (Stewardship committee (example)) |
| `pay.quantum` | stricter | `max_peer_percentile`: 90 → 75<br>`max_ceo_worker_pay_ratio`: not set → 150 | more_against_management | 6 | — | **adopt** | **adopt** (Stewardship committee (example)): The pay ratio only applies where it is disclosed; data coverage to be confirmed. |
| `pay.esg_metrics` | stricter | `require_esg_metric`: no → yes<br>`min_esg_weight_pct`: 10 → 20 | more_against_management | 2 | — | **adopt** | **adopt** (Stewardship committee (example)) |
| `pay.severance` | stricter | `max_severance_multiple`: 2 → 1 | more_against_management | 1 | — | **adopt** | **adopt** (Stewardship committee (example)) |
| `audit.non_audit_fees` | stricter | `max_non_audit_to_audit_ratio`: 1.0 → 0.5 | more_against_management | 2 | — | **adopt** | **adopt** (Stewardship committee (example)) |
| `capital.share_issuance` | stricter | `max_without_preemption_pct`: 10 → 5 | more_against_management | 3 | — | **adopt** | **adopt** (Stewardship committee (example)) |
| `rights.virtual_meetings` | looser | `oppose_virtual_only`: yes → no | fewer_against_management | 1 | — | **review_with_house** | **adopt** (Stewardship committee (example)): Looser than house, but it only affects the client's own shares. |
| `climate.laggard_accountability` | stricter | `vote_target`: responsible_director → board_chair<br>`laggard_threshold`: not set → 30<br>`min_months_engaged_without_progress`: 12 → 6<br>`high_emitters_only`: yes → no | more_against_management | 0 | Threshold set on a placeholder score whose scale is not yet defined. | **adopt_when_scale_defined** | **defer** (Stewardship committee (example)): Adopt once the CLTI scale is fixed; the client's threshold of 30 is recorded as intent. |
| `climate.targets` | stricter | `require_validated_targets`: no → yes<br>`scope`: markets: all, sectors: high_emitters → markets: all | more_against_management | 2 | — | **adopt** | **adopt_with_modification** (Stewardship committee (example)): Validated targets required of high emitters only; too few companies in other sectors have them to vote on. |
| `climate.say_on_climate` | different_action | `action`: case_by_case → against<br>`min_plan_score`: not set → 70 | more_against_management | 1 | Threshold set on a placeholder score whose scale is not yet defined. | **adopt_when_scale_defined** | **defer** (Stewardship committee (example)): Adopt once the transition plan score scale is fixed. |
| `nature.laggard_accountability` | different_action | `action`: escalate → against | more_against_management | 0 | Bypasses the house engagement-first sequence (house escalates through engagement before voting). | **adopt_with_modification** | **decline** (Stewardship committee (example)): Covered by stewardship.engagement_escalation, which votes against the responsible director once engagement reaches the vote step. |
| `social.human_rights` | stricter | `min_controversy_severity`: 5 → 4 | more_against_management | 1 | — | **adopt** | **adopt** (Stewardship committee (example)) |
| `stewardship.engagement_escalation` | changed | `require_prior_notice`: yes → no | different | 0 | Engagement-linked: check pressure-type engagement rules (E6). | **review_with_house** | **decline** (Stewardship committee (example)): Prior notice is part of how the house engages; it cannot differ per client. |

### Questions for the client (unclear)

| Issue | Client text | Question | Decision |
|---|---|---|---|
| `pay.say_on_pay` | Remuneration should be reasonable and aligned with long-term value creation. | Should say-on-pay follow the house red-flag approach, or do you want a stricter default (e.g. against unless all remuneration criteria are met)? | **clarify** (Stewardship committee (example)): Question sent to the client. |

### Unmapped client clauses

| Client text | Suggested catalogue issue | Decision |
|---|---|---|
| We vote against the chair of companies planning new fossil-fuel expansion. | `climate.fossil_fuel_expansion` | **clarify** (Stewardship committee (example)): Propose adding climate.fossil_fuel_expansion to the catalogue. |
| We expect companies to pay a living wage across their supply chain. | `social.living_wage` | **clarify** (Stewardship committee (example)): Living wage is an engagement topic rather than a voting rule; confirm with the client. |

**Identical to house (1):** `gov.shareholder_proposals`

**Client silent, inherits house (28):** `board.committee_independence`, `board.attendance`, `board.tenure_refreshment`, `board.election_practices`, `board.responsiveness`, `pay.performance_alignment`, `pay.equity_plans`, `pay.disclosure`, `pay.non_executive_fees`, `audit.auditor_tenure`, `audit.financial_statements`, `audit.discharge`, `capital.share_buybacks`, `capital.dividend_allocation`, `capital.one_share_one_vote`, `capital.takeover_defences`, `capital.mergers_acquisitions`, `capital.related_party_transactions`, `rights.shareholder_rights`, `climate.disclosure`, `climate.shareholder_proposals`, `nature.disclosure`, `social.workforce`, `social.shareholder_proposals`, `gov.controversy_accountability`, `gov.lobbying_political`, `gov.tax_transparency`, `general.default_management`

## 3. Built custom policy

**Built policy:** `example_client_a_voting_draft_built` · base `house_voting 0.1-draft` · status: built; pending client and house approval

12 of 46 positions come from the client; the rest are the house position.

| Issue | Action | Vote target | Parameters (client values applied) | Decision |
|---|---|---|---|---|
| `board.independence` | against | `nomination_committee_chair` | min_independent_pct: 66, controlled_company_min_pct: 50 | adopt |
| `board.chair_ceo_separation` | against | `combined_chair_ceo` | require_separation: yes, accept_lead_independent_director: no, oppose_former_ceo_as_chair: yes | adopt |
| `board.overboarding` | against | `overboarded_director` | max_mandates_non_executive: 4, max_mandates_executive: 1, chair_counts_as: 2 | adopt |
| `board.gender_diversity` | against | `nomination_committee_chair` | min_underrepresented_gender_pct: 40, markets_with_higher_threshold: EU: 40 | adopt |
| `pay.quantum` | against | `say_on_pay` | max_peer_percentile: 75, max_ceo_worker_pay_ratio: 150 | adopt |
| `pay.esg_metrics` | against | `remuneration_policy` | require_esg_metric: yes, min_esg_weight_pct: 20, require_climate_metric_for_high_emitters: yes | adopt |
| `pay.severance` | against | `remuneration_policy` | max_severance_multiple: 1, oppose_single_trigger: yes | adopt |
| `audit.non_audit_fees` | against | `auditor_ratification` | max_non_audit_to_audit_ratio: 0.5 | adopt |
| `capital.share_issuance` | against | `share_issuance` | max_with_preemption_pct: 33, max_without_preemption_pct: 5 | adopt |
| `rights.virtual_meetings` | against | `articles_amendment` | oppose_virtual_only: no, accept_hybrid: yes | adopt |
| `climate.targets` | against | `responsible_director` | require_net_zero_target: yes, require_interim_targets: yes, require_validated_targets: yes | adopt_with_modification |
| `social.human_rights` | against | `board_chair` | min_controversy_severity: 4, ungc_fail_triggers_action: yes | adopt |

**Open items (house position applies until resolved):**

- `pay.say_on_pay` (clarify): Question sent to the client.
- `climate.laggard_accountability` (defer): Adopt once the CLTI scale is fixed; the client's threshold of 30 is recorded as intent.
- `climate.say_on_climate` (defer): Adopt once the transition plan score scale is fixed.
- `unmapped.1` (clarify): Propose adding climate.fossil_fuel_expansion to the catalogue.
- `unmapped.2` (clarify): Living wage is an engagement topic rather than a voting rule; confirm with the client.

