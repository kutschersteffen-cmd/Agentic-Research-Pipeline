import "@gorules/jdm-editor/dist/style.css";
import { DecisionGraph, JdmConfigProvider, type DecisionGraphType } from "@gorules/jdm-editor";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type {
  CatalogueIssue,
  ClientEscalationPreview,
  ClientExceptionItem,
  CoveragePreview,
  EscalationDecisionItem,
  EscalationPreview,
  EscalationRecommendation,
  IssueCatalogue,
  MonitoringPreview,
  MonitoringTrigger,
  PolicyDifferenceItem,
  StewardPolicyId,
  StewardshipStage,
  StewardshipStream,
  TierChangeItem,
  VotingPolicy,
  VotingPosition,
  VotingPreview,
} from "../../types";
import { ActorField, DataTable, Planned, Section, StudioHeader, VersionsPanel, useActor, usePolicy, words } from "./common";
import { ClientExceptionDecisions, EscalationDecisions, PolicyDifference, TierDecisions } from "./decisions";

export interface StudioProps {
  stage: StewardshipStage;
  onChanged: () => void;
  onOpen: (tab: string) => void;
}

const TIER_ORDER = ["Priority Bilateral", "Thematic & Collaborative", "Scaled Baseline", "Systemic / Market-Level"];

function countMissing(value: unknown): number {
  if (value === null || value === undefined) return 1;
  if (typeof value === "object") return Object.values(value as Record<string, unknown>).reduce<number>((n, v) => n + countMissing(v), 0);
  return 0;
}

/** The working copy of a versioned rule graph: load a version, edit, preview against the active one. */
function useRuleDraft<P>(policyId: StewardPolicyId, previewFn: (graph: Record<string, unknown>) => Promise<P>, stream?: string) {
  const { info, error, reload } = usePolicy(policyId, stream);
  const [graph, setGraph] = useState<Record<string, unknown> | null>(null);
  const [baseVersion, setBaseVersion] = useState<number | null>(null);
  const [preview, setPreview] = useState<P | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  useEffect(() => {
    if (info && graph === null) {
      setGraph(info.active);
      setBaseVersion(info.active_version);
    }
  }, [info, graph]);
  const dirty = !!info && !!graph && JSON.stringify(graph) !== JSON.stringify(info.active);
  async function runPreview() {
    if (!graph) return;
    setPreviewing(true);
    setPreviewError(null);
    try {
      setPreview(await previewFn(graph));
    } catch (err) {
      setPreviewError((err as Error).message);
    } finally {
      setPreviewing(false);
    }
  }
  async function load(version: number) {
    setGraph(await api.getStewardPolicyVersion(policyId, version, stream));
    setBaseVersion(version);
    setPreview(null);
  }
  const editing = `Editing ${baseVersion === null ? "…" : `a copy of v${baseVersion}`}${dirty ? " · unsaved changes" : ""}`;
  return { info, error, reload, graph, setGraph, dirty, editing, load, preview, previewError, previewing, runPreview };
}

// --- 1. Monitoring -------------------------------------------------------------

// The badge palette reads as a score (high = green), so a high severity takes the red one.
const SEVERITY_BADGE: Record<string, string> = { high: "badge-low", medium: "badge-mid", low: "badge-neutral" };

