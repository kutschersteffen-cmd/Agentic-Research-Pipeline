# Theme Radar: momentum flag, one view across scans, company action strength

Status: Draft, for owner approval
Slug: `theme-radar-screen`
Risk: `risk:normal` for every slice (no auth, money, secrets or workflow-gate path)
Size: `L`, three slices, one PR each (R&D Lab plan wave 4, items 16, 15 and 17)

## Decisions for the owner

None open. Every choice is under "Defaults taken"; approving the spec approves them. The two that change the
most rows if the owner wants them different:

1. **The flag numbers** (baseline of 4 scans, Accelerating at burst ≥ 8, Rising at ≥ 3, Cooling at z ≤ −1). The
   fixture rows (AC-3 to AC-9) are computed from them.
2. **"Theme Builder" is today's Thematic Universe screen (`#/theme`)**, and the R&D Lab bar's first link reads
   "Overview". "Themes" in the owner's naming was the hub holding Dossiers and Emerging Themes; Dossiers moves
   under More, so the theme-building screen is the one left to carry the name.

## Why

The engine behind Emerging Themes is strong (grounded claims, clusters tracked across scans, six scores, company
roles, SEC capex check), but the screen shows one scan at a time and the numbers hide what matters:

- You cannot see a theme growing: each scan is its own table, and a theme has a new id in every scan.
- Only a brand-new cluster (lineage BIRTH) becomes a candidate. A theme that keeps growing after its first scan
  never comes back for review.
- There is no momentum flag; `signal_velocity` is a ratio a reader has to interpret.
- Every company in a candidate gets the same "momentum" number: the cluster's velocity
  (`pipeline.py:255`, `CompanyExposure.momentum`).
- The R&D Lab tools carry old names (Emerging Themes, Thematic Universe, Decision Studio, Theme dossiers), and the
  bar does not read Overview · Theme Radar · Theme Builder · More as the owner chose on 2026-11-25.

## What the user can do afterwards that they cannot do today

- Open Theme Radar and see every theme of the last six scans on one chart and one list, each with a flag
  (Accelerating, Rising, New this scan, Steady, Cooling), its last six scans and its source mix.
- Filter the radar by flag and by review status, and open a theme's side panel: why the flag is up, its scan
  history, its signals and companies, and the promote / reject / disconfirm actions of its latest candidate.
- Get a growing theme back for review even though it was not new this scan.
- See, on the R&D Lab Overview, which themes are gaining momentum and which companies are acting on them, ranked
  by each company's own action strength.

## Three versions

- **Safe:** a radar endpoint that groups candidates by lineage, a flag from `signal_velocity` thresholds, renames.
  Misses the burst score, themes that never became candidates, and per-company strength.
- **Strong (specified here):** a radar computed from the saved per-scan cluster history (all clusters, not only
  candidates) with a stable theme id from lineage, the burst-score flag, growing themes eligible for review, a new
  screen over it, the renames, and a per-company action strength from each company's own grounded claims plus its
  SEC capex move, ranked on the Overview.
- **Most ambitious:** the strong version plus watch / not relevant, overlap with your themes, risk view, digest,
  new sources (items 18–28). Next step up would need: the signal store (spec `theme-radar-signal-store`) and the
  triage spec (S3). Not in this spec.

## What exists today (main `7e2e955`)

All backend paths under `backend/arp/`, frontend under `frontend/src/`.

- `emerging_themes/pipeline.py` `execute_emerging_themes_run`: period = ISO week (`current_period`, `:43`);
  clusters, `classify_lineage` against the latest earlier saved period, `score_clusters`, then
  `topic_store.save_period` and `save_lineage_events` (`:176-190`). Only BIRTH clusters are synthesized into
  candidates (`:194-199`). `CompanyExposure(momentum=cluster.velocity)` (`:250-257`). XBRL capex/R&D changes land
  on `candidate.xbrl_corroboration` before exposures are built (`:217-231`).
