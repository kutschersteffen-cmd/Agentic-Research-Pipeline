import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { useReviewer } from "../../lib/reviewer";
import type { MetricSource, StewardPolicyId, StewardPolicyInfo, StewardshipStage } from "../../types";

export const SOURCE_LABEL: Record<MetricSource, string> = { live: "live data", sample: "synthetic sample", portfolio: "portfolio holdings", not_built: "not built yet" };

export function fmt(v: unknown): string {
  if (v === null || v === undefined) return "not set";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}: ${fmt(x)}`).join(", ");
  return String(v);
}

export const words = (s: string) => s.replace(/_/g, " ");

/** Decisions a stage still waits on: every item except policy differences
 * already decided. */
export const openCount = (stage: StewardshipStage | undefined) =>
  stage ? stage.decisions.filter((d) => d.kind !== "policy_difference" || d.decision === null).length : 0;

/** The name recorded with every decision: the app-wide "Reviewing as" identity. */
export const useActor = useReviewer;

export function ActorField({ actor, onChange }: { actor: string; onChange: (v: string) => void }) {
  return (
    <label className="field-label actor-field">
      Your name (recorded with every decision and version)
      <input value={actor} onChange={(e) => onChange(e.target.value)} placeholder="e.g. J. Doe" />
    </label>
  );
}

export type Capability = { label: "Review" | "Design" | "Calibrate" | "Versions" | "Decide"; ready: boolean };

/** Header of every stage studio: what the stage is, its numbers, and what can be done here today. */
export function StudioHeader({ stage, capabilities, children }: { stage: StewardshipStage; capabilities: Capability[]; children?: ReactNode }) {
  return (
    <section className="card">
      <div className="section-heading">
        <h3>
          {stage.number}. {stage.title} studio
        </h3>
        <span className="chip">{stage.layer === "house" ? "House truth" : "Client overlay"}</span>
      </div>
      <p className="help-text">{stage.summary}</p>
      <div className="chip-row" aria-label="What this studio does">
        {capabilities.map((c) => (
          <span key={c.label} className={`chip capability${c.ready ? " ready" : ""}`} title={c.ready ? "Available" : "Not built yet"}>
            {c.ready ? "✓" : "○"} {c.label}
          </span>
        ))}
      </div>
      <MetricTiles stage={stage} />
      {children}
    </section>
  );
}

export function MetricTiles({ stage }: { stage: StewardshipStage }) {
  return (
    <div className="metric-grid">
      {stage.metrics.map((m) => (
        <div key={m.label} className={`metric-tile tone-${m.tone}`}>
          <span className="metric-tile-label">{m.label}</span>
          <strong className="metric-tile-value">{m.value}</strong>
          <span className="metric-tile-source">
            <span className={`source-dot source-${m.source}`} /> {SOURCE_LABEL[m.source]}
          </span>
          {m.hint && <span className="muted">{m.hint}</span>}
        </div>
      ))}
    </div>
  );
}

export function DataTable({ rows, empty = "Nothing to show." }: { rows: Record<string, unknown>[]; empty?: string }) {
  if (rows.length === 0) return <p className="muted">{empty}</p>;
  const keys = Object.keys(rows[0]);
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {keys.map((k) => (
              <th key={k}>{words(k)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {keys.map((k) => (
                <td key={k}>{typeof row[k] === "string" ? words(row[k] as string) : fmt(row[k])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A studio section: one step of review, design, calibration or versions. */
export function Section({ step, title, children, planned }: { step: string; title: string; children: ReactNode; planned?: boolean }) {
  return (
    <section className={`card studio-section${planned ? " planned" : ""}`}>
      <p className="studio-step">{step}</p>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

/** Honest placeholder for a part of the studio that is designed but not built. */
export function Planned({ items }: { items: string[] }) {
  return (
    <>
      <p className="help-text">Designed in the operating model, not built yet. This part of the studio will hold:</p>
      <ul className="planned-list">
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ul>
    </>
  );
}

export function usePolicy(policyId: StewardPolicyId, stream?: string) {
  const [info, setInfo] = useState<StewardPolicyInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    try {
      setInfo(await api.getStewardPolicy(policyId, stream));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [policyId, stream]);
  useEffect(() => {
    reload();
  }, [reload]);
  return { info, error, reload };
}

/** Save the working copy as a new version; activate any version with a named approver. */
export function VersionsPanel({
  policyId,
  stream,
  info,
  workingCopy,
  dirty,
  actor,
  onSaved,
  onLoad,
  onActivated,
}: {
  policyId: StewardPolicyId;
  stream?: string;
  info: StewardPolicyInfo;
  workingCopy: unknown;
  dirty: boolean;
  actor: string;
  onSaved: () => void;
  onLoad: (version: number) => void;
  onActivated: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const needName = actor ? undefined : "Enter your name above first";

  async function save() {
    setBusy("save");
    setError(null);
    setMessage(null);
    try {
      const res = await api.saveStewardPolicyVersion(policyId, { content: workingCopy, note, created_by: actor }, stream);
      setNote("");
      setMessage(`Saved as version ${res.version}. It is not active until someone activates it.`);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function activate(version: number) {
    setBusy(`activate-${version}`);
    setError(null);
    setMessage(null);
    try {
      await api.activateStewardPolicy(policyId, { version, approved_by: actor }, stream);
      setMessage(`Version ${version} is now active.`);
      onActivated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const lastActivation = (v: number) => [...info.activations].reverse().find((a) => a.version === v);

  return (
    <>
      <p className="help-text">
        Saving checks that the policy runs and stores it as a new, unchangeable version. It only takes effect once a second person
        (not its author) activates it; every activation is logged, so you can always roll back.
      </p>
      <div className="inline-fields decision-controls">
        <input aria-label="Version note" placeholder="What changed and why" value={note} onChange={(e) => setNote(e.target.value)} />
        <button onClick={save} disabled={!actor || !dirty || busy !== null} title={needName ?? (dirty ? undefined : "No changes to save")}>
          {busy === "save" ? "Saving…" : "Save as new version"}
        </button>
      </div>
      {message && <p className="status-text">{message}</p>}
      {error && <p className="error-text">{error}</p>}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Version</th>
              <th>Note</th>
              <th>Created</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {[...info.versions].reverse().map((v) => {
              const active = v.version === info.active_version;
              const act = lastActivation(v.version);
              return (
                <tr key={v.version} className={active ? "selected-row" : undefined}>
                  <td>v{v.version}</td>
                  <td>{v.note || "—"}</td>
                  <td>
                    {v.created_by}
                    {v.created_at ? ` · ${new Date(v.created_at).toLocaleDateString()}` : ""}
                  </td>
                  <td>
                    {active ? <strong>active</strong> : "inactive"}
                    {act ? <span className="muted"> · approved by {act.approved_by}</span> : null}
                  </td>
                  <td>
                    <div className="row-actions">
                      <button className="link-button" onClick={() => onLoad(v.version)}>
                        Load into editor
                      </button>
                      {!active && (
                        <button
                          onClick={() => activate(v.version)}
                          disabled={!actor || busy !== null || v.created_by.toLowerCase() === actor.toLowerCase()}
                          title={needName ?? (v.created_by.toLowerCase() === actor.toLowerCase() ? "Four-eyes: someone other than the author must activate" : undefined)}
                        >
                          {busy === `activate-${v.version}` ? "Activating…" : "Activate"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
