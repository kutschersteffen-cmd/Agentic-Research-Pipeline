# RFP example (fictional)

Sample files for trying the RFP agent (`arp rfp`). Firm, policies and figures are invented.

| File | Role in the agent |
|---|---|
| `past_response_approved.docx` | A past response with 8 question and answer pairs. Load it into the library of approved answers. |
| `escalation_standard_reference.docx` | Reference document, give it priority 2. |
| `new_questionnaire.docx` | The investor's questionnaire to auto-fill (8 questions, empty Response column). |

What each new question should show:

1. Climate risk integration: identical to an approved answer, used unchanged.
2. Net-zero commitment, 3. reporting frameworks, 4. conflicts when voting, 7. policy review: close to an approved answer, small changes shown.
5. Escalation: not in the library; answered from the reference document (24 months, letter, meeting, vote).
6. Biodiversity, 8. tobacco: no source states them, so they should stay blank or be flagged for the reviewer.

Run: `arp rfp --help` for the commands (needs a model API key with credit).
