import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { flowHref } from "../lib/argusFlow";
import { errorDetail } from "../lib/barrier";
import { STEPS, argusRows, filterLine, filterRows, tiles, waiting } from "../lib/argusStart";
import { ACTIVE_STATUSES } from "../lib/runs";
import { WORKSPACES } from "../lib/processes";
import { neighbour, useRowFocus } from "../lib/rowFocus";
import { listAllRuns, usePoll } from "../lib/poll";
import type { ArgusDraft, ReviewItem, RunManifest } from "../types";

/** The Transition plan template, preselected for step 3 by #/argus/new/transition_plan and the Transition Plan hand-over. */
const PRESETS: Record<string, string> = { transition_plan: "transition_plan_indicators" };

/** Starts a new flow (optionally with a saved universe and a step 3 template) and opens its step 1,
 * replacing the current history entry so Back never lands on the creating route again. */
export async function openNewFlow({ preset, universePath }: { preset?: string | null; universePath?: string } = {}) {
  // A hand-over (universePath) keeps the sending page in history; a redirect replaces the dead route.
  const { flow_id } = await api.createArgusFlow();
  try {
    const presetId = preset ? PRESETS[preset] : undefined;
    if (presetId) {
      const s = await api.installPreset(presetId);
      await api.patchArgusFlow(flow_id, { schema_choice: { kind: "schema", schema_id: s.schema_id, version: s.version, profile: null } });
    }
    if (universePath) await api.addFlowCompanies(flow_id, { universe_path: universePath });
  } catch (err) {
    await api.deleteArgusFlow(flow_id).catch(() => {}); // leave no empty draft behind; the caller shows the first error
    throw err;
  }
  if (universePath) window.location.hash = flowHref(flow_id, 1);
  else window.location.replace(flowHref(flow_id, 1));
}

/** #/argus/new[/<preset>]: where old links (Universe, Identify, Documents, Transition Plan) land. */
export function ArgusNew({ preset }: { preset: string | null }) {
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false); // one flow, even when React runs the effect twice
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    openNewFlow({ preset }).catch((err) => setError(errorDetail(err as Error)));
  }, [preset]);
  return (
    <div className="page">
      {error ? (
        <p className="error-text" role="alert">
          Could not start an extraction: {error}. <a href="#/argus">Back to Argus</a>
        </p>
      ) : (
        <p className="muted" role="status">Starting a new extraction…</p>
      )}
    </div>
  );
}

