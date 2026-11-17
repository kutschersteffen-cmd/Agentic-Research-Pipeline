# RFP example (fictional)

Sample files for trying the RFP agent (`arp rfp`). Firm, policies and figures are invented.

| File | Role in the agent |
|---|---|
| `past_response_approved.docx` | A past response with 8 question and answer pairs. Load it into the library of approved answers. |
| `documents/dws_stewardship_statement.pdf` | **Master document**, register it with priority 1. The public DWS Stewardship Statement (15 pages, text layer, PDF created 24 Oct 2025). Not committed; download it from [dws.com](https://dws.com/solutions/sustainability/information-on-sustainability) (link "DWS Stewardship Statement"). Check the page for a newer version before use. |
| `escalation_standard_reference.docx` | Fictional reference document, priority 2. The Master document is searched first. |
| `new_questionnaire.docx` | The investor's questionnaire to auto-fill (8 questions, empty Response column). |

What each new question should show:

1. Climate risk integration: identical to an approved answer, used unchanged.
2. Net-zero commitment, 3. reporting frameworks, 4. conflicts when voting, 7. policy review: close to an approved answer, small changes shown.
5. Escalation: not in the library; answered from the Master document (its Engagement and Exercising Voting Rights sections), or from the fictional escalation standard if the Master does not cover it.
6. Biodiversity, 8. tobacco: no source states them, so they should stay blank or be flagged (check the Master document first: it may now answer biodiversity) for the reviewer.

Run: `arp rfp --help` for the commands (needs a model API key with credit).
