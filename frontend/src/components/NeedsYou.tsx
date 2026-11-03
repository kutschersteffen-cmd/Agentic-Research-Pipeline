import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ago, ballotRows, compareSince, needsAttentionRuns, runTypeLabel } from "../lib/runs";
import { useResume } from "../lib/useResume";
import { STAGE_TABS, openCount } from "../pages/steward/common";
import type { DataIssue, ReviewItem, RunManifest, StewardshipFlow } from "../types";

// Which workspace a waiting item belongs to, by the run type that produced it.
const WORKSPACE: Record<string, string> = {
  extraction: "Argus", financials: "Argus", tnfd: "Argus", transition_plan: "Argus", identity: "Argus",
  theme: "R&D Lab", holdings: "Data Hub", proxy_voting: "StewardIQ",
};

// `what` is the decision asked of the person; `source` names the run or place it comes from.
type Row = { key: string; workspace: string; what: string; source: string; count: number; since: string | null; href: string; resumeRunId?: string };

/** Everything waiting on a person, one row per place it waits (a run's review, a ballot run, a stewardship stage,
 * blocking data issues), oldest first, each linking to where it is decided. Counts come from the same sources the
 * Review Queue's sidebar badge uses; nothing is stored. */
export function NeedsYou({ runs, flow, runsError = false, onTotal }: {
  runs: RunManifest[] | null; flow: StewardshipFlow | null;
  /** The page already shows a runs error banner; don't repeat it here. */
  runsError?: boolean;
  /** The sum of the row counts, so the page headline counts the same things; null while loading. */
  onTotal?: (total: number | null | "error") => void;
}) {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [issues, setIssues] = useState<DataIssue[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { busyId, error: resumeError, resume } = useResume();
  // Refetch the item list only when the runs' waiting totals change, not on every 3 s runs poll.
  const waitingKey = (runs ?? []).map((r) => `${r.run_id}:${r.review_count}`).join(",");

  useEffect(() => {
    api.listReviewItems().then((r) => setItems(r.items), (e: Error) => setError(e.message));
    api.listIssues().then((r) => setIssues(r.issues), () => setIssues([]));
  }, [waitingKey]);

  const byRun = new Map((runs ?? []).map((r) => [r.run_id, r]));
  const rows: Row[] = [];
  const reviewCounts = new Map<string, number>();
  for (const i of items ?? []) reviewCounts.set(i.run_id, (reviewCounts.get(i.run_id) ?? 0) + 1);
  for (const [runId, count] of reviewCounts) {
    const run = byRun.get(runId);
    const type = run?.run_type ?? items!.find((i) => i.run_id === runId)!.run_type;
    rows.push({
      key: `review/${runId}`, workspace: WORKSPACE[type] ?? "Review", count, since: run?.updated_at ?? null,
      what: `Review ${count === 1 ? "1 item" : `${count} items`}`, source: `${runTypeLabel(type)} ${runId}`,
      href: `#/review/${type}/${encodeURIComponent(runId)}`,
    });
  }
  for (const b of ballotRows(runs ?? [])) {
    rows.push({ key: `ballots/${b.runId}`, workspace: "StewardIQ", count: b.count, since: byRun.get(b.runId)!.updated_at, what: b.what, source: `Proxy voting ${b.runId}`, href: b.href });
  }
  for (const r of needsAttentionRuns(runs ?? [], new Date())) {
    const done = r.company_count > 0 ? ` (${r.completed_count}/${r.company_count} companies done)` : "";
    rows.push({
      key: `failed/${r.run_id}`, workspace: WORKSPACE[r.run_type] ?? "Review", count: 1, since: r.updated_at,
      what: `Resume ${r.status === "failed" ? "failed" : "partially completed"} run${done}`, source: `${runTypeLabel(r.run_type)} ${r.run_id}`,
      href: "#/history", resumeRunId: r.run_id,
    });
  }
  for (const s of flow?.stages ?? []) {
    const n = openCount(s);
    if (n > 0) {
      const tab = STAGE_TABS.find((t) => t.id === s.id);
      rows.push({
        key: `stage/${s.id}`, workspace: "StewardIQ", count: n, since: null,
        what: `Decide ${n === 1 ? "1 open decision" : `${n} open decisions`}`, source: `Stewardship · ${tab?.label ?? s.title}`,
        href: `#/stewardship/${s.id}`,
      });
    }
  }
  const blocking = (issues ?? []).filter((i) => i.severity === "block");
  if (blocking.length > 0) {
    rows.push({
      key: "issues", workspace: "Data Hub", count: blocking.length, since: null,
      what: `Resolve ${blocking.length === 1 ? "1 blocking data issue" : `${blocking.length} blocking data issues`}`, source: "Data issues", href: "#/issues",
    });
  }
  // Failed runs first (work stopped until someone acts), then oldest waiting; undated places after them.
  rows.sort((a, b) => Number(!a.resumeRunId) - Number(!b.resumeRunId) || compareSince(a.since, b.since));

  const loading = items === null && !error;
  const total = error ? "error" : loading ? null : rows.reduce((n, r) => n + r.count, 0);
  useEffect(() => onTotal?.(total), [total, onTotal]);
  return (
    <section className="needs-you" aria-labelledby="needs-you-title">
      <h2 id="needs-you-title">Needs you</h2>
      {error && (runsError ? <p className="muted">Unknown until the backend responds.</p> : <p className="error-text" role="alert">Review items could not be loaded: {error}</p>)}
      {loading ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        // After a load error an empty list is unknown, not "nothing waits".
        !error && <p className="muted">Nothing waits on you.</p>
      ) : (
        <ul className="needs-you-list">
          {rows.map((r) => (
            <li key={r.key} className={r.resumeRunId ? "needs-you-failed" : undefined}>
              <a href={r.href}>
                <span className="needs-you-count">{r.count}</span>
                <span className="needs-you-what">{r.what}</span>
                <span className="needs-you-meta">
                  {r.workspace} · {r.source}
                  {r.since && ` · ${ago(r.since)}`}
                </span>
                <span className="needs-you-go" aria-hidden>Open →</span>
              </a>
              {r.resumeRunId && (
                <button
                  className="link-button"
                  aria-label={`Resume run ${r.resumeRunId}`}
                  disabled={busyId !== null}
                  onClick={() => resume(r.resumeRunId!)}
                >
                  Resume
                </button>
              )}
              {r.resumeRunId && resumeError?.runId === r.resumeRunId && (
                <p role="alert" className="error-text">{resumeError.message}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
