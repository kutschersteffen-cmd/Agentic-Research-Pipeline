# Process View

The app has 16 functions and some 30 screens. The team thinks in *processes*, though:
"we're onboarding a mandate", "it's proxy season", "the committee wants the climate
review". The app is organised around five **workspaces** that mirror the business,
each running its processes over the existing screens. The start page shows the five
as boxes; each box opens a workspace page (`#/<workspace id>`) that draws its
processes step by step and lists its screens, so a process can be walked end to end
or a single step run by hand.

Above the boxes, **Needs you** lists everything waiting on a person, oldest first:
each run with items to review, each proxy-voting run with ballots to decide, each
Steward Workflow stage with open decisions, and blocking data issues. Every row links
to where it is decided. Below it, **Now** shows only runs that are running or failed.
Both are computed from the run store, the stewardship flow and the issues list; nothing
new is stored.

**Run process** appears only on processes with an engine behind them. Argus *Extract and
score* opens Extraction with every handover automatic (`#/extraction/companies/auto`):
pick the companies and Identify, Documents and Extract follow, stopping wherever something
is flagged. Transition Intelligence *Monthly monitoring* runs last month and lists what
blocked it, if anything. The other processes are human decisions step by step, so they
have no such button.

**Smart Search** (Data Hub, `#/smartSearch`) answers plain-language questions about open
issues, stored outputs and input feeds ("unmatched holdings in PF-1", "outputs nobody
uses"). The model only turns the question into a filter over a fixed vocabulary
(`backend/arp/smart_search.py`); code applies it, counts the rows and shows the filter with
the answer. It never sees the rows or states a number, and every call is audited like Ask
the Portfolio. Questions outside that vocabulary (a figure's change over time, exposure
amounts) get a pointer instead of a guess.

## Principles

1. **A process is a path through existing screens, not a new screen.** Each step
   links into the screen that already does the work, often in another workspace:
   processes cross boxes. The workspace page only holds the order, the handoffs and
   the live status of each step.
2. **Name the handoff.** Every step says what it hands to the next (a resolved
   universe, a ratified taxonomy, decided ballots). If you can't name it, it isn't a
   step.
3. **Show which handoffs are manual.** A dashed line means the person re-uploads
   or re-selects something by hand today. Those are the gaps; we show them instead
   of drawing a smooth line over them.
4. **"Done when" is an outcome a committee would accept**, not "the run finished".
5. **Status comes from the run store and the house stewardship flow.** No new state
   is kept: each step shows the latest run of its type, the items waiting on a
   person, or its Steward Workflow stage's open decisions.

## The workspaces and their processes

| Workspace | Purpose | Processes |
|---|---|---|
| **StewardIQ** (`#/stewardiq`) | Engage, vote, escalate, report to clients | Engage and escalate · Proxy season · Client reporting |
| **Argus** (`#/argus`) | Extract cited data points and score them with ratified Decision Studio templates; XBRL facts as filed | Extract and score · XBRL facts |
| **Transition Intelligence Platform** (`#/transitionIntel`) | Monitor holdings; assess climate and transition risk | Monthly monitoring · Climate transition review |
| **R&D Lab** (`#/rdLab`) | Themes and strategies, scored and built into indices | Launch a thematic product · Research a strategy |
| **Data Hub** (`#/dataHub`) | Input feeds and stored data; the security master maps every security to its internal issuer, once, for the whole tool | Map securities to issuers |

| Process | Cadence | Steps | Done when |
|---|---|---|---|
| **Engage and escalate** | Continuous | Steward · Monitoring → Selection → Engagement → Drafting → Tracking (↺) | Every issue has an owner, a next step and a documented escalation path |
| **Proxy season** | Per meeting, peaks March–June | Proxy Voting → Steward · Voting → Steward · Checkpoint → Engagement | Intentions are published, votes cast are checked against policy, and outcomes feed engagement |
| **Client reporting** | Quarterly | Steward · Client program → Client policy → Reporting → Reports | A client report of house activity plus the points where the client's policy differed |
| **Extract and score** | Per universe | Universe → Companies → Identify → Documents → Schema (custom only) → Extract → Review → Score (optional) → Template in Decision Studio (optional); Universe is the landing page (`#/argusUniverse`) and the next five are the Extraction screen's own tabs (`#/extraction/<step>`) | Every company resolved and documented, every figure cited and reviewed; tiers from a ratified template |
| **XBRL facts** | Per universe | Universe → Fetch → Facts → Verify; Facts hands over to Verify by hand (dashed) | Every company routed to the SEC or ESEF index or marked `no_source` / `unrouted`; filed facts stored and checked against an extraction run |
| **Monthly monitoring** | Monthly | Holdings Intake → Monitoring & Alerts → Dashboards → Steward · Monitoring | Every breach and controversy on a holding is an alert with an owner |
| **Climate transition review** | Annual, plus ad hoc before committees | Risk Monitoring → Transition Barriers → Transition Plan → Decision Studio → Steward · Selection → Reports | A tiered list of issuers to engage, each with a walk-vs-talk verdict and sector context |
| **Launch a thematic product** | Per product idea | Emerging Themes → Taxonomy Library → Thematic Universe → Review Queue → Decision Studio → Index Construction → Reports | A ratified theme, a reviewed universe and an effective-dated index calibration |
| **Research a strategy** | Per paper or idea | Strategy Replication → Decision Studio → Index Construction → Reports | Tested out of sample, compared with alternatives, and built as an index if it holds |
| **Map securities to issuers** | When the security master or a holding changes | Load security master → Map holdings → Unmatched → Data Library | Every held security mapped to exactly one internal issuer by the security master, and nothing mapped any other way |

**Argus · Universe** (`#/argusUniverse`, `POST /api/universe/workbench`) is the first step of both Argus processes.
The user uploads or picks a saved universe; the page maps every company through the security master (exact LEI,
ISIN or CIK only), suggests an XBRL source (SEC or ESEF, or `no_source` / `unrouted` with the reason) and shows what
the tool already holds: identity result, documents, extraction runs and XBRL files. Companies are ticked (or the whole
universe is taken) and handed to Extraction or XBRL facts as a saved universe, enriched with the master's missing
LEI, CIK and ISIN. The page never starts a run itself.

**The security master is the golden source for issuer identity.** It is loaded only in Data Hub
(`#/securityMaster`, approvers only; CSV/Excel now, an API source later) into the identifier map
(`data/identifier_map.jsonl`): an internal issuer id per row, with any of ISIN, CUSIP, SEDOL, FIGI, LEI
and CIK. A load replaces the master whole (the previous one is archived) and is refused if any row is
invalid or one identifier points at two issuers over the same dates. Matching is exact everywhere:
holdings map by ISIN (or the row's LEI) through it, and extraction and Argus's Identify step use the
internal issuer id whenever the master knows the company's LEI, ISIN or CIK. Nothing is matched by name
and no issuer is assigned by hand; an unmatched security is listed in Data Hub and fixed in the master.
Holdings are mapped as they load, so reload them after a master change. The Argus Universe page and XBRL Auto
routing use the master the same way, read-only: it fills a company's missing LEI, CIK and ISIN (never country) before
routing, and a CIK from the master counts like one on the row.

**Data Hub · Feeds** (`#/feeds`, `GET /api/feeds`) lists every input feed (security master, portfolio holdings,
index constituents, ESG data, news) with its data date, last load and whether it is behind: its latest good load
is older than last month end, or nothing is loaded. It only reads the existing load records; loading stays on
Holdings Intake and the Security Master screen. "Pull now" fetches from the API for API-fed holders, ESG and news
(`POST /api/feeds/esg/pull`, `POST /api/feeds/news/pull`). News articles are tied to issuers through the security
master only (ISIN or LEI); an article it cannot match is stored without a company. The news and ESG vendors' formats
are assumed until known.

**Data Hub · Issues** (`#/issues`, `GET /api/issues`) is every open data problem in one list, blocking first:
feeds behind or whose last load failed, held securities the security master does not map, and failing checks
(warn or block) on the latest extracted value of each field that no reviewer has decided yet. Nothing is re-run or
guessed: it reads the feed overview, the identifier map and the check results stored with each extraction run. Within
a severity, feed and master problems come before check findings, which may only be their symptom. Each issue links to
where it is fixed (Feeds, Security Master, or the run in the Review Queue).

**Data Hub · Outputs** (`#/outputs`, `GET /api/outputs?kind=`) is the output catalog: every stored result one step
produces and another can use (saved universes, runs, published scores, taxonomies, index calibrations) in one shape,
newest first, with its status, author and **Used by**: what has already read it. Nothing is copied: it reads the
existing stores and the links consumers record (a run's universe and taxonomy, a Decision Studio table's source run,
an index review's publications and calibration, a report's runs and decisions). Extraction runs started from one
saved universe record it in `inputs.json`; theme runs record the taxonomy version their theme came from, unedited.
Stewardship always reads the latest publication and records nothing.

The same catalog backs one shared picker (`components/InputPicker.tsx`): newest first, with date, status and author;
drafts and unfinished runs stay pickable but are marked. Every universe picker offers "Or pick a saved universe", and
Thematic Universe preselects the newest ratified taxonomy.

The workspaces, processes and steps live in `frontend/src/lib/processes.ts`: one
registry to edit when a process changes. Old links (`#/processes/<id>`,
`#/themeMachine`, `#/designStudio`) open the matching workspace.

## Manual handoffs to close, most valuable first

Each of these is a place where a person carries data between screens by hand.
They are listed by how often a process crosses them.

1. ~~**Decision Studio → Steward · Selection / Index Construction.**~~ **Closed.**
   A ratified framework's result can be *published*: frozen, signed by a named
   person, with each row matched to an issuer by its id column (`Company_Id`,
   `issuer_id`, …). Consumers read the latest publication per framework as
   ordinary company fields, `decision.<framework_id>.tier` / `.score` / `.rank`:
   - **Steward · Selection**: the fields reach the coverage rules as
     `issuer.decision.<framework_id>.*`. A person adds a column that uses them,
     and tier changes are confirmed at stage 5 as before. The studio lists each
     publication and how many issuers in scope it matched.
   - **Index Construction**: pick a publication under *Start from a preset*. Its
     fields join the universe by company id and become pickable in every rule.
     A candidate without a match lacks the field, so the rule's missing-value
     policy decides. A review dated before the publication is refused, and the
     review records which publications it read.
   Strategy research stays manual here: its rows are strategies, not companies.
2. ~~**Proxy Voting run → Steward · Voting / Checkpoint.**~~ **Closed.** The
   stewardship flow reads every Proxy Voting run (`arp/stewardship/voting_feed.py`):
   - **Steward · Voting** shows the decided ballots next to the policy's
     recommendation, plus live counts (items decided, votes against management).
   - **Steward · Checkpoint** lists every vote decided against the policy's
     recommendation, with the decider, co-signer and reason, for review.
   - Per issuer, the counts become company fields (`vote.decided`,
     `vote.against_management`, `vote.overrode_policy`, `vote.last_meeting_date`),
     so any stewardship rule can use them.
   The expected-vote metrics on the synthetic meeting sample stay as they were.
3. ~~**Document Discovery → Extraction / Transition Plan.**~~ **Closed.** Once a
   discovery run starts, Document Discovery offers "Extraction →" and
   "Transition Plan →" with the same universe, so nothing is uploaded twice.
4. ~~**Risk Monitoring → Transition Plan / Steward · Monitoring.**~~ **Closed.**
   - Under the portfolio selection, "Use the companies held in … in:" saves the
     companies held in the selected portfolios (as of the selected date) as a
     universe and opens Transition Plan, Extraction or Document Discovery with
     it. Holdings that don't resolve to a company are left out and counted.
   - Open Risk Monitoring alerts (open, acknowledged or escalated) become
     company fields, `alert.open_news_controversy` and
     `alert.open_threshold_breach`. Two new default house monitoring rules
     raise a stewardship trigger from them, and Steward · Monitoring opens the
     engagement. Alerts match stewardship issuers by company id.
5. ~~**Checkpoint → Engagement.**~~ **Closed with gap #2.** A new house monitoring
   rule (`vote_against_management`) raises a `vote_outcome` trigger when we voted
   against management; Steward · Monitoring opens the engagement from it. The
   trigger reads *our* vote, not the meeting result: vote results (support
   levels) have no feed yet. An installation that already saved its own
   monitoring rules needs the row added in the rule editor; the default applies
   only where no version was saved.
6. ~~**Extraction / Transition Plan → Decision Studio.**~~ **Closed.** A saved
   framework is a scoring template: pick one in the run's "Score the results"
   step (or attach it after the run) and the run is scored with that version
   pinned, shown under the run. Decision Studio is where the template is built,
   tuned and ratified; see `DECISION_MECHANISM.md` §7a. Once the run has
   finished and its template version is ratified, the run's Scoring panel
   publishes the tiers to Steward · Selection and Index Construction directly.
7. **Transition Barriers → Transition Plan.** Sector context is read, not joined.
   Fix: show the issuer's sector × jurisdiction barrier cells next to its
   walk-vs-talk verdict.

### One set of companies

Steward Workflow's overview has a house setting, **Companies covered**:
*Synthetic sample* (the default, 12 fictional companies with meetings and rich
company data) or *Portfolio holdings* (the companies held in the house
portfolios). On portfolio holdings, stewardship issuer ids are the portfolio
company ids, so Decision Studio publications, Proxy Voting ballots and Risk
Monitoring alerts all match. The holdings supply AUM held, the share of house
holdings (in place of an index weight) and position changes. Company fields are
the latest portfolio data points plus a placeholder CLTI score, and figures are
labelled "portfolio holdings". What the holdings don't carry (meetings,
governance data, engagement history) is left empty, not invented, so for
example expected votes read 0 until agendas arrive.

The universe handoff between screens is one piece of state in `App.tsx` that
records its sender and its destination, so only the addressed screen picks it
up and names where it came from.

## Deliberately not done

- **No process instances or process state.** A "run of the climate review for Q3"
  object would duplicate what runs, streams and calibrations already record. Add
  one if the team needs to see a process's history as one record.
- **No stepper that locks the order.** Steps are links, and real work loops back
  and skips steps.
