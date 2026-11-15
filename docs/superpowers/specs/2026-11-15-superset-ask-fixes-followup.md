# Superset "ask for a chart": two asks at once, and the "502: " in the error line

Slug: superset-ask-fixes-followup

Risk: `risk:normal` for the implementing PR (proposed). Size S, one PR. Backend `arp/bi` plus one frontend line,
so the UI review applies (Playwright screenshot of the Dashboards tab, `/impeccable:impeccable audit`).

Status: draft, waiting for owner approval.

Parent: [`2026-11-14-superset-ask-fixes.md`](2026-11-14-superset-ask-fixes.md). Its hidden tests stay in the
regression suite.

## Why

Two findings from the review of the parent spec, on `main` (`b53ad65`):

1. **Two asks at the same time lose a chart.** `_add_to_scratch` (`backend/arp/bi/service.py:138-167`) reads the
   charts on `arp-scratch` (`dashboard_charts`), creates the new chart, then calls `update_dashboard` with the
   layout of the charts it read plus its own. Nothing stops two asks from interleaving: both read N charts, both
   write a layout of N+1, and the last write drops the other ask's chart from the layout, while that chart stays
   attached to the dashboard. When `arp-scratch` does not exist yet, both asks try to create it and the second
   fails on the taken slug. Found by code trace, not reproduced.
2. **The ask/design error starts with "502: ".** The error line under the brief
   (`frontend/src/pages/portfolio-monitoring/SupersetBI.tsx:305-308`) shows the client error text raw, so it reads
   `502: Superset is not reachable at ...`. The list banner (`ListError`, line 117) and `embedErrorText`
   (`frontend/src/lib/biEmbed.ts`) already strip the code with `/^\d{3}:\s*/`. The parent spec's non-goals
   ("any UI work beyond the one banner line") left this out; this spec lifts that for this one line.

## Goals

1. Two asks running at the same time in one backend process both end up in the `arp-scratch` layout.
2. The ask/design error line shows the server's message without the `NNN: ` status code, using the same strip as
   the list banner.

## Non-goals

- Several backend processes. The showcase runs one uvicorn process. A lock across processes (a Postgres advisory
  lock) is out; the lock's comment names this limit.
- `design` (`_build_dashboard`): each brief gets its own `arp-<hash>` dashboard, so no shared layout is rewritten.
- Any other wording on the page; the `ListError` banner and the embed error text keep their output.
- Concurrency tests against a real Superset.

## Anti-goals

- A failed ask leaves the lock held (it must be released on every exception, e.g. a `with` block).

## Approaches considered

1. **Process-wide `threading.Lock` around the scratch read-modify-write (chosen; owner fixed this in the intake).**
   Same pattern as `_EMBED_LOCK` (`service.py:193`). Small, and right for the one-process showcase.
2. **Postgres advisory lock.** Right for several workers, but the BI service has no database session today and the
   showcase runs one process. Rejected for now; the `shortcut:` comment says when to switch.
3. **Re-read and merge before the write (optimistic).** Superset has no compare-and-set on `position_json`, so a
   window stays open. Rejected.

For the error line there is one sensible way: export one strip function from `biEmbed.ts` and use it on that line.

## Design

### Lock (`backend/arp/bi/service.py`)

- A module-level `_SCRATCH_LOCK = threading.Lock()` next to `_EMBED_LOCK`, with a comment in the form
  `# shortcut: one backend process only; several workers would need a Postgres advisory lock.`
- `_add_to_scratch` holds it from before `find_dashboard(SCRATCH_SLUG)` until after the dashboard create or update
  and any cleanup, i.e. around its whole body. So the reuse check (parent goal 3), the chart create and the layout
  write are one step per ask. A second ask with the same question at the same time therefore reuses the first
  ask's chart, as a sequential one does.
- No other function takes this lock. `ask_chart` and the API router do not change. `_add_to_scratch` already runs
  in the worker thread `asyncio.to_thread` gives it, so waiting for the lock never blocks the event loop.

### Error line (`frontend/src/lib/biEmbed.ts`, `SupersetBI.tsx`)

- `biEmbed.ts` exports `withoutStatusCode(error: string): string`, which returns `error` with a leading
  `/^\d{3}:\s*/` removed, and nothing else changed.
- The error line under the brief renders `withoutStatusCode(error)`.
- `ListError`'s danger branch and `embedErrorText` call `withoutStatusCode` instead of their own copy of the regex;
  their output does not change. `ListError`'s 503 branch stays as it is.
- Test: `frontend/tests/biEmbed.test.ts`.

## Other specs this changes

- Parent non-goal "any UI work beyond the one banner line in (1)" is lifted for the ask/design error line only.
- Parent AC-19 to AC-22 (scratch reuse, run one ask at a time) still hold unchanged. AC-1 to AC-5 here add the
  concurrent case. No parent row is retired.

## Left to the builder

Test layout and fakes; where in `biEmbed.ts` the function goes.

## Acceptance

