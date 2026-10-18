---
type: frontend architecture
title: Frontend application
description: The React 19 + Vite single-page app in frontend/src, covering hash routing with lazily loaded pages, the single API client with bearer-token auth, the generated OpenAPI types and the compile-time API contract, and the extraction, review and run screens.
tags: [frontend, react, vite, api-client, routing, review-ui]
verified:
  - by: openwiki/0.7.2
    at: 2026-10-18T15:42:30.245Z
sources:
  - id: openwiki-source-1047363cf615000e4c9bb694
    resource: repo://frontend/package.json
  - id: openwiki-source-e1203af9dfebfe1b0264745d
    resource: repo://frontend/src/api/client.ts
  - id: openwiki-source-c19532cf98f6988dc30041f9
    resource: repo://frontend/src/api/contract.ts
  - id: openwiki-source-454c9bcdde0b77b35e0fc994
    resource: repo://frontend/src/App.tsx
  - id: openwiki-source-4b14405022447966efb7e84e
    resource: repo://frontend/src/lib/auth.ts
  - id: openwiki-source-88e289bd6c07b4f09a4f703a
    resource: repo://frontend/src/lib/poll.ts
  - id: openwiki-source-4622f09188c7b2fdc738352b
    resource: repo://frontend/src/main.tsx
  - id: openwiki-source-f490bfee9ae0fdc7aaa9bb95
    resource: repo://frontend/src/pages/Extraction.tsx
  - id: openwiki-source-f3c3831319a97a917f428f9c
    resource: repo://frontend/src/pages/ReviewQueue.tsx
  - id: openwiki-source-378e3cf05ab0d05d335c68d5
    resource: repo://frontend/vite.config.ts
generated: { by: "claude-code", at: "2026-10-18T15:42:30.245Z" }
---

# Frontend application

`frontend/src` is a React 19 single-page app built with Vite (`frontend/package.json`). It is the authoring,
monitoring and review UI for the FastAPI backend. It has no router library and no state library: the URL hash decides
the screen, and every backend call goes through one module, `frontend/src/api/client.ts`.

## Entry and shell

- `frontend/src/main.tsx` mounts `<App/>` in `StrictMode`. It also listens for `vite:preloadError`: a tab left open
  across a deploy points at old hashed chunks, so the app reloads once (at most every 10 s) instead of going blank.
- `frontend/src/App.tsx` is the shell. It holds the sidebar, the command palette (Ctrl/Cmd+K), the "Needs you" counts
  and the page area.

### Routing

The hash is the source of truth: `#/<tab>/<param>...`. `parseHash` maps it to a `TABS` id plus params. Unknown tabs
fall back to `home`, and a few legacy ids are redirected (`themeMachine` and `designStudio` go to `rdLab`). Refresh,
Back and pasted links therefore all land on the same view, for example `#/review/extraction/<run id>` or
`#/companies/<ref>`. When the hash changes, the app asks the open screen whether it may be left (`canLeave`, from
`frontend/src/lib/leaveGuard.ts`). If the screen refuses, the old hash is put back with `history.replaceState`.

Every page is loaded on demand with `React.lazy`. `TABS` lists every screen. `HUBS` groups several screens under one
sidebar item with a tab strip. `NAV_GROUPS` arranges the sidebar into "Needs you", "Workspaces", "Output" and a
collapsed "All screens" group.

The shell refreshes its counters on every navigation and after every decision (`arp:decided` events, see
`frontend/src/lib/announce.ts`). It sums `review_count` over all runs of the reviewable types (`theme`, `extraction`,
`financials`, `identity`) and over proxy-voting runs. If that request fails, the counts are hidden rather than shown
as zero.

## API client

`frontend/src/api/client.ts` exports one `api` object with a method per endpoint. All of them use `request<T>()`,
which:

- prefixes `VITE_API_BASE` (default `http://localhost:8000`);
- goes through `authFetch`, which adds `Authorization: Bearer <token>` when a token is stored, clears the token on a
  401, and throws an `Error("<status>: <detail>")` for any non-2xx response, turning FastAPI validation errors into
  readable text;
