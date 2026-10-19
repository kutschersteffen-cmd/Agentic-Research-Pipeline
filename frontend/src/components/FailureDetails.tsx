import { useEffect, useState } from "react";
import { api } from "../api/client";
import { COMPANY_ERRORS_SHOWN } from "../lib/runs";
import type { RunFailure } from "../types";

// Mounted only while its Run History row is open, so every open fetches once.
export function FailureDetails({ runId }: { runId: string }) {
  const [failure, setFailure] = useState<RunFailure | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .getRunFailure(runId)
      .then((f) => live && setFailure(f))
      .catch((err) => live && setError((err as Error).message));
    return () => {
      live = false;
    };
  }, [runId]);

  if (error) return <p role="alert" className="error-text">{error}</p>;
  if (!failure) return <p className="muted">Loading…</p>;

  const shown = failure.company_errors.slice(0, COMPANY_ERRORS_SHOWN);
  const more = failure.company_errors.length - shown.length;
  return (
    <div className="failure-details">
      {failure.error && <p className="error-text">{failure.error}</p>}
      {failure.traceback === null ? (
        <p className="muted">No traceback was recorded for this run.</p>
      ) : (
        <pre>{failure.traceback}</pre>
      )}
      {shown.length > 0 && (
        <ul>
          {shown.map((c) => (
            <li key={c.key}>{c.key}: {c.error}</li>
          ))}
        </ul>
      )}
      {more > 0 && <p className="muted">and {more} more</p>}
    </div>
  );
}