**`holdout` for the lock, not `unit`:** the race can be forced deterministically in-process, with no real
Superset: the fake Superset makes the first ask wait at a barrier until the second ask has made the same read.
Without the lock both asks meet there and the layout loses a chart every time; with the lock the barrier times
out and the asks run one after the other.

Setup for AC-1 to AC-5 (in-process, like the parent's holdout rows): one
`SupersetClient("http://127.0.0.1:8088", "arp_designer", <pw>, transport=httpx.MockTransport(...))` shared by both
asks. The fake keeps state: created charts get new ids; `PUT /api/v1/dashboard/{id}` replaces that dashboard's
layout; `GET /api/v1/dashboard/{id}/charts` lists the charts attached to it. The model stand-in returns a valid
one-chart plan titled `A` for question `qa` and one titled `B`, with a different metric, for question `qb`.
"At the same time" is `asyncio.gather(ask_chart("qa", llm, client), ask_chart("qb", llm, client))`. "Waits at
the barrier" means the fake's handler for that request calls `threading.Barrier(2).wait(timeout=2)` and answers
normally after it returns or raises `BrokenBarrierError`. "Chart ids in the layout" are the `meta.chartId` values
of the `CHART` nodes in `position_json`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | `arp-scratch` exists (id 5) holding chart 1 titled `Existing`; the fake's `GET /api/v1/dashboard/5/charts` waits at the barrier | `qa` and `qb` asked at the same time | both calls return a `DesignResult` with `slug` `arp-scratch` and `dashboard_id` 5; neither raises | holdout |
| AC-2 | as AC-1 | `qa` and `qb` asked at the same time | the chart ids in the layout of the last `PUT /api/v1/dashboard/5` are exactly chart 1 and the two charts created for `A` and `B` (three ids) | holdout |
| AC-3 | `arp-scratch` does not exist; the fake's dashboard lookup by slug (`GET /api/v1/dashboard/?q=...`) waits at the barrier | `qa` and `qb` asked at the same time | the fake received exactly one `POST /api/v1/dashboard/` | holdout |
| AC-4 | as AC-3 | `qa` and `qb` asked at the same time | the chart ids in that dashboard's final layout (its last `PUT /api/v1/dashboard/{id}`, else its POST) are exactly the two charts created for `A` and `B` | holdout |
| AC-5 | `arp-scratch` exists (id 5) holding chart 1; the fake answers the **first** chart POST with 500 and every later chart POST normally | `qa` is asked (it raises `BIError`), then `qb` is asked | `qb` returns within 5 s with `slug` `arp-scratch` and `dashboard_id` 5 (the lock was released) | holdout |
| AC-6 | `withoutStatusCode` | called with `502: Superset is not reachable at http://127.0.0.1:8088. It is not set up here or not running.` | returns `Superset is not reachable at http://127.0.0.1:8088. It is not set up here or not running.` | unit |
| AC-7 | `withoutStatusCode` | called with `Superset request failed.` | returns `Superset request failed.` unchanged | unit |
| AC-8 | `withoutStatusCode` | called with `Error 502: x` | returns `Error 502: x` unchanged (only a leading code goes) | unit |
| AC-9 | `embedErrorText` | called with `404: gone`, then with `500: Superset request failed (HTTP 500).` | returns `This dashboard is no longer available here.`, then `Superset request failed (HTTP 500).`, as on `main` | unit |
| AC-10 | the e2e stack started with `ARP_SUPERSET_PASSWORD` and `ARP_ANTHROPIC_API_KEY` set to any value (the ask fails at Superset before any model call) and nothing listening on `127.0.0.1:8088` | Risk Monitoring, Dashboards tab: type `exposure by sector` in the brief and click `Ask as one chart` | the error line under the brief reads exactly `Superset is not reachable at http://127.0.0.1:8088. It is not set up here or not running.` (no `502: ` in front) | evaluator |
| AC-11 | as AC-10 | the page loads | the list banner reads exactly `The dashboard list could not be loaded. Superset is not reachable at http://127.0.0.1:8088. It is not set up here or not running.`, as on `main` | evaluator |
| AC-12 | the e2e stack started with `ARP_SUPERSET_PASSWORD` unset (its default) | Risk Monitoring, Dashboards tab loads | the warning banner reads exactly `Superset is not configured: set ARP_SUPERSET_PASSWORD.`, as on `main` | evaluator |
| AC-13 | the PR branch | `cd backend && python scripts/export_openapi.py` | `frontend/src/api/openapi.json` is byte-identical to `main` | unit |

Must not change:

- AC-9: the embed error texts. AC-11, AC-12: the list banner, both branches.
- AC-5: a failed ask releases the lock.
- AC-13: the OpenAPI document.
- Parent AC-19 to AC-22: one ask at a time on `arp-scratch` (first ask, reuse, same title with another metric, other
  title), still in the regression suite.
- The existing tests in `frontend/tests/biEmbed.test.ts`, `backend/tests/test_bi_service.py` and
  `backend/tests/test_api_bi.py` pass unchanged.
