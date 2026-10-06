import { useEffect, useState } from "react";
import { api } from "../api/client";
import { runTypeLabel } from "../lib/runs";
import { STAGE_TABS, openCount } from "../pages/steward/common";
import type { DataIssue, ReviewItem, RunManifest, StewardshipFlow } from "../types";

// Which workspace a waiting item belongs to, by the run type that produced it.
const WORKSPACE: Record<string, string> = {
  extraction: "Argus", financials: "Argus", tnfd: "Argus", transition_plan: "Argus", identity: "Argus",
  theme: "R&D Lab", holdings: "Data Hub", proxy_voting: "StewardIQ",
};

type Row = { key: string; workspace: string; what: string; count: number; since: string | null; href: string };

/** Everything waiting on a person, one row per place it waits (a run's review, a ballot run, a stewardship stage,
 * blocking data issues), oldest first, each linking to where it is decided. Counts come from the same sources the
 * sidebar badges use; nothing is stored. */
export function NeedsYou({ runs, flow }: { runs: RunManifest[] | null; flow: StewardshipFlow | null }) {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [issues, setIssues] = useState<DataIssue[] | null>(null);
  const [error, setError] = useState<string | null>(null);
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
      what: `${runTypeLabel(type)} run ${runId}: ${count === 1 ? "1 item" : `${count} items`} to review`,
      href: `#/review/${type}/${encodeURIComponent(runId)}`,
    });
  }
  for (const r of runs ?? []) {
    if (r.run_type === "proxy_voting" && r.review_count > 0) {
      rows.push({
        key: `ballots/${r.run_id}`, workspace: "StewardIQ", count: r.review_count, since: r.updated_at,
        what: `Proxy voting run ${r.run_id}: ${r.review_count === 1 ? "1 ballot" : `${r.review_count} ballots`} to decide`,
        href: `#/voting/${encodeURIComponent(r.run_id)}`,
      });
    }
  }
  for (const s of flow?.stages ?? []) {
    const n = openCount(s);
    if (n > 0) {
      const tab = STAGE_TABS.find((t) => t.id === s.id);
      rows.push({
        key: `stage/${s.id}`, workspace: "StewardIQ", count: n, since: null,
        what: `Steward · ${tab?.label ?? s.title}: ${n === 1 ? "1 decision" : `${n} decisions`} open`,
        href: `#/stewardship/${s.id}`,
      });
    }
  }
  const blocking = (issues ?? []).filter((i) => i.severity === "block");
  if (blocking.length > 0) {
    rows.push({
      key: "issues", workspace: "Data Hub", count: blocking.length, since: null,
      what: `${blocking.length === 1 ? "1 blocking data issue" : `${blocking.length} blocking data issues`}`, href: "#/issues",
    });
  }
  // Oldest waiting first; places without a date (stages, data issues) after them.
  rows.sort((a, b) => (a.since ?? "~").localeCompare(b.since ?? "~"));

  const loading = items === null && !error;
  return (
    <section className="needs-you" aria-labelledby="needs-you-title">
      <h2 id="needs-you-title">Needs you</h2>
      {error && <p className="error-text" role="alert">Review items could not be loaded: {error}</p>}
      {loading ? (
        <p className="muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="muted">Nothing waits on you.</p>
      ) : (
        <ul className="needs-you-list">
          {rows.map((r) => (
            <li key={r.key}>
              <a href={r.href}>
                <span className="needs-you-count">{r.count}</span>
                <span className="needs-you-what">{r.what}</span>
                <span className="needs-you-meta">
                  {r.workspace}
                  {r.since && ` · waiting since ${new Date(r.since).toLocaleDateString()}`}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
