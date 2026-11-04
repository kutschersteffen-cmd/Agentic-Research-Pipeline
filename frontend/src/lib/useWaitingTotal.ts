import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ballotRows, needsAttentionRuns } from "./runs";
import { openCount } from "./workspaceCard";
import type { DataIssue, ReviewItem, RunManifest, StewardshipFlow } from "../types";

/** How many decisions wait on a person: review items, ballots, open stewardship decisions,
 * failed runs to resume and blocking data issues. null while loading, "error" if review items
 * could not be loaded. Nothing is stored; counts come from the same sources the Review Queue uses. */
export function useWaitingTotal(runs: RunManifest[] | null, flow: StewardshipFlow | null): number | null | "error" {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [issues, setIssues] = useState<DataIssue[] | null>(null);
  const [error, setError] = useState(false);
  // Refetch only when the runs' waiting totals change, not on every 3 s runs poll.
  const waitingKey = (runs ?? []).map((r) => `${r.run_id}:${r.review_count}`).join(",");
  useEffect(() => {
    api.listReviewItems().then((r) => { setItems(r.items); setError(false); }, () => setError(true));
    api.listIssues().then((r) => setIssues(r.issues), () => setIssues([]));
  }, [waitingKey]);
  if (error) return "error";
  if (items === null || issues === null) return null;
  const all = runs ?? [];
  return (
    items.length +
    ballotRows(all).reduce((n, b) => n + b.count, 0) +
    needsAttentionRuns(all, new Date()).length +
    (flow?.stages ?? []).reduce((n, s) => n + openCount(s), 0) +
    issues.filter((i) => i.severity === "block").length
  );
}
