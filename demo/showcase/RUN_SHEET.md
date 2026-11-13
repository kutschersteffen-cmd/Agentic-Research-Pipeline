# Run sheet: ARP showcase, 17 Nov 2026 (60 minutes)

Four workspaces, one storyline: ten listed companies (RWE, E.ON, Engie, BASF, thyssenkrupp, Heidelberg
Materials, NextEra, Duke Energy, Nucor, Dow). Scenes T1 and R3 use public index portfolios instead.
Click paths are for the app on `main` of 13 Nov; "Depends on" below says which open PR changes a screen and
what to do without it.

Simulated: the ESG values, controversial revenue shares, transition grades (A to F) and the June to October 2026 holdings history come from `data/simulated/esg_simulated.csv`; say "simulated" whenever one is on screen.
Invented: the three trigger-scan rows in S2 and the client name "Demo Pension Fund"; nothing else is invented.

Holdings are public ETF holdings files (DWS constituent exports as of 2 Nov 2026, AI & Big Data as of
12 Nov 2026); no position of the bank is shown.

## Day before

1. In the Jupyter terminal: `scripts/launch_jupyter.sh up`, then `scripts/launch_jupyter.sh check` (the
   `fetch` line says whether live document search will work; the show does not need it).
2. Save the 14 PDFs listed in `demo/showcase/documents.csv` into `demo/showcase/documents/` under their
   `file_name`. Each annual report needs a text layer with the company name on its first pages.
3. Load the pack, from `backend/`: `python scripts/load_showcase_pack.py`. It takes about 5 minutes
   (`arp showcase load` alone about 3). Every line must read `ok`; a `skip portfolios` line means #434 is not
   merged yet (T1 and R3 then fall back, see below). Run it again whenever you like: nothing doubles.
4. Taxonomy for R2: Taxonomy Library → New taxonomy → method "LLM draft (freeform)", theme "Energy transition" →
   Draft & save taxonomy → review the drafted activities and accept them (edit any you would not show, then
   "Save adjustments as new version"). Then Library → "Energy transition" → Ratify version → generate its
   schema → Release schema (the release records you as the approver).
5. Thematic run for R2: Thematic Universe → Saved taxonomy "Energy transition" → Load → 3. Choose the
   company universe → "Or pick a saved universe": "Showcase companies (10 companies)" → Start run.
6. Prepared alert for T1's fallback: Risk Monitoring → Monitoring & Alerts → Add a monitoring rule: name
   "Prepared: carbon intensity above 40", rule type "Portfolio aggregate (WACI-style)", field "Carbon
   intensity", "> greater than", 40 → Add rule. Then Holdings Intake → Monthly run → month 2026-10 → Run now.
   Monitoring & Alerts then lists open alerts on the public index portfolios (DAX among them), each ending
   with a `Simulated:` sentence; AI & Big Data stays below 40.
