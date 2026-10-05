# Portfolio monitoring: alignment with stewardship monitoring

Status: draft for review. No code changed.

## Purpose

Make Risk Monitoring and the Stewardship Monitoring stage (stage 1 of Steward Workflow) work as one tool for two users:

- the **risk / sustainability analyst** (climate and ESG exposure, alerts, data issues);
- the **stewardship analyst** (which issuers to engage, and why now).

Scope is climate, ESG and stewardship signals. Financial risk (VaR, factor, stress) is out of scope.

## Decisions already made

| Decision | Effect |
|---|---|
| Delete the PCAF-style 1-5 data-quality score | The app has no such score today, so this only means it is not added. |
| Delete the **Governance & Audit** tab **and its backend** | UI, routes and `portfolio/governance.py` are removed. See "Governance & Audit removal" for what survives. |
| Delete the **climate data conflict panel** | The panel and its review flow are removed. |
| No role checks on write routes | Unchanged from today; out of scope. |
| Company Profile is a hybrid | A fixed action strip (engagements, triggers) above an embedded Superset dashboard that analysts lay out by drag and drop. See section 6. |
| Keep the `AlertRule` evaluator | Not replaced by stewardship's ZEN rule engine. |
| Keep entity resolution as part of the tool | Its review queue moves into Holdings Intake. |
| Superset for all dashboards and analytics | The in-app Standard Analytics tab is removed. |
| ESG and portfolio data arrive monthly by API | Both can also be uploaded as CSV or Excel. |

## Differences today (verified in code, unless marked)

| | Risk Monitoring | Stewardship Monitoring |
|---|---|---|
| Unit | Portfolio, holding, company field | Issuer, with holding, issuer and engagement-history context |
| Rules | `AlertRule` objects (threshold, concentration, drift, news) in `backend/arp/portfolio/monitoring/evaluator.py` | ZEN decision table, hit policy `collect`, in `backend/arp/stewardship/monitoring.py` |
| Rule lifecycle | Added or edited directly | Immutable versions, four-eyes activation, preview (`stewardship/policies.py`) |
| Output | Stored alerts with status (open, acknowledged, escalated, resolved, false positive) | Triggers (type, theme, severity, reason). **Not stored** |
| Change since last run | Alert history | Only `holding.change_pct` (latest vs previous snapshot) |
| Scheduling | `IntervalScheduler` | None. Re-evaluates on every request |
| Default data | Holdings snapshots, mock ESG and news | Synthetic `data/examples/sample_meetings.json`; real snapshots only if the universe setting is `portfolio` |
| Link between them | None in code except one direction: stewardship reads two open-alert fields (`alert.open_news_controversy`, `alert.open_threshold_breach`) via `stewardship/alerts_feed.py` | |

The Stewardship findings come from a read-only review and were not independently re-run. Not verified: the `/monitoring/run` endpoint, `escalation.contexts`, `voting_feed`, and `entity_resolution.py` internals.

## Target architecture

```
Monthly API ─┐
             ├─> Intake ─> Portfolio + ESG store ─> Superset (all dashboards)
CSV / Excel ─┘   (one validator)       │
                                        ├─> Entity resolution + review queue
                                        ├─> AlertRule evaluator ─> stored alerts ──┐
                                        └─> Stewardship ZEN rules ─> stored triggers ┘
                                                         shared company_id
```

### 1. Intake

- **Holdings:** already supported. `POST /api/holdings/upload` reads CSV or Excel through a per-provider mapping, validates and ingests with provenance (`backend/arp/api/routers/holdings.py`). A pull endpoint and csv/xlsx templates exist.
- **ESG data:** no upload route and no real API connector exist; the only source is `climate/mock_esg_source.py`. Add an upload route that mirrors the holdings one (same validator, mapping and provenance pattern) writing dated observations per company and field (Scope 1/2/3, intensity, EVIC, green revenue %), plus csv/xlsx templates.
- **Monthly API pull** for both data types calls the same ingest function as the upload route. One code path per data type.
- **Idempotency:** a load is keyed by (holder or provider, as-of month). Re-loading creates a new revision, as holdings already do. It never overwrites silently.
- **Failure handling:** a failed or partial monthly load blocks the downstream run for that month and is shown in Holdings Intake. Rules are never evaluated on half-loaded data.

