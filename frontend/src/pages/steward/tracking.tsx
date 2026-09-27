import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { CaseStudy, CommitmentDueItem, TrackedCommitment, TrackedEngagement } from "../../types";
import { ActorField, DataTable, Section, StudioHeader, useActor, words } from "./common";
import { FlaggedText } from "./drafting";
import type { StudioProps } from "./studios";

const isOpen = (e: TrackedEngagement) => e.status === "open" || e.status === "stalled";
const key = (e: { company_id: string; issue_id: string }) => `${e.company_id}|${e.issue_id}`;

function EngagementSelect({ engagements, value, onChange }: { engagements: TrackedEngagement[]; value: string; onChange: (v: string) => void }) {
  return (
    <label className="field-label">
      Engagement
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {engagements.map((e) => (
          <option key={key(e)} value={key(e)}>
            {e.company} · {words(e.theme)}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Stage 6: commitments with target dates (overdue or missed ones raise stage 1 triggers),
 * closing an engagement with its outcome, and E7 case studies from closed engagements. */
export function TrackingStudio({ stage, onChanged }: StudioProps) {
  const [actor, setActor] = useActor();
  const [data, setData] = useState<{ commitments: TrackedCommitment[]; engagements: TrackedEngagement[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [newC, setNewC] = useState({ target: "", text: "", date: "" });
  const [closing, setClosing] = useState({ target: "", status: "resolved" as "resolved" | "closed", outcome: "" });
  const [study, setStudy] = useState<CaseStudy | null>(null);

  const load = () => api.getTracking().then(setData, (e) => setError((e as Error).message));
  useEffect(() => {
    load();
  }, [stage]);

  async function run(id: string, fn: () => Promise<unknown>) {
    setBusy(id);
    setError(null);
    try {
      await fn();
      await load();
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const setStatus = (c: TrackedCommitment, status: "verified" | "missed") =>
    run(c.commitment_id, () => api.setCommitmentStatus(c.commitment_id, { company_id: c.company_id, issue_id: c.issue_id, status, decided_by: actor }));
  const due = stage.decisions.filter((d): d is CommitmentDueItem => d.kind === "commitment_due");
  const open = data?.engagements.filter(isOpen) ?? [];
  const closed = data?.engagements.filter((e) => !isOpen(e)) ?? [];
  const needName = actor ? undefined : "Enter your name above first";

  const commitmentButtons = (c: TrackedCommitment) => (
    <div className="row-actions">
      <button onClick={() => setStatus(c, "verified")} disabled={!actor || busy !== null} title={needName}>
        Verified
      </button>
      <button className="secondary" onClick={() => setStatus(c, "missed")} disabled={!actor || busy !== null} title={needName}>
        Missed
      </button>
    </div>
  );

  return (
    <>
      <StudioHeader
        stage={stage}
        capabilities={[
          { label: "Review", ready: true },
          { label: "Decide", ready: true },
          { label: "Design", ready: false },
        ]}
      >
        <p className="muted">
          Missed commitments, commitments past their target date and stalled engagements go back to stage 1 as triggers. Correspondence
          is logged on the Engagement page and when outreach is sent (stage 3).
        </p>
      </StudioHeader>
      <ActorField actor={actor} onChange={setActor} />
      {error && <p className="error-text">{error}</p>}
      <Section step="Decide" title="Commitments past their target date">
        {due.length === 0 ? (
          <p className="muted">None: every open commitment is within its target date.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Commitment</th>
                  <th>Target date</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {due.map((c) => (
                  <tr key={c.commitment_id}>
                    <td>
                      {c.company} · {words(c.theme)}
                    </td>
                    <td>{c.text}</td>
                    <td>{c.target_date}</td>
                    <td>{commitmentButtons(c)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      <Section step="Construct" title="Record a commitment">
        <p className="help-text">A commitment the company made, as you validated it. Its target date is what monitoring checks.</p>
        <div className="inline-fields">
          <EngagementSelect engagements={open} value={newC.target} onChange={(target) => setNewC({ ...newC, target })} />
          <label className="field-label">
            Target date
            <input type="date" value={newC.date} onChange={(e) => setNewC({ ...newC, date: e.target.value })} />
          </label>
        </div>
        <label className="field-label">
          Commitment
          <input value={newC.text} onChange={(e) => setNewC({ ...newC, text: e.target.value })} placeholder="e.g. Publish interim 2030 targets" />
        </label>
        <div className="toolbar">
          <button
            disabled={!actor || !newC.target || !newC.text.trim() || busy !== null}
            title={needName}
            onClick={() => {
              const [company_id, issue_id] = newC.target.split("|");
              run("add", async () => {
                await api.addCommitment({ company_id, issue_id, text: newC.text, target_date: newC.date || undefined, recorded_by: actor });
                setNewC({ target: newC.target, text: "", date: "" });
              });
            }}
          >
            Record commitment
          </button>
        </div>
      </Section>
      <Section step="Review" title="All commitments">
        {data === null ? (
          <p className="status-text">Loading…</p>
        ) : data.commitments.length === 0 ? (
          <p className="muted">No commitments recorded yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Commitment</th>
                  <th>Target date</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.commitments.map((c) => (
                  <tr key={c.commitment_id}>
                    <td>
                      {c.company} · {words(c.theme)}
                    </td>
                    <td>{c.text}</td>
                    <td>{c.target_date ?? "none"}</td>
                    <td>
                      {c.overdue ? <span className="badge badge-mid">overdue</span> : c.status}
                      {c.validated_by && c.status !== "open" ? <span className="muted"> · {c.validated_by}</span> : null}
                    </td>
                    <td>{c.status === "open" && commitmentButtons(c)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      <Section step="Decide" title="Close an engagement">
        <p className="help-text">The outcome is logged on the engagement and becomes the last paragraph of its case study.</p>
        <div className="inline-fields">
          <EngagementSelect engagements={open} value={closing.target} onChange={(target) => setClosing({ ...closing, target })} />
          <label className="field-label">
            Closed as
            <select value={closing.status} onChange={(e) => setClosing({ ...closing, status: e.target.value as "resolved" | "closed" })}>
              <option value="resolved">resolved (the company did what we asked)</option>
              <option value="closed">closed (ended without resolution)</option>
            </select>
          </label>
        </div>
        <label className="field-label">
          Outcome
          <input value={closing.outcome} onChange={(e) => setClosing({ ...closing, outcome: e.target.value })} placeholder="What the company did, and when" />
        </label>
        <div className="toolbar">
          <button
            disabled={!actor || !closing.target || !closing.outcome.trim() || busy !== null}
            title={needName}
            onClick={() => {
              const [company_id, issue_id] = closing.target.split("|");
              run("close", async () => {
                await api.closeEngagement({ company_id, issue_id, status: closing.status, outcome: closing.outcome, decided_by: actor });
                setClosing({ target: "", status: "resolved", outcome: "" });
              });
            }}
          >
            Close engagement
          </button>
        </div>
      </Section>
      <Section step="Construct" title="Case studies (E7)">
        {closed.length === 0 ? (
          <p className="muted">Case studies are drafted from closed engagements; none is closed yet.</p>
        ) : (
          <div className="toolbar">
            {closed.map((e) => (
              <button key={key(e)} className="secondary" onClick={() => api.getCaseStudy(e.company_id, e.issue_id).then(setStudy, (err) => setError((err as Error).message))}>
                {e.company} · {words(e.theme)}
              </button>
            ))}
          </div>
        )}
        {study && (
          <>
            <h4>
              {study.company}: {words(study.theme)} ({study.status})
            </h4>
            <FlaggedText text={study.text} flags={study.style_flags} />
            <p className="muted">
              {study.provenance} {study.style_flags.length
                ? `${study.style_flags.length} style ${study.style_flags.length === 1 ? "flag" : "flags"} (E8) to rewrite before use.`
                : "No style flags."}
            </p>
          </>
        )}
      </Section>
      <Section step="Review" title="Open engagements by milestone">
        <DataTable rows={stage.details[0]?.rows ?? []} empty="No open engagements." />
      </Section>
    </>
  );
}
