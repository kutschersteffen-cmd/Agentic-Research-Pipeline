import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { STEPS, argusRows, filterRows, tiles, waiting } from "../lib/argusStart";
import { ACTIVE_STATUSES } from "../lib/runs";
import { listAllRuns, usePoll } from "../lib/poll";
import type { ReviewItem, RunManifest } from "../types";

/** #/argus: the five-step process, the team's Argus runs and what waits on a person. */
export function ArgusStart() {
  const [runs, setRuns] = useState<RunManifest[] | null>(null);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<string | null>(null);
  const [onlyMine, setOnlyMine] = useState(false);
  const [step, setStep] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, i] = await Promise.all([listAllRuns(), api.listReviewItems()]);
      setRuns(r);
      setItems(i.items);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);
  usePoll(load, runs?.some((r) => ACTIVE_STATUSES.has(r.status)) ? 3000 : 15000);
  useEffect(() => {
    api.getMe().then((m) => setMe(m.user_id), () => setMe(null));
  }, []);

  const mine = filterRows(argusRows(runs ?? []), { step: null, mineOf: onlyMine ? me : null });
  const shown = filterRows(mine, { step, mineOf: null });
  const wait = waiting(mine, items);

  return (
    <div className="page hub argus-start">
      <div className="argus-head">
        <h1>Argus</h1>
        {/* shortcut: opens the old companies screen until slice 2 builds step 1 */}
        <button onClick={() => (window.location.hash = "#/extraction/companies")}>Start new extraction</button>
      </div>
      {error && <p className="error-text" role="alert">Runs could not be loaded: {error}.</p>}
      <section className="argus-tiles" aria-label="Process">
        {tiles(mine, items).map((t) => (
          <a
            key={t.step}
            href="#/argus"
            className={t.needs ? "argus-tile argus-tile-await" : "argus-tile"}
            aria-pressed={step === t.step}
            onClick={(e) => {
              e.preventDefault();
              setStep(step === t.step ? null : t.step);
            }}
          >
            <span className="argus-tile-name">
              {t.step} {t.label}
            </span>
            <span className="argus-tile-count">{t.count}</span>
            {t.needs && <span className="argus-tile-needs">{t.needs}</span>}
          </a>
        ))}
      </section>
      <div className="argus-body">
        <div>
          <label className="argus-mine">
            <input type="checkbox" id="argus-only-mine" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} /> Only mine
          </label>
          <div className="table-wrap">
            <table className="data-table stack-on-phone" aria-label="Runs">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Companies</th>
                  <th>Step</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs !== null && shown.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      No runs yet. Start a new extraction.
                    </td>
                  </tr>
                )}
                {shown.map((r) => (
                  <tr key={r.runId}>
                    <td>
                      {r.label}
                      <div className="muted">
                        {r.startedBy ?? "—"} · {new Date(r.createdAt).toLocaleDateString()}
                      </div>
                    </td>
                    <td>{r.companies} companies</td>
                    <td>
                      {r.step} {STEPS[r.step - 1]}
                    </td>
                    <td className={r.status === "Needs you" ? "await-text" : undefined}>{r.status}</td>
                    <td>
                      <a href={r.openHref}>Open</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            <a href="#/xbrl">XBRL Facts</a>
          </p>
        </div>
        <aside className="card argus-waiting" aria-label="Waiting for you">
          <h2>Waiting for you</h2>
          <p className={wait.total ? "argus-waiting-total await-text" : "argus-waiting-total"}>{wait.total}</p>
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