- `storage/topic_store.py` `TopicStateStore` (files under `settings.emerging_themes_state_dir / "topics"`):
  `periods/<period>.json` (that period's `TopicCluster`s), `lineage/<period>.jsonl` (its `LineageEvent`s),
  `candidates.jsonl` (every candidate ever written). `list_periods()` sorts period keys. A second scan in the same
  ISO week overwrites that week's period file.
- `emerging_themes/lineage.py` `classify_lineage`: BIRTH (no link back), GROWTH (one prior, one successor), SPLIT
  (one prior, several successors), MERGE (several priors), DEATH (prior with no successor, recorded under the
  current period with the prior's `cluster_id`). Links only to the immediately earlier saved period.
- `schemas/emerging_themes.py` `TopicCluster` has `mention_count` and `source_types` (distinct
  `MentionSourceType`s: `gdelt`, `edgar_fts`, `regulatory_rss`), no per-source counts.
  `EmergingThemeCandidate.confidence_score` equals `novelty` (`synthesis.py:162`).
- `emerging_themes/company_exposure.py`: `tags_by_company`, `compute_company_risk`,
  `compute_company_evidence_quality`. `synthesis.py::independent_source_count` counts distinct URLs of grounded
  tags.
- `api/routers/emerging_themes.py`: `POST /runs`, `GET /runs/{run_id}/candidates` (decisions folded by
  `load_candidates_with_status`), promote / reject / disconfirm, `GET|PUT /schedule`. No cross-scan endpoint.
- `pages/EmergingThemesDetector.tsx`: h1 "Emerging Themes"; cards "Run a scan now", "Recent scans" (run table,
  "View candidates"), "Candidates — <run>" (table, expandable detail at `:318-438` with brief, citations, XBRL,
  company exposure line showing `momentum`, decision bar), "Automatic schedule".
- Navigation: `lib/processes.ts:191-209` R&D Lab `screens`, `row: ["#/designStrategy", "#/themes", "#/decision",
  "#/index"]`, `more: [taxonomy, theme, strategyReplication, signals, valueChain]`; `rowLinks` puts the workspace
  name first (`:323`). `lib/nav.ts:9` hub "Themes" with tabs Dossiers / Emerging themes. `App.tsx:66-94` tab
  labels (palette). `pages/ProcessHub.tsx:690` `WorkspaceOverview` is the generic page for every workspace.

## Goals

1. A theme keeps one id across scans, worked out from the saved lineage (item 15a).
2. Each theme gets a flag computed in code from its scan history with the burst score (item 16a); a theme in its
   first scan says "new this scan".
3. A growing theme that never had a candidate becomes one (item 16b).
4. One API returns the themes of the last six scans with history, flag, status and source mix (item 15a).
5. The Theme Radar screen replaces the scan-by-scan table (item 15b), and the R&D Lab tools carry the new names
   (item 15c).
6. Each company in a candidate gets an action strength from its own grounded claims and SEC capex move, replacing
   the copied cluster velocity (item 17a), and the R&D Lab Overview ranks companies by it under a radar card
   (item 17b).

## Non-goals

- `confidence_score == novelty`: the screen does not show confidence, so it stays as it is (noted for later).
- Watch / Not relevant, overlap with your themes, risk view, digest, new sources, Source Workbench (items 18–28;
  specs S3–S6). The status filter here has no "Watching" or "Not relevant"; S3 adds them.
- A persisted item store or daily scans (spec `theme-radar-signal-store`). This spec reads only the existing
  per-scan cluster files and does not depend on that spec.
- A new action type (for example "launch"). Extraction and its prompt do not change; no golden-set impact.
- Renaming route ids, API paths, run types or code identifiers (`#/emergingThemes`, `emerging_themes`,
  `DecisionStudio.tsx` stay).
- The "in progress" and "verified themes" Overview cards (R&D Lab plan item 29, another spec), Theme Workbench
  (item 13).

## Anti-goals (must stay true)

- No language model call decides a flag, an id, a status or an action strength.
- No candidate is ever written twice for the same theme by the growing-theme rule.
- No old name ("Emerging Themes", "Emerging themes", "Thematic Universe", "Thematic universe", "Decision Studio",
  "Theme dossiers") in visible text on the screens AC-52 lists.
- No new config setting, table, service or dependency.

Reviewers check both of the first and last line in the diff (no `arp.llm` import in `radar.py` or in the new
`company_exposure.py` functions; no `Settings` field, migration, `pyproject.toml` or `package.json` dependency
added); AC-26 and AC-89 pin them.

## Design

### Terms

- **Scan**: one saved period in the topic store (`list_periods()`), oldest first. "The latest scan" is the last.
- **Source category**: `news` (`gdelt`), `filings` (`edgar_fts`), `regulators` (`regulatory_rss`), `research`,
  `jobs`. The last two have no source today; the signal-store and sources specs add them under these names.
- **Theme**: a chain of clusters across scans joined by lineage, identified by its `radar_id`.

### Cluster source counts (slice 1)

`TopicCluster` gets `source_counts: dict[str, int] = {}`: mentions per source category (keys from the five
category names, zero counts left out). `clustering.cluster_tags` fills it from each member mention's
`source_type`. A cluster saved before this change has `{}`; wherever counts are read, such a cluster counts 1 for
the category of each of its `source_types`.

### Theme ids (slice 1)

`arp/emerging_themes/radar.py` walks every saved scan oldest first with that scan's clusters and lineage events
(a cluster with no event in its scan's lineage file, or a scan with no lineage file, counts as BIRTH):

- BIRTH: `radar_id` = the cluster's own `cluster_id`.
- GROWTH: the prior cluster's `radar_id`.
- SPLIT: of the clusters of this scan whose event is SPLIT from the same prior, the one with the highest
  `overlap_score` (ties: larger `mention_count`, then smaller `cluster_id`) keeps the prior's `radar_id`; each other
  one starts a new theme with its own `cluster_id`.
- MERGE: the `radar_id` of the prior with the largest `mention_count` (ties: smaller `radar_id`). The other
  priors' themes are **absorbed**: they end at the earlier scan and are not listed on the radar.
- DEATH events add nothing.

### Burst score and flag (slice 1)

For theme T and scan p (constants in `radar.py`: `BASELINE_SCANS = 4`, `SD_FLOOR = 0.01`, `ACCELERATING_AT = 8.0`,
`RISING_AT = 3.0`, `COOLING_Z = -1.0`, `HISTORY_SCANS = 6`):

- `n(p)` = `mention_count` of T's cluster in p, 0 if T has none there.
- `share(p)` = `n(p)` / sum of `mention_count` over all clusters saved for p (0 if that sum is 0).
- Baseline = `share` of T in the up to 4 saved scans immediately before p (0 where T has no cluster). `μ` = mean,
  `σ` = population standard deviation, `σ' = max(σ, 0.01)`, `z = (share(p) − μ) / σ'`.
- `H(p)` = Shannon entropy (natural log) of T's source counts in p over the categories with a count, divided by
  `ln 5`; 0 when T has no cluster in p.
- `burst(p) = max(0, z) × (1 + H(p)) × ln(1 + n(p))`. When no saved scan precedes p, `burst(p) = 0` and `z = 0`.
- Flag at the latest scan t: `new` when T's first scan is t; else `accelerating` when `burst(t) ≥ 8`, `rising`
  when `≥ 3`, `cooling` when `z ≤ −1`, else `steady`.

### Growing themes become candidates (slice 1)

`radar.eligible_cluster_ids(topic_store, period) -> set[str]`, with `period` the latest saved scan: the clusters
of `period` whose event is BIRTH, plus the clusters whose theme's flag is `accelerating` or `rising` and whose
theme has no candidate in `topic_store.list_candidates()` (a candidate belongs to the theme of its `cluster_id`).
The pipeline calls it right after `save_lineage_events` and synthesizes exactly those clusters (in place of
`birth_cluster_ids`); everything after synthesis is unchanged. A growing theme's candidate keeps today's
`first_detected_date` (the scan date).

### Radar API (slice 1, companies in slice 3)

`GET /api/emerging-themes/radar` (any signed-in role) → 200, response model `RadarResponse`
(`schemas/emerging_themes.py`), built by `radar.build_radar(topic_store, run_store)`:

```
{
  "periods": [str],            // the last up to 6 saved scans, oldest first
  "themes": [{
    "radar_id": str,
    "label": str,              // latest candidate's theme_name, else the theme's last cluster's representative_label
    "flag": "accelerating" | "rising" | "new" | "steady" | "cooling",
    "burst": float,            // burst at the latest scan
    "share": float,            // share at the latest scan
    "baseline_share": float,   // μ at the latest scan
    "first_period": str, "last_period": str,   // first and last scan with a cluster of this theme
    "status": "none" | "candidate" | "under_review" | "promoted" | "rejected" | "disconfirmed",
    "candidate": {"run_id": str, "theme_id": str} | null,   // the latest candidate
    "source_mix": {"news": int, "filings": int, "regulators": int, "research": int, "jobs": int},
    "company_count": int,      // len(company_ids) of the last cluster
    "labels": [str],           // first 5 distinct member_labels of the last cluster, in stored order
    "history": [{"period": str, "mention_count": int, "share": float, "burst": float}]  // one per "periods" entry
  }],
  "companies": [...]           // slice 3; slice 1 returns []
}
```

- Every float is rounded with Python `round(x, 4)`. `source_mix` and `company_count` come from the theme's last
  cluster (all five keys present).
- **Listed themes:** themes with a cluster in any of `periods`, plus any theme whose status is `candidate` or
  `under_review`; an absorbed theme is never listed, even with an open candidate.
- **Status:** the theme's latest candidate row in the topic store's `candidates.jsonl` (largest `created_at`;
  ties: the later line), with `run_store.read_decisions(<its run_id>)` folded onto it by `theme_id` the way
  `load_candidates_with_status` folds them (last decision row for that `theme_id` wins; `promote` → `promoted`,
  `reject` → `rejected`, `disconfirm` → `disconfirmed`; no row → the candidate's own `status`). `none` and
  `candidate: null` when the theme has no candidate. A candidate whose `cluster_id` is in no saved scan belongs to no theme.
- **Order:** flag `accelerating`, `rising`, `new`, `steady`, `cooling`; then `burst` descending; then `radar_id`.
- No saved scan: `{"periods": [], "themes": [], "companies": []}`.
- A line in `frontend/src/api/contract.ts` for the new `request<T>()`; OpenAPI and `schema.gen.ts` regenerated.

### Action strength (slice 3)

In `emerging_themes/company_exposure.py`:

- Tiers: `capex`, `orders`, `capacity`, `hiring` = committed money (3); `partnership` = launches and deals (2);
  `other` = mentions (1). Only tags with `grounded` true count.
- `strongest_action_tag(company_tags) -> ExtractedTag | None`: the first grounded tag in list order with the
  highest tier; `None` when no tag is grounded.
- `compute_action_strength(company_tags, mentions_by_id, capex_pct_change: float | None) -> int`: 0 when no tag is
  grounded; else base (tier 3: 60, tier 2: 35, tier 1: 15) + `6 × min(independent_source_count(company_tags,
  mentions_by_id), 5)` + capex (+10 when `capex_pct_change > 0`, −10 when `< 0`, 0 when `None` or 0), clamped to
  0–100.

`CompanyExposure` loses `momentum` and gains `action_strength: int | None = None`,
`strongest_action: ActionType | None = None`, `strongest_claim: str | None = None`, `source_count: int = 0`
(candidates written before this change load with these defaults). The pipeline fills them where it builds each
exposure today, with `capex_pct_change` from the candidate's `xbrl_corroboration` entry for that company (None if
there is none) and `source_count = independent_source_count(company_tags, mentions_by_id)`.

Radar `companies`: for each listed theme whose flag is `accelerating`, `rising` or `new` and whose status is not
`rejected` or `disconfirmed`, every `company_exposure` entry of its latest candidate with a non-null
`action_strength`, as `{"company_id", "name", "radar_id", "theme" (the theme's label), "action_strength",
"strongest_action", "strongest_claim", "source_count"}`. `name` is the company's `name` in the candidate's
`context_brief.companies`, else its `company_id`. Order: `action_strength` descending, `source_count`
descending, `company_id`, `radar_id`.

### Theme Radar screen (slice 2)

`#/emergingThemes` (and `#/emergingThemes/<radar_id>`, which opens with that theme selected):

- h1 "Theme Radar"; help text "Themes companies are starting to put money behind, across your last six scans.
  A theme keeps one id from scan to scan; its flag compares its share of mentions with its own last four scans."
- "Run a scan now" and "Automatic schedule" stay as they are. "Recent scans" and "Candidates — <run>" go.
- Card "Themes on the radar" (h2), loading `GET /api/emerging-themes/radar` on open, after a decision in the side
  panel, and on its "Refresh" button:
  - Two filter groups, `role="group"` named "Flag" and "Status", of toggle buttons (`aria-pressed`). Flag buttons,
    in order, with `data-flag`: Accelerating (`accelerating`), Rising (`rising`), New this scan (`new`), Steady
    (`steady`), Cooling (`cooling`). Status buttons with `data-status`: To review (`review`: candidate and
    under_review), Already a theme (`promoted`), Rejected (`rejected`), Disconfirmed (`disconfirmed`), Not a
    candidate (`none`). Each button reads its label, a space and the number of listed themes with that value
    (counted over all themes, whatever is pressed). Within a group pressed buttons combine with OR; across groups
    with AND; a group with nothing pressed does not filter.
  - Chart: an `svg` named "Theme Radar chart". x = the theme's last `history` entry's `mention_count`, y = `burst`,
    dot size grows with `company_count`. One `circle` with `data-radar-id` per shown theme; one `polyline` with
    `data-tail` = `radar_id` through the theme's `history` entries with `mention_count > 0`, oldest first, only when
    there are at least 2 such entries.
  - List: a table named "Themes on the radar", one `tr` with `data-radar-id` per shown theme in API order; columns
    Theme (label), Flag (the button label), Last 6 scans (`history` mention counts joined with " · "), Burst
    (`burst` to 1 decimal), Sources (non-zero `source_mix` entries in key order as "<key> <n>", joined with " · "),
    Companies (`company_count`), Status (the button label).
  - No theme at all: "No themes yet. Run a scan above, or turn on the automatic schedule below." Filters leave
    none: "No theme matches these filters." Load failure: one `role="alert"` reading "The radar could not be
    loaded: <detail>".
  - Clicking a row or a dot, or Enter on a focused row, selects the theme.
- Side panel: `aside` named "Theme details", shown while a theme is selected, with a "Close" button.
  - h2 = label. A flag line: for `new`, "New this scan: no growth rate until its second scan."; else
    "<Flag> · burst <burst, 1 decimal> · share <share × 100, 1 decimal>% vs <baseline_share × 100, 1 decimal>%
    baseline".
  - Table "Scan history": columns Scan, Mentions, Share, Burst, one row per `history` entry (share as a percent to
    1 decimal, burst to 1 decimal).
  - With a candidate: loads `GET /api/emerging-themes/runs/{run_id}/candidates`, finds `theme_id`, and shows the
    same detail block the expanded candidate row shows today (description, discovery signal, rationale, sources,
    XBRL, contradiction evidence, company exposure, context brief, decision bar or decision line, Open dossier,
    Run company exposure), its actions calling the same endpoints with that `run_id`. Load failure: one
    `role="alert"` reading "Candidates could not be loaded: <detail>". `theme_id` not in the answer: the
    without-candidate block below.
  - Without a candidate: h3 "Signals" with `labels` as a list, the line "No candidate yet: this theme has not
    passed the source and action checks.", and "<company_count> companies named".

### Renames and navigation (slice 2)

Visible text only; route ids, files and identifiers stay.

| Today | New |
|---|---|
| Emerging Themes / Emerging themes (screen `#/emergingThemes`) | Theme Radar |
| Thematic Universe / Thematic universe (screen `#/theme`) | Theme Builder |
| Decision Studio (screen `#/decision`) | Scoring Rules |
| Theme dossiers (screen `#/themes`) | Dossiers |

- Every visible string in `frontend/src` (JSX text, labels, titles, `does` texts, run-type labels, messages,
  `aria-label`s, placeholders) naming one of these screens uses the new name: for example the `emerging_themes`
  run-type label "Theme Radar scan", `theme` "Theme Builder run" where a run is meant, "in Scoring Rules".
- R&D Lab `row`: `#/emergingThemes`, `#/theme`; `more`, in order: `#/decision`, `#/index`, `#/themes`,
  `#/designStrategy`, `#/taxonomy`, `#/strategyReplication`, `#/signals`, `#/valueChain`. The row's first link
  (`#/rdLab`) reads "Overview" for R&D Lab only (other workspaces keep their name). The nav keeps the name
  "R&D Lab screens"; the Overview's h1 stays "R&D Lab".
- `lib/nav.ts`: the "Themes" hub goes, so `#/themes` and `#/emergingThemes` show no tab strip.

### R&D Lab Overview (slice 3)

`WorkspaceOverview` for `rdLab` only, between the ask box and the process list: a container with two cards, in
this order (item 29 later appends its two cards to the same container):

1. **Radar card**, h2 "What is gaining momentum": the Theme Radar chart (the same component) over all radar themes;
   clicking a dot opens `#/emergingThemes/<radar_id>`; a link "Open Theme Radar" to `#/emergingThemes`. No theme:
   "No scans yet." 
2. **Company list**, h2 "Who is putting money behind the rising themes", help text "Ranked by action strength:
   committed money (capex, orders, capacity, hiring) counts more than partnerships, and partnerships more than
   mentions. More independent sources raise the score.", a table named "Companies by action strength" with columns
   #, Company, Theme, What they did, Action strength, Sources; the first 10 `companies`; "What they did" =
   action label (`capex` Capex, `orders` Orders, `capacity` Capacity, `hiring` Hiring, `partnership` Partnership,
   `other` Mention), " · ", `strongest_claim`. No company: "No company has acted on a rising theme yet."

Both cards share one `GET /api/emerging-themes/radar`; its failure shows one `role="alert"` reading "The radar
could not be loaded: <detail>" and leaves the rest of the Overview as it is. Other workspaces do not request it.

The candidate detail block's exposure line reads "(risk <n>%, action strength <action_strength or –>, evidence
quality <n>%)" and its intro "(role + Risk/Action strength/Evidence-quality — …)".

## Defaults taken

- A scan is a saved ISO-week period, as today; two scans in one week count once (the later one).
- Baseline 4 scans (today's `_DEFAULT_BASELINE_PERIODS`), σ floor 1 percentage point of share, thresholds 8 / 3 /
  −1. History of 6 scans.
- Source entropy is divided by `ln 5` (the five categories), so today's three sources can reach at most 0.68 and
  later sources raise it.
- Chart x axis is mentions in the theme's last scan (not independent sources, which the saved clusters do not hold)
  and dot size is companies named (not companies acting).
- A split-off cluster starts a new theme; a merge keeps the biggest prior's id.
- A growing theme that already had a candidate (any status) gets no new one; its latest candidate stays its status.
- Status filter has five values from today's candidate states; "Watching" and "Not relevant" come with S3.
- The Overview company list leaves out themes that are Steady or Cooling, rejected or disconfirmed.
- Action strength: 60 / 35 / 15 base, 6 per independent source up to 5, ±10 for the SEC capex move; hiring counts
  as committed money; partnerships stand in for launches (no launch action type exists).
- Theme Builder = `#/theme`; the R&D Lab bar's first link reads "Overview"; "Build a thematic portfolio" moves into
  More (the owner's bar has three named links).

## Notes for the builder

- Smallest diff, lowest complexity (owner rule 2026-11-25): no refactor, no new abstraction beyond `radar.py` and the
  shared chart component, no unrelated cleanup. Reviewers check it.
- Never the word "product" in UI text or docs.
- No real model call in any test; the radar and action strength are pure code.
- Existing tests that open "View candidates" (`backend/tests/e2e/test_app_robustness_screens.py`,
  `test_showcase_themes_screens.py`, `test_showcase_themes_pr2_screens.py`) or assert old names
  (`frontend/tests/processes.test.ts`, `searchOrAsk.test.ts`, `workspaceCard.test.ts`,
  `showcaseThemesFixes*.test.ts`, `backend/tests/e2e/test_proxy_prefix.py`, `test_ui_polish_1.py`) move to the
  side panel or the new names; list each in the PR.
- `openwiki/` will need its weekly refresh (screen names, radar).

## Rows of earlier specs this spec supersedes

| Spec | Rows | Why | Replaced by |
|---|---|---|---|
| `rd-lab-rename` | AC-1, AC-12 | R&D Lab bar and More menu change | AC-50, AC-51 |
| `rd-lab-rename` | AC-8 | "Build a thematic portfolio" moves into More | AC-53 |
| `rd-lab-rename` | AC-11 (unit) | its text says "Decision Studio" | AC-55 |
| `ui-trim-workspaces` | AC-17, `#/emergingThemes` case only | h1 is Theme Radar | AC-52 |
| `ui-trim-workspaces` | AC-18, terms `thematic universe` and `emerging themes` only | palette labels change | AC-54 |
| `ui-trim-workspaces` | AC-19 | the Themes tab strip goes | AC-56 |
| `app-robustness` | AC-15, AC-16, AC-17, AC-56 | CRASH opened "View candidates", which goes | AC-58 to AC-61 |
| `app-robustness` | AC-18 | same, h1 changes | AC-62 |
| `app-robustness` | AC-40 | "Recent scans" goes | AC-42 |
| `app-robustness` | AC-42 | "View candidates" goes | AC-45 |
| `theme-dossier` | AC-32 (evaluator) | "Theme dossiers" link renamed | AC-51 |
| `theme-dossier` | AC-37 (evaluator) | candidates table goes; Open dossier now in the side panel | AC-40 |
| `theme-context-brief` | AC-25 (evaluator) | "view the candidate" is now the side panel | AC-40 |
| `failed-run-recovery` | AC-28 (evaluator) | "Thematic universe run" becomes "Theme Builder run" | AC-52 |
| `showcase-themes-fixes` | AC-44 (unit) | the detail cell moves into the side panel | AC-49 |
| `showcase-themes-fixes` | AC-53, AC-54, AC-55 (unit) | the per-scan candidates table, "Recent scans" and "Scanning…" go | retired |

`app-robustness` AC-41 (schedule load error) still holds unchanged.

## Acceptance

**Radar rows** call `GET /api/emerging-themes/radar` through FastAPI's `TestClient` on `arp.api.main:app` with
`app.dependency_overrides[get_topic_store]` returning a `TopicStateStore(<tmp>/topics)` the test filled with
`save_period`, `save_lineage_events` and `append_candidate`, and the app's own `get_run_store()` (the holdout job's
Postgres; run ids below are unique per test, decisions written with `RunStore.append_decision_row(run_id,
{"theme_id", "action", "reason", "decided_at"})`). Floats compare exactly as returned (they are rounded to 4
places).

**Fixture H** (scans `2026-W40` … `2026-W45`). Cluster ids are the theme letter and the week (`a40` … `a45`); a
theme's clusters share one `representative_label` (`alpha`, `bravo`, `charlie`, `delta`, `echo`, `zulu`);
`source_counts` all `news` unless stated; lineage: a theme's first cluster BIRTH, each later one GROWTH from the
previous week's cluster of the same letter with `overlap_score` 0.9.

| Theme | W40 | W41 | W42 | W43 | W44 | W45 |
|---|---|---|---|---|---|---|
| a | 5 | 5 | 5 | 5 | 6 | 20 (`news` 10, `filings` 6, `regulators` 4; `company_ids` `["acme","beta","gamma"]`; `member_labels` `["cell plant","grid storage","cell plant","sodium cells","pilot line","supply deal","offtake"]`) |
| b | – | 4 | 4 | 4 | 4 | 6 |
| c | 10 | 10 | 10 | 10 | 10 | 10 |
| d | 12 | 12 | 12 | 12 | 12 | 6 (`news` 3, `filings` 3) |
| e | – | – | – | – | – | 5 |
| z | 73 | 69 | 69 | 69 | 68 | 53 |

Candidates (minimal `EmergingThemeCandidate`s; unnamed fields at their defaults; `first_detected_date`
`2026-11-01`, `signal_velocity` 1.0; a decision "X in R" is the row `{"theme_id": <id>, "action": "promote" |
"reject" | "disconfirm", "reason": "r", "decided_at": "2026-11-04T00:00:00Z"}` appended to run R): **K1** `et_b1` "Bravo theme", cluster `b42`, run `rh1`, created
`2026-10-14T00:00:00Z`, rejected in `rh1`; **K2** `et_b2` "Bravo again", `b45`, run `rh2`,
`2026-11-03T00:00:00Z`, no decision; **K3** `et_c` "Charlie theme", `c41`, run `rh0`, `2026-10-07T00:00:00Z`,
promoted in `rh0`; **K4** `et_e` "Echo theme", `e45`, run `rh2`, `2026-11-03T00:00:01Z`, no decision; **K5** `et_d`
"Delta theme", `d43`, run `rh1`, `2026-10-21T00:00:00Z`, disconfirmed in `rh1`. **H+** is H with K1–K5.

**Fixture S** (scans `2026-W40`, `2026-W41`): W40 clusters `p1` (10), `p2` (4), `q` (5), all BIRTH. W41: `s1` (6)
SPLIT from `p1` overlap 0.8; `s2` (5) SPLIT from `p1` overlap 0.5; `m` (9) MERGE of `["p2","q"]` overlap 0.6, saved
with `source_counts` `{}` and `source_types` `["edgar_fts","gdelt"]`.

**Node rows** import the named export from `frontend/src/` under `node --test --experimental-strip-types`.
**Browser rows** run in headless Chromium at 1440 × 900 against `backend/scripts/e2e_stack.sh up` (dev auth, role
`approver`), with every API response the row names stubbed by `page.route`; "fails" answers 500
`{"detail": "boom"}`. **Fixture R** is the stubbed `GET /api/emerging-themes/radar` body: `periods` `2026-W40` …
`2026-W45`, `companies` `[]`, and these themes in this order (`history[i].period` = `periods[i]`; `share` and
`burst` of each history entry as listed, else 0):

| radar_id | label | flag | burst | share / baseline | status, candidate | source_mix (non-zero) | company_count | history mention counts | history burst | labels |
|---|---|---|---|---|---|---|---|---|---|---|
| r1 | Sodium-ion batteries | accelerating | 73.6362 | 0.2 / 0.05 | none, null | news 10, filings 6, regulators 4 | 9 | 5, 5, 5, 5, 6, 20 | 0, 0, 0, 0, 1.9459, 73.6362 (shares 0.05 ×4, 0.06, 0.2) | `["cell plant","grid storage"]` |
| r2 | Small modular reactors | rising | 3.8918 | 0.06 / 0.04 | candidate, `{"run_id":"et1","theme_id":"e2"}` | news 6 | 5 | 0, 4, 4, 4, 4, 6 | last 3.8918 | `[]` |
| r3 | Solid-state transformers | new | 8.9588 | 0.05 / 0 | none, null | news 5 | 3 | 0, 0, 0, 0, 0, 5 | last 8.9588 | `["grid transformer"]` |
| r4 | Industrial heat pumps | steady | 0 | 0.1 / 0.1 | promoted, `{"run_id":"et0","theme_id":"e4"}` | news 10 | 6 | 10 ×6 | 0 | `[]` |
| r5 | Green ammonia shipping | cooling | 0 | 0.06 / 0.12 | rejected, `{"run_id":"et0","theme_id":"e5"}` | news 3, filings 3 | 4 | 12 ×5, 6 | 0 | `[]` |

**Candidate e2** is the stubbed `GET /api/emerging-themes/runs/et1/candidates` body: one candidate `theme_id`
`e2`, `theme_name` "Small modular reactors", `rationale` "Two utilities placed firm orders.", `status`
`candidate`, `cluster_id` `k2`, `run_id` `et1`, `company_exposure` `[]`, other fields valid defaults.
**CRASH-R** is: open `#/emergingThemes` with the radar stub answering Fixture R with r1's `history` replaced by the
string `"x"` (so drawing it throws).

### Slice 1: theme ids, flag, growing themes, radar API

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-1 | an empty topic store | radar | 200, body `{"periods": [], "themes": [], "companies": []}` | holdout |
| AC-2 | H+ | radar | `periods` `["2026-W40", …, "2026-W45"]` (6); `themes` `radar_id`s in order `a40`, `b41`, `e45`, `c40`, `d40`, `z40` | holdout |
| AC-3 | H+ | radar, theme `a40` | `flag` `accelerating`, `burst` 73.6362, `share` 0.2, `baseline_share` 0.0525 | holdout |
| AC-4 | H+ | radar, theme `b41` | `flag` `rising`, `burst` 3.8918, `share` 0.06, `baseline_share` 0.04 | holdout |
| AC-5 | H+ | radar, theme `e45` | `flag` `new`, `burst` 8.9588, `first_period` `2026-W45` | holdout |
| AC-6 | H+ | radar, theme `c40` | `flag` `steady`, `burst` 0.0 | holdout |
| AC-7 | H+ | radar, themes `d40` and `z40` | both `flag` `cooling`, `burst` 0.0; `d40` `baseline_share` 0.12 | holdout |
| AC-8 | H+ | radar, theme `a40` `history` | 6 entries, `period` W40 … W45, `mention_count` 5, 5, 5, 5, 6, 20, `share` 0.05, 0.05, 0.05, 0.05, 0.06, 0.2, `burst` 0.0, 0.0, 0.0, 0.0, 1.9459, 73.6362 | holdout |
| AC-9 | H+ | radar, theme `e45` `history` | `mention_count` 0, 0, 0, 0, 0, 5 and `share` 0.0 ×5, 0.05 | holdout |
| AC-10 | H+ | radar, theme `a40` | `source_mix` `{"news": 10, "filings": 6, "regulators": 4, "research": 0, "jobs": 0}`; `company_count` 3; `labels` `["cell plant", "grid storage", "sodium cells", "pilot line", "supply deal"]`; `first_period` `2026-W40`, `last_period` `2026-W45`; `label` `alpha` | holdout |
| AC-11 | H+ | radar, `status`, `candidate`, `label` per theme | `a40` `none`, null, `alpha`; `b41` `candidate`, `{"run_id": "rh2", "theme_id": "et_b2"}`, `Bravo again`; `e45` `candidate`, `{"run_id": "rh2", "theme_id": "et_e"}`, `Echo theme`; `c40` `promoted`, `{"run_id": "rh0", "theme_id": "et_c"}`, `Charlie theme`; `d40` `disconfirmed`, `{"run_id": "rh1", "theme_id": "et_d"}`, `Delta theme`; `z40` `none`, null, `zulu` | holdout |
| AC-12 | S | radar | `radar_id`s listed: exactly `p1`, `q`, `s2` (in any order); `p2` absent | holdout |
| AC-13 | S | radar | `s2` `flag` `new`, `first_period` `2026-W41`; `q` `first_period` `2026-W40`, `last_period` `2026-W41`; `p1` `last_period` `2026-W41` | holdout |
| AC-14 | S | radar, theme `q` | `source_mix` `{"news": 1, "filings": 1, "regulators": 0, "research": 0, "jobs": 0}` (cluster saved without counts) | holdout |
| AC-15 | H+ with the W43 lineage file removed | radar | `a40` `last_period` `2026-W42`; a theme `a43` with `first_period` `2026-W43` and `last_period` `2026-W45` | holdout |
| AC-16 | H+ plus 2 more scans `2026-W38`, `2026-W39`, each with one BIRTH cluster `old38`/`old39` (count 1) and no candidate | radar | `periods` is `2026-W40` … `2026-W45`; neither `old38` nor `old39` is listed | holdout |
| AC-17 | AC-16's store plus a candidate on `old38` (run `rh9`, no decision) | radar | `old38` listed with `status` `candidate`, 6 `history` entries all `mention_count` 0 | holdout |
| AC-19 | a `TopicCluster` JSON row without `source_counts` | `TopicCluster.model_validate` | `source_counts` `{}` | holdout |
| AC-20 | H with only K1 | `radar.eligible_cluster_ids(store, "2026-W45")` | `{"a45", "e45"}` | holdout |
| AC-21 | H with K1 and a candidate on `a43` (run `rh3`) | same call | `{"e45"}` | holdout |
| AC-22 | S with no candidate | `eligible_cluster_ids(store, "2026-W41")` | `{"m"}` (m's theme `q` is accelerating with no candidate; `s2` is new but not BIRTH; `s1` is cooling) | holdout |
| AC-23 | a run with stand-ins for sources, LLM, clustering and lineage making one GROWTH cluster whose theme is accelerating with no candidate, and one BIRTH cluster | `execute_emerging_themes_run` | both clusters are synthesized into candidates (2 `results.jsonl` rows) | unit |
| AC-24 | tags from mentions with source types `gdelt` ×2 and `edgar_fts` ×1 in one cluster | `cluster_tags` | that cluster's `source_counts` `{"news": 2, "filings": 1}` | unit |
| AC-25 | `main`'s routes | `GET /api/emerging-themes/runs/{run_id}/candidates`, promote, reject, disconfirm, `GET|PUT /schedule` | paths, methods, request bodies and status codes as on `main`; the candidates response has `main`'s top-level and candidate keys, `company_exposure[]` entries aside (they follow AC-78, AC-80) (must not change) | unit |
| AC-26 | slice 1's diff | read `radar.py`'s imports | nothing from `arp.llm` | unit |
| AC-27 | S plus a candidate on `p2` (run `rh8`, no decision) | radar | `p2` is not listed | holdout |

AC-22 worked: `q` W40 share 5/19, W41 9/20, z 18.6842, H ln 2 / ln 5, burst 61.5505; `p1` (via `s1`) z −22.6316.

### Slice 2: Theme Radar screen and renames

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-30 | radar stub R | open `#/emergingThemes` | h1 `Theme Radar`; table "Themes on the radar" rows `data-radar-id` in order r1, r2, r3, r4, r5 | holdout |
| AC-31 | AC-30 | read row r1's cells | `Sodium-ion batteries`, `Accelerating`, `5 · 5 · 5 · 5 · 6 · 20`, `73.6`, `news 10 · filings 6 · regulators 4`, `9`, `Not a candidate` | holdout |
| AC-32 | AC-30 | read the Flag and Status button texts | Flag, in order: `Accelerating 1`, `Rising 1`, `New this scan 1`, `Steady 1`, `Cooling 1`; Status, in order: `To review 1`, `Already a theme 1`, `Rejected 1`, `Disconfirmed 0`, `Not a candidate 2` | holdout |
| AC-33 | AC-30 | press `[data-flag=rising]` | it has `aria-pressed="true"`; table rows: r2 only; chart `circle[data-radar-id]`: r2 only | holdout |
| AC-34 | AC-33 | press `[data-flag=cooling]` | table rows r2, r5 | holdout |
| AC-35 | AC-34 | press `[data-status=rejected]` | table rows r5 only | holdout |
| AC-36 | AC-35 | press `[data-status=rejected]` again, then `[data-status=promoted]` | the text `No theme matches these filters.` is shown and no row | holdout |
| AC-37 | AC-30 | read the chart | 5 `circle[data-radar-id]`; `polyline[data-tail=r1]` has 6 points, `[data-tail=r2]` 5, `[data-tail=r5]` 6; no `polyline[data-tail=r3]` | holdout |
| AC-38 | AC-30 | click row r1 | `aside` "Theme details" shows h2 `Sodium-ion batteries`, the text `Accelerating · burst 73.6 · share 20.0% vs 5.0% baseline`, a table "Scan history" with 6 rows whose last reads `2026-W45`, `20`, `20.0%`, `73.6`, the list items `cell plant`, `grid storage`, and `No candidate yet: this theme has not passed the source and action checks.` | holdout |
| AC-39 | AC-30 | click `circle[data-radar-id=r3]` | the panel h2 is `Solid-state transformers` and it shows `New this scan: no growth rate until its second scan.` | holdout |
| AC-40 | AC-30 plus candidate stub e2 | click row r2 | the panel shows `Two utilities placed firm orders.`, an input "Reason" and buttons `Promote`, `Reject`, `Disconfirm` | holdout |
| AC-41 | AC-40, `POST /api/emerging-themes/runs/et1/candidates/e2/reject` stubbed 200 | type `noise` in "Reason", click `Reject` | that POST was sent with body `{"reason": "noise"}`, then `GET /api/emerging-themes/radar` was requested again | holdout |
| AC-42 | the radar request fails | open `#/emergingThemes` | exactly one `role="alert"`, reading `The radar could not be loaded: boom`; no page error | holdout |
| AC-43 | radar stub `{"periods": [], "themes": [], "companies": []}` | open `#/emergingThemes` | the text `No themes yet. Run a scan above, or turn on the automatic schedule below.` | holdout |
| AC-44 | radar stub R | open `#/emergingThemes/r4` | the panel is open with h2 `Industrial heat pumps` | holdout |
| AC-45 | AC-30, the e2 candidates request fails | click row r2 | exactly one `role="alert"`, reading `Candidates could not be loaded: boom` | holdout |
| AC-46 | radar stub R | open `#/emergingThemes` | no button `View candidates` and no heading `Recent scans`; headings `Run a scan now` and `Automatic schedule` present (must not change) | holdout |
| AC-47 | radar stub R, viewport 390 × 844 | open `#/emergingThemes`, click row r1 | `document.scrollingElement.scrollWidth` ≤ 390 | holdout |
| AC-48 | the running app with Fixture H+ written to `$ARP_EMERGING_THEMES_STATE_DIR/topics` before `e2e_stack.sh up` | open Theme Radar at 1440 and 390 wide, click `alpha` | no two dot labels overlap; each tail ends at its dot; the panel's sections in order: flag line, Scan history, Signals (or the candidate block); `scrollWidth` ≤ the viewport width at 390 | evaluator |
| AC-49 | AC-40 with e2's `rationale` 600 characters with no line break | click row r2, at 1440 × 900 and at 390 × 844 | the `aside` "Theme details" has `scrollWidth` not greater than its `clientWidth` at both sizes | holdout |
| AC-50 | e2e stack | open `#/rdLab` | the navigation "R&D Lab screens" reads, in order: links `Overview`, `Theme Radar`, `Theme Builder`, then a button `More` | holdout |
| AC-51 | AC-50 | press `More` | its items read, in order: `Scoring Rules`, `Portfolio Builder`, `Dossiers`, `Build a thematic portfolio`, `Taxonomy Library`, `Strategy Replication`, `Signals workbench`, `Value Chain Explorer` | holdout |
| AC-52 | e2e stack | open each of `#/rdLab`, `#/emergingThemes`, `#/theme`, `#/decision`, `#/themes`, `#/index`, `#/designStrategy`, `#/transitionIntel`, `#/argus`, `#/history` | h1 of `#/emergingThemes` `Theme Radar`, `#/theme` `Theme Builder`, `#/decision` `Scoring Rules`, `#/themes` `Dossiers`; on every page, no visible text contains `Emerging Themes`, `Emerging themes`, `Thematic Universe`, `Thematic universe`, `Decision Studio` or `Theme dossiers` (case-sensitive) | holdout |
| AC-53 | e2e stack | open `#/designStrategy`, then `#/theme`, then `#/emergingThemes` | on `#/designStrategy` the `More` button has `aria-current="page"`; on `#/theme` the link `Theme Builder` does; on `#/emergingThemes` the link `Theme Radar` does | holdout |
| AC-54 | e2e stack | press Ctrl+K and type, one at a time, `theme radar`, `theme builder`, `scoring rules`, `dossiers` | each shows an option (not `Ask ARP: …`) reading `Theme Radar`, `Theme Builder`, `Scoring Rules`, `Dossiers` respectively; pressing `Theme Radar` opens `#/emergingThemes` | holdout |
| AC-55 | the Argus workspace's process list | read the step labelled Template | its `does` text is `Build and ratify scoring templates in Scoring Rules (R&D Lab); only ratified versions reach Argus.` | unit |
| AC-56 | e2e stack | open `#/themes`, then `#/emergingThemes` | neither page has a `nav.hub-nav` (the Themes tab strip); the document title on `#/emergingThemes` is `Theme Radar · ARP` | holdout |
| AC-57 | e2e stack | open `#/stewardiq` | its navigation's first link reads `StewardIQ` (other workspaces keep their name; must not change) | holdout |
| AC-58 | — | CRASH-R | one `role="alert"` contains heading `This screen stopped working`, the text `Something went wrong while showing it. The rest of the app still works: try again, or open another screen.` and a button `Try again`; no page error | holdout |
| AC-59 | the end state of AC-58 | look at the page | the top bar's `Main` navigation and the link `ARP start` are visible | holdout |
| AC-60 | the end state of AC-58 | click `ARP start` | the URL hash is `#/home` and no element shows `This screen stopped working` | holdout |
| AC-61 | the end state of AC-58 | press Ctrl+K | the command palette dialog (`Search or ask`) is open | holdout |
| AC-62 | the end state of AC-58, then the radar stub changed to answer R | click `Try again` | h1 `Theme Radar` is visible and no element shows `This screen stopped working` | holdout |

### Slice 3: action strength and the Overview

| ID | Given | When | Then (observable, exact) | Checked by |
|----|-------|------|--------------------------|------------|
| AC-70 | tags `t1` capex (mention `m1`, url `u1`), `t2` other (`m2`, `u2`), `t3` partnership (`m2`), all grounded | `compute_action_strength(tags, mentions, None)` | 72 | holdout |
| AC-71 | AC-70's tags | with `capex_pct_change` 0.05, then −0.03, then 0.0 | 82, 62, 72 | holdout |
| AC-72 | one grounded partnership tag (one URL) | `compute_action_strength(…, None)` | 41 | holdout |
| AC-73 | 7 grounded `other` tags with 7 distinct URLs | `compute_action_strength(…, None)` | 45 | holdout |
| AC-74 | an ungrounded capex tag and a grounded `other` tag (one URL) | `compute_action_strength(…, 0.2)` | 31 | holdout |
| AC-75 | no tags; then only ungrounded tags | `compute_action_strength(…, 0.5)` | 0 and 0 | holdout |
| AC-76 | 5 grounded capex tags with 5 distinct URLs | `compute_action_strength(…, 0.1)` | 100 | holdout |
| AC-77 | tags in order: grounded partnership, grounded capex "Acme will build a plant.", grounded orders | `strongest_action_tag(tags)` | the capex tag; with no grounded tag, `None` | holdout |
| AC-78 | a run with stand-ins (sources, LLM, clustering) where company `acme` has one grounded capex tag from one URL and XBRL capex change +0.1, exposure enabled | run, read the candidate's `company_exposure` | `acme`: `action_strength` 76, `strongest_action` `capex`, `strongest_claim` its tag's claim, `source_count` 1, no `momentum` key | unit |
| AC-79 | H+ with K2's `company_exposure` `[{delta, adopter, "r", action_strength 72, orders, "Delta ordered 40 units.", source_count 3}]`, K3's `[{zeta, …, 90, capex, "z", 4}]`, K4's `[{acme, …, 72, capex, "Acme will build a cell plant.", 2}, {beta, …, action_strength null}, {gamma, …, 41, partnership, "Gamma signed a pilot.", 1}]` | radar | `companies` exactly, in order: `{company_id: delta, name: delta, radar_id: b41, theme: Bravo again, action_strength: 72, strongest_action: orders, strongest_claim: "Delta ordered 40 units.", source_count: 3}`, then `acme` (`e45`, `Echo theme`, 72, `capex`, 2), then `gamma` (`e45`, `Echo theme`, 41, `partnership`, 1) | holdout |
| AC-80 | a candidate row in `results.jsonl` whose exposure holds `momentum` 1.4 and no `action_strength` | `GET /api/emerging-themes/runs/{run_id}/candidates` | 200; that exposure has `action_strength` null and `source_count` 0 | holdout |
| AC-81 | radar stub R with `companies` = 12 entries; the first `{company_id: varn, name: "Varn Cell Works", radar_id: r1, theme: "Sodium-ion batteries", action_strength: 94, strongest_action: capex, strongest_claim: "New 8 GWh cell line, start 2027.", source_count: 6}`, the 11th named `Eleventh Co` | open `#/rdLab` | h2 `Who is putting money behind the rising themes`; table "Companies by action strength" has 10 body rows; row 1 reads `1`, `Varn Cell Works`, `Sodium-ion batteries`, `Capex · New 8 GWh cell line, start 2027.`, `94`, `6`; `Eleventh Co` is not shown | holdout |
| AC-82 | radar stub R | open `#/rdLab` | h2 `What is gaining momentum` with an `svg` "Theme Radar chart" holding 5 `circle[data-radar-id]`; a link `Open Theme Radar` with `href` `#/emergingThemes` | holdout |
| AC-83 | AC-82 plus candidate stub e2 | click `circle[data-radar-id=r2]` | the URL hash is `#/emergingThemes/r2` and the panel h2 is `Small modular reactors` | holdout |
| AC-84 | the radar request fails | open `#/rdLab` | exactly one `role="alert"` reading `The radar could not be loaded: boom`; h1 `R&D Lab` and the process `Build a thematic portfolio` still shown | holdout |
| AC-85 | radar stub R (`companies` `[]`) | open `#/rdLab` | the text `No company has acted on a rising theme yet.` | holdout |
| AC-86 | e2e stack, requests recorded | open `#/stewardiq` | no request to `/api/emerging-themes/radar` | holdout |
| AC-87 | AC-40 with e2's `company_exposure` `[{company_id: acme, role: adopter, role_rationale: "Acme ordered two units.", risk: 0, evidence_quality: 1, action_strength: 72, strongest_action: orders, strongest_claim: "Acme ordered two units.", source_count: 2}]` | click row r2 | the panel shows `(risk 0%, action strength 72, evidence quality 100%)` | holdout |
| AC-88 | the running app with Fixture H+ (with AC-79's exposures) written to `$ARP_EMERGING_THEMES_STATE_DIR/topics` before `e2e_stack.sh up` | open `#/rdLab` at 1440 and 390 wide | radar card above the company list; the list's columns in the order #, Company, Theme, What they did, Action strength, Sources; no two dot labels overlap; `scrollWidth` ≤ the viewport width at 390 | evaluator |
| AC-89 | slice 3's diff | read `company_exposure.py`'s imports, `Settings`, `pyproject.toml`, `package.json`, migrations | no `arp.llm` import; no field, dependency or migration added | unit |

AC-70 worked: tier 3 → 60, 2 URLs → +12. AC-74: only the `other` tag counts → 15 + 6 + 10. AC-78: 60 + 6 + 10.

Must not change: AC-25, AC-46, AC-57, `app-robustness` AC-41, `rd-lab-rename` AC-4, AC-13, AC-14 and AC-17.

## Slices

Three PRs, each `risk:normal`, each with `Spec: theme-radar-screen` and its `Rows:` line, every test it changes
listed, in this order (each starts after the one before merges; 2 and 3 both edit `EmergingThemesDetector.tsx`
and 3 builds on 1's radar):

| Slice | Size | PR contents | Rows |
|---|---|---|---|
| 1 | M | `emerging_themes/radar.py` (ids, burst, flag, `build_radar`, `eligible_cluster_ids`), `TopicCluster.source_counts` + `clustering.py`, `pipeline.py` eligibility, `GET /radar` + response models, OpenAPI + `schema.gen.ts`, `contract.ts`, tests | AC-1 to AC-27 (no AC-18) |
| 2 | L | `EmergingThemesDetector.tsx` (radar card, filters, chart component, list, side panel, `#/emergingThemes/<id>`), renames across `frontend/src`, `processes.ts` row/more and the "Overview" first link, `nav.ts` hub removal, `App.tsx` labels, moved e2e/frontend tests. Needs `UI review (factory)` | AC-30 to AC-62 |
| 3 | M | `company_exposure.py` (`compute_action_strength`, `strongest_action_tag`), `CompanyExposure` fields, `pipeline.py` exposure, radar `companies`, OpenAPI + `schema.gen.ts`, R&D Lab Overview cards in `ProcessHub.tsx`, exposure line in the detail block, tests. Needs `UI review (factory)` | AC-70 to AC-89 |

Files this spec owns against the R&D Lab redesign specs (items 1–14, 29): the R&D Lab `row`/`more`/first-link
label in `lib/processes.ts`, `lib/nav.ts` hub entries, the tab labels in `App.tsx`, the Overview card container
in `WorkspaceOverview` (item 29 appends its two cards there), the radar card and the company list.
