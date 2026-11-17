# RFP example

Sample files for trying and demonstrating the RFP agent (`arp rfp`). The investor and the questionnaire are fictional. The answers restate the public DWS Stewardship Statement.

| File | Role in the agent |
|---|---|
| `documents/dws_stewardship_statement.pdf` | **Master document**, register it with priority 1. 15 pages, text layer, PDF created 24 Oct 2025. Not committed; download it from [dws.com](https://dws.com/solutions/sustainability/information-on-sustainability) (link "DWS Stewardship Statement") and check for a newer version. |
| `past_response_approved.docx` | Library of approved answers: 10 question and answer pairs, each restating the Statement. Load it first. It is an example, not an actual DWS RFP response. |
| `new_questionnaire.docx` | The investor's questionnaire to auto-fill: 10 questions, empty Response column. |

## What the agent does with each question

Tested end to end on 17 Nov 2026 with Gemini only (`ARP_ANTHROPIC_API_KEY` blank, `ARP_GEMINI_API_KEY` set): library import, Master document at priority 1, then a new project with the questionnaire. All 10 questions were found and nothing was flagged stale.

| # | Question | Result |
|---|---|---|
| 1 | Conflicts of interest | Approved answer used unchanged (100% kept). |
| 2 | Who is accountable, reports to whom | Approved answer used unchanged (100% kept), although the question is worded differently. |
| 3 | Collaborative engagement or voting | Approved answer used unchanged (100% kept). |
| 4 | Voting rights for every equity position | Approved answer used unchanged (100% kept). The first wording ("For which of your equity holdings...") found no source, so it was reworded. |
| 5 | Which proxy advisers | Mixed: 16% of the approved voting answer kept, the rest from the Master document (ISS, IVOX Glass Lewis). The best question to show "library first, then documents". |
| 6 | Securities lending | Not in the library: answered from the Master document. |
| 7 | Escalation measures | Not in the library: answered from the Master document (formal letters, statements at AGMs, extra meetings). |
| 8 | Nature-related risks | Not in the library: answered from the Master document. |
| 9 | Full-time staff | No source: left blank, as it should be. |
| 10 | Net-zero target | No source: left blank, as it should be. |

No question showed a small, tracked change to an approved answer; if you want that scene, add a library answer that is only partly right for a question.

## Running it

- Library: `arp rfp library import past_response_approved.docx` (or the Library page). Register the Master document on the Documents page, priority 1, and set its date to this year or it is flagged stale after 12 months.
- Questionnaire: create a project from `new_questionnaire.docx`; auto-fill runs in the background (about a minute).
- In this cloud container the PDF could not be registered: docling fails to load its layout model (`AutoImageProcessor` import error), which the app reports as "could not be read". The test used the Statement's text saved as .docx, so no page numbers were shown. Register the PDF on your own machine or the bank JupyterLab.