### 2. Entity resolution and review panels

- Entity resolution stays. Its review queue (securities below the confidence threshold) moves from the deleted Governance tab into Holdings Intake, next to the load that produced it.
- The climate data conflict panel is **deleted**, not moved.
- The entity-resolution review threshold remains as configuration (settings), not UI and not a versioned policy.
- Known weakness to track: name matching uses `difflib.SequenceMatcher` on raw names, with no LEI or ticker path and no legal-suffix normalisation (`portfolio/entity_resolution.py`).

### 3. Alignment of the two rule systems (engines are not merged)

1. **Shared issuer ID.** Stewardship always reads the real `company_id` universe. The synthetic sample is no longer the default.
2. **Shared trigger shape.** Both tools emit issuer, type, theme, severity, reason and status. Risk alerts map onto this shape.
3. **Stored stewardship triggers.** Persist per monthly run with a "new since last run" flag, reusing the alert status workflow.
4. **Wider alert feed.** Stewardship receives every open alert type, not only the two fields it reads today.
5. **Monthly run model.** One run per monthly load: ingest, resolve entities, evaluate `AlertRule`s, then evaluate stewardship rules. This replaces re-evaluation on every page load.

### 4. Superset

- Superset reads only the `bi` views over **Postgres** (`backend/arp/bi/views.py`). Postgres becomes required for this tool.
- Existing datasets: `holdings`, `holdings_history`, `company_facts`, `company_facts_pending`, `run_records`, `documents`.
- WACI, financed emissions and coverage are computed in Python today (`climate/metrics.py`, `aggregation.py`). **Decision:** keep the formulas in Python and publish a `portfolio_climate_metrics` dataset (portfolio, as-of date, WACI, financed emissions, coverage, uncovered market value). Superset charts it. Do not re-implement the formulas in SQL.
- New datasets: `alerts`, `triggers`, and optionally `entity_resolution_queue`.
- Dashboards use the `arp-` slug prefix so the existing Dashboards tab embeds them: portfolio climate overview, trend over months, data coverage, alerts and triggers by status, issuer drill-down for stewardship, and the company profile dashboard (section 6).
- Ask the Portfolio (LLM Q&A) keeps computing in Python. It is the one analytics surface not moving to Superset.

### 5. Governance & Audit removal

Removed: the tab, the `/api/portfolio/governance/*` routes, risk-category ownership, the policy-change history, climate-conflict review, and `backend/arp/portfolio/governance.py` with its store methods (`list_governance_events` and the append path in the file and Postgres stores) and `schemas/governance.py`.

**Dependency that must be resolved, not just deleted.** `governance.py` is not only the tab's backend:

- `record_decision` and `latest_decisions` are how accept / override / reject on the entity-resolution review queue are stored. Entity resolution is kept, so this decision log must move into the entity-resolution module (keep the append-only log and per-item latest decision; drop the climate-conflict item type).
- `get_current_policy` supplies the review threshold to `routers/portfolio.py` (line 42) and `cli/portfolio.py` (line 34). Replace it with plain settings values.
- `list_pending_reviews` feeds the queue in the UI; keep only the entity-resolution part.

| Content on the tab | Outcome |
|---|---|
| Methodology settings | Settings values; no change history |
| Risk category ownership | Deleted. Alerts have no owner field |
| Entity-resolution review queue | Kept, moved to Holdings Intake; decisions stored by the entity-resolution module |
| Climate data conflicts | Deleted |

Open follow-up for the plan: `climate/validation.py` (the API-vs-extracted conflict check) only existed to feed the conflict panel. Delete it too only after the references in open question 2 are checked.

