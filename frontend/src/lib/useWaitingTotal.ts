import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ballotRows, needsAttentionRuns } from "./runs";
import { openCount, waitingTarget } from "./workspaceCard";
import type { DataIssue, ReviewItem, RunManifest, StewardshipFlow } from "../types";

/** How many decisions wait on a person: review items, ballots, open stewardship decisions,
 * failed runs to resume and blocking data issues. null while loading, "error" if review items
 * could not be loaded. Nothing is stored; counts come from the same sources the Review Queue uses.
 * Also where the waiting link should go, from the same fetch so the two never disagree. */
export function useWaiting(runs: RunManifest[] | null, flow: StewardshipFlow | null): { total: number | null | "error"; target: "#/review" | "#/stewardiq" } {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [issues, setIssues] = useState<DataIssue[] | null>(null);
  const [error, setError] = useState(false);
  // Refetch only when the runs' waiting totals change, not on every 3 s runs poll.
  const waitingKey = (runs ?? []).map((r) => `${r.run_id}:${r.review_count}`).join(",");
  useEffect(() => {
    api.listReviewItems().then((r) => { setItems(r.items); setError(false); }, () => setError(true));
    api.listIssues().then((r) => setIssues(r.issues), () => setIssues([]));
  }, [waitingKey]);
  const stewardship = (flow?.stages ?? []).reduce((n, s) => n + openCount(s), 0);
  const target = waitingTarget(items?.length ?? 0, stewardship);
  if (error) return { total: "error", target };
  if (items === null || issues === null) return { total: null, target };
  const all = runs ?? [];
  return {
    total:
      items.length +
      ballotRows(all).reduce((n, b) => n + b.count, 0) +
      needsAttentionRuns(all, new Date()).length +
      stewardship +
      issues.filter((i) => i.severity === "block").length,
    target,
  };
}