/** #/argus: the five-step process, the team's Argus runs and what waits on a person. */
export function ArgusStart() {
  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [flows, setFlows] = useState<ArgusDraft[]>([]);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [itemsError, setItemsError] = useState<string | null>(null);
  const [me, setMe] = useState<string | null>(null);
  const [canDelete, setCanDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [runsTable, focusRow] = useRowFocus();
  const deleting = useRef(false); // one request per draft; the button stays enabled, so a failed delete keeps the keyboard on it
  const gone = useRef(new Set<string>()); // drafts deleted here: a poll that began before the delete must not list them again
  const [onlyMine, setOnlyMine] = useState(false);
  const [step, setStep] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      const [r, f] = await Promise.all([listAllRuns(), api.listArgusFlows()]);
      setRuns(r);
      setFlows(f.flows.filter((x) => !gone.current.has(x.flow_id)));
      setError(null);
    } catch (err) {
      setError(errorDetail(err as Error));
    }
  }, []);
  const loadItems = useCallback(async () => {
    try {
      setItems((await api.listReviewItems()).items);
      setItemsError(null);
    } catch (err) {
      setItemsError(errorDetail(err as Error));
    }
  }, []);
  usePoll(loadRuns, runs?.some((r) => ACTIVE_STATUSES.has(r.status)) ? 3000 : 15000);
  // Items read every reviewable run's files: the slow interval only.
  usePoll(loadItems, 15000);
  useEffect(() => {
    api.getMe().then((m) => (setMe(m.user_id), setCanDelete(m.role !== "viewer")), () => setMe(null));
  }, []);

  const all = argusRows(runs ?? [], items, flows);
  const mine = filterRows(all, { step: null, mineOf: onlyMine ? me : null });
  const shown = filterRows(mine, { step, mineOf: null });
  const wait = waiting(mine, items);
  const purpose = WORKSPACES.find((w) => w.id === "argus")!.purpose;

  async function start() {
    setStarting(true);
    try {
      window.location.hash = flowHref((await api.createArgusFlow()).flow_id, 1);
    } catch (err) {
      setStartError(errorDetail(err as Error));
      setStarting(false);
    }
  }
  async function discard(flowId: string, next?: string) {
    if (!window.confirm("Delete this draft? Its company list and file choices are removed. Documents stay on the companies.")) return;
    if (deleting.current) return;
    deleting.current = true;
    try {
      await api.discardArgusFlow(flowId);
    } catch (err) {
      if (!/^404: /.test((err as Error).message)) return setDeleteError(errorDetail(err as Error)); // 404: it is gone already
    } finally {
      deleting.current = false;
    }
    gone.current.add(flowId);
    setFlows((fs) => fs.filter((f) => f.flow_id !== flowId));
    setDeleteError(null);
    focusRow(next);
  }

  return (
    <div className="page hub argus-start">
      <p className="hub-crumb">
        <a href="#/home">Start</a> › Argus
      </p>
      <div className="argus-head">
        <h1>Argus</h1>
        <span className="argus-head-actions">
          <a href="#/argusWalkthrough">Walkthrough</a>
          <a href="#/xbrl">XBRL Facts</a>
          <button disabled={starting} onClick={() => void start()}>
            Start new extraction
          </button>
        </span>
      </div>
      <p className="help-text">{purpose}</p>
      {startError && <p className="error-text" role="alert">The extraction could not be started: {startError}.</p>}
      {deleteError && <p className="error-text" role="alert">The draft could not be deleted: {deleteError}</p>}
      {error && <p className="error-text" role="alert">Runs could not be loaded: {error}.</p>}
      {itemsError && <p className="error-text" role="alert">Review items could not be loaded: {itemsError}. Waiting counts are unknown.</p>}
      <section className="argus-tiles" aria-label="Process">
        <p className="help-text argus-tiles-help">Extractions at each step. Click a step to list only its extractions.</p>
        {tiles(mine, items).map((t) => (
          <a
            key={t.step}
            href="#/argus"
            className={`argus-tile${t.needs ? " argus-tile-await" : ""}${t.count === 0 ? " argus-tile-empty" : ""}`}
            aria-pressed={step === t.step}
            onClick={(e) => {
              e.preventDefault();
              setStep(step === t.step ? null : t.step);
            }}
          >
            <span className="argus-tile-name">
              <span className="argus-tile-num">{t.step}</span> {t.label}
            </span>
            <span className="argus-tile-count">{t.count}</span>
            {t.needs && <span className="argus-tile-needs">{t.needs}</span>}
          </a>
        ))}
      </section>
      <div className="argus-body">
        <div>
          <label className="argus-mine">
            <input type="checkbox" id="argus-only-mine" checked={onlyMine} disabled={me === null} onChange={(e) => setOnlyMine(e.target.checked)} /> Only mine
          </label>
          {filterLine(step) && <p className="argus-filter-line" role="status">{filterLine(step)}</p>}
          <div className="table-wrap">
            <table ref={runsTable} tabIndex={-1} className="data-table stack-on-phone" aria-label="Runs">
              <thead hidden={shown.length === 0}>
                <tr>
                  <th>Run</th>
                  <th>Companies</th>
                  <th>Step</th>
                  <th>Status</th>
                  <th><span className="visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {runs !== null && shown.length === 0 && (
                  <tr>
                    {all.length > 0 ? (
                      <td colSpan={5} className="muted">
                        No run matches this filter.{" "}
                        <button className="link-button" onClick={() => (setStep(null), setOnlyMine(false))}>
                          Show all
                        </button>
                      </td>
                    ) : (
                      <td colSpan={5} className="muted">
                        No runs yet.{" "}
                        <button className="link-button" disabled={starting} onClick={() => void start()}>
                          Start one
                        </button>
                        : pick companies, find their documents, choose a schema, extract and review.
                      </td>
                    )}
                  </tr>
                )}
                {shown.map((r, i) => (
                  <tr key={r.runId} data-row={r.runId}>
                    <td data-label="Run">
                      {/* one block, so the name and its line stack inside a phone's label/value row */}
                      <div>
                        {r.label}
                        <div className="muted">
                          {r.starterName ?? "—"} · {new Date(r.createdAt).toLocaleDateString()}
                          {r.status === "Draft" && ` ${new Date(r.createdAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" })}`}
                          {r.names && ` · ${r.names}`}
                        </div>
                      </div>
                    </td>
                    <td data-label="Companies">{r.companies} {r.companies === 1 ? "company" : "companies"}</td>
                    <td data-label="Step">
                      {r.step} {STEPS[r.step - 1]}
                    </td>
                    <td data-label="Status" className={r.status === "Needs you" ? "await-text" : undefined}>{r.status}</td>
                    <td>
                      <span className="row-actions">
                        <a href={r.openHref}>Open</a>
                        {r.status === "Draft" && canDelete && (
                          <button className="link-button" aria-label={`Delete draft ${r.names}`} onClick={() => void discard(r.runId, neighbour(shown, i)?.runId)}>
                            Delete
                          </button>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <aside className="card argus-waiting" aria-label="Waiting for you">
          <h2>Waiting for you</h2>
          {wait.total ? <p className="argus-waiting-total await-text">{wait.total}</p> : <p className="muted">Nothing waits for you.</p>}
          <ul>
            {wait.groups.map((g) => (
              <li key={g.label}>
                {g.label}: {g.count}
              </li>
            ))}
          </ul>
          <a href="#/review">Open the review list</a>
        </aside>
      </div>
    </div>
  );
}
