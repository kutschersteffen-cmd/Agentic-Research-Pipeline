# RFP example

Sample files for trying and demonstrating the RFP agent (`arp rfp`). The investor and the questionnaire are fictional. The answers restate the public DWS Stewardship Statement.

| File | Role in the agent |
|---|---|
| `documents/dws_stewardship_statement.pdf` | **Master document**, register it with priority 1. 15 pages, text layer, PDF created 24 Oct 2025. Not committed; download it from [dws.com](https://dws.com/solutions/sustainability/information-on-sustainability) (link "DWS Stewardship Statement") and check for a newer version. |
| `past_response_approved.docx` | Library of approved answers: 10 question and answer pairs, each restating the Statement. Load it first. It is an example, not an actual DWS RFP response. |
| `new_questionnaire.docx` | The investor's questionnaire to auto-fill: 10 questions, empty Response column. |

## What each new question should show

| # | Question | Expected result |
|---|---|---|
| 1 | Conflicts of interest | Identical to an approved answer: used unchanged. |
| 2 | Who is accountable, reports to whom | Close to an approved answer: small change shown. |
| 3 | Collaborative engagement or voting | Close to an approved answer: small change shown. |
| 4 | Holdings with voting rights | Close to an approved answer: small change shown. |
| 5 | Which proxy advisers | The approved voting answer covers the use of recommendations; the missing part (ISS, IVOX Glass Lewis) comes from the Master document, priority 1. |
| 6 | Securities lending | Not in the library: answered from the Master document (page 9, Securities lending). |
| 7 | Escalation measures | Not in the library: answered from the Master document (page 11: formal letters, statements at AGMs, extra meetings). |
| 8 | Nature-related risks | Not in the library: answered from the Master document (page 5, Nature). |
| 9 | Full-time staff | Not stated anywhere: should stay blank or be flagged for the reviewer. |
| 10 | Net-zero target | Not stated anywhere: should stay blank or be flagged for the reviewer. |

Page numbers are the Statement's own footer numbers. Run `arp rfp --help` for the commands (needs a model API key with credit). Not yet run through the agent.