export function MonitoringStudio({ stage, onChanged, onOpen }: StudioProps) {
  const draft = useRuleDraft<MonitoringPreview>("monitoring_rules", api.previewMonitoring);
  const { info, graph, preview } = draft;
  const [actor, setActor] = useActor();
  const [contexts, setContexts] = useState<Record<string, unknown>[] | null>(null);
  const [triggers, setTriggers] = useState<MonitoringTrigger[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadTriggers = () =>
    api.getMonitoringTriggers().then(
      (r) => setTriggers(r.triggers),
      (e) => setLoadError((e as Error).message),
    );
  useEffect(() => {
    api.getCoverageInputs().then(
      (r) => setContexts(r.contexts),
      (e) => setLoadError((e as Error).message),
    );
    loadTriggers();
  }, []);

  async function openEngagement(t: MonitoringTrigger) {
    setBusy(`${t.issuer_id}-${t.rule}`);
    setActionError(null);
    try {
      await api.openEngagementFromTrigger({ issuer_id: t.issuer_id, rule: t.rule, decided_by: actor });
      await loadTriggers();
      onChanged();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const rows = (contexts ?? []).map((c) => {
    const issuer = c.issuer as Record<string, unknown>;
    const holding = c.holding as Record<string, unknown>;
    const history = c.history as Record<string, unknown>;
    return {
      company: c.name,
      sector: issuer.sector,
      region: issuer.region,
      "index weight %": holding.index_weight_pct,
      "AUM held (EUR m)": holding.aum_held_eur_m,
      "position change %": holding.change_pct,
      "values missing": countMissing(issuer),
      "open engagements": history.open_engagements,
    };
  });
  const ruleRows = preview
    ? [...new Set([...Object.keys(preview.by_rule_active), ...Object.keys(preview.by_rule_candidate)])].map((rule) => ({
        rule,
        active: preview.by_rule_active[rule] ?? 0,
        "this draft": preview.by_rule_candidate[rule] ?? 0,
      }))
    : [];

  return (
    <>
      <StudioHeader
        stage={stage}
        capabilities={[
          { label: "Review", ready: true },
          { label: "Design", ready: true },
          { label: "Calibrate", ready: true },
          { label: "Versions", ready: true },
          { label: "Decide", ready: true },
        ]}
      />
      <ActorField actor={actor} onChange={setActor} />
      {loadError && <p className="error-text">{loadError}</p>}
      <Section step="Review · Decide" title="Triggers raised">
        <p className="help-text">
          What the active monitoring rules raise on today&apos;s company data. A trigger on the same theme as an open engagement is
          attached to it; any other trigger makes the company a selection candidate. Opening an engagement takes its theme and
          severity from the rule.
        </p>
        {actionError && <p className="error-text">{actionError}</p>}
        {triggers === null ? (
          <p className="status-text">Loading…</p>
        ) : triggers.length === 0 ? (
          <p className="muted">No trigger raised.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Severity</th>
                  <th>Type</th>
                  <th>Theme</th>
                  <th>Why</th>
                  <th>Engagement</th>
                </tr>
              </thead>
              <tbody>
                {triggers.map((t) => (
                  <tr key={`${t.issuer_id}-${t.rule}`}>
                    <td>{t.company}</td>
                    <td>
                      <span className={`badge ${SEVERITY_BADGE[t.severity]}`}>{t.severity}</span>
                    </td>
                    <td>{words(t.type)}</td>
                    <td>{words(t.theme)}</td>
                    <td>
                      {t.reason} <span className="muted">({t.rule})</span>
                    </td>
                    <td>
                      {t.engagement_id ? (
                        <span className="muted">attached to {t.engagement_id}</span>
                      ) : (
                        <button
                          onClick={() => openEngagement(t)}
                          disabled={!actor || busy !== null}
                          title={actor ? undefined : "Enter your name above first"}
                        >
                          {busy === `${t.issuer_id}-${t.rule}` ? "Opening…" : "Open engagement"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="toolbar">
          <button className="link-button" onClick={() => onOpen("selection")}>
            New engagements are tiered at stage 2 →
          </button>
        </div>
      </Section>
      <Section step="Review" title="Companies in scope">
        <p className="help-text">
          Every company the house holds, with its position and how complete its data is. Missing values never trigger anything; they
          show where data coverage needs work.
        </p>
        {contexts === null ? <p className="status-text">Loading…</p> : <DataTable rows={rows} />}
      </Section>
      {draft.error && <p className="error-text">{draft.error}</p>}
      <Section step="Design" title="Monitoring rules">
        <p className="help-text">
          A decision table where <strong>every</strong> matching row raises a trigger, so one company can raise several. Inputs per
          company: scores (<code>issuer.score.clti</code>, <code>issuer.score.nature</code>, placeholders), controversies
          (<code>issuer.controversy.*</code>), climate flags, <code>issuer.pay.misalignment_years</code> and{" "}
          <code>holding.change_pct</code> (any company field can be added as a column). Outputs: <code>type</code> (controversy,
          score_change, holding_change, vote_outcome, commitment_missed, engagement_stalled, calendar or manual), <code>theme</code>,{" "}
          <code>severity</code> (low, medium, high), <code>rule</code> and <code>reason</code>. Open the table with{" "}
          <em>Edit Table</em>.
        </p>
        <p className="muted">{draft.editing}</p>
        {graph && <PolicyCanvas graph={graph} onChange={draft.setGraph} />}
      </Section>
      <Section step="Calibrate" title="What this draft would raise">
        <div className="toolbar">
          <button onClick={draft.runPreview} disabled={!graph || draft.previewing}>
            {draft.previewing ? "Running…" : "Preview against the active rules"}
          </button>
        </div>
        {draft.previewError && <p className="error-text">{draft.previewError}</p>}
        {preview && (
          <>
            <p className="muted">
              {preview.companies} companies (synthetic sample). This draft raises {preview.triggers_candidate} triggers on{" "}
              {preview.flagged_candidate} companies ({Math.round((100 * preview.flagged_candidate) / preview.companies)}%); the active
              rules raise {preview.triggers_active} on {preview.flagged_active}.
            </p>
            <div className="studio-columns">
              <div>
                <h4>Triggers per rule</h4>
                <DataTable rows={ruleRows} />
              </div>
              <div>
                <h4>Newly flagged</h4>
                <DataTable rows={preview.newly_flagged.map((c) => ({ company: c.company }))} empty="Nobody new." />
                <h4>No longer flagged</h4>
                <DataTable rows={preview.no_longer_flagged.map((c) => ({ company: c.company }))} empty="Nobody drops out." />
              </div>
            </div>
          </>
        )}
      </Section>
      <Section step="Versions" title="Save and activate">
        {info && graph && (
          <VersionsPanel
            policyId="monitoring_rules"
            info={info}
            workingCopy={graph}
            dirty={draft.dirty}
            actor={actor}
            onSaved={draft.reload}
            onLoad={draft.load}
            onActivated={() => {
              draft.reload();
              loadTriggers();
              onChanged();
            }}
          />
        )}
      </Section>
    </>
  );
}

// --- 2. Research & Selection: coverage tiers -------------------------------------

function PolicyCanvas({ graph, onChange }: { graph: Record<string, unknown>; onChange: (g: Record<string, unknown>) => void }) {
  return (
    <div className="card rule-canvas studio-canvas">
      <JdmConfigProvider theme={{ token: { colorPrimary: "#33507a", fontFamily: "IBM Plex Sans, sans-serif", borderRadius: 6 } }}>
        <DecisionGraph
          value={graph as unknown as DecisionGraphType}
          onChange={(next) => {
            if (JSON.stringify(next) !== JSON.stringify(graph)) onChange(next as unknown as Record<string, unknown>);
          }}
        />
      </JdmConfigProvider>
    </div>
  );
}

export function SelectionStudio({ stage, onChanged, onOpen }: StudioProps) {
  const draft = useRuleDraft<CoveragePreview>("coverage_rules", api.previewCoverage);
  const { info, graph, preview } = draft;
  const [actor, setActor] = useActor();
  const distributionRows = preview
    ? TIER_ORDER.map((t) => ({
        tier: t,
        active: preview.distribution_active[t] ?? 0,
        "this draft": preview.distribution_candidate[t] ?? 0,
      }))
    : [];

  return (
    <>
      <StudioHeader
        stage={stage}
        capabilities={[
          { label: "Review", ready: true },
          { label: "Design", ready: true },
          { label: "Calibrate", ready: true },
          { label: "Versions", ready: true },
        ]}
      />
      <Section step="Review" title="Confirmed coverage tiers">
        <DataTable rows={stage.details.find((d) => d.label.includes("coverage"))?.rows ?? []} />
        <div className="toolbar">
          <button className="link-button" onClick={() => onOpen("checkpoint")}>
            Tier changes are confirmed at stage 5 →
          </button>
        </div>
      </Section>
      <ActorField actor={actor} onChange={setActor} />
      {draft.error && <p className="error-text">{draft.error}</p>}
      <Section step="Design" title="Coverage rules">
        <p className="help-text">
          A decision table, read top to bottom: the <strong>first</strong> row that matches decides the tier. Inputs per company:{" "}
          <code>holding.index_weight_pct</code>, <code>holding.aum_held_eur_m</code>, <code>history.escalated</code>,{" "}
          <code>history.open_engagements</code>, <code>issuer.climate.high_emitter</code>,{" "}
          <code>issuer.nature.high_impact_sector</code> (any company field can be added as a column). Outputs: <code>tier</code>{" "}
          (priority_bilateral, thematic_collaborative, scaled_baseline or systemic), <code>rule</code> and <code>reason</code>. Open
          the table with <em>Edit Table</em>.
        </p>
        <p className="muted">{draft.editing}</p>
        {graph && <PolicyCanvas graph={graph} onChange={draft.setGraph} />}
      </Section>
      <Section step="Calibrate" title="What this draft would change">
        <div className="toolbar">
          <button onClick={draft.runPreview} disabled={!graph || draft.previewing}>
            {draft.previewing ? "Running…" : "Preview against the active rules"}
          </button>
        </div>
        {draft.previewError && <p className="error-text">{draft.previewError}</p>}
        {preview && (
          <>
            <p className="muted">
              {preview.companies} companies (synthetic sample). {preview.changes.length} would change tier.
            </p>
            <div className="studio-columns">
              <div>
                <h4>Tier distribution</h4>
                <DataTable rows={distributionRows} />
              </div>
              <div>
                <h4>Rules that fired</h4>
                <DataTable rows={Object.entries(preview.rules_fired).map(([rule, companies]) => ({ rule, companies }))} />
              </div>
            </div>
            <h4>Companies that would move</h4>
            <DataTable
              rows={preview.changes.map((c) => ({ company: c.company, from: c.from, to: c.to, why: `${c.reason} (${c.rule})` }))}
              empty="No company would change tier."
            />
          </>
        )}
      </Section>
      <Section step="Versions" title="Save and activate">
        {info && graph && (
          <VersionsPanel
            policyId="coverage_rules"
            info={info}
            workingCopy={graph}
            dirty={draft.dirty}
            actor={actor}
            onSaved={draft.reload}
            onLoad={draft.load}
            onActivated={() => {
              draft.reload();
              onChanged();
            }}
          />
        )}
      </Section>
    </>
  );
}

// --- 3. Drafting -------------------------------------------------------------------

export function DraftingStudio({ stage }: StudioProps) {
  return (
    <>
      <StudioHeader
        stage={stage}
        capabilities={[
          { label: "Review", ready: true },
          { label: "Design", ready: false },
          { label: "Calibrate", ready: false },
        ]}
      >
        <p className="muted">
          Outreach letters, talking points and meeting summaries are drafted on the <strong>Engagement</strong> page, with grounded
          citations and a human sign-off before anything is sent.
        </p>
      </StudioHeader>
      <Section step="Design" title="Drafting rules and house style" planned>
        <Planned
          items={[
            "Interaction tagging (E6): informational vs advocacy/pressure, with pressure-type outreach always stopping at the checkpoint.",
            "Phrase blocklist (E8): generic ESG-narrative phrases flagged in every client-facing text before it reaches a person.",
            "Outreach templates per coverage tier and theme.",
          ]}
        />
      </Section>
    </>
  );
}

// --- 4. Voting: house voting policy ------------------------------------------------

function ParamInput({ spec, value, onChange }: { spec: CatalogueIssue["parameters"][string]; value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? null));
  const [bad, setBad] = useState(false);
  if (spec.type === "bool")
    return <input type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} aria-label={spec.description} />;
  if (spec.type === "number")
    return (
      <input
        type="number"
        className="param-number"
        value={value === null || value === undefined ? "" : String(value)}
        placeholder="not set"
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        aria-label={spec.description}
      />
    );
  if (spec.type === "enum")
    return (
      <select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} aria-label={spec.description}>
        {(spec.values ?? []).map((v) => (
          <option key={v} value={v}>
            {words(v)}
          </option>
        ))}
      </select>
    );
  if (spec.type === "field")
    return <input value={String(value ?? "")} onChange={(e) => onChange(e.target.value || null)} aria-label={spec.description} />;
  return (
    <input
      className={bad ? "param-json invalid" : "param-json"}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        try {
          onChange(JSON.parse(text));
          setBad(false);
        } catch {
          setBad(true);
        }
      }}
      aria-label={spec.description}
      title="JSON, e.g. {&quot;EU&quot;: 40}"
    />
  );
}

function PositionEditor({
  issue,
  position,
  active,
  actions,
  onChange,
}: {
  issue: CatalogueIssue;
  position: VotingPosition;
  active: VotingPosition | undefined;
  actions: string[];
  onChange: (p: VotingPosition) => void;
}) {
  const changed = JSON.stringify(position) !== JSON.stringify(active);
  return (
    <div className={`position-card${changed ? " changed" : ""}`}>
      <div className="decision-card-head">
        <strong>{issue.title}</strong>
        <code className="muted">{issue.issue_id}</code>
        {changed && <span className="chip">changed</span>}
      </div>
      <p className="muted">{issue.description}</p>
      <div className="position-grid">
        <label className="field-label">
          Vote
          <select value={position.action} onChange={(e) => onChange({ ...position, action: e.target.value })}>
            {actions.map((a) => (
              <option key={a} value={a}>
                {words(a)}
              </option>
            ))}
          </select>
        </label>
        <label className="field-label">
          Target
          <select value={position.vote_target} onChange={(e) => onChange({ ...position, vote_target: e.target.value })}>
            {issue.vote_targets.map((t) => (
              <option key={t} value={t}>
                {words(t)}
              </option>
            ))}
          </select>
        </label>
        {Object.entries(issue.parameters).map(([name, spec]) => (
          <label key={name} className="field-label" title={spec.description}>
            {words(name)}
            {spec.unit ? ` (${spec.unit})` : ""}
            <ParamInput spec={spec} value={position.parameters[name]} onChange={(v) => onChange({ ...position, parameters: { ...position.parameters, [name]: v } })} />
          </label>
        ))}
      </div>
      <label className="field-label">
        Rationale (used in vote disclosure)
        <input value={position.rationale} onChange={(e) => onChange({ ...position, rationale: e.target.value })} />
      </label>
    </div>
  );
}

export function VotingStudio({ stage, onChanged }: StudioProps) {
  const { info, error, reload } = usePolicy("house_voting");
  const [actor, setActor] = useActor();
  const [catalogue, setCatalogue] = useState<IssueCatalogue | null>(null);
  const [policy, setPolicy] = useState<VotingPolicy | null>(null);
  const [baseVersion, setBaseVersion] = useState<number | null>(null);
  const [category, setCategory] = useState<string>("board");
  const [preview, setPreview] = useState<VotingPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getIssueCatalogue().then(setCatalogue);
  }, []);
  useEffect(() => {
    if (info && policy === null) {
      setPolicy(info.active as unknown as VotingPolicy);
      setBaseVersion(info.active_version);
    }
  }, [info, policy]);

  const activePolicy = info?.active as unknown as VotingPolicy | undefined;
  const activeById = useMemo(() => new Map((activePolicy?.positions ?? []).map((p) => [p.issue_id, p])), [activePolicy]);
  const changedCount = policy ? policy.positions.filter((p) => JSON.stringify(p) !== JSON.stringify(activeById.get(p.issue_id))).length : 0;
  const titles = useMemo(() => new Map((catalogue?.issues ?? []).map((i) => [i.issue_id, i.title])), [catalogue]);

  function update(next: VotingPosition) {
    if (!policy) return;
    setPolicy({ ...policy, positions: policy.positions.map((p) => (p.issue_id === next.issue_id ? next : p)) });
  }
  async function runPreview() {
    if (!policy) return;
    setBusy(true);
    setPreviewError(null);
    try {
      setPreview(await api.previewVoting(policy));
    } catch (err) {
      setPreviewError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function load(version: number) {
    setPolicy((await api.getStewardPolicyVersion("house_voting", version)) as unknown as VotingPolicy);
    setBaseVersion(version);
    setPreview(null);
  }

  const issues = (catalogue?.issues ?? []).filter((i) => i.category === category);
  const positions = new Map((policy?.positions ?? []).map((p) => [p.issue_id, p]));
  const voteMix = preview
    ? ["for", "against", "case_by_case", "abstain"].map((v) => ({ vote: v, active: preview.base_votes[v] ?? 0, "this draft": preview.other_votes[v] ?? 0 }))
    : [];

  return (
    <>
      <StudioHeader
        stage={stage}
        capabilities={[
          { label: "Review", ready: true },
          { label: "Design", ready: true },
          { label: "Calibrate", ready: true },
          { label: "Versions", ready: true },
        ]}
      />
      <Section step="Review" title="What the active policy decides">
        <p className="help-text">The most frequent reasons the active house policy votes against, on the synthetic meeting sample.</p>
        <DataTable rows={(stage.details[0]?.rows ?? []).map((r) => ({ ...r, issue: titles.get(String(r.issue)) ?? r.issue }))} />
      </Section>
      <ActorField actor={actor} onChange={setActor} />
      {error && <p className="error-text">{error}</p>}
      <Section step="Design" title="House voting positions">
        <p className="help-text">
          One position per catalogue issue: the vote, what it targets, and the thresholds. Each position compiles into a rule of the
          house voting graph.
        </p>
        <p className="muted">
          Editing {baseVersion === null ? "…" : `a copy of v${baseVersion}`} · {changedCount} position{changedCount === 1 ? "" : "s"} changed
        </p>
        <nav className="sub-nav" aria-label="Issue categories">
          {(catalogue?.categories ?? []).map((c) => (
            <button key={c} className={c === category ? "nav-tab active" : "nav-tab"} onClick={() => setCategory(c)}>
              {words(c)}
            </button>
          ))}
        </nav>
        {policy && catalogue ? (
          issues.map((issue) => {
            const position = positions.get(issue.issue_id);
            return position ? (
              <PositionEditor
                key={`${baseVersion}-${issue.issue_id}`}
                issue={issue}
                position={position}
                active={activeById.get(issue.issue_id)}
                actions={catalogue.position_actions}
                onChange={update}
              />
            ) : null;
          })
        ) : (
          <p className="status-text">Loading…</p>
        )}
      </Section>
      <Section step="Calibrate" title="Back-test against the active policy">
        <div className="toolbar">
          <button onClick={runPreview} disabled={!policy || busy}>
            {busy ? "Running…" : "Run back-test"}
          </button>
        </div>
        {previewError && <p className="error-text">{previewError}</p>}
        {preview && (
          <>
            <p className="muted">
              {preview.resolutions} resolutions (synthetic sample): this draft changes the expected vote on{" "}
              <strong>{preview.changed}</strong>.
            </p>
            <div className="studio-columns">
              <div>
                <h4>Vote mix</h4>
                <DataTable rows={voteMix} />
              </div>
              <div>
                <h4>Changes by issue</h4>
                <DataTable
                  rows={Object.keys({ ...preview.affected_by_issue, ...preview.masked_by_issue }).map((i) => ({
                    issue: titles.get(i) ?? i,
                    "votes changed": preview.affected_by_issue[i] ?? 0,
                    masked: preview.masked_by_issue[i] ?? 0,
                  }))}
                  empty="No position change reaches a vote."
                />
              </div>
            </div>
            <h4>Resolutions whose expected vote changes</h4>
            <DataTable
              rows={preview.changed_rows.slice(0, 25).map((r) => ({
                resolution: r.resolution_id,
                category: r.category,
                active: r.base_vote,
                "this draft": r.other_vote,
                because: r.issues.map((i) => titles.get(i) ?? i).join(", "),
              }))}
              empty="None."
            />
            {Object.keys(preview.unused_parameters).length > 0 && (
              <p className="muted">
                Not part of any vote rule (preferences or process steps):{" "}
                {Object.entries(preview.unused_parameters)
                  .map(([i, ps]) => `${titles.get(i) ?? i}: ${ps.map(words).join(", ")}`)
                  .join(" · ")}
              </p>
            )}
          </>
        )}
      </Section>
      <Section step="Versions" title="Save and activate">
        {info && policy && (
          <VersionsPanel
            policyId="house_voting"
            info={info}
            workingCopy={policy}
            dirty={changedCount > 0}
            actor={actor}
            onSaved={reload}
            onLoad={load}
            onActivated={() => {
              reload();
              onChanged();
            }}
          />
        )}
      </Section>
    </>
  );
}

// --- 5. Human checkpoint -------------------------------------------------------------

const LADDER = [
  "private_engagement",
  "joint_engagement",
  "written_escalation_to_board",
  "escalation_to_chair",
  "vote_against_management",
  "file_or_cofile_resolution",
  "public_statement",
];

export function CheckpointStudio({ stage, onChanged, onOpen }: StudioProps) {
  const [actor, setActor] = useActor();
  const draft = useRuleDraft<EscalationPreview>("escalation_rules", api.previewEscalation);
  const { info, graph, preview } = draft;
  const [recs, setRecs] = useState<EscalationRecommendation[] | null>(null);
  const [recError, setRecError] = useState<string | null>(null);
  const loadRecs = () =>
    api.getEscalationRecommendations().then(
      (r) => setRecs(r.recommendations),
      (e) => setRecError((e as Error).message),
    );
  useEffect(() => {
    loadRecs();
  }, []);
  const escalations = stage.decisions.filter((d): d is EscalationDecisionItem => d.kind === "escalation");
  const tiers = stage.decisions.filter((d): d is TierChangeItem => d.kind === "tier_change");
  const clientItems = stage.decisions.filter((d): d is ClientExceptionItem => d.kind === "client_exception");
  const ruleRows = preview
    ? [...new Set([...Object.keys(preview.by_rule_active), ...Object.keys(preview.by_rule_candidate)])].map((rule) => ({
        rule,
        active: preview.by_rule_active[rule] ?? 0,
        "this draft": preview.by_rule_candidate[rule] ?? 0,
      }))
    : [];
  return (
    <>
      <StudioHeader
        stage={stage}
        capabilities={[
          { label: "Review", ready: true },
          { label: "Decide", ready: true },
          { label: "Design", ready: true },
          { label: "Calibrate", ready: true },
          { label: "Versions", ready: true },
        ]}
      />
      <ActorField actor={actor} onChange={setActor} />
      <Section step="Decide" title="Decisions waiting">
        {escalations.length === 0 && tiers.length === 0 && clientItems.length === 0 && (
          <p className="muted">Nothing is waiting for a decision.</p>
        )}
        {escalations.length > 0 && (
          <>
            <h4>Escalations</h4>
            <p className="help-text">
              Live engagements the escalation rules recommend moving up. Escalating moves the engagement to the recommended step and
              records you and the rule; the rules only recommend.
            </p>
            <EscalationDecisions
              items={escalations}
              actor={actor}
              onDone={() => {
                loadRecs();
                onChanged();
              }}
            />
          </>
        )}
        {clientItems.length > 0 && (
          <>
            <h4>Client escalations above the house</h4>
            <ClientExceptionDecisions items={clientItems} actor={actor} onDone={onChanged} />
          </>
        )}
        {tiers.length > 0 && <TierDecisions items={tiers} actor={actor} onDone={onChanged} />}
      </Section>
      <Section step="Review" title="Escalation recommendations">
        <p className="help-text">
          What the active rules recommend for every open engagement: the live ones and the synthetic sample ones. The coverage tier
          (confirmed, else proposed) caps the step; wanting to go past the cap means the tier should be promoted (coverage rules,
          stage 2). A trigger or missed commitment escalates only after 3 months at the current step, so one trigger does not climb
          the whole ladder.
        </p>
        <div className="toolbar">
          <button className="link-button" onClick={() => onOpen("selection")}>
            Coverage tiers are set at stage 2 →
          </button>
        </div>
        {recError && <p className="error-text">{recError}</p>}
        {recs === null ? (
          <p className="status-text">Loading…</p>
        ) : (
          <DataTable
            rows={recs.map((r) => ({
              company: r.company,
              theme: r.theme,
              data: r.source === "live" ? "live" : "sample",
              tier: r.tier ?? "none",
              "step now": r.current,
              recommended: r.escalate ? r.recommended : "hold",
              "tier cap": r.max_step + (r.promote_tier ? " · promote" : ""),
              why: `${r.reason} (${r.rule})`,
            }))}
            empty="No open engagements."
          />
        )}
      </Section>
      {draft.error && <p className="error-text">{draft.error}</p>}
      <Section step="Design" title="Escalation rules and tier caps">
        <p className="help-text">
          Two tables, both read top to bottom with the <strong>first</strong> matching row deciding. <code>tier_caps</code> sets the
          highest ladder step per coverage tier (<code>tier.max_step</code>, 0-6). <code>escalation_rules</code> sets how many steps
          up an engagement should move (<code>escalate_by</code>) with <code>rule</code> and <code>reason</code>. Its inputs:{" "}
          <code>triggers.high_same_theme</code>, <code>triggers.same_theme</code>, <code>engagement.commitments_missed</code>,{" "}
          <code>engagement.months_at_step</code>, <code>engagement.stalled</code>, <code>engagement.step_index</code>,{" "}
          <code>tier.tier</code>, <code>tier.max_step</code> and any company field under <code>issuer</code>. The ladder:{" "}
          {LADDER.map((step, i) => `${i} ${words(step)}`).join(" · ")}.
        </p>
        <p className="muted">{draft.editing}</p>
        {graph && <PolicyCanvas graph={graph} onChange={draft.setGraph} />}
      </Section>
      <Section step="Calibrate" title="What this draft would recommend">
        <div className="toolbar">
          <button onClick={draft.runPreview} disabled={!graph || draft.previewing}>
            {draft.previewing ? "Running…" : "Preview against the active rules"}
          </button>
        </div>
        {draft.previewError && <p className="error-text">{draft.previewError}</p>}
        {preview && (
          <>
            <p className="muted">
              {preview.engagements} open engagements. This draft recommends {preview.escalations_candidate} escalations and{" "}
              {preview.promotions_candidate} tier promotions; the active rules recommend {preview.escalations_active} and{" "}
              {preview.promotions_active}.
            </p>
            <div className="studio-columns">
              <div>
                <h4>Recommendations per rule</h4>
                <DataTable rows={ruleRows} empty="No rule recommends anything." />
              </div>
            </div>
            <h4>Engagements whose recommendation would change</h4>
            <DataTable rows={preview.changes} empty="No recommendation would change." />
          </>
        )}
      </Section>
      <Section step="Versions" title="Save and activate">
        {info && graph && (
          <VersionsPanel
            policyId="escalation_rules"
            info={info}
            workingCopy={graph}
            dirty={draft.dirty}
            actor={actor}
            onSaved={draft.reload}
            onLoad={draft.load}
            onActivated={() => {
              draft.reload();
              loadRecs();
              onChanged();
            }}
          />
        )}
      </Section>
      <Section step="Design" title="Other checkpoint rules" planned>
        <Planned
          items={[
            "The engagement SLA (days without activity before an engagement counts as stalled); today a server setting.",
            "Which items always need a second sign-off (e.g. vote sanctions, advocacy outreach).",
            "Voting intentions and disclosure records to approve (E2, E3), once the voting feed exists.",
          ]}
        />
      </Section>
    </>
  );
}

// --- 6. Tracking ---------------------------------------------------------------------

export function TrackingStudio({ stage }: StudioProps) {
  return (
    <>
      <StudioHeader
        stage={stage}
        capabilities={[
          { label: "Review", ready: true },
          { label: "Design", ready: false },
        ]}
      />
      <Section step="Review" title="Open engagements by milestone">
        <DataTable rows={stage.details[0]?.rows ?? []} empty="No open engagements." />
        <p className="muted">Correspondence and commitments are logged on the Engagement page.</p>
      </Section>
      <Section step="Design" title="Milestones and commitment tracking" planned>
        <Planned
          items={[
            "The milestone ladder (identified → contacted → dialogue → response → commitment → verified), configurable per house.",
            "Commitment deadlines that raise a trigger in stage 1 when they are missed.",
            "Escalation case studies (E7) from closed escalation histories.",
          ]}
        />
      </Section>
    </>
  );
}

// --- 7. Client policy ----------------------------------------------------------------

export function ClientPicker({
  streams,
  active,
  onChange,
  onOpen,
}: {
  streams: StewardshipStream[];
  active: string;
  onChange: (id: string) => void;
  onOpen: (tab: string) => void;
}) {
  const clients = streams.filter((s) => s.kind === "client");
  return (
    <div className="toolbar client-picker">
      {clients.length === 0 ? (
        <p className="muted">No client streams yet.</p>
      ) : (
        <label className="field-label">
          Client stream
          <select value={clients.some((c) => c.stream_id === active) ? active : ""} onChange={(e) => onChange(e.target.value)}>
            <option value="" disabled>
              Choose a client…
            </option>
            {clients.map((c) => (
              <option key={c.stream_id} value={c.stream_id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <button className="link-button" onClick={() => onOpen("overview")}>
        + Add a client stream on the overview
      </button>
    </div>
  );
}

export function ClientPolicyStudio({ stage, streamId, onChanged }: StudioProps & { streamId: string }) {
  const [actor, setActor] = useActor();
  const draft = useRuleDraft<ClientEscalationPreview>(
    "escalation_rules",
    (graph) => api.previewClientEscalation(streamId, graph),
    streamId,
  );
  const { info, graph, preview } = draft;
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const differences = stage.decisions.filter((d): d is PolicyDifferenceItem => d.kind === "policy_difference");
  const open = differences.filter((d) => d.decision === null);
  async function build() {
    setBuilding(true);
    setError(null);
    try {
      await api.buildStreamPolicy(streamId);
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBuilding(false);
    }
  }
  return (
    <>
      <StudioHeader
        stage={stage}
        capabilities={[
          { label: "Review", ready: true },
          { label: "Calibrate", ready: true },
          { label: "Decide", ready: true },
          { label: "Design", ready: true },
          { label: "Versions", ready: true },
        ]}
      />
      <ActorField actor={actor} onChange={setActor} />
      <Section step="Review · Calibrate · Decide" title="The client's voting policy against the house policy">
        <p className="muted">
          {open.length} of {differences.length} differences still to decide. Each shows its back-test effect on the synthetic sample.
        </p>
        {stage.can_build && (
          <div className="toolbar">
            <button onClick={build} disabled={building}>
              {building ? "Building…" : "Build the custom policy"}
            </button>
          </div>
        )}
        {error && <p className="error-text">{error}</p>}
        {[...open, ...differences.filter((d) => d.decision !== null)].map((item) => (
          <PolicyDifference key={item.issue_id} item={item} streamId={streamId} actor={actor} onDone={onChanged} />
        ))}
      </Section>
      {draft.error && <p className="error-text">{draft.error}</p>}
      <Section step="Design" title="The client's escalation rules">
        <p className="help-text">
          The same two tables as the house rules (stage 5), evaluated after them with the house answer under <code>house.*</code>:{" "}
          <code>house.escalate_by</code>, <code>house.max_step</code>, <code>house.recommended_step</code>, <code>house.rule</code>,{" "}
          <code>house.reason</code>. Version 0 returns the house answer unchanged; a client rule overrides it where the client wants
          more. Where the client&apos;s step is above the house&apos;s on a live engagement, the house decides at stage 5 whether to
          adopt it. Give trigger-based rules a wait at each step (<code>engagement.months_at_step</code>), otherwise one condition
          keeps asking for the next step.
        </p>
        <div className="toolbar">
          <span className="muted">{draft.editing}</span>
          <button
            className="secondary"
            onClick={async () => draft.setGraph(await api.getClientEscalationExample())}
            title="A client that escalates climate engagements with CLTI laggards one step further than the house"
          >
            Start from the example client rules
          </button>
        </div>
        {graph && <PolicyCanvas graph={graph} onChange={draft.setGraph} />}
      </Section>
      <Section step="Calibrate" title="Client against house">
        <div className="toolbar">
          <button onClick={draft.runPreview} disabled={!graph || draft.previewing}>
            {draft.previewing ? "Running…" : "Preview against the house and the client's active rules"}
          </button>
        </div>
        {draft.previewError && <p className="error-text">{draft.previewError}</p>}
        {preview && (
          <>
            <p className="muted">
              {preview.engagements} open engagements. This draft goes above the house on {preview.higher_candidate}; the client&apos;s
              active rules on {preview.higher_active}.
            </p>
            <DataTable rows={preview.rows} />
          </>
        )}
      </Section>
      <Section step="Versions" title="Save and activate the client's escalation rules">
        {info && graph && (
          <VersionsPanel
            policyId="escalation_rules"
            stream={streamId}
            info={info}
            workingCopy={graph}
            dirty={draft.dirty}
            actor={actor}
            onSaved={draft.reload}
            onLoad={draft.load}
            onActivated={() => {
              draft.reload();
              onChanged();
            }}
          />
        )}
      </Section>
    </>
  );
}

// --- 8. Reporting --------------------------------------------------------------------

export function ReportingStudio({ stage }: StudioProps) {
  return (
    <>
      <StudioHeader
        stage={stage}
        capabilities={[
          { label: "Review", ready: true },
          { label: "Design", ready: false },
        ]}
      />
      <Section step="Design · Construct" title="Reports and disclosure" planned>
        <Planned
          items={[
            "Per-client stewardship report from house truth plus the client's policy, rendered with the Report Builder templates.",
            "Public vote disclosure (E2): per-meeting records with a mandatory rationale for every vote against management.",
            "Program proposal and PPT for a client program (Part 5), and escalation case studies (E7), checked against the phrase blocklist (E8).",
          ]}
        />
      </Section>
    </>
  );
}
