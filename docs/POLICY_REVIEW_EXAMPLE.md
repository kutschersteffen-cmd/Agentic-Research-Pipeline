# Policy Review — Worked Example

Output of the policy review (section 5.7 of
[`STEWARDSHIP_OPERATING_MODEL.md`](STEWARDSHIP_OPERATING_MODEL.md)) for a
**fictional** client, compared with the **draft** house voting policy. Both
policies are illustrative. Regenerate with:

```
cd backend
python -m arp.stewardship.policy_review arp/stewardship/data/examples/client_policy_example.json
```

Inputs:
[client policy](../backend/arp/stewardship/data/examples/client_policy_example.json),
[house policy draft](../backend/arp/stewardship/data/house_voting_policy_draft.json),
[issue catalogue](../backend/arp/stewardship/data/policy_issue_catalogue.json).
The client policy is captured as a questionnaire: each position states only what
differs, and everything else inherits the house value. Recommendations are
suggestions for the reviewers; the `decision` on every register row is empty until
a person decides it.

**Client:** Example Client A (fictional public pension fund) · **Client policy:** `example_client_a_voting_draft` · **House policy:** `house_voting 0.1-draft` · **Catalogue:** `0.2-draft` · **Mandate:** vehicle_type: SMA, benchmark: MSCI World, voting_mode: house_voted

Differences that change how the client's shares are voted: **15** need a separate vote of the client's shares, **0** cannot be delivered in a pooled vehicle. Impact per difference (resolutions affected) is not computed yet: it needs ingested voting history.

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
| adopt | 12 |
| review_with_house | 2 |
| clarify_or_add_issue | 2 |
| clarify | 1 |
| adopt_when_scale_defined | 1 |
| adopt_with_modification | 1 |

### Difference register

| Issue | Kind | Changes (house → client) | Direction | Flags | Recommendation |
|---|---|---|---|---|---|
| `board.independence` | stricter | `min_independent_pct`: 50 → 66<br>`controlled_company_min_pct`: 33 → 50 | more_against_management | — | **adopt** |
| `board.chair_ceo_separation` | stricter | `require_separation`: no → yes<br>`accept_lead_independent_director`: yes → no | more_against_management | — | **adopt** |
| `board.overboarding` | stricter | `max_mandates_non_executive`: 5 → 4 | more_against_management | — | **adopt** |
| `board.gender_diversity` | stricter | `min_underrepresented_gender_pct`: 30 → 40 | more_against_management | — | **adopt** |
| `pay.quantum` | stricter | `max_peer_percentile`: 90 → 75<br>`max_ceo_worker_pay_ratio`: not set → 150 | more_against_management | — | **adopt** |
| `pay.esg_metrics` | stricter | `require_esg_metric`: no → yes<br>`min_esg_weight_pct`: 10 → 20 | more_against_management | — | **adopt** |
| `pay.severance` | stricter | `max_severance_multiple`: 2 → 1 | more_against_management | — | **adopt** |
| `audit.non_audit_fees` | stricter | `max_non_audit_to_audit_ratio`: 1.0 → 0.5 | more_against_management | — | **adopt** |
| `capital.share_issuance` | stricter | `max_without_preemption_pct`: 10 → 5 | more_against_management | — | **adopt** |
| `rights.virtual_meetings` | looser | `oppose_virtual_only`: yes → no | fewer_against_management | — | **review_with_house** |
| `climate.laggard_accountability` | stricter | `vote_target`: responsible_director → board_chair<br>`laggard_threshold`: not set → 30<br>`min_months_engaged_without_progress`: 12 → 6<br>`high_emitters_only`: yes → no | more_against_management | Threshold set on a placeholder score whose scale is not yet defined. | **adopt_when_scale_defined** |
| `climate.targets` | stricter | `require_validated_targets`: no → yes<br>`scope`: markets: all, sectors: high_emitters → markets: all | more_against_management | — | **adopt** |
| `climate.say_on_climate` | different_action | `action`: case_by_case → against<br>`min_plan_score`: not set → 70 | more_against_management | — | **adopt** |
| `nature.laggard_accountability` | different_action | `action`: escalate → against | more_against_management | Bypasses the house engagement-first sequence (house escalates through engagement before voting). | **adopt_with_modification** |
| `social.human_rights` | stricter | `min_controversy_severity`: 5 → 4 | more_against_management | — | **adopt** |
| `stewardship.engagement_escalation` | changed | `require_prior_notice`: yes → no | different | Engagement-linked: check pressure-type engagement rules (E6). | **review_with_house** |

### Questions for the client (unclear)

| Issue | Client text | Question |
|---|---|---|
| `pay.say_on_pay` | Remuneration should be reasonable and aligned with long-term value creation. | Should say-on-pay follow the house red-flag approach, or do you want a stricter default (e.g. against unless all remuneration criteria are met)? |

### Unmapped client clauses

| Client text | Suggested catalogue issue |
|---|---|
| We vote against the chair of companies planning new fossil-fuel expansion. | `climate.fossil_fuel_expansion` |
| We expect companies to pay a living wage across their supply chain. | `social.living_wage` |

**Identical to house (1):** `gov.shareholder_proposals`

**Client silent, inherits house (28):** `board.committee_independence`, `board.attendance`, `board.tenure_refreshment`, `board.election_practices`, `board.responsiveness`, `pay.performance_alignment`, `pay.equity_plans`, `pay.disclosure`, `pay.non_executive_fees`, `audit.auditor_tenure`, `audit.financial_statements`, `audit.discharge`, `capital.share_buybacks`, `capital.dividend_allocation`, `capital.one_share_one_vote`, `capital.takeover_defences`, `capital.mergers_acquisitions`, `capital.related_party_transactions`, `rights.shareholder_rights`, `climate.disclosure`, `climate.shareholder_proposals`, `nature.disclosure`, `social.workforce`, `social.shareholder_proposals`, `gov.controversy_accountability`, `gov.lobbying_political`, `gov.tax_transparency`, `general.default_management`

