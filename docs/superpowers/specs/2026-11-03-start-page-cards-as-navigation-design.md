# Start page: workspace cards as navigation

Status: approved by owner 2026-11-03. Follows four `/impeccable critique` runs of the start page (27, 26, 27, 26 out of 40).

## Why

The start page reports the same waiting work twice. The Needs you list counts every decision ("Review 7 items",
"Resume failed run"), and the five workspace cards repeat those counts in a footer ("7 waiting on you · 1 failed").
Four rounds of fixes made the two agree, but the critiques kept scoring consistency and minimalism 2/4 because a
reader still has to reconcile them. On a busy day the signal colour appears about 15 times. In light mode the
footer's "waiting" and "failed" text measure 1.01:1 apart, so the split added in #320 cannot be seen.

## Decisions

| Topic | Decision |
|---|---|
| One status | Needs you, the headline ("N decisions wait on you.") and the "waiting on you" stat are the only places that count waiting work. They do not change. |
| Card role | A card is a way into its workspace. It keeps: icon, name, purpose line, the process dots, the one mono line naming the process that matters now, and "Open →". |
| Card footer | The status text goes: no "N waiting on you", no "N failed", no "N running", no "Nothing waiting", no "Status unknown". The footer is "Open →" alone. |
| Non-numeric cues stay | The dots keep their states (signal = waiting, red diamond = failed, ring = running, ink = done, hollow = idle, dashed = unknown). The icon's signal accent and the card's ink border still mark a card that waits on someone (DESIGN.md Icon Accent Rule). |
| Now line | Names the first waiting process, else the first running or failed one, else "Last run <n> ago", else "No runs yet". The "Listed under Needs you" fallback added in #320 goes, since the card no longer shows a count it has to explain. |
| Screen readers | The card link's label is "<Name>. <process>: <state>; <process>: <state>…", with no count. |
| Data issues | A blocking data issue is not a process. It counts in Needs you and the headline, never on a card. |
| Backend down | When runs could not be loaded, every dot is dashed (unknown), the now line is an empty element, and the footer is "Open →". |
| Testable seam | What a card shows is computed by one pure function, `cardView(workspace, runs, flow, now: Date)` in `frontend/src/lib/` (`now` is passed in, not read from the clock), returning `{ dots, now, footer, label, awaits }`. The card renders only that. `awaits` is true exactly when at least one entry of `dots` is `"wait"`; it drives the ink border and the icon accent. A failed run alone does not set it (the red diamond shows it). |
| DESIGN.md | The Process Card section drops "and a status in the signal colour when someone is needed". |

## Non-goals

- The Needs you list, the headline, the stats row, the Now row and the Engagement line.
- The sidebar badge wording and the failed row's link target (separate small fixes).
- Removing the cards or moving them to the sidebar.

## Acceptance

`unit` rows call `cardView` with these fixtures (`now` = 2026-11-03T12:00:00Z; each run's `updated_at` is 2 h before `now` unless stated):

Unless stated, a run's `review_count` is 0 and `flow` is `{ stages: [] }`. A stage with "2 open decisions" is a `StewardshipStage` whose `decisions` holds 2 entries of a kind other than `policy_difference`. The same `flow` is passed for every card.

- **busy:** Argus: an `extraction` run with `review_count` 7, status `completed`. R&D Lab: a `theme` run with status `failed`. Transition Intelligence Platform: a `transition_plan` run with status `running`. StewardIQ: a `proxy_voting` run with status `completed` and `review_count` 3; the flow's `drafting` stage has 2 open decisions. Data Hub: no runs. (The `transition_plan` run also matches the Argus run types; that is intended and changes no row below.)
- **calm:** the same five workspaces; Argus: one `extraction` run, status `completed`, `review_count` 0; every other workspace has no runs and the flow has no open decisions.
- **down:** `runs` is `null` and `flow` is `null`.

| ID   | Given | When | Then (observable, exact) | Checked by |
|------|-------|------|--------------------------|------------|
| AC-1 | busy | `cardView` runs for each of the five workspaces | Every result's `footer` is exactly `"Open →"`. | unit |
| AC-2 | calm | `cardView` runs for each of the five workspaces | Every result's `footer` is exactly `"Open →"`. | unit |
| AC-3 | down | `cardView` runs for each of the five workspaces | Every result's `footer` is exactly `"Open →"`. | unit |
| AC-4 | busy | `cardView` runs for R&D Lab | `dots[0]` is `"failed"`. | unit |
| AC-5 | busy | `cardView` runs for Argus | `dots[0]` is `"wait"`. | unit |
| AC-6 | busy | `cardView` runs for StewardIQ | `dots[0]` and `dots[1]` are both `"wait"`. | unit |
| AC-7 | busy | `cardView` runs for Transition Intelligence Platform | `dots` contains `"now"`. | unit |
| AC-8 | busy | `cardView` runs for Data Hub | `dots` is `["idle"]`. | unit |
| AC-9 | busy | `cardView` runs for each workspace | `awaits` is `true` for Argus and StewardIQ and `false` for R&D Lab, Transition Intelligence Platform and Data Hub. | unit |
| AC-10 | busy | `cardView` runs for R&D Lab | `now` is `"Launch a thematic product"`. | unit |
| AC-11 | busy | `cardView` runs for Data Hub | `now` is `"No runs yet"`. | unit |
| AC-12 | calm | `cardView` runs for Argus | `now` is `"Last run 2 h ago"`. | unit |
| AC-13 | down | `cardView` runs for each workspace | `now` is `""` and every entry of `dots` is `"unknown"`. | unit |
| AC-14 | busy | `cardView` runs for Argus | `label` is exactly `"Argus. Extract and score: waiting on a person; XBRL facts: no activity yet"`. | unit |
| AC-21 | down | `cardView` runs for Argus | `label` is exactly `"Argus. Extract and score: status unknown; XBRL facts: status unknown"`. | unit |
| AC-15 | the app started by `backend/scripts/e2e_stack.sh up` | the start page `#/home` loads at 1440×900 | Inside `.hub-cards`, no element's text contains "waiting on you", "failed", "running", "Nothing waiting", "Status unknown" or "Listed under Needs you". | evaluator |
| AC-16 | the same app | the start page loads | Each `.hub-card-foot` element's text is exactly "Open →". | evaluator |
| AC-17 | the same app | the start page loads | Let N be the sum of the integers in every `.needs-you-count` element (0 if none). The second `<span>` of the `h1` in `.hub-hero` reads "N decisions wait on you." for N ≥ 2, "1 decision waits on you." for N = 1, "Nothing waits on you." for N = 0 (unchanged). | evaluator |
| AC-18 | the same app | the start page loads | The `.hub-stats` row still shows the four labels "waiting on you", "running", "failed this week", "done today" (unchanged). | evaluator |
| AC-19 | the same app | the start page loads | A `.hub-now` element is present and its first text is "Now", and a `.hub-engagement` element is present (unchanged). | evaluator |
| AC-22 | the same app | the start page loads | Every `.hub-card` that contains a `.hub-dot-wait` dot has the class `hub-card-await`; every `.hub-card` without one does not. | evaluator |
| AC-20 | this PR's DESIGN.md | it is read | The Process Card section does not contain "a status in the signal colour when someone is needed". | unit |

Must not change: the headline count (AC-17), the stats row (AC-18), the Now row and Engagement line (AC-19). Needs you is
untouched by this change; its existing tests cover it.
