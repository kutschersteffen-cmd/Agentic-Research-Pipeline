# Ask the portfolio: a clear message when the model fails

Slug: ask-portfolio-provider-error

Risk: `risk:normal`. Size S, 1 PR. Backend, plus one line in the Ask panel.

Status: draft, round 2 of the findings clean-up the owner asked for on 15 Nov 2026 ("clean up further bugs and
findings"). Checked against `origin/main` `5df84c4`.

## Why

When the language model fails (out of credit, a bad key, the provider down), `POST /api/portfolio/ask`
(`backend/arp/api/routers/portfolio.py`, `ask`) re-raises the error. It lands in the catch-all handler in
`backend/arp/api/main.py` (`server_error_handler`), which answers `500 {"detail": "Internal error", "request_id": …}`.

What the person then sees, from reading the code:

- **Frontend on another origin** (Vite dev on `:5173`, API on `:8000`): Starlette runs the catch-all handler
  outside the CORS middleware, so the 500 has no `Access-Control-Allow-Origin` header. The browser hides it and
  the Ask panel shows `TypeError: Failed to fetch`, which is what was reported.
- **Same origin** (the bank JupyterLab, where the API serves the built frontend): the panel shows
  `Error: 500: Internal error`.

Neither says what went wrong or what to do. The real model keys are out of credit right now, so the showcase
(about 27 Nov 2026) will hit this unless a working key is in place.

The main Ask box (`backend/arp/api/routers/ask.py`, `post_ask`) already handles this: any failure answers
`502` with `Ask could not answer this question. Try again.`, and the frontend strips the status code
(`askErrorText` in `frontend/src/lib/askHistory.ts`).

## Goals

- A failure while answering returns 502 with a plain sentence, so the panel shows that sentence.
- The `qa_audit` record of the failed call stays, with the error.
- The Ask panel shows the sentence without `Error:` or the status code.

## Non-goals

`qa_agent`, the fallback LLM client, the Superset ask, any other endpoint, retries, telling "out of credit" apart
from other failures. The input checks (`_check_ask_request`, 422) are unchanged. The alerts follow-up (PR #497)
edits another function in the same file; no overlap.

## Approach

One sensible way: copy `post_ask`'s pattern into `ask`. The `except` raises `HTTPException(502, …) from exc`
instead of re-raising; `error` is still set first, so the `finally` audit row is unchanged. Before raising it
logs `logger.exception("portfolio ask failed")`, so the server log keeps the traceback the catch-all handler
writes today. Telling provider
errors apart by exception type was dropped: each client (Gemini, LangChain, fallback) raises its own types, and
the 502 sentence is true for any failure.

**Message (author's call).** The same sentence as the main Ask box: `Ask could not answer this question. Try
again.` One wording for one kind of failure across both Ask entry points. A sentence naming the model ("the
language model did not answer") was dropped: it would be wrong when the failure is the database.

**Why a 502 also fixes `Failed to fetch`.** An `HTTPException` is answered inside the CORS middleware, so it
carries the CORS headers; the catch-all 500 is not, which is why a browser on another origin hid it.

**The Ask panel needs one line.** `AskThePortfolio.tsx` shows `String(e)`, which reads
`Error: 502: Ask could not …`. It switches to the existing `askErrorText(e)` for every error it shows, which
drops `Error:` and the status code (a 422 then reads `as_of must be YYYY-MM-DD`).

## Test change (list it in the PR)

`backend/tests/test_qa_audit.py::test_unresolvable_and_error_still_audited` asserts `status_code == 500  # still
raised`; it becomes `== 502`. The audit assertions in it stay. This follows the new behaviour; nothing is weakened.

## Acceptance

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | The app started by `backend/scripts/e2e_stack.sh up` with `ARP_STANDINS_DIR` set and `model/_ParsedQuestion.json` = `{"error": "credit balance is too low"}` (the stand-in model raises `RuntimeError("credit balance is too low")`) | `POST http://127.0.0.1:8000/api/portfolio/ask` `{"question": "What is my largest holding?"}` | Status 502, body `{"detail": "Ask could not answer this question. Try again."}` | holdout |
| AC-2 | The portfolio router in a test app with a stand-in LLM client raising `RuntimeError("credit balance is too low")` | The same request, then read `qa_audit.jsonl` | One new row: `endpoint` `portfolio.ask`, `question` `What is my largest holding?`, `answer_sha256` the SHA-256 of `""`, `error` `RuntimeError: credit balance is too low` | unit |
| AC-3 | AC-1 | The 502 response | Its body does not contain `credit balance` | holdout |
| AC-4 | AC-1's app | `POST http://127.0.0.1:8000/api/portfolio/ask` `{"question": "x", "as_of": "01/11/2026"}` | Status 422, body `{"detail": "as_of must be YYYY-MM-DD"}` | holdout |
| AC-5 | AC-1's app | A user asks `What is my largest holding?` in the Ask the portfolio panel | The alert reads exactly `Ask could not answer this question. Try again.` | evaluator |
| AC-6 | AC-2's test app | The AC-4 request, then read `qa_audit.jsonl` | No new row | unit |
| AC-7 | AC-1's app | AC-1's request with header `Origin: http://localhost:5173` | Status 502, response header `access-control-allow-origin: http://localhost:5173` | holdout |
| AC-8 | AC-2's test app, but the stand-in returns a resolvable parse; one portfolio with a snapshot | `POST /api/portfolio/ask` | Status 200; one new audit row with `error` null and `answer_sha256` the SHA-256 of the returned `answer_text` | unit |
| AC-9 | — | `askErrorText(new Error("422: as_of must be YYYY-MM-DD"))` (`frontend/tests/askHistory.test.ts`) | Returns exactly `as_of must be YYYY-MM-DD` | unit |
| AC-10 | AC-2's test app | The server log during AC-2's request | One `ERROR` record with message `portfolio ask failed` and a traceback naming `RuntimeError` | unit |

Must not change: AC-2, AC-3, AC-4, AC-6, AC-8, AC-9.

AC-2, AC-6, AC-8 and AC-10 read the audit file or the server log, which a hidden test cannot reach from outside, so
they are `unit`. The frontend's `npm test` renders no components, so the panel change is checked only by the
evaluator (AC-5); AC-9 guards the existing helper it now uses.
