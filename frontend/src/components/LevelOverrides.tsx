import { useState } from "react";
import { REVIEWER_REQUIRED, useReviewer } from "../lib/reviewer";
import type { EntityDecision, LevelOverride } from "../types";

interface Props {
  entity: EntityDecision;
  /** [lowest, highest] level on the framework's scale. */
  scale: [number, number];
  onSet: (override: LevelOverride) => Promise<void>;
  onRemove: (criterionId: string, reviewer: string, reason: string) => Promise<void>;
}

/** One entity's level per criterion, as the rules set it or as a reviewer
 * overrode it. An override needs a reason and a named reviewer; the rules'
 * level stays beside it, and removing one is recorded too. */
export function LevelOverrides({ entity, scale, onSet, onRemove }: Props) {
  const [reviewer] = useReviewer();
  const [editing, setEditing] = useState<string | null>(null);
  const [level, setLevel] = useState<number>(scale[1]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const levels = Array.from({ length: scale[1] - scale[0] + 1 }, (_, i) => scale[1] - i);
  const criteria = entity.contributions.filter((c) => c.criterion_id);

  async function run(action: () => Promise<void>) {
    if (!reviewer.trim()) {
      setError(REVIEWER_REQUIRED);
      return;
    }
    if (reason.trim().length < 3) {
      setError("Give a reason: it is shown to anyone reading this score, and kept in the audit log.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await action();
      setEditing(null);
      setReason("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function start(criterionId: string, current: number | null | undefined) {
    setEditing(criterionId);
    setLevel(current ?? scale[1]);
    setReason("");
    setError(null);
  }

  if (criteria.length === 0) {
    return <p className="muted">These scores were stored before levels could be overridden. Re-score to see each criterion&apos;s level.</p>;
  }

  return (
    <div className="level-overrides">
      <table className="data-table">
        <thead>
          <tr>
            <th>Criterion</th>
            <th>Level</th>
            <th>Weight</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {criteria.map((c) => {
            const id = c.criterion_id!;
            const overridden = !!c.override;
            return (
              <tr key={id} className={overridden ? "level-overridden" : undefined}>
                <td>
                  {c.column}
                  {c.imputed && !overridden && <span className="muted"> (default)</span>}
                </td>
                <td>
                  <strong>{c.normalised != null ? c.normalised : "—"}</strong>
                  {overridden && (
                    <div className="level-override-note">
                      rules: {c.overridden_from ?? "—"} · overridden by {c.override!.reviewer}
                      {c.override!.at && ` on ${new Date(c.override!.at).toLocaleDateString()}`}: “{c.override!.reason}”
                    </div>
                  )}
                  {editing === id && (
                    <div className="level-override-form">
                      <label className="field-label">
                        New level
                        <select value={level} onChange={(e) => setLevel(Number(e.target.value))}>
                          {levels.map((lv) => (
                            <option key={lv} value={lv}>
                              {lv}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="field-label">
                        Reason
                        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. disclosed in the 2025 CDP response" />
                      </label>
                      <div className="toolbar">
                        <button
                          disabled={busy}
                          onClick={() => run(() => onSet({ entity_key: entity.entity_key, criterion_id: id, level, reason: reason.trim(), reviewer: reviewer.trim() }))}
                        >
                          Set level {level}
                        </button>
                        {overridden && (
                          <button className="secondary" disabled={busy} onClick={() => run(() => onRemove(id, reviewer.trim(), reason.trim()))}>
                            Remove override
                          </button>
                        )}
                        <button className="link-button" onClick={() => setEditing(null)}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </td>
                <td>{(c.weight * 100).toFixed(1)}%</td>
                <td>
                  {editing !== id && (
                    <button className="link-button" onClick={() => start(id, c.normalised)}>
                      {overridden ? "Change" : "Override"}
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {error && <p className="error-text" role="alert">{error}</p>}
    </div>
  );
}