### 6. Company Profile (hybrid)

The current Company Profiles tab (`frontend/src/pages/portfolio-monitoring/CompanyProfiles.tsx`) shows a fixed list of fields for one issuer. It is replaced by two parts on one page.

**Action strip (fixed, native UI), above the dashboard.** Always shows, for the selected issuer:

- **Engagements:** open and stalled engagements with step and theme, and an **Open engagement** action. The backend action already exists (`POST /api/stewardship/monitoring/open-engagement`, `api/routers/stewardship.py`).
- **Triggers:** stored stewardship triggers (section 3) with type, severity, reason, status and "new since last run", with actions to acknowledge, resolve or open an engagement from the trigger.
- **Alerts:** open risk alerts for the issuer, with the existing status transition (`POST /api/portfolio/monitoring/alerts/{scope_id}/{alert_id}/transition`).
- Issuer picker and as-of month. The picker drives the dashboard below.

**Dashboard area (Superset), below the strip.** One Superset dashboard per profile layout, embedded through the existing embed SDK path (`SupersetBI.tsx`, guest token). Analysts build and rearrange it in Superset's own drag-and-drop editor with a company filter. No custom grid library is added to the frontend.

- Needs a `company_profile` dataset: latest value per company and field from `company_facts`, plus holdings by portfolio, so charts can show emissions, intensity, EVIC, green revenue share, exposure by portfolio and trend over months.
- `alerts` and `triggers` datasets (section 4) are also usable as profile charts.
- A shipped default profile dashboard (`arp-company-profile`) is provisioned from code so the page is useful before anyone builds a layout. Analysts copy it to make their own; copies use the `arp-` slug prefix.
- **How the selected issuer reaches the dashboard** is not verified. Two candidates: a row-level-security clause in the guest token (robust, but the filter cannot be changed inside Superset), or a native-filter value passed to the embed. The plan must test which one the embed SDK in this repo supports.

**What is deliberately not built:** a custom in-app widget grid, widget registry or layout storage. If analysts need widgets Superset cannot draw (for example free-text notes or engagement timelines), those go in the action strip, not in the dashboard.

**Permissions caveat:** who may edit dashboards in Superset is governed by Superset roles, not by this app. Role checks in this app remain out of scope.

## Out of scope

Financial risk analytics, benchmark-relative analysis, SFDR PAI indicators, replacing the `AlertRule` engine, a PCAF data-quality score, role checks on write routes.

## Open questions

1. **Provider API.** The format is unknown. It is a corporate internal API that requires authentication. The plan builds a pluggable provider mapping (column mapping, units, paging) and an authentication hook (credentials from environment or secret store, never in the repo), plus one generic reference mapping to test against. The real mapping is filled in once the API is specified.
2. Resolved: `climate/validation.py` is called only by `portfolio/mock_data.py` (demo generation), so it is deleted with the conflict panel. The generic event-log store methods stay, because the entity-resolution decision log and monthly load records use them.

Resolved: backend governance code is deleted (with the entity-resolution dependency above); the climate conflict panel is deleted; role checks on write routes are out of scope.

## Risks

- Requiring Postgres changes how the demo and local setup run (the demo dataset currently works on files).
- Removing Standard Analytics before the Superset dashboards exist leaves a gap; the plan must order the work so dashboards land first.
- The profile's issuer-to-dashboard link (section 6) is unverified and could force a different embed approach.
- Stored stewardship triggers add a new store and a migration for any existing consumers (program selection, escalation).

## Testing approach

- Unit tests for the ESG validator and mapping, idempotent re-load, and failed-load blocking.
- A page-level check that the profile action strip renders for a seeded issuer and that the embed receives the issuer.
- A test that both tools produce the shared trigger shape for the same issuer.
- A run-level test for the monthly sequence on the seeded demo data.
- Dashboard definitions provisioned from code and checked by the existing BI tests.