7. Wait until these runs show as finished: `argus-capex` and `argus-plan` in Argus (start page list, status Finished), `voting` in StewardIQ → Proxy Voting (run list), and the R2 thematic run in Thematic Universe (4. Run progress).
8. Open the prepared capex extraction once (Argus start page, the row "Transition capex, R&D and redline
   facts v1", 10 companies) and pick the value you will correct in A2. Argus has no name for an
   extraction: the loader calls it "Showcase: transition capex", the list shows the template's name.

## 0 to 12 · Argus

A1 (live, minute 2). Argus → New extraction → step 1: upload `demo/showcase/companies.csv` (10 companies,
each with LEI) → step 2: "I upload them", attach `RWE_annual_report_2025.pdf` and
`NEE_annual_report_2025.pdf` → keep the files that pass → step 3: template "Transition capex, R&D and
redline facts" → Start. Leave it running; it comes back in minute 48.
Depends on Argus fixes PR 2 (#435, steps 1 to 3 in the browser): wording and buttons may move; the steps stay.
Fallback A1: open the prepared capex extraction instead and say the live one would look the same in 10 minutes.

A2 (prepared). Argus start page → the prepared "Transition capex, R&D and redline facts v1" row → step 5
Results: values per company → click a value to see its source passage → correct the value chosen the day
before → approve → download CSV.
Depends on Argus fixes PR 3 (steps 4 and 5, Results).
Fallback A2: Review Queue (Argus → Review Queue) shows the same values with their passages.

## 12 to 24 · Transition Intelligence

T1 (live). Risk Monitoring (`#/portfolio-monitoring`) → Holdings Intake: the seven public portfolios
(DAX, EURO STOXX 50, MSCI EM, MSCI Europe, MSCI World, S&P 500, AI Big Data), loaded June to November
(June to October is simulated history). → Monitoring & Alerts → Add a monitoring rule: name
"Carbon intensity above 45", rule type "Portfolio aggregate (WACI-style)", field "Carbon intensity",
"> greater than", 45 → Add rule → Holdings Intake → Monthly run → month 2026-10 (already filled in) →
Run now → Monitoring & Alerts: the new alert on "DAX (public ETF holdings, 2026-11-02)" (October WACI about
50) with its `Simulated:` sentence. AI & Big Data stays clear (about 14).
Depends on #434 (public portfolios, simulated ESG, monthly runs); without it there is no public portfolio:
skip T1 and go to T2.
Fallback T1: the prepared alerts of "Prepared: carbon intensity above 40" (day before, step 6) are already in
Monitoring & Alerts.

T2 (prepared, `argus-plan`). Search "RWE AG" → company page → Transition section: sector "Power & Utilities",
the transition plan indicators from the RWE annual report → Transition Barriers → one cell of the barrier
matrix for Power & Utilities.
If showcase-portfolio-data PR 3 is merged, Risk Monitoring → Company Profiles also shows a "Simulated ESG"
card with the A to F grade; say "simulated".
Fallback T2: the Transition section's sector and capex lines come from the registry and the capex
extraction alone; show those if the plan run did not finish.

## 24 to 36 · R&D Lab

R1 (live, 4 minutes). Taxonomy Library → ETF holdings overlap: display name "DAX", file
`demo/showcase/etf_dax.csv`; display name "EURO STOXX 50", file `demo/showcase/etf_euro_stoxx_50.csv` →
Compute holdings overlap: 17 core holdings (both index funds hold them), and the weight-adjusted overlap.
Then Universe builder → 2. Build a company universe from a holdings export → `demo/showcase/etf_ai_big_data.csv`
(100 equities of the AI & Big Data index fund).
Depends on Themes fixes #429 (universe upload) and Themes fixes PR 2 (screen polish); the overlap works on `main`.
Fallback R1: the overlap needs no model; if an upload fails, show the three files' `Source:` lines in `demo/showcase/README.md`.

R2 (prepared by hand, 4 minutes). Thematic Universe → the run on "Showcase companies" with the ratified
"Energy transition" taxonomy: verdict and evidence per company, click one passage.
Depends on Themes fixes #429 (decompose save, run card, web citations).
Fallback R2: Taxonomy Library → Library → "Energy transition": the ratified activities, and why each company would match.

R3 (live, 4 minutes). Index Construction → Starting universe "DAX.xlsx" (40 companies, holdings as of
2026-11-02, simulated ESG fields matched) → Start from a preset "eu_pab" → add a screen on the simulated
`transition_grade` (leave out F) and on controversial revenue (`coal_revenue_pct` above 5) → Preview:
constituents, weights, and the notes "Starting universe: DAX.xlsx ..." and "Simulated ESG data: matched ...".
Depends on index-starting-universe PR 2 (the starting-universe card); its backend is on `main`.
Fallback R3: without that PR, Index Construction runs on the built-in demo universe: say it is synthetic (60
invented companies), load the preset "eu_pab" and Preview.

## 36 to 48 · StewardIQ

S1 (prepared, `voting`). StewardIQ → Proxy Voting → the run for NextEra, Duke Energy, Nucor and Dow: per
resolution the recommendation and the reason, with the proxy statement passage.
Fallback S1: Review Queue → the run's open items, which show the same recommendations.

S2 (live). Engagement → Trigger & detection scan. Companies: NEE "NextEra Energy Inc", DUK "Duke Energy Corp",
NUE "Nucor Corp". Signals (the trigger-scan rows; invented, say so):

| Company ID | Theme | Severity | What happened |
|---|---|---|---|
| NEE | climate_transition | high | Invented demo signal: capex plan delays a coal exit by two years |
| DUK | executive_compensation | medium | Invented demo signal: say-on-pay support fell below 70% |
| NUE | board_diversity | low | Invented demo signal: no new independent director this year |

→ run the scan: three trigger events. Then Steward Workflow (`#/stewardship`) → Add a client stream:
client name "Demo Pension Fund", no file (the stream starts from the example envisioned policy) → Create
stream → show where the client policy differs from the house policy.
Fallback S2: the three trigger events stay listed under Engagement after the scan; the example policy needs no model.

## 48 to 60 · Argus, questions

The A1 extraction from minute 2 is finished: Argus start page → its row → Results. Off-script: an analyst
names a company (step 1 single-company form, upload its report in step 2) or types what to extract
(step 3 → a new template drafted from the request).
No scene of its own has a fallback here: if the A1 run is not finished, show its progress (step 4) and A2.

## Depends on

| PR | Scenes | Without it |
|---|---|---|
| #434 (showcase-portfolio-data PR 2, `arp showcase load`) | T1, R3 (simulated ESG fields) | `skip portfolios` in the loader; skip T1, R3 on the demo universe |
| Themes fixes #429 | R1 universe upload, R2 | R1 overlap only; R2 fallback (the ratified taxonomy) |
| Themes fixes PR 2 | R1, R2 screen polish | the same clicks on today's screens |
| index-starting-universe PR 2 | R3 starting universe | R3 on the built-in demo universe, called synthetic |
| Argus fixes PR 2 (#435) | A1 steps 1 to 3 | the same steps on today's screens |
| Argus fixes PR 3 | A2 and minute 48 (steps 4 and 5, Results) | Review Queue for the values and passages |
| showcase-portfolio-data PR 3 | T2 grade card, company page grades | no grade on screen; T1 alerts still say `Simulated` |

## Start from an empty database

There is no reset command. In the bank Jupyter: `scripts/launch_jupyter.sh down`; ask for the Postgres
database to be dropped and created again (or point `ARP_POSTGRES_DSN` at a fresh one); move `runs/` and
`data/documents/` aside; `scripts/launch_jupyter.sh up` (it migrates the new database); then the day-before
list from step 3.
