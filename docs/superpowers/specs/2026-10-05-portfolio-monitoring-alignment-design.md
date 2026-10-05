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
| Delete the **Governance & Audit** tab | Removed from the UI. See "Governance & Audit removal" for what happens to its content. |
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
- Climate data conflicts (API value vs extracted value beyond tolerance) move the same way, as a second panel. This is a proposal; drop it if conflicts are not wanted.
- Thresholds (entity-resolution review threshold, conflict tolerance) remain as configuration, not UI.
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
- Dashboards use the `arp-` slug prefix so the existing Dashboards tab embeds them: portfolio climate overview, trend over months, data coverage, alerts and triggers by status, issuer drill-down for stewardship.
- Ask the Portfolio (LLM Q&A) keeps computing in Python. It is the one analytics surface not moving to Superset.

### 5. Governance & Audit removal

| Content on the tab | Outcome |
|---|---|
| Methodology settings | Kept as config files |
| Risk category ownership | Dropped. Alerts lose the owner field |
| Entity-resolution review queue | Moved to Holdings Intake |
| Climate data conflicts | Moved to Holdings Intake (proposal) |

`backend/arp/portfolio/governance.py` is also referenced by `storage/portfolio_store.py`, `storage/postgres_portfolio_store.py`, `cli/portfolio.py` and `api/routers/portfolio.py`. Whether that backend code is deleted or only the tab is a decision for the plan (see open questions).

## Out of scope

Financial risk analytics, benchmark-relative analysis, SFDR PAI indicators, replacing the `AlertRule` engine, a PCAF data-quality score.

## Open questions

1. Which provider's API format is the monthly pull built for (columns, authentication)? Until decided, build a pluggable provider mapping and one generic reference mapping.
2. Delete `governance.py` and its store methods, or remove only the tab and keep the backend?
3. Keep climate-conflict review (section 2) or drop it?
4. Write routes for rules, evaluate-now, demo seed, universe and news classify have only an authentication check, no role check (`api/routers/portfolio.py`). Fixing this is not part of this spec; decide whether it belongs in the same plan.

## Risks

- Requiring Postgres changes how the demo and local setup run (the demo dataset currently works on files).
- Removing Standard Analytics before the Superset dashboards exist leaves a gap; the plan must order the work so dashboards land first.
- Stored stewardship triggers add a new store and a migration for any existing consumers (program selection, escalation).

## Testing approach

- Unit tests for the ESG validator and mapping, idempotent re-load, and failed-load blocking.
- A test that both tools produce the shared trigger shape for the same issuer.
- A run-level test for the monthly sequence on the seeded demo data.
- Dashboard definitions provisioned from code and checked by the existing BI tests.