- sets the JSON content type unless the body is `FormData`.

`fetchFile`, `downloadFile` and `openFile` cover authenticated file downloads, which a plain `<a href>` cannot do
because it cannot send the bearer token. `openFile` only opens types that are safe to show from this origin (PDF,
images, text) and saves everything else.

`frontend/src/lib/auth.ts` keeps the token in `localStorage` under `arp.token`, with an in-memory fallback when storage
is blocked. It notifies listeners on every change, so the UI can ask for a token again after a 401. On the server side,
`auth_mode="dev"` signs in loopback requests as an approver without a token. See
<!-- openwiki: broken internal link [/openwiki/architecture/overview.md] link "/openwiki/architecture/overview.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[System architecture](/openwiki/architecture/overview.md).

### Typed contract with the backend

The backend's OpenAPI schema is exported to `frontend/src/api/openapi.json`, and `npm run gen:api` generates
`frontend/src/api/schema.gen.ts` from it. Both files are generated and should not be edited by hand.
`frontend/src/api/contract.ts` is a compile-time check: each `Satisfies<Served<S["X"]>, FrontendType>` line fails
`tsc -b` when a backend response model no longer fits the hand-written frontend type it is read into. A new typed
`request<T>()` against an endpoint with a response model should get a line there.

## Main screens for the extraction path

| Screen | File | Backend it drives |
|---|---|---|
| Extraction | `frontend/src/pages/Extraction.tsx`, `frontend/src/pages/extraction/*` | `POST /api/extraction/start` (`api.startExtraction`), schema drafting and rule suggestions, run results and review decisions per profile, cancel |
| Review Queue | `frontend/src/pages/ReviewQueue.tsx` | `GET /api/review/items`, `POST /api/review/runs/{run}/items/{key}/decision` (`api.decideItem`) |
| Run History | `frontend/src/pages/RunHistory.tsx` | `/api/runs` list, resume, cancel, diff, export |
| Company | `frontend/src/pages/Company.tsx` | `/api/companies/{ref}`, `/api/companies/{ref}/facts`, `/api/facts/{id}/trail` |

The Review Queue is a single inbox across every run with flagged items, sorted lowest confidence first. Opening it from
`#/review/<kind>/<run id>` starts it filtered to that run. Decisions are append-only on the server, so a decided item
stays in place collapsed, and choosing "Change" records a new decision. The keyboard shortcuts A, C and R open the
approve, correct and reject form of the focused card. `SourcePanel` shows the cited source page next to the item.

Long-running work is polled with `usePoll` and `pollAfter` (`frontend/src/lib/poll.ts`), which pause while the tab is
hidden and fire as soon as it is visible again. For example, `frontend/src/pages/extraction/useRunManifest.ts` polls
`api.getRun`.

The current pages do not call publishing. That happens through the API or the CLI (see
<!-- openwiki: broken internal link [/openwiki/pipeline/publish.md] link "/openwiki/pipeline/publish.md" is root-absolute, which no real consumer resolves against the repository root (not a coding agent reading the page, not GitHub's Markdown renderer, not a local viewer); use a path relative to this file instead. Fix the href or restore the target, then delete this comment. -->
[Publishing facts](/openwiki/pipeline/publish.md)).

## Cross-origin isolation

`frontend/vite.config.ts` sends `Cross-Origin-Opener-Policy: same-origin` and
`Cross-Origin-Embedder-Policy: require-corp` from both the dev and preview servers, and `frontend/nginx.conf` does the
same in production. Decision Studio's rule engine runs as threaded WebAssembly, which needs `SharedArrayBuffer`, and
browsers only allow that on an isolated page.

## Checks

`npm run lint` (oxlint), `npx tsc -b` (which includes the API contract) and `npm test` run Node's built-in test runner
over `frontend/tests/*.test.ts`. These tests cover pure helpers in `frontend/src/lib` and page modules, for example
`reviewKeys`, `fieldValue` and `sourceText`.
